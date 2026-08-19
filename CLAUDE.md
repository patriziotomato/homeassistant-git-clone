# Projektregeln für dieses Repository

Home-Assistant-App **Git Sync** (`git-sync/`) — koppelt die HA-Konfiguration
an ein GitHub-Repo: main ist die Quelle der Wahrheit, lokale Änderungen
sammeln sich in genau einem Sync-PR, nur dessen manueller Merge verändert
main, Konflikte werden auf GitHub gelöst (nie in HA).

## Änderungsprotokoll — Pflicht bei jedem PR

- Jeder PR mit nutzersichtbarer Änderung ergänzt `git-sync/CHANGELOG.md`
  **und** hebt `version:` in `git-sync/config.yaml` an — im selben PR.
  Ohne Versions-Bump bietet Home Assistant kein Update an; der Add-on-Store
  rendert genau diese CHANGELOG.md im Update-Dialog.
- Format (so, wie Home Assistant es anzeigt): neueste Version oben,
  `## <version>` als Überschrift, darunter Stichpunkte mit `-`.
  Stichpunkte beschreiben, was sich für Nutzer ändert — keine Dateinamen-
  oder Implementierungsaufzählungen.
- Versionierung: 0.x-Phase — Feature-PRs heben die Minor (0.4.0 → 0.5.0),
  reine Fixes die Patch-Stelle.
- Sprache im Changelog: Englisch (die App soll veröffentlicht werden);
  UI-Texte der App selbst sind Deutsch.

## Arbeitsweise

- Feature-Branches + PR gegen `main`, Squash-Merge. Nie direkt auf `main`
  pushen (das ist auch das Prinzip der App selbst).
- Vor jedem PR: `python3 tests/test_git_ops.py` (braucht nur git, kein
  Netzwerk) — testet die komplette Git-Engine gegen ein lokales Bare-Repo.
  Zusätzlich den Server lokal starten (README „Local development") und die
  betroffenen Endpunkte kurz durchklicken/curlen.
- Die CI (`.github/workflows/builder.yaml`) baut nur aarch64 + amd64 —
  32-bit-ARM ist ausgemustert, nicht wieder hinzufügen.
- Niemals Secrets, Tokens oder `.storage`-Inhalte ins Repo — auch nicht in
  Tests oder Beispielen. Der Schutzblock in `git_ops.ALWAYS_EXCLUDE` ist
  nicht verhandelbar und bleibt in jedem Profil aktiv.
- Der GitHub-Token der Nutzer wird ausschließlich in `/data` gehalten und
  pro Git-Aufruf als Header injiziert — nie in `.git/config`, nie in
  API-Antworten.
