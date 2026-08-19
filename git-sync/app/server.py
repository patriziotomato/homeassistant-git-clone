"""Git Sync — Home Assistant app backend.

Milestone 1: read-only status API over the Home Assistant configuration
directory. The directory is mounted at /homeassistant inside the app
container (map: homeassistant_config); CONFIG_DIR overrides it for local
development.
"""

import os
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/homeassistant")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Git Sync", docs_url=None, redoc_url=None)


def _git(*args: str) -> tuple[int, str]:
    """Run git against CONFIG_DIR, returning (exit code, stripped stdout)."""
    try:
        result = subprocess.run(
            ["git", "-C", CONFIG_DIR, *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return 1, str(err)
    return result.returncode, result.stdout.strip()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict:
    """Git state of the configuration directory, for the status page."""
    if not os.path.isdir(CONFIG_DIR):
        return {"config_dir": CONFIG_DIR, "exists": False, "is_repo": False}

    code, _ = _git("rev-parse", "--is-inside-work-tree")
    if code != 0:
        return {"config_dir": CONFIG_DIR, "exists": True, "is_repo": False}

    _, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    remote_code, remote = _git("remote", "get-url", "origin")
    _, last_commit = _git("log", "-1", "--format=%h␟%s␟%cr")

    changes = []
    code, porcelain = _git("status", "--porcelain")
    if code == 0 and porcelain:
        for line in porcelain.splitlines():
            changes.append({"state": line[:2].strip() or "??", "path": line[3:]})

    ahead = behind = None
    code, counts = _git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if code == 0 and counts:
        left, _, right = counts.partition("\t")
        ahead, behind = int(left), int(right)

    commit = None
    if last_commit:
        parts = last_commit.split("␟")
        if len(parts) == 3:
            commit = {"hash": parts[0], "subject": parts[1], "when": parts[2]}

    return {
        "config_dir": CONFIG_DIR,
        "exists": True,
        "is_repo": True,
        "branch": branch,
        "remote": remote if remote_code == 0 else None,
        "last_commit": commit,
        "changes": changes,
        "ahead": ahead,
        "behind": behind,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
