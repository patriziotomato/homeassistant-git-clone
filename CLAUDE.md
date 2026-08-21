# Projektregeln für dieses Repository

Home-Assistant-App **Git Sync** (`git-sync/`) — koppelt die HA-Konfiguration
an ein GitHub-Repo: main ist die Quelle der Wahrheit, lokale Änderungen
sammeln sich in genau einem Sync-PR, nur dessen manueller Merge verändert
main, Konflikte werden auf GitHub gelöst (nie in HA).

## Änderungsprotokoll — Pflicht bei jedem PR

- Jeder PR mit nutzersichtbarer Änderung ergänzt `git-sync/CHANGELOG.md`.
  Ohne angehobene `version:` in `git-sync/config.yaml` bietet Home Assistant
  kein Update an; der Add-on-Store rendert genau diese CHANGELOG.md im
  Update-Dialog.
- **Die Zielversion nie selbst festlegen, sondern nachfragen.** Nicht jede
  Änderung bekommt ein eigenes Release — oft sollen mehrere Features in
  einem Release zusammenkommen. Also einen begründeten Vorschlag machen
  (Grundlage ist die Versionierungsregel unten) und fragen, auf welche
  Version gebucht werden soll. Erst danach Changelog und `version:` anfassen.
- Je nach Antwort zwei Fälle:
  - **Eigenes Release** — neuen `## <version>`-Block oben anlegen und
    `version:` in `git-sync/config.yaml` anheben.
  - **Auf ein noch unveröffentlichtes Release buchen** — die Stichpunkte in
    dessen `## <version>`-Block einsortieren (notfalls den Block anlegen),
    `version:` in `config.yaml` bleibt unangetastet. So sammeln mehrere PRs
    ein Release an; erst der letzte PR der Serie hebt `version:` an und
    liefert alles gemeinsam aus. Maßgeblich ist allein `config.yaml`: steht
    diese Version dort auf `main` schon drin, hat Home Assistant sie bereits
    als Update angeboten und Nachzügler erreichen niemanden mehr.
- Format (so, wie Home Assistant es anzeigt): neueste Version oben,
  `## <version>` als Überschrift, darunter Stichpunkte mit `-`.
  Stichpunkte beschreiben, was sich für Nutzer ändert — keine Dateinamen-
  oder Implementierungsaufzählungen.
- Versionierung als Grundlage des Vorschlags: 0.x-Phase — Feature-PRs heben
  die Minor (0.4.0 → 0.5.0), reine Fixes die Patch-Stelle.
- Sprache im Changelog: Englisch (die App soll veröffentlicht werden).

## Zweisprachigkeit — Pflicht bei jedem nutzersichtbaren Text

- Die App ist Deutsch **und** Englisch. Jeder neue nutzersichtbare Text
  kommt in beide Wörterbücher: Panel-Texte nach `I18N.de` / `I18N.en` in
  `git-sync/app/static/index.html`, Backend-Texte (Sync-PR,
  HA-Benachrichtigungen, Commit-Vorlagen) nach `git-sync/app/i18n.py`.
  Nie einen Text direkt in Markup oder Code schreiben.
- Die gewählte Sprache gehört zur Instanz (Setting `language`), nicht zum
  Browser — nur so sind Panel, Benachrichtigungen und PR gleichsprachig.
  Beim ersten Start entscheidet die Browsersprache.
- `python3 tests/test_i18n.py` bewacht das: gleiche Schlüssel und gleiche
  Platzhalter in beiden Sprachen, und jeder im Panel verwendete Schlüssel
  existiert auch. Fehlt eine Übersetzung, schlägt der Test fehl.

## Arbeitsweise

- Feature-Branches + PR gegen `main`, Squash-Merge. Nie direkt auf `main`
  pushen (das ist auch das Prinzip der App selbst).
- Die PR-Beschreibung hat genau zwei Abschnitte, in dieser Reihenfolge:
  `## Änderungen aus User-Sicht` (was Nutzer merken) und
  `## Umsetzungsdetails` (wie es gebaut ist). Keine weiteren Abschnitte —
  auch nicht für Tests, Changelog oder Screenshots. Beide Abschnitte so
  kompakt wie möglich: ein paar Stichpunkte, keine Fließtext-Absätze.
- Vor jedem PR: `python3 tests/test_git_ops.py` (braucht nur git, kein
  Netzwerk) — testet die komplette Git-Engine gegen ein lokales Bare-Repo —
  und `python3 tests/test_i18n.py` (nur Standardbibliothek).
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
