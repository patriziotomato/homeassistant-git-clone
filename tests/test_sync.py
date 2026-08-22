"""Checks the auto-commit quiet period: the timer has to measure time since
the *last* change, and the cap has to fire even while edits keep arriving.

Drives sync.observe_changes() with a fake clock — no git, no network, no
event loop. Needs nothing but the standard library.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "git-sync" / "app"))

# sync.py imports gh.py and ha.py, which import httpx at module level — gh.py
# even annotates a return type with httpx.Response, so the name has to resolve
# at import time. Nothing under test here ever makes a request (the quiet-period
# timer is pure), and both the CI workflow and the README promise these suites
# need only git and the standard library. Use the real library when it happens
# to be installed, and a stand-in when it is not, rather than adding a
# dependency to a suite that has no use for one.
try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    _httpx = types.ModuleType("httpx")
    _httpx.Response = type("Response", (), {})
    _httpx.HTTPError = type("HTTPError", (Exception,), {})
    _httpx.TimeoutException = type("TimeoutException", (_httpx.HTTPError,), {})
    sys.modules["httpx"] = _httpx

import sync  # noqa: E402

DELAY = 120  # seconds, the shipped default
CAP = DELAY * sync.AUTO_COMMIT_CAP

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def edit(*paths, state="M"):
    return [{"state": state, "path": path} for path in paths]


class Clock:
    """A poller driven by a fake clock: tick() advances time, feeds the change
    set to sync and reports whether an automatic commit would run now."""

    def __init__(self):
        sync._reset_quiet_period()
        self.now = 1_000_000.0
        self.commits = 0

    def tick(self, changes, seconds=60):
        self.now += seconds
        sync.observe_changes(changes, self.now)
        due = sync.auto_commit_deadline(DELAY)
        if changes and due is not None and self.now >= due:
            self.commits += 1
            sync._reset_quiet_period()   # what commit_now() does after pushing
            return True
        return False


# --- the timer measures quiet time, not time since the first change
clock = Clock()
clock.tick(edit("automations.yaml"))
committed = [clock.tick(edit("automations.yaml", f"scripts{n}.yaml")) for n in range(3)]
check("editing keeps the timer from firing", not any(committed), str(committed))

quiet = [clock.tick(edit("automations.yaml", "scripts2.yaml")) for _ in range(2)]
check("commit follows the quiet period", quiet == [False, True], str(quiet))
check("one commit, not one per tick", clock.commits == 1, str(clock.commits))

# --- the cap fires even while the change set keeps moving
clock = Clock()
fired_at = None
for i in range(40):
    if clock.tick(edit("automations.yaml", f"file{i}.yaml")):
        fired_at = (i + 1) * 60
        break
check("continuous editing still commits", fired_at is not None)
check("cap fires no earlier than the cap", fired_at is not None and fired_at >= CAP,
      f"{fired_at}s vs cap {CAP}s")
check("cap fires within one poll of the cap", fired_at is not None and fired_at <= CAP + 60,
      f"{fired_at}s vs cap {CAP}s")

# --- a clean tree resets everything
clock = Clock()
clock.tick(edit("automations.yaml"))
clock.tick([])
check("clean tree clears the deadline", sync.auto_commit_deadline(DELAY) is None)
clock.tick(edit("automations.yaml"))
check("dirty again restarts the timer",
      sync.auto_commit_deadline(DELAY) == clock.now + DELAY)

# --- the deadline the dashboard shows is the earlier of the two clocks
clock = Clock()
clock.tick(edit("a.yaml"))
first_dirty = clock.now
for i in range(5):
    clock.tick(edit("a.yaml", f"b{i}.yaml"))
check("deadline follows the last change, while under the cap",
      sync.auto_commit_deadline(DELAY) == clock.now + DELAY,
      str(sync.auto_commit_deadline(DELAY) - clock.now))
check("deadline never exceeds the cap",
      sync.auto_commit_deadline(DELAY) <= first_dirty + CAP)

# --- the signature notices what a user would call an edit
check("same paths and states are the same tick",
      sync._changes_signature(edit("a.yaml", "b.yaml"))
      == sync._changes_signature(edit("b.yaml", "a.yaml")))
check("a new file is a change",
      sync._changes_signature(edit("a.yaml"))
      != sync._changes_signature(edit("a.yaml", "b.yaml")))
check("a changed state is a change",
      sync._changes_signature(edit("a.yaml", state="M"))
      != sync._changes_signature(edit("a.yaml", state="??")))

# --- adaptive polling: fast while something is happening, idle otherwise
NOW = 2_000_000.0
IDLE = {"poll_interval": 300}
sync._fast_until = 0.0
check("idle uses the user's interval", sync.poll_interval(IDLE, NOW) == 300)
check("the floor still applies", sync.poll_interval({"poll_interval": 5}, NOW) == 15)

sync.begin_fast_poll(NOW)
check("fast right after activity", sync.poll_interval(IDLE, NOW) == 10)
check("still fast just before the window closes",
      sync.poll_interval(IDLE, NOW + sync.FAST_POLL_WINDOW - 1) == 10)
check("idle again once the window closes",
      sync.poll_interval(IDLE, NOW + sync.FAST_POLL_WINDOW) == 300)
check("a low idle setting is never slower than the fast phase",
      sync.poll_interval({"poll_interval": 15}, NOW) == 10)
sync._fast_until = 0.0

# The whole point: fewer calls per day when nothing happens.
before = 24 * 3600 / 60      # the old 60 s default
after = 24 * 3600 / sync.DEFAULT_SETTINGS["poll_interval"]
check("idle instances poll less than before", after < before, f"{after} vs {before}")

print()
print("FAILED: " + (", ".join(FAILED) if FAILED else "none"))
sys.exit(1 if FAILED else 0)
