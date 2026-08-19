# Changelog

## 0.5.1

- Fix: when creating the collecting pull request failed once (network
  hiccup, missing pull-request permission on a fine-grained token), the
  pushed sync branch stayed on GitHub without a PR forever. The app now
  retries automatically in the background, the dashboard shows the real
  cause plus a "PR jetzt anlegen" button, and a failed PR creation no
  longer masks a successful commit.

## 0.5.0

- After changes from main land in the configuration, the app now runs the
  configuration check (`ha core check`) automatically and shows the result
  in a dashboard banner. A restart of Home Assistant (`ha core restart`)
  can be triggered right there — always as an explicit, user-confirmed
  action, and locked while the check reports an error.
- Optional persistent notification when a restart is pending (on by
  default, configurable).

## 0.4.1

- Fix: "Jetzt übernehmen" (and background auto-pull) failed right after
  coupling, before the first commit was pushed — the sync branch does not
  exist on GitHub yet and the fetch aborted. A missing remote sync branch
  is now tolerated.
- Git and GitHub errors now land in the app log with their real cause, so
  "Details im App-Protokoll" actually delivers details.

## 0.4.0

- Settings view in the panel: auto-pull and poll interval, auto-commit and
  quiet period, template for automatic commit messages ({dateien},
  {anzahl}), notification toggles, profile change without re-running the
  wizard, connection overview. Deliberately no push-mode switch — the
  PR-only principle is not an option.
- Persistent Home Assistant notifications (via the Supervisor API): on
  conflict (cleared automatically once resolved) and a one-time reminder
  when the collecting PR has been waiting for a merge longer than the
  configured period.

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
