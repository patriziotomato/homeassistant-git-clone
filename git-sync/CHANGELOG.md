# Changelog

## 0.8.0

- Before merging the sync PR, the panel now asks for the text of the merge
  commit: the merge button opens an input prefilled with a suggestion
  (summarizing the PR's changed files, plus the PR number), and the text you
  confirm becomes the headline of the squash commit on main.

## 0.7.2

- Fix: button labels no longer overflow the card frame — when a card is too
  narrow for a row of buttons (e.g. ".gitignore bearbeiten" and "Verbindung
  trennen" in the setup card), the buttons now wrap onto their own line
  instead of running out of the card.

## 0.7.1

- The settings button in the header now shows a proper gear icon — the
  previous symbol looked more like a sun or brightness control.

## 0.7.0

- The panel now speaks English as well as German. On first start it follows
  your browser language; a DE/EN switch in the header changes it at any
  time, and the choice is remembered for the instance.
- The language applies beyond the panel: Home Assistant notifications, the
  collecting pull request and the automatic commit messages are written in
  it too.
- The template for automatic commit messages follows the language as long
  as it is untouched ({dateien}/{anzahl} in German, {files}/{count} in
  English). Both spellings keep working, so a template you wrote yourself
  survives a language switch.
- The panel is now mobile friendly: on phones and narrow windows the
  dashboard and settings stack into a single column, the setup wizard
  (stepper, repository form, profile picker) fits small screens, and long
  file paths or branch names no longer overflow the layout.
- Buttons and toggles are easier to hit on touch screens, and focusing an
  input field on iOS no longer zooms the whole page.
- The dashboard card collecting local changes is now called
  "Änderungen aus HA" / "Changes from HA" (previously "Offener
  Sync-PR"), making it clearer that it holds the changes made in
  Home Assistant.
- The setup wizard and the documentation now point out that GitHub's
  repository setting "Automatically delete head branches" should stay
  switched off — Git Sync manages the lifetime of the sync branch itself.

## 0.6.0

- Commits listed on the dashboard (in the collecting pull request and under
  incoming changes) now link to the commit on GitHub, so the actual file
  changes are one click away.
- Fix: after the collecting pull request was merged, the next pull kept
  creating empty merge commits that re-imported the already-merged history —
  resurrecting the just-deleted sync branch on GitHub and listing old
  commits in the next pull request. Merges that would bring no changes are
  now skipped entirely and the sync branch restarts cleanly from main.
- The restart reminder and the automatic configuration check now only
  trigger when a pull actually changed files, not on history-only updates.
- Fix: the first file in the local-changes list (and in auto-generated
  commit messages) lost the first character of its name when it was a
  modified file — e.g. "ustom_components/…" instead of "custom_components/…".

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
