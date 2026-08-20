"""Git operations against the Home Assistant configuration directory.

Working model: the working tree lives permanently on the *sync branch*.
The main branch is the source of truth — it only ever changes through the
merge of the collecting pull request. Local edits are committed onto the
sync branch and pushed; incoming main commits are merged into the sync
branch (a conflict there is the same conflict GitHub shows in the PR, and
is resolved there, never locally).

Authentication: the GitHub token is injected per invocation via an
`http.extraheader` (like actions/checkout does) — it is never written to
the repository's .git/config.
"""

import base64
import json
import os
import subprocess
import threading
from pathlib import Path

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/homeassistant")

# Mutating git operations are serialized (API calls + background poller).
LOCK = threading.RLock()

ALWAYS_EXCLUDE = [
    "secrets.yaml",
    ".storage/",
    ".cloud/",
    ".ssh/",
    ".git-credentials",
    "*.db",
    "*.db-shm",
    "*.db-wal",
    "*.log*",
    ".uuid",
    ".ha_run.lock",
    "ip_bans.yaml",
    ".cache/",
    "deps/",
    "tts/",
    "image/",
    "backups/",
    "__pycache__/",
    "esphome/.esphome/",
    "esphome/secrets.yaml",
]

GROUP_PATHS = {
    "core": ["configuration.yaml", "automations.yaml", "scripts.yaml", "scenes.yaml"],
    "blueprints": ["blueprints/", "dashboards/"],
    "esphome": ["esphome/"],
    "themes_www": ["themes/", "www/"],
    "apps": ["custom_components/"],
}

MARK_BEGIN = "# >>> git-sync managed block — do not edit between the markers"
MARK_END = "# <<< git-sync managed block"
LOCKFILE = "custom_components.lock.json"
COMMIT_IDENT = ["-c", "user.name=Git Sync", "-c", "user.email=git-sync@addon.local"]


class GitError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail or kind)
        self.kind = kind
        self.detail = detail


def _auth_args(token: str | None) -> list[str]:
    if not token:
        return []
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return [
        "-c", "credential.helper=",
        "-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}",
    ]


def _git(*args: str, token: str | None = None, timeout: int = 120,
         strip: bool = True) -> tuple[int, str, str]:
    cmd = ["git", "-C", CONFIG_DIR, "-c", f"safe.directory={CONFIG_DIR}"]
    cmd += _auth_args(token)
    cmd += list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        return 1, "", str(err)
    return result.returncode, result.stdout.strip() if strip else result.stdout, result.stderr.strip()


def _must(*args: str, token: str | None = None, timeout: int = 120) -> str:
    code, out, err = _git(*args, token=token, timeout=timeout)
    if code != 0:
        raise GitError("git_failed", f"git {' '.join(args[:3])}…: {err or out}")
    return out


def is_repo() -> bool:
    code, out, _ = _git("rev-parse", "--is-inside-work-tree")
    return code == 0 and out == "true"


def has_commits() -> bool:
    code, _, _ = _git("rev-parse", "--verify", "HEAD")
    return code == 0


def remote_url() -> str | None:
    code, out, _ = _git("remote", "get-url", "origin")
    return out if code == 0 else None


def current_branch() -> str | None:
    code, out, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    return out if code == 0 else None


def coupling_state(repo_cfg: dict) -> str:
    """not_a_repo | no_origin | remote_mismatch | wrong_branch | coupled"""
    if not os.path.isdir(CONFIG_DIR):
        return "config_missing"
    if not is_repo():
        return "not_a_repo"
    url = remote_url()
    if not url:
        return "no_origin"
    expected = repo_cfg["full_name"].lower()
    normalized = url.lower().removesuffix(".git")
    override = (repo_cfg.get("clone_url") or "").lower().removesuffix(".git")
    if normalized != override and not (
        normalized.endswith(f"github.com/{expected}")
        or normalized.endswith(f"github.com:{expected}")
    ):
        return "remote_mismatch"
    if current_branch() != repo_cfg["sync_branch"]:
        return "wrong_branch"
    return "coupled"


def couple(token: str, repo_cfg: dict, force_remote: bool = False) -> str:
    """Bring CONFIG_DIR into the working model; returns the final state."""
    # clone_url is a test seam (local bare repo); production always github.
    https_url = repo_cfg.get("clone_url") or f"https://github.com/{repo_cfg['full_name']}"
    main = repo_cfg["main_branch"]
    sync = repo_cfg["sync_branch"]

    with LOCK:
        state = coupling_state(repo_cfg)
        if state == "config_missing":
            raise GitError("config_missing", CONFIG_DIR)

        if state == "not_a_repo":
            _must("init", "-b", main)
            state = "no_origin"

        if state == "no_origin":
            _must("remote", "add", "origin", https_url)
        elif state == "remote_mismatch":
            if not force_remote:
                raise GitError("remote_mismatch", remote_url() or "")
            _must("remote", "set-url", "origin", https_url)

        # Reject SSH remotes — pushes authenticate via HTTPS token headers.
        url = remote_url() or ""
        if url.startswith("git@") or url.startswith("ssh://"):
            if not force_remote:
                raise GitError("remote_mismatch", url)
            _must("remote", "set-url", "origin", https_url)

        _must("fetch", "origin", main, token=token, timeout=300)

        if not has_commits():
            # Fresh repository around an existing config: adopt remote main as
            # the baseline; local differences stay as uncommitted changes.
            _must("update-ref", f"refs/heads/{main}", "FETCH_HEAD")
            _must("symbolic-ref", "HEAD", f"refs/heads/{main}")
            _must("reset", "--mixed", main)

        # Work on the sync branch from the current HEAD (no tree change).
        if current_branch() != sync:
            _must("checkout", "-B", sync)
        return coupling_state(repo_cfg)


def apply_excludes(profile: dict) -> None:
    """Write the managed block in .git/info/exclude (never the user's .gitignore).

    Profile "eigene_gitignore": the user's own .gitignore governs the sync
    scope — the managed block then carries only the non-negotiable safety
    exclusions.
    """
    lines = [MARK_BEGIN]
    lines += ALWAYS_EXCLUDE
    if profile.get("name") != "eigene_gitignore":
        groups = profile.get("groups", {})
        for key, paths in GROUP_PATHS.items():
            if key == "apps":
                continue
            if not groups.get(key, False):
                lines += paths
        if not groups.get("apps", False) or profile.get("apps_mode") == "lockfile":
            lines.append("custom_components/")
    lines.append(MARK_END)

    info = Path(CONFIG_DIR) / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    exclude = info / "exclude"
    existing = exclude.read_text() if exclude.exists() else ""
    if MARK_BEGIN in existing:
        head = existing.split(MARK_BEGIN)[0]
        tail = existing.split(MARK_END, 1)[1] if MARK_END in existing else ""
        existing = head + tail
    content = existing.rstrip("\n")
    exclude.write_text((content + "\n\n" if content else "") + "\n".join(lines) + "\n")


def write_lockfile(profile: dict) -> bool:
    """Record custom_components names+versions; returns True if file changed."""
    if profile.get("name") == "eigene_gitignore":
        return False
    if not profile.get("groups", {}).get("apps") or profile.get("apps_mode") != "lockfile":
        return False
    apps = {}
    root = Path(CONFIG_DIR) / "custom_components"
    if root.is_dir():
        for manifest in sorted(root.glob("*/manifest.json")):
            try:
                data = json.loads(manifest.read_text())
                apps[data.get("domain", manifest.parent.name)] = data.get("version", "unknown")
            except (OSError, ValueError):
                apps[manifest.parent.name] = "unreadable"
    target = Path(CONFIG_DIR) / LOCKFILE
    payload = json.dumps({"applications": apps}, indent=2, sort_keys=True) + "\n"
    if target.exists() and target.read_text() == payload:
        return False
    target.write_text(payload)
    return True


def local_changes() -> list[dict]:
    # Unstripped: an unstaged modification (" M …") in the first line starts
    # with a space — stripping it would shift the columns and eat the first
    # character of the path.
    code, out, _ = _git("status", "--porcelain", strip=False)
    if code != 0:
        return []
    return [{"state": line[:2].strip() or "??", "path": line[3:]}
            for line in out.splitlines() if line]


def commit_and_push(token: str, repo_cfg: dict, message: str, profile: dict) -> str | None:
    """Commit everything onto the sync branch and push. Returns commit sha."""
    with LOCK:
        write_lockfile(profile)
        if not local_changes():
            return None
        _must("add", "-A")
        _must(*COMMIT_IDENT, "commit", "-m", message)
        sha = _must("rev-parse", "--short", "HEAD")
        _must("push", "-u", "origin", repo_cfg["sync_branch"], token=token, timeout=300)
        return sha


def fetch(token: str, repo_cfg: dict) -> None:
    with LOCK:
        _must("fetch", "origin", repo_cfg["main_branch"], token=token, timeout=300)
        # The sync branch only exists on the remote after the first push —
        # a missing ref must not fail the whole fetch.
        sync = repo_cfg["sync_branch"]
        code, _, _ = _git("fetch", "origin", sync, token=token, timeout=300)
        if code != 0:
            # Deleted on the remote (PR merge)? Then drop the stale tracking
            # ref, or integrate() would merge the already-merged history back
            # in — an empty merge commit that resurrects the branch on GitHub.
            ls_code, _, _ = _git("ls-remote", "--exit-code", "origin",
                                 f"refs/heads/{sync}", token=token, timeout=60)
            if ls_code == 2:
                _git("update-ref", "-d", f"refs/remotes/origin/{sync}")


def incoming_count(repo_cfg: dict) -> int:
    code, out, _ = _git("rev-list", "--count", f"HEAD..origin/{repo_cfg['main_branch']}")
    return int(out) if code == 0 and out.isdigit() else 0


def incoming_commits(repo_cfg: dict, limit: int = 5) -> list[dict]:
    code, out, _ = _git("log", f"-{limit}", "--format=%h␟%s␟%cr",
                        f"HEAD..origin/{repo_cfg['main_branch']}")
    commits = []
    if code == 0 and out:
        for line in out.splitlines():
            parts = line.split("␟")
            if len(parts) == 3:
                commits.append({"hash": parts[0], "subject": parts[1], "when": parts[2]})
    return commits


def outgoing_commits(repo_cfg: dict, limit: int = 10) -> list[dict]:
    code, out, _ = _git("log", f"-{limit}", "--format=%h␟%s␟%cr",
                        f"origin/{repo_cfg['main_branch']}..HEAD")
    commits = []
    if code == 0 and out:
        for line in out.splitlines():
            parts = line.split("␟")
            if len(parts) == 3:
                commits.append({"hash": parts[0], "subject": parts[1], "when": parts[2]})
    return commits


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    code, _, _ = _git("merge-base", "--is-ancestor", ancestor, descendant)
    return code == 0


def integrate(token: str, repo_cfg: dict) -> str:
    """Bring origin/sync and origin/main into the local sync branch.

    Returns ok | conflict. A dirty tree must be committed by the caller
    first (commit early is the whole philosophy).

    A merge that would bring no content — identical trees, diverged history,
    the signature of a squash-merged PR — is skipped: it would only write an
    empty merge commit that re-imports the already-merged commits into the
    next PR.
    """
    sync = repo_cfg["sync_branch"]
    main = repo_cfg["main_branch"]
    with LOCK:
        if local_changes():
            raise GitError("dirty", "uncommitted changes")
        # GitHub-side updates of the PR branch (e.g. a conflict resolved in
        # the web editor) come first…
        code, remote_sync, _ = _git("rev-parse", "--verify", f"origin/{sync}")
        if code == 0:
            if _tree_of(f"origin/{sync}") == tree_hash():
                if not _is_ancestor(f"origin/{sync}", "HEAD"):
                    # The remote branch carries our content under stale
                    # pre-squash history (branch deletion after the PR merge
                    # never happened): reset it to the clean local history.
                    _git("push", f"--force-with-lease={sync}:{remote_sync}",
                         "origin", sync, token=token, timeout=300)
            else:
                merge_code, _, err = _git(*COMMIT_IDENT, "merge", "--no-edit", f"origin/{sync}")
                if merge_code != 0:
                    _git("merge", "--abort")
                    return "conflict"
        # …then main itself.
        if _tree_of(f"origin/{main}") == tree_hash() and not _is_ancestor(f"origin/{main}", "HEAD"):
            # Same content as main, diverged history: our commits arrived
            # there as a squash — restart the branch from main.
            _must("reset", "--hard", f"origin/{main}")
        else:
            merge_code, _, err = _git(*COMMIT_IDENT, "merge", "--no-edit", f"origin/{main}")
            if merge_code != 0:
                _git("merge", "--abort")
                return "conflict"
        # If the merge produced commits, keep the PR branch on GitHub current.
        code, out, _ = _git("rev-list", "--count", f"origin/{sync}..HEAD")
        if code == 0 and out.isdigit() and int(out) > 0:
            _git("push", "origin", sync, token=token, timeout=300)
        return "ok"


def realign_after_merge(token: str, repo_cfg: dict) -> None:
    """After the PR merged (squash), restart the sync branch from main."""
    sync = repo_cfg["sync_branch"]
    main = repo_cfg["main_branch"]
    with LOCK:
        _must("fetch", "origin", main, token=token, timeout=300)
        stashed = False
        if local_changes():
            _must("stash", "push", "-u", "-m", "git-sync: realign")
            stashed = True
        try:
            _must("checkout", "-B", sync, f"origin/{main}")
            # The merge flow just deleted the remote sync branch; drop the
            # tracking ref so the pre-squash history is never merged back in.
            _git("update-ref", "-d", f"refs/remotes/origin/{sync}")
        finally:
            if stashed:
                _git("stash", "pop")


def head_sha() -> str | None:
    code, out, _ = _git("rev-parse", "HEAD")
    return out if code == 0 else None


def tree_hash() -> str | None:
    code, out, _ = _git("rev-parse", "HEAD^{tree}")
    return out if code == 0 else None


def _tree_of(ref: str) -> str | None:
    code, out, _ = _git("rev-parse", f"{ref}^{{tree}}")
    return out if code == 0 else None


def last_commit() -> dict | None:
    code, out, _ = _git("log", "-1", "--format=%h␟%s␟%cr")
    if code != 0 or not out:
        return None
    parts = out.split("␟")
    return {"hash": parts[0], "subject": parts[1], "when": parts[2]} if len(parts) == 3 else None
