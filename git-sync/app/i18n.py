"""User-facing backend texts in the languages the panel offers.

The panel itself carries its own dictionary; this module covers everything
the backend writes on its own — the collecting pull request, the persistent
Home Assistant notifications and the automatic commit messages.

The chosen language lives in the sync settings ("language"); an empty value
means "not picked yet" and falls back to DEFAULT_LANGUAGE.
"""

DEFAULT_LANGUAGE = "de"
LANGUAGES = ("de", "en")

TEXTS = {
    "de": {
        "pr.title": "Sync: Lokale Änderungen aus Home Assistant",
        "pr.body": (
            "Dieser Pull Request wird von der Git-Sync-App gepflegt. Lokale Änderungen "
            "aus Home Assistant sammeln sich hier als Commits.\n\n"
            "Mergen — hier oder aus der App — übernimmt sie in den Main-Branch; die "
            "App setzt den Sync-Branch danach automatisch neu auf."
        ),
        "commit.template": "Sync: {dateien}",
        "commit.fallback": "Sync: Änderungen aus Home Assistant",
        "commit.more": " (+{count} weitere)",
        "notify.conflict.title": "Git Sync: Konflikt",
        "notify.conflict.body": (
            "Deine Änderungen und der Main-Branch widersprechen sich. "
            "Bitte löse den Konflikt im Pull Request auf GitHub — "
            "danach geht es automatisch weiter."
        ),
        "notify.pr_waiting.title": "Git Sync: Sync-PR wartet auf Merge",
        "notify.pr_waiting.body": (
            "Pull Request #{number} sammelt seit über {hours} Stunden Änderungen. "
            "Merge ihn im Git-Sync-Panel oder auf GitHub, um main zu aktualisieren."
        ),
        "notify.restart.title": "Git Sync: Neustart empfohlen",
        "notify.restart.body": (
            "Änderungen aus main wurden übernommen und die Konfigurationsprüfung "
            "war erfolgreich. Starte Home Assistant über das Git-Sync-Panel neu, "
            "um sie zu aktivieren."
        ),
        "notify.check_failed.title": "Git Sync: Konfigurationsprüfung fehlgeschlagen",
        "notify.check_failed.body": (
            "Änderungen aus main wurden übernommen, aber `ha core check` meldet "
            "einen Fehler: {message}. Bitte vor einem Neustart korrigieren."
        ),
        "notify.check_failed.see_panel": "siehe Panel",
    },
    "en": {
        "pr.title": "Sync: local changes from Home Assistant",
        "pr.body": (
            "This pull request is maintained by the Git Sync app. Local changes "
            "from Home Assistant collect here as commits.\n\n"
            "Merging it — here or from the app — brings them into the main branch; "
            "the app then restarts the sync branch from main automatically."
        ),
        "commit.template": "Sync: {files}",
        "commit.fallback": "Sync: changes from Home Assistant",
        "commit.more": " (+{count} more)",
        "notify.conflict.title": "Git Sync: conflict",
        "notify.conflict.body": (
            "Your changes and the main branch contradict each other. "
            "Please resolve the conflict in the pull request on GitHub — "
            "everything continues automatically afterwards."
        ),
        "notify.pr_waiting.title": "Git Sync: sync PR is waiting for a merge",
        "notify.pr_waiting.body": (
            "Pull request #{number} has been collecting changes for more than "
            "{hours} hours. Merge it in the Git Sync panel or on GitHub to update main."
        ),
        "notify.restart.title": "Git Sync: restart recommended",
        "notify.restart.body": (
            "Changes from main have been applied and the configuration check "
            "succeeded. Restart Home Assistant from the Git Sync panel to "
            "activate them."
        ),
        "notify.check_failed.title": "Git Sync: configuration check failed",
        "notify.check_failed.body": (
            "Changes from main have been applied, but `ha core check` reports "
            "an error: {message}. Please fix it before restarting."
        ),
        "notify.check_failed.see_panel": "see the panel",
    },
}


def resolve(language: str | None) -> str:
    """Map a stored (possibly empty or unknown) value to a supported language."""
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


def t(language: str | None, key: str, **values: object) -> str:
    """Look up a text and fill in its {placeholders}.

    Substitution is a plain replace, not str.format — texts such as the
    commit template deliberately carry placeholders that stay untouched.
    """
    texts = TEXTS[resolve(language)]
    text = texts.get(key, TEXTS[DEFAULT_LANGUAGE].get(key, key))
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text
