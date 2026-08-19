"""Persistent app state.

Home Assistant apps get a private, persistent /data volume; DATA_DIR
overrides it for local development. The state file holds the GitHub token,
so it is written with owner-only permissions.
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
STATE_FILE = DATA_DIR / "state.json"


def load() -> dict:
    try:
        with STATE_FILE.open() as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with tmp.open("w") as fh:
        json.dump(state, fh, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(STATE_FILE)


def update(**changes) -> dict:
    state = load()
    for key, value in changes.items():
        if value is None:
            state.pop(key, None)
        else:
            state[key] = value
    save(state)
    return state
