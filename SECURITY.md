# Security policy

Git Sync holds a GitHub token with write access to a repository of yours, and
it runs with read-write access to your Home Assistant configuration directory.
Anything that undermines either is worth reporting.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private vulnerability reporting instead: go to the
[Security tab](https://github.com/patriziotomato/homeassistant-git-clone/security)
of this repository and choose **Report a vulnerability**. That opens a private
advisory visible only to you and the maintainer.

Useful in a report: the app version from `git-sync/config.yaml`, your Home
Assistant installation type, what you did, what happened, and what you expected
instead. A proof of concept helps but is not required.

Expect a first response within a week. If a report turns out to be valid, the
fix ships in a normal release with an entry in `git-sync/CHANGELOG.md`, and
you are credited unless you would rather not be.

## Supported versions

This is a 0.x/1.x project maintained by one person: **only the latest release
gets fixes.** There are no backports to earlier versions.

## What the app does with your credentials

Stated here so you can check whether a finding contradicts it:

- The GitHub token is stored **only** in the app's private `/data` volume, in
  `state.json`, written with owner-only permissions (`0600`).
- It is injected **per git invocation** as an `http.extraheader`, the way
  `actions/checkout` does. It is never written into the repository's
  `.git/config`.
- It is never returned by the app's HTTP API and never written to the log.
- `secrets.yaml`, `.storage/` (which holds Home Assistant's own credentials),
  databases, logs and caches are excluded from every sync profile through a
  managed block in `.git/info/exclude`. That block cannot be switched off, and
  it is re-established on every start and before every commit.

**One consequence worth knowing:** `/data` is part of Home Assistant's add-on
backups, so your GitHub token is inside every backup that includes this app —
including backups uploaded to cloud storage. That is what makes a restore work,
and it matches how other add-ons store credentials, but treat those backups
accordingly.

## Out of scope

- Findings that require an attacker who already has access to your Home
  Assistant instance or its host. The app's panel is reachable only through
  ingress and inherits Home Assistant's own authentication.
- The absence of a custom AppArmor profile. The Supervisor's default profile
  applies; a tighter custom one is
  [tracked as future work](https://github.com/patriziotomato/homeassistant-git-clone/issues/32).
- Vulnerabilities in Home Assistant, the Supervisor or GitHub themselves —
  please report those to the respective projects.
