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
import i18n
import store

LOG = logging.getLogger("git-sync")

DEFAULT_SETTINGS = {
    "auto_pull": True,
    "auto_commit": True,
    "auto_commit_delay": 120,  # seconds of quiet before auto-committing
    # The *idle* cadence. Almost every tick used to return nothing — roughly
    # 1,400 fetches a day at the old 60 s default — so idling is slower now and
    # the fast phase below covers the moments that actually matter.
    "poll_interval": 300,
    # Empty values follow the UI language: "" means "not picked yet" for the
    # language, and "use this language's default" for the commit template.
    "language": "",
    "commit_template": "",
    "notify_conflict": True,
    "notify_pr_waiting": True,
    "pr_waiting_hours": 24,
    "notify_restart": True,
}

NOTIFY_CONFLICT_ID = "git_sync_conflict"
NOTIFY_PR_ID = "git_sync_pr_waiting"
NOTIFY_RESTART_ID = "git_sync_restart"

# Adaptive polling: after something happens, watch closely for a while, then
# fall back to the user's idle interval.
FAST_POLL_INTERVAL = 10    # seconds between polls during the fast phase
FAST_POLL_WINDOW = 180     # how long the fast phase lasts
MIN_POLL_INTERVAL = 15     # floor for the user's idle setting

_fast_until: float = 0.0


def begin_fast_poll(now: float | None = None) -> None:
    """Something just happened — poll closely for the next few minutes."""
    global _fast_until
    _fast_until = (time.time() if now is None else now) + FAST_POLL_WINDOW


def poll_interval(settings: dict, now: float | None = None) -> int:
    """Seconds until the next poll: the fast phase while something is going
    on, the user's idle interval otherwise."""
    now = time.time() if now is None else now
    if now < _fast_until:
        return FAST_POLL_INTERVAL
    return max(MIN_POLL_INTERVAL, int(settings["poll_interval"]))

# A commit is forced after this multiple of the delay even while edits keep
# arriving: without it, continuous editing would never commit at all — and an
# uncommitted tree also blocks auto-pull (see #28).
AUTO_COMMIT_CAP = 4

# Two clocks, because the quiet period and the cap measure different things:
# _quiet_since restarts whenever the change set differs from the previous
# tick, _dirty_since runs from the clean -> dirty transition and never
# restarts until the tree is clean again.
_dirty_since: float | None = None
_quiet_since: float | None = None
_dirty_signature: str | None = None


def _changes_signature(changes: list[dict]) -> str:
    """What the working tree looks like this tick — paths plus their states.

    Enough to notice an edit: a new file, a removed one, or a path moving
    between states. Not content — two saves of the same file inside one poll
    interval look identical, and a poll interval of quiet is not the point.
    """
    return "\n".join(sorted(f"{c['state']} {c['path']}" for c in changes))


def observe_changes(changes: list[dict], now: float) -> None:
    """Advance the quiet-period clocks from this tick's change set."""
    global _dirty_since, _quiet_since, _dirty_signature
    if not changes:
        _dirty_since = _quiet_since = _dirty_signature = None
        return
    signature = _changes_signature(changes)
    if _dirty_since is None:
        _dirty_since = now
    if signature != _dirty_signature:
        _dirty_signature = signature
        _quiet_since = now


def auto_commit_deadline(delay: int) -> float | None:
    """When the next automatic commit is due — quiet period or cap, whichever
    comes first. None while the tree is clean."""
    if _quiet_since is None or _dirty_since is None:
        return None
    return min(_quiet_since + delay, _dirty_since + delay * AUTO_COMMIT_CAP)


def _reset_quiet_period() -> None:
    global _dirty_since, _quiet_since, _dirty_signature
    _dirty_since = _quiet_since = _dirty_signature = None


def effective_settings(stored: dict | None = None) -> dict:
    """Defaults + stored values, with the language-dependent bits filled in."""
    settings = {**DEFAULT_SETTINGS, **(stored or {})}
    settings["language"] = i18n.resolve(settings.get("language"))
    if not settings.get("commit_template"):
        settings["commit_template"] = i18n.t(settings["language"], "commit.template")
    return settings


def _ctx():
    state = store.load()
    github = state.get("github", {})
    return (
        github.get("token"),
        state.get("repo"),
        state.get("profile"),
        effective_settings(state.get("sync_settings")),
    )


def configured() -> bool:
    token, repo, profile, _ = _ctx()
    return bool(token and repo and profile)


def couple(force_remote: bool = False, confirm_deletions: bool = False) -> dict:
    token, repo, profile, _ = _ctx()
    state = git_ops.couple(token, repo, force_remote=force_remote,
                           confirm_deletions=confirm_deletions)
    git_ops.apply_excludes(profile)
    git_ops.write_lockfile(profile)
    store.update(coupled_at=int(time.time()))
    return {"coupling": state}


def reassert_excludes() -> bool:
    """Re-write the managed safety block if it went missing (startup check).

    `.git/info/exclude` is untracked by design, so git never restores it: a
    backup predating the coupling, a hand-run git command or a partially
    restored snapshot can leave the configuration directory without a single
    exclusion. Nothing in the dashboard would show it — the next automatic
    commit would simply push secrets.yaml and .storage/ to the repository.
    """
    _, repo, profile, _ = _ctx()
    if not (repo and profile) or git_ops.coupling_state(repo) != "coupled":
        return False
    restored = git_ops.apply_excludes(profile)
    if restored:
        LOG.warning("Safety exclusions were missing or outdated in "
                    ".git/info/exclude — restored on startup")
    return restored


def ensure_pr(token: str, repo: dict, language: str | None = None) -> dict | None:
    """The one collecting PR — reuse the open one or create it on demand."""
    if not git_ops.outgoing_commits(repo, limit=1):
        return None  # nothing on the sync branch beyond main -> no PR needed
    pr = gh.find_open_pr(token, repo["full_name"], repo["sync_branch"])
    if pr:
        return pr
    return gh.create_pr(
        token, repo["full_name"], repo["sync_branch"], repo["main_branch"],
        i18n.t(language, "pr.title"), i18n.t(language, "pr.body"),
    )


def commit_now(message: str | None) -> dict:
    token, repo, profile, settings = _ctx()
    # Before the working tree is read: without the managed block a lost
    # .git/info/exclude would put secrets.yaml & friends into the change list
    # and from there into the commit message. commit_and_push() re-asserts it
    # again right before `add -A` — that is the guarantee, this is the tidy
    # message. Both are no-ops while the block is intact.
    if profile:
        git_ops.apply_excludes(profile)
    changes = git_ops.local_changes()
    if not changes and not message:
        return {"committed": None}
    text = (message or "").strip() or auto_message(changes, settings)
    sha = git_ops.commit_and_push(token, repo, text, profile)
    _reset_quiet_period()
    # The commit is safely pushed at this point — a failing PR creation must
    # not fail the whole call. The poller and the dashboard retry it.
    try:
        pr = ensure_pr(token, repo, settings["language"])
    except gh.GitHubError as err:
        LOG.warning("Sync PR could not be created (%s): %s", err.kind, err.detail or "-")
        return {"committed": sha, "pr": None, "pr_error": err.kind}
    return {"committed": sha, "pr": pr}


def ensure_pr_now() -> dict:
    """Create the collecting PR on demand (dashboard action / self-heal)."""
    token, repo, _, settings = _ctx()
    return {"pr": ensure_pr(token, repo, settings["language"])}


def auto_message(changes: list[dict], settings: dict | None = None) -> str:
    settings = settings or effective_settings()
    language = settings.get("language")
    paths = [c["path"] for c in changes]
    if not paths:
        return i18n.t(language, "commit.fallback")
    head = ", ".join(paths[:2])
    more = i18n.t(language, "commit.more", count=len(paths) - 2) if len(paths) > 2 else ""
    template = settings.get("commit_template") or i18n.t(language, "commit.template")
    # Both spellings stay live so a template survives a language switch.
    files, count = head + more, str(len(paths))
    return (template
            .replace("{dateien}", files).replace("{files}", files)
            .replace("{anzahl}", count).replace("{count}", count))


def merge_suggested_message(pr_number: int, repo: dict, settings: dict) -> str:
    """Prefill for the merge-commit text: the PR's whole diff summarized
    like an automatic commit message, plus the PR reference GitHub links."""
    files = [{"path": path} for path in git_ops.outgoing_files(repo)]
    return f"{auto_message(files, settings)} (#{pr_number})"


def _notify_conflict(active: bool, settings: dict) -> None:
    """Edge-triggered persistent notification for the conflict state."""
    state = store.load().get("notify_state", {})
    was_active = bool(state.get("conflict"))
    if active == was_active:
        return
    state["conflict"] = active
    store.update(notify_state=state)
    if active and settings.get("notify_conflict"):
        language = settings.get("language")
        ha.notify(
            NOTIFY_CONFLICT_ID,
            i18n.t(language, "notify.conflict.title"),
            i18n.t(language, "notify.conflict.body"),
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
        language = settings.get("language")
        ha.notify(
            NOTIFY_PR_ID,
            i18n.t(language, "notify.pr_waiting.title"),
            i18n.t(language, "notify.pr_waiting.body",
                   number=pr["number"], hours=settings.get("pr_waiting_hours", 24)),
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
    language = settings.get("language")
    if ok:
        ha.notify(
            NOTIFY_RESTART_ID,
            i18n.t(language, "notify.restart.title"),
            i18n.t(language, "notify.restart.body"),
        )
    elif ok is False:
        ha.notify(
            NOTIFY_RESTART_ID,
            i18n.t(language, "notify.check_failed.title"),
            i18n.t(language, "notify.check_failed.body",
                   message=message or i18n.t(language, "notify.check_failed.see_panel")),
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


def reload_core() -> dict:
    """Reload the reloadable YAML without restarting Home Assistant.

    restart_pending is deliberately NOT cleared: reload does not cover the
    homeassistant: block, integration setup, custom_components/ or anything
    evaluated only at startup. Presenting a reload as "everything applied"
    would leave a half-applied configuration with no signal that something is
    missing — worse than asking for a restart too often. The banner stays,
    says what a reload does not cover, and keeps offering the restart.
    """
    if not ha.core_reload():
        return {"ok": False}
    core = store.load().get("core", {})
    core["reloaded_at"] = int(time.time())
    store.update(core=core)
    return {"ok": True, "core": core}


def dismiss_restart() -> dict:
    """Clear the pending-restart flag without restarting.

    _after_apply() sets the flag whenever a pull changed files, and until now
    restart_core() was the only thing clearing it — a restart from Developer
    Tools, the Supervisor UI, `ha core restart` or a power cycle left the
    banner standing for good, telling the user to do what they had just done.
    """
    store.update(core={"restart_pending": False, "check": None})
    ha.dismiss(NOTIFY_RESTART_ID)
    return {"ok": True}


def pull_now() -> dict:
    """Fetch and integrate origin/sync + origin/main into the local branch."""
    token, repo, _, settings = _ctx()
    git_ops.fetch(token, repo)
    if git_ops.local_changes():
        commit_now(None)  # commit-first keeps merges clean
    before = git_ops.tree_hash()
    result = git_ops.integrate(token, repo)
    begin_fast_poll()  # the user is syncing right now — stay close for a while
    if result == "ok":
        store.update(last_pull=int(time.time()))
        # Tree comparison, not head: history-only updates (skipped empty
        # merges, realigned branch) change no files and need no restart.
        if git_ops.tree_hash() != before:
            _after_apply(settings)
    _notify_conflict(result == "conflict", settings)
    return {"result": result}


def merge_now(message: str | None = None) -> dict:
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
    outcome = gh.merge_pr(token, repo["full_name"], pr["number"],
                          commit_title=(message or "").strip() or None)
    if not outcome.get("merged"):
        return {"merged": False, "error": "merge_failed", "pr": detail}
    gh.delete_branch(token, repo["full_name"], repo["sync_branch"])
    begin_fast_poll()  # the moment the user is watching
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
    due = auto_commit_deadline(settings["auto_commit_delay"])
    result.update(
        changes=changes,
        suggested_message=auto_message(changes, settings) if changes else None,
        last_commit=git_ops.last_commit(),
        incoming=git_ops.incoming_commits(repo),
        incoming_count=git_ops.incoming_count(repo),
        applied=git_ops.applied_commits(repo),
        outgoing=git_ops.outgoing_commits(repo),
        core=state.get("core"),
        auto_commit_at=(
            int(due) if due is not None and settings["auto_commit"] and changes else None
        ),
    )
    try:
        pr = gh.find_open_pr(token, repo["full_name"], repo["sync_branch"])
        if pr:
            pr = gh.get_pr(token, repo["full_name"], pr["number"])
            result["merge_suggested_message"] = merge_suggested_message(
                pr["number"], repo, settings)
        result["pr"] = pr
    except gh.GitHubError as err:
        result["pr_error"] = err.kind
    return result


_last_pr_check = 0.0


async def poller():
    """Background loop: watch for local edits (auto-commit after a quiet
    period), new commits on main (auto-pull), and notification triggers."""
    global _last_pr_check
    while True:
        try:
            token, repo, profile, settings = _ctx()
            if token and repo and profile and git_ops.coupling_state(repo) == "coupled":
                changes = await asyncio.to_thread(git_ops.local_changes)
                now = time.time()
                observe_changes(changes, now)
                due = auto_commit_deadline(settings["auto_commit_delay"])
                if changes and settings["auto_commit"] and due is not None and now >= due:
                    await asyncio.to_thread(commit_now, None)
                if settings["auto_pull"]:
                    await asyncio.to_thread(git_ops.fetch, token, repo)
                    behind = git_ops.incoming_count(repo)
                    dirty = bool(await asyncio.to_thread(git_ops.local_changes))
                    if behind and not dirty:
                        before = git_ops.tree_hash()
                        result = await asyncio.to_thread(git_ops.integrate, token, repo)
                        if result == "ok":
                            # Activity begets activity: having just taken
                            # something over, look again soon.
                            begin_fast_poll()
                            store.update(last_pull=int(time.time()))
                            if git_ops.tree_hash() != before:
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
                            await asyncio.to_thread(ensure_pr, token, repo, settings["language"])
                        except gh.GitHubError as err:
                            LOG.warning("Collecting PR is missing and could not be created (%s): %s",
                                        err.kind, err.detail or "-")
                    if has_outgoing or reminded:
                        await asyncio.to_thread(_check_pr_reminder, token, repo, settings)
            interval = poll_interval(settings) if configured() else 30
        except Exception:  # never let the loop die
            LOG.exception("poller iteration failed")
            interval = 60
        await asyncio.sleep(interval)
