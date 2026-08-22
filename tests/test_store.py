"""Checks the persisted state: the schema field, the owner-only permissions
and that a damaged or foreign file cannot take the app down.

Needs nothing but the standard library.
"""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="gitsync-store-"))
os.environ["DATA_DIR"] = str(TMP)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "git-sync" / "app"))
import store  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def written():
    return json.loads(store.STATE_FILE.read_text())


# --- a missing file is empty state, not a crash
check("missing file reads as empty", store.load() == {})

# --- every write stamps the schema version
store.update(repo={"full_name": "jane/ha-config"})
check("schema is written", written().get("schema") == store.SCHEMA_VERSION, str(written()))
check("the payload survives alongside it",
      written().get("repo") == {"full_name": "jane/ha-config"})

# --- the token file stays owner-only
mode = stat.S_IMODE(store.STATE_FILE.stat().st_mode)
check("state.json is 0600", mode == 0o600, oct(mode))

# --- a file from before the field existed still loads
store.STATE_FILE.write_text(json.dumps({"repo": {"full_name": "jane/ha-config"}}))
check("a file without the field loads", store.load().get("repo") is not None)
check("and is stamped on the next write",
      store.update(profile={"name": "nur_kern"}).get("schema") == store.SCHEMA_VERSION)

# --- a file from a newer version is tolerated rather than fatal
store.STATE_FILE.write_text(json.dumps({"schema": store.SCHEMA_VERSION + 5, "repo": {"x": 1}}))
check("a newer file still loads", store.load().get("repo") == {"x": 1})

# --- damaged input never takes the app down
store.STATE_FILE.write_text("{ this is not json")
check("broken json reads as empty", store.load() == {})
store.STATE_FILE.write_text(json.dumps(["not", "an", "object"]))
check("a non-object reads as empty", store.load() == {})

print()
print("FAILED: " + (", ".join(FAILED) if FAILED else "none"))
sys.exit(1 if FAILED else 0)
