"""End-to-end test of git_ops against a local bare repo simulating GitHub."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="gitsync-test-"))
BARE = TMP / "github.git"
CONFIG = TMP / "config"
WORK = TMP / "work"  # a second clone playing "someone edits on GitHub"

os.environ["CONFIG_DIR"] = str(CONFIG)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "git-sync" / "app"))
import git_ops  # noqa: E402

REPO = {
    "full_name": "jane-doe/ha-config",
    "main_branch": "main",
    "sync_branch": "ha-sync",
    "clone_url": str(BARE),
}
PROFILE_OA = {"name": "ohne_anwendungen",
              "groups": {"core": True, "blueprints": True, "esphome": True,
                         "themes_www": True, "apps": True, "ui_export": False},
              "apps_mode": "lockfile"}
PROFILE_OWN = {"name": "eigene_gitignore", "groups": {}, "apps_mode": None}

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def sh(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{args}: {result.stderr}")
    return result.stdout.strip()


# --- Seed the "GitHub" side: bare repo with a main branch
BARE.mkdir(parents=True)
sh("git", "init", "--bare", "-b", "main", str(BARE))
sh("git", "clone", str(BARE), str(WORK))
(WORK / "README.md").write_text("# config\n")
(WORK / "configuration.yaml").write_text("default_config:\nlogger:\n  default: info\n")
sh("git", "-C", str(WORK), "-c", "user.name=Remote", "-c", "user.email=r@x", "add", "-A")
sh("git", "-C", str(WORK), "-c", "user.name=Remote", "-c", "user.email=r@x", "commit", "-m", "Erststand")
sh("git", "-C", str(WORK), "push", "origin", "main")

# --- The HA config dir: not a repo yet, content differs from main
CONFIG.mkdir()
(CONFIG / "configuration.yaml").write_text("default_config:\nlogger:\n  default: warning\n")
(CONFIG / "automations.yaml").write_text("[]\n")
(CONFIG / "secrets.yaml").write_text("api_key: SUPERSECRET\n")
(CONFIG / ".storage").mkdir()
(CONFIG / ".storage" / "auth").write_text("{}")
cc = CONFIG / "custom_components" / "demo_app"
cc.mkdir(parents=True)
(cc / "manifest.json").write_text(json.dumps({"domain": "demo_app", "version": "1.2.3"}))

# 1) Coupling adopts main as baseline, keeps local diffs
state = git_ops.couple(None, REPO)
check("couple -> coupled", state == "coupled", state)
check("on sync branch", git_ops.current_branch() == "ha-sync", str(git_ops.current_branch()))
git_ops.apply_excludes(PROFILE_OA)
git_ops.write_lockfile(PROFILE_OA)
paths = [c["path"] for c in git_ops.local_changes()]
check("local diff visible", "configuration.yaml" in paths and "automations.yaml" in paths, str(paths))
check("secrets excluded", not any("secrets" in p for p in paths), str(paths))
check(".storage excluded", not any(".storage" in p for p in paths), str(paths))
check("custom_components excluded (lockfile mode)",
      not any(p.startswith("custom_components/") for p in paths), str(paths))
check("lockfile tracked", git_ops.LOCKFILE in paths, str(paths))
lock = json.loads((CONFIG / git_ops.LOCKFILE).read_text())
check("lockfile content", lock["applications"].get("demo_app") == "1.2.3", str(lock))

# 1b) Regression: fetch before the first push — the sync branch does not
# exist on the remote yet, which must not fail the fetch ("Jetzt übernehmen"
# right after coupling).
try:
    git_ops.fetch(None, REPO)
    check("fetch tolerates missing remote sync branch", True)
except git_ops.GitError as err:
    check("fetch tolerates missing remote sync branch", False, str(err))

# 2) Commit & push onto the sync branch
sha = git_ops.commit_and_push(None, REPO, "Sync: Testlauf", PROFILE_OA)
check("commit pushed", sha is not None)
remote_branches = sh("git", "-C", str(BARE), "branch")
check("ha-sync on remote", "ha-sync" in remote_branches, remote_branches)
check("tree clean after commit", git_ops.local_changes() == [])
check("outgoing commits > 0", len(git_ops.outgoing_commits(REPO)) == 1)

# 3) main advances remotely -> incoming + clean integrate
sh("git", "-C", str(WORK), "pull", "origin", "main")
(WORK / "scripts.yaml").write_text("{}\n")
sh("git", "-C", str(WORK), "-c", "user.name=Remote", "-c", "user.email=r@x", "add", "-A")
sh("git", "-C", str(WORK), "-c", "user.name=Remote", "-c", "user.email=r@x", "commit", "-m", "Skripte ergänzt")
sh("git", "-C", str(WORK), "push", "origin", "main")
git_ops.fetch(None, REPO)
check("incoming detected", git_ops.incoming_count(REPO) == 1, str(git_ops.incoming_count(REPO)))
result = git_ops.integrate(None, REPO)
check("integrate ok", result == "ok", result)
check("main change arrived", (CONFIG / "scripts.yaml").exists())
check("incoming now 0", git_ops.incoming_count(REPO) == 0)

# 4) Conflict: same file changed on main and locally
(WORK / "automations.yaml").write_text("- id: remote_change\n")
sh("git", "-C", str(WORK), "-c", "user.name=Remote", "-c", "user.email=r@x", "add", "-A")
sh("git", "-C", str(WORK), "-c", "user.name=Remote", "-c", "user.email=r@x", "commit", "-m", "Automation remote")
sh("git", "-C", str(WORK), "push", "origin", "main")
(CONFIG / "automations.yaml").write_text("- id: local_change\n")
git_ops.commit_and_push(None, REPO, "Sync: automations.yaml", PROFILE_OA)
git_ops.fetch(None, REPO)
result = git_ops.integrate(None, REPO)
check("conflict detected", result == "conflict", result)
check("tree clean after aborted merge", git_ops.local_changes() == [])
check("local version kept", (CONFIG / "automations.yaml").read_text() == "- id: local_change\n")

# 5) Realign after (simulated) PR merge: resolve on "GitHub", merge to main
sh("git", "-C", str(WORK), "fetch", "origin", "ha-sync")
code = subprocess.run(["git", "-C", str(WORK), "-c", "user.name=Remote", "-c", "user.email=r@x",
                       "merge", "--no-edit", "origin/ha-sync"], capture_output=True, text=True)
sh("git", "-C", str(WORK), "checkout", "--theirs", "automations.yaml")
sh("git", "-C", str(WORK), "-c", "user.name=Remote", "-c", "user.email=r@x", "add", "-A")
subprocess.run(["git", "-C", str(WORK), "-c", "user.name=Remote", "-c", "user.email=r@x",
                "commit", "--no-edit"], capture_output=True, text=True)
sh("git", "-C", str(WORK), "push", "origin", "main")
(CONFIG / "scenes.yaml").write_text("[]\n")  # fresh uncommitted local edit survives realign
git_ops.realign_after_merge(None, REPO)
check("realigned to main", git_ops.incoming_count(REPO) == 0)
check("no outgoing after realign", git_ops.outgoing_commits(REPO) == [], str(git_ops.outgoing_commits(REPO)))
check("resolved content adopted", (CONFIG / "automations.yaml").read_text() == "- id: local_change\n",
      (CONFIG / "automations.yaml").read_text())
paths = [c["path"] for c in git_ops.local_changes()]
check("uncommitted edit survived realign", "scenes.yaml" in paths, str(paths))

# 6) Profile "eigene_gitignore": no group excludes, no lockfile
git_ops.apply_excludes(PROFILE_OWN)
exclude = (CONFIG / ".git" / "info" / "exclude").read_text()
check("own-gitignore: safety block present", "secrets.yaml" in exclude and ".storage/" in exclude)
check("own-gitignore: no custom_components exclude", "custom_components/" not in exclude, exclude)
check("own-gitignore: managed block exactly once", exclude.count(git_ops.MARK_BEGIN) == 1)
check("own-gitignore: no lockfile write", git_ops.write_lockfile(PROFILE_OWN) is False)

print()
print("FAILED: " + (", ".join(FAILED) if FAILED else "none"))
sys.exit(1 if FAILED else 0)
