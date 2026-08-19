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
import ha
import store

LOG = logging.getLogger("git-sync")

DEFAULT_SETTINGS = {
    "auto_pull": True,
    "auto_commit": True,
    "auto_commit_delay": 120,  # seconds of quiet before auto-committing
    "poll_interval": 60,
    "commit_template": "Sync: {dateien}",
    "notify_conflict": True,
    "notify_pr_waiting": True,
    "pr_waiting_hours": 24,
    "notify_restart": True,
}

NOTIFY_CONFLICT_ID = "git_sync_conflict"
NOTIFY_PR_ID = "git_sync_pr_waiting"
NOTIFY_RESTART_ID = "git_sync_restart"

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
    token, repo, profile, settings = _ctx()
    changes = git_ops.local_changes()
    if not changes and not message:
        return {"committed": None}
    text = (message or "").strip() or auto_message(changes, settings)
    sha = git_ops.commit_and_push(token, repo, text, profile)
    _first_dirty_at = None
    # The commit is safely pushed at this point — a failing PR creation must
    # not fail the whole call. The poller and the dashboard retry it.
    try:
        pr = ensure_pr(token, repo)
    except gh.GitHubError as err:
        LOG.warning("Sync-PR konnte nicht angelegt werden (%s): %s", err.kind, err.detail or "-")
        return {"committed": sha, "pr": None, "pr_error": err.kind}
    return {"committed": sha, "pr": pr}


def ensure_pr_now() -> dict:
    """Create the collecting PR on demand (dashboard action / self-heal)."""
    token, repo, _, _ = _ctx()
    return {"pr": ensure_pr(token, repo)}


def auto_message(changes: list[dict], settings: dict | None = None) -> str:
    paths = [c["path"] for c in changes]
    if not paths:
        return "Sync: Änderungen aus Home Assistant"
    head = ", ".join(paths[:2])
    more = f" (+{len(paths) - 2} weitere)" if len(paths) > 2 else ""
    template = (settings or {}).get("commit_template") or DEFAULT_SETTINGS["commit_template"]
    return template.replace("{dateien}", head + more).replace("{anzahl}", str(len(paths)))


def _notify_conflict(active: bool, settings: dict) -> None:
    """Edge-triggered persistent notification for the conflict state."""
    state = store.load().get("notify_state", {})
    was_active = bool(state.get("conflict"))
    if active == was_active:
        return
    state["conflict"] = active
    store.update(notify_state=state)
    if active and settings.get("notify_conflict"):
        ha.notify(
            NOTIFY_CONFLICT_ID,
            "Git Sync: Konflikt",
            "Deine Änderungen und der Main-Branch widersprechen sich. "
            "Bitte löse den Konflikt im Pull Request auf GitHub — "
            "danach geht es automatisch weiter.",
        )
    elif not active:
        ha.dismiss(NOTIFY_CONFLICT_ID)


def _check_pr_reminder(token: str, repo: dict, settings: dict) -> None:
    """Remind once per PR when it has been waiting for a merge too long."""
    import datetime

    state = store.load().get("notify_state", {})
    pr = gh.find_open_pr(token, repo["full_name"], repo["sync_branch"])
    if not pr:
        if state.get("pr_reminded") is not None:
            state["pr_reminded"] = None
            store.update(notify_state=state)
            ha.dismiss(NOTIFY_PR_ID)
        return
    if not settings.get("notify_pr_waiting") or state.get("pr_reminded") == pr["number"]:
        return
    created = pr.get("created_at")
    if not created:
        return
    opened = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
    age_hours = (datetime.datetime.now(datetime.timezone.utc) - opened).total_seconds() / 3600
    if age_hours >= settings.get("pr_waiting_hours", 24):
        state["pr_reminded"] = pr["number"]
        store.update(notify_state=state)
        ha.notify(
            NOTIFY_PR_ID,
            "Git Sync: Sync-PR wartet auf Merge",
            f"Pull Request #{pr['number']} sammelt seit über "
            f"{settings.get('pr_waiting_hours', 24)} Stunden Änderungen. "
            "Merge ihn im Git-Sync-Panel oder auf GitHub, um main zu aktualisieren.",
        )


def _after_apply(settings: dict) -> None:
    """Remote changes just landed in /config: run `ha core check` and flag
    that a core restart is pending — the restart itself is always a manual,
    user-confirmed action."""
    ok, message = ha.core_check()
    result = "ok" if ok else ("unavailable" if ok is None else "error")
    store.update(core={
        "restart_pending": True,
        "check": {"result": result, "message": message, "at": int(time.time())},
    })
    if not settings.get("notify_restart"):
        return
    if ok:
        ha.notify(
            NOTIFY_RESTART_ID,
            "Git Sync: Neustart empfohlen",
            "Änderungen aus main wurden übernommen und die Konfigurations"
            "prüfung war erfolgreich. Starte Home Assistant über das "
            "Git-Sync-Panel neu, um sie zu aktivieren.",
        )
    elif ok is False:
        ha.notify(
            NOTIFY_RESTART_ID,
            "Git Sync: Konfigurationsprüfung fehlgeschlagen",
            "Änderungen aus main wurden übernommen, aber `ha core check` "
            f"meldet einen Fehler: {message or 'siehe Panel'}. "
            "Bitte vor einem Neustart korrigieren.",
        )


def check_core() -> dict:
    """Re-run the configuration check without touching the pending flag."""
    ok, message = ha.core_check()
    state = store.load().get("core", {})
    state["check"] = {
        "result": "ok" if ok else ("unavailable" if ok is None else "error"),
        "message": message,
        "at": int(time.time()),
    }
    store.update(core=state)
    return state


def restart_core() -> dict:
    if not ha.core_restart():
        return {"ok": False}
    store.update(core={"restart_pending": False, "check": None})
    ha.dismiss(NOTIFY_RESTART_ID)
    return {"ok": True}


def pull_now() -> dict:
    """Fetch and integrate origin/sync + origin/main into the local branch."""
    token, repo, _, settings = _ctx()
    git_ops.fetch(token, repo)
    if git_ops.local_changes():
        commit_now(None)  # commit-first keeps merges clean
    before = git_ops.head_sha()
    result = git_ops.integrate(token, repo)
    if result == "ok":
        store.update(last_pull=int(time.time()))
        if git_ops.head_sha() != before:
            _after_apply(settings)
    _notify_conflict(result == "conflict", settings)
    return {"result": result}


def merge_now() -> dict:
    token, repo, _, settings = _ctx()
    if git_ops.local_changes():
        commit_now(None)
    pr = gh.find_open_pr(token, repo["full_name"], repo["sync_branch"])
    if not pr:
        return {"merged": False, "error": "no_pr"}
    detail = gh.get_pr(token, repo["full_name"], pr["number"])
    if detail.get("mergeable") is False:
        _notify_conflict(True, settings)
        return {"merged": False, "error": "conflict", "pr": detail}
    outcome = gh.merge_pr(token, repo["full_name"], pr["number"])
    if not outcome.get("merged"):
        return {"merged": False, "error": "merge_failed", "pr": detail}
    gh.delete_branch(token, repo["full_name"], repo["sync_branch"])
    tree_before = git_ops.tree_hash()
    git_ops.realign_after_merge(token, repo)
    store.update(last_pull=int(time.time()), notify_state={"conflict": False, "pr_reminded": None})
    ha.dismiss(NOTIFY_CONFLICT_ID)
    ha.dismiss(NOTIFY_PR_ID)
    # Content only changes here when the merge brought more than our own
    # commits (e.g. a conflict resolved on GitHub) — then check + restart.
    if git_ops.tree_hash() != tree_before:
        _after_apply(settings)
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
        core=state.get("core"),
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


_last_pr_check = 0.0


async def poller():
    """Background loop: watch for local edits (auto-commit after a quiet
    period), new commits on main (auto-pull), and notification triggers."""
    global _first_dirty_at, _last_pr_check
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
                        before = git_ops.head_sha()
                        result = await asyncio.to_thread(git_ops.integrate, token, repo)
                        if result == "ok":
                            store.update(last_pull=int(time.time()))
                            if git_ops.head_sha() != before:
                                await asyncio.to_thread(_after_apply, settings)
                        _notify_conflict(result == "conflict", settings)
                # PR-Pflege: höchstens alle 5 Minuten — fehlt der Sammel-PR
                # trotz bereitliegender Commits (z. B. weil die Erstellung
                # einmal fehlschlug), wird er hier nachgeholt; danach die
                # Warte-Erinnerung.
                if time.time() - _last_pr_check > 300:
                    _last_pr_check = time.time()
                    has_outgoing = bool(git_ops.outgoing_commits(repo, limit=1))
                    reminded = store.load().get("notify_state", {}).get("pr_reminded") is not None
                    if has_outgoing:
                        try:
                            await asyncio.to_thread(ensure_pr, token, repo)
                        except gh.GitHubError as err:
                            LOG.warning("Sammel-PR fehlt und konnte nicht angelegt werden (%s): %s",
                                        err.kind, err.detail or "-")
                    if has_outgoing or reminded:
                        await asyncio.to_thread(_check_pr_reminder, token, repo, settings)
            interval = settings["poll_interval"] if configured() else 30
        except Exception:  # never let the loop die
            LOG.exception("poller iteration failed")
            interval = 60
        await asyncio.sleep(max(15, interval))
