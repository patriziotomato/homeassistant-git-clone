# Changelog

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
