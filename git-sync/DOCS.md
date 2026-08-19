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

This is an early preview (milestone 1): the panel shows the git status of
your configuration directory. GitHub connection, sync profiles and the
pull-request workflow are under active development.

## Configuration

No options yet. The app maps your Home Assistant configuration directory
read-write and serves its panel through ingress.
