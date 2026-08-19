"""Sync engine: couples the config directory, keeps ONE collecting pull
request for local changes, pulls main automatically, and merges the PR only
on explicit request. Conflicts are never resolved locally — the PR on
GitHub is the place for that.
"""

import asyncio
import logging
import time

import gh
import git_ops
import store

LOG = logging.getLogger("git-sync")

DEFAULT_SETTINGS = {
    "auto_pull": True,
    "auto_commit": True,
    "auto_commit_delay": 120,  # seconds of quiet before auto-committing
    "poll_interval": 60,
}

PR_TITLE = "Sync: Lokale Änderungen aus Home Assistant"
PR_BODY = (
    "Dieser Pull Request wird von der Git-Sync-App gepflegt. Lokale Änderungen "
    "aus Home Assistant sammeln sich hier als Commits.\n\n"
    "Mergen — hier oder aus der App — übernimmt sie in den Main-Branch; die "
    "App setzt den Sync-Branch danach automatisch neu auf."
)

_first_dirty_at: float | None = None


def _ctx():
    state = store.load()
    github = state.get("github", {})
    return (
        github.get("token"),
        state.get("repo"),
        state.get("profile"),
        {**DEFAULT_SETTINGS, **state.get("sync_settings", {})},
    )


def configured() -> bool:
    token, repo, profile, _ = _ctx()
    return bool(token and repo and profile)


def couple(force_remote: bool = False) -> dict:
    token, repo, profile, _ = _ctx()
    state = git_ops.couple(token, repo, force_remote=force_remote)
    git_ops.apply_excludes(profile)
    git_ops.write_lockfile(profile)
    store.update(coupled_at=int(time.time()))
    return {"coupling": state}


def ensure_pr(token: str, repo: dict) -> dict | None:
    """The one collecting PR — reuse the open one or create it on demand."""
    if not git_ops.outgoing_commits(repo, limit=1):
        return None  # nothing on the sync branch beyond main -> no PR needed
    pr = gh.find_open_pr(token, repo["full_name"], repo["sync_branch"])
    if pr:
        return pr
    return gh.create_pr(
        token, repo["full_name"], repo["sync_branch"], repo["main_branch"],
        PR_TITLE, PR_BODY,
    )


def commit_now(message: str | None) -> dict:
    global _first_dirty_at
    token, repo, profile, _ = _ctx()
    changes = git_ops.local_changes()
    if not changes and not message:
        return {"committed": None}
    text = (message or "").strip() or auto_message(changes)
    sha = git_ops.commit_and_push(token, repo, text, profile)
    _first_dirty_at = None
    pr = ensure_pr(token, repo)
    return {"committed": sha, "pr": pr}


def auto_message(changes: list[dict]) -> str:
    paths = [c["path"] for c in changes]
    head = ", ".join(paths[:2])
    more = f" (+{len(paths) - 2} weitere)" if len(paths) > 2 else ""
    return f"Sync: {head}{more}" if paths else "Sync: Änderungen aus Home Assistant"


def pull_now() -> dict:
    """Fetch and integrate origin/sync + origin/main into the local branch."""
    token, repo, _, _ = _ctx()
    git_ops.fetch(token, repo)
    if git_ops.local_changes():
        commit_now(None)  # commit-first keeps merges clean
    result = git_ops.integrate(token, repo)
    if result == "ok":
        store.update(last_pull=int(time.time()))
    return {"result": result}


def merge_now() -> dict:
    token, repo, _, _ = _ctx()
    if git_ops.local_changes():
        commit_now(None)
    pr = gh.find_open_pr(token, repo["full_name"], repo["sync_branch"])
    if not pr:
        return {"merged": False, "error": "no_pr"}
    detail = gh.get_pr(token, repo["full_name"], pr["number"])
    if detail.get("mergeable") is False:
        return {"merged": False, "error": "conflict", "pr": detail}
    outcome = gh.merge_pr(token, repo["full_name"], pr["number"])
    if not outcome.get("merged"):
        return {"merged": False, "error": "merge_failed", "pr": detail}
    gh.delete_branch(token, repo["full_name"], repo["sync_branch"])
    git_ops.realign_after_merge(token, repo)
    store.update(last_pull=int(time.time()))
    return {"merged": True, "pr": detail}


def full_status() -> dict:
    token, repo, profile, settings = _ctx()
    state = store.load()
    if not (token and repo and profile):
        return {"configured": False}

    coupling = git_ops.coupling_state(repo)
    result: dict = {
        "configured": True,
        "coupling": coupling,
        "repo": repo,
        "settings": settings,
        "last_pull": state.get("last_pull"),
    }
    if coupling == "remote_mismatch":
        result["current_remote"] = git_ops.remote_url()
    if coupling != "coupled":
        return result

    changes = git_ops.local_changes()
    result.update(
        changes=changes,
        suggested_message=auto_message(changes) if changes else None,
        last_commit=git_ops.last_commit(),
        incoming=git_ops.incoming_commits(repo),
        incoming_count=git_ops.incoming_count(repo),
        outgoing=git_ops.outgoing_commits(repo),
        auto_commit_at=(
            int(_first_dirty_at + settings["auto_commit_delay"])
            if _first_dirty_at and settings["auto_commit"] and changes
            else None
        ),
    )
    try:
        pr = gh.find_open_pr(token, repo["full_name"], repo["sync_branch"])
        if pr:
            pr = gh.get_pr(token, repo["full_name"], pr["number"])
        result["pr"] = pr
    except gh.GitHubError as err:
        result["pr_error"] = err.kind
    return result


async def poller():
    """Background loop: watch for local edits (auto-commit after a quiet
    period) and for new commits on main (auto-pull)."""
    global _first_dirty_at
    while True:
        try:
            token, repo, profile, settings = _ctx()
            if token and repo and profile and git_ops.coupling_state(repo) == "coupled":
                changes = await asyncio.to_thread(git_ops.local_changes)
                if changes:
                    if _first_dirty_at is None:
                        _first_dirty_at = time.time()
                    quiet = time.time() - _first_dirty_at
                    if settings["auto_commit"] and quiet >= settings["auto_commit_delay"]:
                        await asyncio.to_thread(commit_now, None)
                else:
                    _first_dirty_at = None
                if settings["auto_pull"]:
                    await asyncio.to_thread(git_ops.fetch, token, repo)
                    behind = git_ops.incoming_count(repo)
                    dirty = bool(await asyncio.to_thread(git_ops.local_changes))
                    if behind and not dirty:
                        await asyncio.to_thread(git_ops.integrate, token, repo)
                        store.update(last_pull=int(time.time()))
            interval = settings["poll_interval"] if configured() else 30
        except Exception:  # never let the loop die
            LOG.exception("poller iteration failed")
            interval = 60
        await asyncio.sleep(max(15, interval))
