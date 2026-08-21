"""Checks that German and English stay in sync — in the backend texts and in
the panel's own dictionary. Needs nothing but the standard library.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "git-sync" / "app"))
import i18n  # noqa: E402

PANEL = (ROOT / "git-sync" / "app" / "static" / "index.html").read_text()

# Keys whose placeholders are themselves translated: the commit template and
# the panel hint documenting it use {dateien}/{anzahl} vs. {files}/{count}.
PY_PLACEHOLDER_EXEMPT = {"commit.template"}
JS_PLACEHOLDER_EXEMPT = {"settings.template.hint"}

# Keys the panel builds at runtime instead of writing them out literally.
COUPLING_STATES = ["not_a_repo", "no_origin", "remote_mismatch", "wrong_branch", "config_missing"]
ERROR_CODES = ["invalid_token", "forbidden", "network", "branches_equal", "invalid_repo",
               "missing_name", "missing_token", "remote_mismatch", "not_configured",
               "not_connected", "git_failed", "config_missing", "cannot_create_repo",
               "reload_failed", "restart_failed", "unknown"]
CHECK_RESULTS = ["ok", "error", "unavailable"]

FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def placeholders(text):
    return set(re.findall(r"\{(\w+)\}", text))


def js_dict(language):
    """The panel's I18N.<language> entries as {key: text}."""
    body = PANEL.split("var I18N = {", 1)[1]
    opener = "\n    %s: {\n" % language
    start = body.index(opener) + len(opener)
    block = body[start:body.index("\n    }", start)]
    return dict(re.findall(r"^      '([^']+)': '(.*)',?$", block, re.M))


# --- Backend texts
py_de, py_en = i18n.TEXTS["de"], i18n.TEXTS["en"]
check("backend: same keys in de/en", set(py_de) == set(py_en),
      str(set(py_de) ^ set(py_en)))
for key in sorted(set(py_de) & set(py_en)):
    if key in PY_PLACEHOLDER_EXEMPT:
        continue
    check(f"backend: placeholders match for {key}",
          placeholders(py_de[key]) == placeholders(py_en[key]),
          f"{placeholders(py_de[key])} vs {placeholders(py_en[key])}")
check("backend: no empty text", all(v.strip() for v in list(py_de.values()) + list(py_en.values())))
check("backend: resolve falls back", i18n.resolve("") == i18n.DEFAULT_LANGUAGE
      and i18n.resolve("fr") == i18n.DEFAULT_LANGUAGE and i18n.resolve("en") == "en")
check("backend: t substitutes",
      i18n.t("en", "notify.pr_waiting.body", number=7, hours=24).startswith("Pull request #7"),
      i18n.t("en", "notify.pr_waiting.body", number=7, hours=24))
check("backend: t leaves template placeholders alone",
      "{files}" in i18n.t("en", "commit.template") and "{dateien}" in i18n.t("de", "commit.template"))
check("backend: unknown key returns the key", i18n.t("de", "nope.nope") == "nope.nope")

# --- Panel dictionary
js_de, js_en = js_dict("de"), js_dict("en")
check("panel: dictionary parsed", len(js_de) > 100 and len(js_en) > 100, f"{len(js_de)}/{len(js_en)}")
check("panel: same keys in de/en", set(js_de) == set(js_en), str(set(js_de) ^ set(js_en)))
for key in sorted(set(js_de) & set(js_en)):
    if key in JS_PLACEHOLDER_EXEMPT:
        continue
    check(f"panel: placeholders match for {key}",
          placeholders(js_de[key]) == placeholders(js_en[key]),
          f"{placeholders(js_de[key])} vs {placeholders(js_en[key])}")

# The hint has to document the placeholders the backend template really uses.
for language, js in (("de", js_de), ("en", js_en)):
    check(f"panel: {language} template hint documents the real placeholders",
          placeholders(i18n.TEXTS[language]["commit.template"]) <=
          placeholders(js["settings.template.hint"]),
          js["settings.template.hint"])

# --- Every key the panel asks for exists in both languages
used = set(re.findall(r'data-i18n(?:-html|-placeholder|-title)?="([^"]+)"', PANEL))
used |= set(re.findall(r"\bt\('([^']+)'\s*[,)]", PANEL))
for key in ["couple." + s for s in COUPLING_STATES]:
    used.add(key)
for key in ["error." + c for c in ERROR_CODES]:
    used.add(key)
for key in ["restart.check." + r for r in CHECK_RESULTS] + ["restart.meta." + r for r in CHECK_RESULTS]:
    used.add(key)
for name in re.findall(r"var PROFILES = \[([^\]]*)\]", PANEL)[0].split(","):
    name = name.strip().strip("'")
    if name:
        used.add("profile." + name + ".name")
        used.add("profile." + name + ".desc")
for name in re.findall(r"\{ key: '(\w+)'", PANEL):
    used.add("group." + name + ".name")
    used.add("group." + name + ".files")
used |= {"group.apps.lockfile", "group.apps.full"}

check("panel: dynamic key families collected", len(used) > 120, str(len(used)))
missing = sorted(k for k in used if k not in js_de or k not in js_en)
check("panel: every used key is translated", not missing, str(missing))

# --- Nothing translated is left unused (typos in either direction)
literal = set(re.findall(r'data-i18n(?:-html|-placeholder|-title)?="([^"]+)"', PANEL))
literal |= set(re.findall(r"\bt\('([^']+)'\s*[,)]", PANEL))
prefixes = ("couple.", "error.", "profile.", "group.", "restart.check.", "restart.meta.")
unused = sorted(k for k in js_de if k not in literal and not k.startswith(prefixes))
check("panel: no unused keys", not unused, str(unused))

print()
print("FAILED: " + (", ".join(FAILED) if FAILED else "none"))
sys.exit(1 if FAILED else 0)
