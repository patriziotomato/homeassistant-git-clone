# Git Sync

Couples your Home Assistant configuration to a GitHub repository.

## How it works

- Your **main branch is the source of truth**: changes merged there are
  pulled onto the instance automatically.
- **Local changes** (from the UI, File Editor, SSH, …) are committed onto a
  dedicated sync branch and collect in **one open pull request**.
- Merging that pull request is always a **manual action** — from this panel
  or on GitHub. Nothing is ever committed directly to main.
- **Conflicts are resolved on GitHub** in the pull request; the panel links
  you straight there.
- `secrets.yaml`, `.storage/`, databases and logs are **never** transferred.

## Current state

This is an early preview (milestone 4): setup wizard, the working sync
engine — coupling the configuration directory, auto-committing local edits
onto the sync branch, one collecting pull request, background auto-pull of
main, merging the PR from the panel (conflicts lock the merge and link to
the pull request on GitHub) — plus a settings view and persistent Home
Assistant notifications on conflicts and long-waiting sync PRs.

## Sync profiles

Presets (Komplett / Ohne Anwendungen / Nur Kern-Konfiguration /
Benutzerdefiniert) manage the sync scope through `.git/info/exclude` —
your own `.gitignore` is never modified. The profile **Eigene .gitignore**
hands the scope over to the repository's own `.gitignore`, editable right
in the panel; it is the default when the chosen repository already has one.
In every profile the safety exclusions (`secrets.yaml`, `.storage/`,
databases, logs, caches) remain built-in and cannot be disabled.

## GitHub token

The wizard asks for a personal access token:

- **Classic token**: `repo` scope.
- **Fine-grained token**: read/write access to *Contents* and
  *Pull requests* for the target repository.

The token is validated against the GitHub API and stored only in the app's
private `/data` volume on your instance. It is never written to the
repository and never returned by the app's API.

## Configuration

No add-on options yet — everything is configured in the panel. The app maps
your Home Assistant configuration directory read-write and serves its panel
through ingress.
