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

This is an early preview (milestone 2): the panel walks you through the
setup — GitHub token, repository & branches, sync profile — and shows the
git status of your configuration directory. The actual sync engine
(auto-commit, the accumulating pull request, auto-pull) is under active
development.

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
