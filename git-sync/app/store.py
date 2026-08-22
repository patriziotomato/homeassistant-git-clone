"""Persistent app state.

Home Assistant apps get a private, persistent /data volume; DATA_DIR
overrides it for local development. The state file holds the GitHub token,
so it is written with owner-only permissions.
"""

import json
import logging
import os
from pathlib import Path

LOG = logging.getLogger("git-sync")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
STATE_FILE = DATA_DIR / "state.json"

# Shape of state.json. Bump when the layout changes and give _migrate() the
# corresponding step. Files written before the field existed read as 0.
SCHEMA_VERSION = 1


def _migrate(state: dict) -> dict:
    """Bring a state file written by an older version up to SCHEMA_VERSION.

    There is nothing to migrate yet; the point is that the loader respects the
    field from the very first release that has it. Without that, the first
    change to the layout — a renamed settings key, a restructured repo block —
    would have to infer the old shape from whatever happens to be present.
    """
    version = state.get("schema", 0)
    if version > SCHEMA_VERSION:
        # A newer version of the app wrote this file and the user went back.
        # Refusing would take the app down over something usually harmless, so
        # carry on and say so — the log is where a real diagnosis lives.
        LOG.warning("state.json was written by a newer version (schema %s > %s) — "
                    "continuing, but settings it does not know may be lost",
                    version, SCHEMA_VERSION)
    return state


def load() -> dict:
    try:
        with STATE_FILE.open() as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict):
        LOG.warning("state.json does not hold an object — ignoring it")
        return {}
    return _migrate(state)


def save(state: dict) -> dict:
    """Write the state, stamped with the schema version. Returns what was
    written, so callers see the same thing the file holds."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = {**state, "schema": SCHEMA_VERSION}
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with tmp.open("w") as fh:
        json.dump(state, fh, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(STATE_FILE)
    return state


def update(**changes) -> dict:
    state = load()
    for key, value in changes.items():
        if value is None:
            state.pop(key, None)
        else:
            state[key] = value
    return save(state)
