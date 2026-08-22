"""Git Sync — Home Assistant app backend.

Milestone 2: setup wizard (GitHub token, repository & branches, sync
profile) on top of the milestone-1 read-only git status API.

The Home Assistant configuration directory is mounted at /homeassistant
inside the app container (map: homeassistant_config); CONFIG_DIR overrides
it for local development.
"""

import asyncio
import logging
import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

import gh
import git_ops
import i18n
import store
import sync

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/homeassistant")
STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("git-sync")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # First thing after a restart: make sure the safety exclusions are still
    # in place. A restored backup can bring back a /config whose
    # .git/info/exclude predates the coupling — the poller would start
    # committing without them.
    try:
        sync.reassert_excludes()
    except Exception:  # a broken exclude file must not keep the app down
        LOG.exception("safety exclusions could not be re-asserted on startup")
    task = asyncio.create_task(sync.poller())
    yield
    task.cancel()


app = FastAPI(title="Git Sync", docs_url=None, redoc_url=None, lifespan=lifespan)

# Sync profiles: which file groups end up in git. "apps_mode" is the
# custom_components/ handling — "lockfile" records names & versions only.
GROUP_KEYS = ["core", "blueprints", "esphome", "themes_www", "apps"]
PROFILES = {
    "komplett": {
        "groups": {"core": True, "blueprints": True, "esphome": True,
                   "themes_www": True, "apps": True},
        "apps_mode": "full",
    },
    "ohne_anwendungen": {
        "groups": {"core": True, "blueprints": True, "esphome": True,
                   "themes_www": True, "apps": True},
        "apps_mode": "lockfile",
    },
    "nur_kern": {
        "groups": {"core": True, "blueprints": False, "esphome": False,
                   "themes_www": False, "apps": False},
        "apps_mode": "lockfile",
    },
    # The user's own .gitignore governs the sync scope; only the built-in
    # safety exclusions stay managed. Default when the chosen repo already
    # carries a .gitignore.
    "eigene_gitignore": {"groups": {}, "apps_mode": None},
}


def _github_error(err: gh.GitHubError) -> HTTPException:
    LOG.warning("GitHub error (%s): %s", err.kind, err.detail or "-")
    status = {"invalid_token": 401, "forbidden": 403, "network": 502}.get(err.kind, 502)
    return HTTPException(status_code=status, detail=err.kind)


def _token() -> str:
    token = store.load().get("github", {}).get("token")
    if not token:
        raise HTTPException(status_code=409, detail="not_connected")
    return token


# --------------------------------------------------------------- setup state

@app.get("/api/setup")
def setup_state() -> dict:
    """Wizard state — never returns the token itself."""
    state = store.load()
    github = state.get("github", {})
    repo = state.get("repo")
    profile = state.get("profile")
    if not github.get("token"):
        step = 1
    elif not repo:
        step = 2
    elif not profile:
        step = 3
    else:
        step = 0  # configured
    return {
        "configured": step == 0,
        "step": step,
        "github": {"connected": bool(github.get("token")), "login": github.get("login")},
        "repo": repo,
        "profile": profile,
        # Empty until a language was picked — the panel then offers the one
        # the browser asks for and stores that choice.
        "language": state.get("sync_settings", {}).get("language", ""),
    }


@app.post("/api/setup/token")
def set_token(payload: dict = Body(...)) -> dict:
    token = (payload.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="missing_token")
    try:
        user = gh.get_user(token)
    except gh.GitHubError as err:
        raise _github_error(err) from err
    store.update(github={"token": token, "login": user["login"]})
    return {"login": user["login"]}


@app.delete("/api/setup/token")
def disconnect() -> dict:
    store.update(github=None, repo=None, profile=None)
    return {"ok": True}


@app.post("/api/setup/repo")
def set_repo(payload: dict = Body(...)) -> dict:
    _token()
    full_name = (payload.get("full_name") or "").strip()
    main_branch = (payload.get("main_branch") or "main").strip()
    sync_branch = (payload.get("sync_branch") or "ha-sync").strip()
    if not full_name or "/" not in full_name:
        raise HTTPException(status_code=400, detail="invalid_repo")
    if main_branch == sync_branch:
        raise HTTPException(status_code=400, detail="branches_equal")
    repo = {"full_name": full_name, "main_branch": main_branch, "sync_branch": sync_branch}
    store.update(repo=repo)
    return repo


@app.post("/api/setup/profile")
def set_profile(payload: dict = Body(...)) -> dict:
    _token()
    name = payload.get("name")
    if name in PROFILES:
        profile = {"name": name, **PROFILES[name]}
    elif name == "benutzerdefiniert":
        groups = payload.get("groups") or {}
        profile = {
            "name": name,
            "groups": {key: bool(groups.get(key)) for key in GROUP_KEYS},
            "apps_mode": payload.get("apps_mode", "lockfile"),
        }
    else:
        raise HTTPException(status_code=400, detail="unknown_profile")
    store.update(profile=profile)
    # A profile change applies immediately on an already-coupled directory.
    repo = store.load().get("repo")
    if repo and git_ops.coupling_state(repo) == "coupled":
        git_ops.apply_excludes(profile)
        git_ops.write_lockfile(profile)
    return profile


# ------------------------------------------------------------------ sync

def _git_error(err: git_ops.GitError) -> HTTPException:
    LOG.warning("Git error (%s): %s", err.kind, err.detail or "-")
    status = {"remote_mismatch": 409, "dirty": 409, "config_missing": 500}.get(err.kind, 500)
    return HTTPException(status_code=status, detail=err.kind)


@app.get("/api/sync")
def sync_status() -> dict:
    try:
        return sync.full_status()
    except (git_ops.GitError, gh.GitHubError) as err:
        raise HTTPException(status_code=502, detail=getattr(err, "kind", "sync_failed")) from err


@app.post("/api/sync/couple")
def sync_couple(payload: dict = Body(default={})) -> dict:
    if not sync.configured():
        raise HTTPException(status_code=409, detail="not_configured")
    try:
        return sync.couple(force_remote=bool(payload.get("force_remote")))
    except git_ops.GitError as err:
        raise _git_error(err) from err


@app.post("/api/sync/commit")
def sync_commit(payload: dict = Body(default={})) -> dict:
    try:
        return sync.commit_now(payload.get("message"))
    except git_ops.GitError as err:
        raise _git_error(err) from err
    except gh.GitHubError as err:
        raise _github_error(err) from err


@app.post("/api/sync/pull")
def sync_pull() -> dict:
    try:
        return sync.pull_now()
    except git_ops.GitError as err:
        raise _git_error(err) from err
    except gh.GitHubError as err:
        raise _github_error(err) from err


@app.post("/api/sync/merge")
def sync_merge(payload: dict = Body(default={})) -> dict:
    try:
        return sync.merge_now(payload.get("message"))
    except git_ops.GitError as err:
        raise _git_error(err) from err
    except gh.GitHubError as err:
        raise _github_error(err) from err


@app.get("/api/settings")
def settings_get() -> dict:
    state = store.load()
    return {
        "settings": sync.effective_settings(state.get("sync_settings")),
        "repo": state.get("repo"),
        "profile": state.get("profile"),
        "github": {"login": state.get("github", {}).get("login")},
    }


@app.post("/api/sync/ensure-pr")
def sync_ensure_pr() -> dict:
    if not sync.configured():
        raise HTTPException(status_code=409, detail="not_configured")
    try:
        return sync.ensure_pr_now()
    except git_ops.GitError as err:
        raise _git_error(err) from err
    except gh.GitHubError as err:
        raise _github_error(err) from err


@app.post("/api/sync/check")
def sync_check() -> dict:
    return sync.check_core()


@app.post("/api/sync/restart")
def sync_restart() -> dict:
    result = sync.restart_core()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail="restart_failed")
    return result


@app.post("/api/sync/settings")
def sync_settings(payload: dict = Body(...)) -> dict:
    state = store.load()
    settings = {**sync.DEFAULT_SETTINGS, **state.get("sync_settings", {})}
    for key in ("auto_pull", "auto_commit", "notify_conflict", "notify_pr_waiting",
                "notify_restart"):
        if key in payload:
            settings[key] = bool(payload[key])
    for key in ("auto_commit_delay", "poll_interval"):
        if key in payload:
            settings[key] = max(15, int(payload[key]))
    if "pr_waiting_hours" in payload:
        settings["pr_waiting_hours"] = min(168, max(1, int(payload["pr_waiting_hours"])))
    if "language" in payload:
        language = str(payload["language"])
        if language not in i18n.LANGUAGES:
            raise HTTPException(status_code=400, detail="unknown_language")
        # A template still sitting at the old language's default follows the
        # switch; anything the user typed themselves stays untouched.
        if settings.get("commit_template") == i18n.t(settings.get("language"), "commit.template"):
            settings["commit_template"] = ""
        settings["language"] = language
    if "commit_template" in payload:
        # Empty means "follow the language default" (see sync.effective_settings).
        settings["commit_template"] = str(payload["commit_template"]).strip()[:120]
    store.update(sync_settings=settings)
    return sync.effective_settings(settings)


# ------------------------------------------------------------- .gitignore

@app.get("/api/gitignore")
def gitignore_get() -> dict:
    target = Path(CONFIG_DIR) / ".gitignore"
    if not target.exists():
        return {"exists": False, "content": ""}
    return {"exists": True, "content": target.read_text()}


@app.put("/api/gitignore")
def gitignore_put(payload: dict = Body(...)) -> dict:
    content = payload.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="missing_content")
    target = Path(CONFIG_DIR) / ".gitignore"
    target.write_text(content if content.endswith("\n") or not content else content + "\n")
    return {"exists": True, "content": target.read_text()}


# ------------------------------------------------------------- GitHub proxy

@app.get("/api/github/repos")
def github_repos() -> list[dict]:
    try:
        return gh.list_repos(_token())
    except gh.GitHubError as err:
        raise _github_error(err) from err


@app.post("/api/github/repos")
def github_create_repo(payload: dict = Body(...)) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")
    try:
        return gh.create_repo(_token(), name)
    except gh.GitHubError as err:
        raise _github_error(err) from err


@app.get("/api/github/branches")
def github_branches(repo: str) -> list[str]:
    try:
        return gh.list_branches(_token(), repo)
    except gh.GitHubError as err:
        raise _github_error(err) from err


@app.get("/api/github/gitignore")
def github_gitignore(repo: str, ref: str) -> dict:
    """Does the chosen repo already carry a .gitignore? (wizard default)"""
    try:
        content = gh.get_file(_token(), repo, ".gitignore", ref)
    except gh.GitHubError as err:
        raise _github_error(err) from err
    return {"exists": content is not None, "content": content or ""}


# ---------------------------------------------------------------- git status

def _git(*args: str) -> tuple[int, str]:
    """Run git against CONFIG_DIR, returning (exit code, stripped stdout)."""
    try:
        result = subprocess.run(
            ["git", "-C", CONFIG_DIR, *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return 1, str(err)
    return result.returncode, result.stdout.strip()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict:
    """Git state of the configuration directory, for the status page."""
    if not os.path.isdir(CONFIG_DIR):
        return {"config_dir": CONFIG_DIR, "exists": False, "is_repo": False}

    code, _ = _git("rev-parse", "--is-inside-work-tree")
    if code != 0:
        return {"config_dir": CONFIG_DIR, "exists": True, "is_repo": False}

    _, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    remote_code, remote = _git("remote", "get-url", "origin")
    _, last_commit = _git("log", "-1", "--format=%h␟%s␟%cr")

    changes = []
    code, porcelain = _git("status", "--porcelain")
    if code == 0 and porcelain:
        for line in porcelain.splitlines():
            changes.append({"state": line[:2].strip() or "??", "path": line[3:]})

    ahead = behind = None
    code, counts = _git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if code == 0 and counts:
        left, _, right = counts.partition("\t")
        ahead, behind = int(left), int(right)

    commit = None
    if last_commit:
        parts = last_commit.split("␟")
        if len(parts) == 3:
            commit = {"hash": parts[0], "subject": parts[1], "when": parts[2]}

    return {
        "config_dir": CONFIG_DIR,
        "exists": True,
        "is_repo": True,
        "branch": branch,
        "remote": remote if remote_code == 0 else None,
        "last_commit": commit,
        "changes": changes,
        "ahead": ahead,
        "behind": behind,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
