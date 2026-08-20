# Git Sync — Home Assistant App

Couple your Home Assistant configuration to a GitHub repository with a
pull-request-based workflow.

## The idea

Most git-backed Home Assistant setups either push blindly or pull blindly —
and conflicts end up being resolved by hand on the box. Git Sync avoids
conflicts instead of resolving them inside Home Assistant:

1. **`main` is the source of truth.** Changes merged to your main branch are
   pulled onto the instance as quickly as possible (webhook or polling).
2. **Local changes are committed away quickly** — always onto a dedicated
   sync branch that accumulates in **one open pull request**. There is no
   way to commit directly to main, by design.
3. **Only a manual merge of that PR changes main.** The merge can be
   triggered from the Home Assistant UI, but it is always a deliberate,
   manual action — never automatic.
4. **Conflicts are resolved on GitHub**, in the pull request, with a deep
   link from the app. There is deliberately no diff/merge UI inside
   Home Assistant.

On the GitHub side, leave the repository setting **"Automatically delete head
branches"** switched off. Git Sync manages the lifetime of the sync branch
itself — it removes the branch after a merge from the panel and recreates it
with the next commit.

Sync **profiles** control which file groups are versioned — e.g.
"Without applications" keeps `custom_components/` out of the repo and
records a version lockfile instead. Secrets (`secrets.yaml`, `.storage/`,
databases, logs) are always excluded and cannot be opted in.

## Status

Early development.

- [x] Milestone 1 — app skeleton: ingress panel with a read-only git status
      view of the configuration directory
- [ ] Milestone 2 — GitHub connection (device flow), repository & branch setup
- [ ] Milestone 3 — sync profiles (file groups, application lockfile mode)
- [ ] Milestone 4 — the sync-PR workflow: auto-commit, accumulating PR,
      manual merge from the panel, conflict deep links
- [ ] Publishing: pre-built multi-arch images, public app repository

## Installing (for testing)

Until pre-built images are published, install it as a **local app**:

1. Copy the `git-sync/` folder to the `/addons` directory of your
   Home Assistant instance (e.g. via the SSH or Samba add-on).
2. In Home Assistant open **Settings → Apps → App store**, choose
   **⋮ → Check for updates**.
3. *Git Sync* appears under **Local apps** — install and start it. The panel
   shows up in the sidebar via ingress.

The `image:` key in `git-sync/config.yaml` must stay commented out for local
installs so the image is built on the device.

## Development

The backend is a small FastAPI service (`git-sync/app/`); the panel is served
through Home Assistant ingress on port 8099.

Run it locally against any git working tree:

```bash
cd git-sync/app
pip install -r requirements.txt
CONFIG_DIR=/path/to/some/repo uvicorn server:app --port 8099
```

Build the container image locally:

```bash
docker build git-sync/ -t git-sync-dev
```

CI runs a `home-assistant/builder` test build for all supported
architectures on every push and pull request.

## License

[MIT](LICENSE)
