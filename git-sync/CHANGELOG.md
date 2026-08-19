# Changelog

## 0.3.0

- Sync engine: the panel can now couple the configuration directory to the
  chosen repository (adopting main as the baseline — local differences stay
  as changes), commits local edits onto the sync branch, keeps exactly one
  collecting pull request, pulls main automatically in the background, and
  merges the PR on explicit request (squash; the sync branch restarts from
  main afterwards). Conflicts lock the merge and deep-link to the PR on
  GitHub — they are never resolved inside Home Assistant.
- New profile "Eigene .gitignore": the repo's own .gitignore governs the
  sync scope and can be edited right in the panel; it is preselected when
  the chosen repository already carries one. The built-in safety exclusions
  (secrets.yaml, .storage/, databases, logs) stay active in every profile
  via .git/info/exclude — the user's .gitignore is never touched.
- Auto-commit after a quiet period and auto-pull are configurable
  (/api/sync/settings); dashboard reworked to the four-card layout with
  conflict banner.

## 0.2.0

- Setup wizard: connect GitHub with a personal access token (validated via
  the GitHub API, stored only inside the app's private /data volume),
  choose or create the repository, pick the main branch (source of truth)
  and the sync branch, and select a sync profile (Komplett / Ohne
  Anwendungen / Nur Kern-Konfiguration / Benutzerdefiniert, with a
  lockfile-or-full switch for custom_components).
- Dashboard now shows the setup summary next to the git status; the GitHub
  connection can be disconnected again.

## 0.1.0

- Initial skeleton: ingress panel with a read-only git status view of the
  Home Assistant configuration directory (branch, remote, last commit,
  local changes, ahead/behind).
