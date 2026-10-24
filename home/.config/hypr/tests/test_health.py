"""scripts/health.py: the self-healing checkup -- fake journal output grouped
(noise counted, known problems worded, bursts merged, numbers masked,
secrets masked, coredump stacks attached), doctor's checks turned into
findings with the right remedy (or none), the remedies re-checked against
their fixed catalogs (a tampered report cannot point them elsewhere), the
auto_* switches, rotate + undo on real scratch files, the explanation
budget and cache with the model stubbed, the report / brief / doctor lines,
the built-in tasks.py type, and Settings > Desktop health's pure helpers.

Hermetic: HOME, the state folder and both config files are scratch paths;
no journalctl, coredumpctl, systemctl, gio or model runs (sh, gio_trash,
unit_info, ask_model and notify are stubbed per test)."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

import helpers

T = helpers.import_script("tasks.py", "tasks")
H = helpers.import_script("health.py", "health")
H.log = lambda *a, **k: None
H.notify = lambda *a, **k: None

NOW = 1_790_000_000.0


def entry(msg, who="app", prio=4, at=NOW - 600, unit=None, pid="100", **extra):
    e = {"MESSAGE": msg, "SYSLOG_IDENTIFIER": who, "PRIORITY": str(prio), "_PID": pid,
         "__REALTIME_TIMESTAMP": str(int(at * 1e6))}
    if unit:
        e["_SYSTEMD_USER_UNIT"] = unit
    e.update(extra)
    return e


def journal_text(entries):
    return "\n".join(json.dumps(e) for e in entries) + "\n"


FAKE_USER = [
    entry("A backend call failed: Inhibiting other than idle not supported", who="xdg-desktop-portal"),
    entry("A backend call failed: Inhibiting other than idle not supported", who="xdg-desktop-portal"),
    entry("worker 4123 lost connection after 17 retries", who="myd", unit="myd.service", prio=3, at=NOW - 500),
    entry("worker 99 lost connection after 2 retries", who="myd", unit="myd.service", prio=3, at=NOW - 400),
    entry("worker 7 lost connection after 5 retries", who="myd", unit="myd.service", prio=3, at=NOW - 300),
    entry("login failed for token=abcdef123456", who="secretd", prio=3, at=NOW - 250),
    entry("Traceback (most recent call last):", who="python3", prio=3, at=NOW - 200, pid="555"),
    entry('  File "x.py", line 3, in <module>', who="python3", prio=3, at=NOW - 199.8, pid="555"),
    entry("KeyError: 'name'", who="python3", prio=3, at=NOW - 199.6, pid="555"),
    entry("waybar.service: Main process exited, code=dumped, status=6/ABRT", who="systemd", prio=4),
    entry("Process 4242 (waybar) of user 1000 dumped core.\n\nModule libc.so\nStack trace of thread 4242:\n"
          "#0  0x1 raise (libc.so.6)\n#1  0x2 abort (libc.so.6)", who="systemd-coredump", prio=2,
          COREDUMP_PID="4242"),
    entry("checkup (tasks): all good", who="health", prio=4),
    entry("mysvc.service: Failed with result 'exit-code'.", who="systemd", prio=4),
    entry("repo-preview-X.service: Service reached runtime time limit. Stopping.", who="systemd"),
    entry("repo-preview-X.service: Failed with result 'timeout'.", who="systemd"),
]
FAKE_SYSTEM = [
    entry("/etc/udev/rules.d/81-x.rules:2 Failed to resolve group 'plugdev', ignoring: Unknown group",
          who="systemd-udevd", prio=3),
    entry("/etc/udev/rules.d/81-x.rules:3 Failed to resolve group 'plugdev', ignoring: Unknown group",
          who="systemd-udevd", prio=3),
    entry("[Hardware Error]: System Fatal error.", who="kernel", prio=0, at=NOW - 100, pid=""),
    entry("[Hardware Error]: Bank 11 is reserved.", who="kernel", prio=0, at=NOW - 100, pid=""),
    entry("[Hardware Error]: cache level: RESV", who="kernel", prio=0, at=NOW - 100, pid=""),
]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="health-test-")
        self.old = (H.HOME, H.STATE_DIR, H.CONFIG, H.HYPR_DIR, H.UNIT_DIR, H.RUNTIME, H.generated_files,
                    H.sh, H.gio_trash, H.unit_info, H.ask_model, H.cache_holders, H.du_size, H.notify,
                    T.CONFIG, T.STATE_DIR, sys.modules.get("tasks"))
        H.HOME = os.path.join(self.dir, "home")
        H.STATE_DIR = os.path.join(self.dir, "state")
        H.CONFIG = os.path.join(self.dir, "health.json")
        H.HYPR_DIR = os.path.join(H.HOME, ".config", "hypr")
        H.UNIT_DIR = os.path.join(H.HOME, ".config", "systemd", "user")
        H.RUNTIME = os.path.join(self.dir, "run")
        T.CONFIG = os.path.join(self.dir, "tasks.json")
        T.STATE_DIR = os.path.join(self.dir, "tasks-state")
        sys.modules["tasks"] = T            # health.py's tasks() is this (patched) module
        os.makedirs(H.HYPR_DIR)
        self.trashed = []

        def trash(path):
            dest = os.path.join(self.dir, "trash", os.path.basename(path))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(path, dest)
            self.trashed.append(path)
            return True, ""
        H.gio_trash = trash
        H.sh = lambda *cmd, **k: (0, "", "")
        H.ask_model = lambda prompts: ([None] * len(prompts), "stubbed")
        H.cache_holders = lambda path: []
        self.notes = []
        H.notify = lambda summary, body, open_page=True: self.notes.append(summary)

    def tearDown(self):
        (H.HOME, H.STATE_DIR, H.CONFIG, H.HYPR_DIR, H.UNIT_DIR, H.RUNTIME, H.generated_files, H.sh, H.gio_trash,
         H.unit_info, H.ask_model, H.cache_holders, H.du_size, H.notify, T.CONFIG, T.STATE_DIR, mod) = self.old
        if mod is None:
            sys.modules.pop("tasks", None)
        else:
            sys.modules["tasks"] = mod
        shutil.rmtree(self.dir, ignore_errors=True)

    def home(self, *parts):
        return os.path.join(H.HOME, *parts)

    def write(self, path, data=b"x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def conf(self, **over):
        return dict(H.DEFAULTS, **over)


class Journal(Base):
    def test_parse_skips_garbage(self):
        text = journal_text(FAKE_USER[:2]) + "not json\n[1, 2]\n"
        self.assertEqual(len(H.parse_journal(text)), 2)

    def test_grouping(self):
        g = H.group_journal(H.parse_journal(journal_text(FAKE_USER)), "user", {"myd.service"})
        by_who = {}
        for grp in g["groups"]:
            by_who.setdefault(grp["who"], []).append(grp)
        # noise counted, not grouped; our own line and the coredump left out
        self.assertEqual(g["noise"], {"xdg-desktop-portal": 2})
        self.assertNotIn("health", by_who)
        self.assertNotIn("systemd-coredump", by_who)
        # numbers masked: three lines, one problem, from a unit of ours
        myd = by_who["myd"]
        self.assertEqual(len(myd), 1)
        self.assertEqual(myd[0]["count"], 3)
        self.assertTrue(myd[0]["ours"])
        self.assertEqual(myd[0]["prio"], 3)
        # secrets masked in what is kept
        secret = by_who["secretd"][0]
        self.assertFalse(any("abcdef123456" in line for line in secret["raw"]))
        self.assertNotIn("abcdef123456", secret["message"] + secret["sig"])
        # a traceback is one event
        py = by_who["python3"]
        self.assertEqual(len(py), 1)
        self.assertEqual(py[0]["count"], 1)
        self.assertEqual(len(py[0]["raw"]), 3)
        # the bar's crash and the coredump's stack (from "Stack trace" on)
        self.assertEqual(len(g["waybar"]), 1)
        self.assertTrue(g["coredump_stacks"]["4242"].startswith("Stack trace of thread"))
        # a known problem: both lines of one unit, one finding
        known = [grp for grp in g["groups"] if grp["known"]]
        self.assertEqual(len(known), 1)
        self.assertEqual(known[0]["count"], 2)
        self.assertEqual(known[0]["known_args"][0], "repo-preview-X.service")

    def test_known_udev_one_group_and_mce_burst(self):
        g = H.group_journal(H.parse_journal(journal_text(FAKE_SYSTEM)), "system")
        udev = [x for x in g["groups"] if x["who"] == "systemd-udevd"]
        self.assertEqual(len(udev), 1)
        self.assertEqual(udev[0]["count"], 2)
        words = H.known_words(udev[0]["known"], udev[0]["known_args"])
        self.assertIn("/etc/udev/rules.d/81-x.rules", words)
        self.assertIn("'plugdev'", words)
        kernel = [x for x in g["groups"] if x["who"] == "kernel"]
        self.assertEqual(len(kernel), 1)
        self.assertEqual(len(kernel[0]["raw"]), 3)
        self.assertEqual(kernel[0]["prio"], 0)

    def test_signature_masks_ids(self):
        a = H.signature("x", "bus :1.37544 id 0xdeadbeef uuid 123e4567-e89b-12d3-a456-426614174000 n=5")
        b = H.signature("x", "bus :1.2 id 0x1 uuid 00000000-0000-0000-0000-000000000000 n=77")
        self.assertEqual(a, b)
        self.assertNotEqual(a, H.signature("y", "bus :1.2"))

    def test_bytes_message(self):
        e = entry([104, 105, 255], who="app")
        self.assertTrue(H.text_of(e["MESSAGE"]).startswith("hi"))

    def test_read_journal_system_not_readable(self):
        H.sh = lambda *cmd, **k: (0, "", "Hint: You are currently not seeing messages from other users and "
                                         "the system.")
        entries, why = H.read_journal("system", NOW - 3600)
        self.assertEqual(entries, [])
        self.assertIn("systemd-journal", why)


def facts(**over):
    base = {"since": NOW - 86400, "until": NOW, "notes": [],
            "doctor": [], "wanted": ["waybar.service", "launcher.service"], "units": {},
            "journal_user": [], "journal_system": [], "coredumps": [], "coredump_info": {},
            "caches": [], "logs": [], "generated": [], "broken": []}
    base.update(over)
    return base


class Analyse(Base):
    def test_units(self):
        f = facts(doctor=[
            {"name": "units", "level": "fail", "text": "launcher.service: failed (exit-code)", "unit": "launcher.service"},
            {"name": "units", "level": "fail", "text": "sessions-offer.service: not running (inactive)",
             "unit": "sessions-offer.service"},
            {"name": "units", "level": "fail", "text": "other.service: failed", "unit": "other.service"},
            {"name": "units", "level": "fail", "text": "presence.service: failed", "unit": "presence.service"},
            {"name": "hyprland", "level": "fail", "text": "config errors: bad line"},
            {"name": "disk", "level": "warn", "text": "/: 50 GiB free (8%)"},
            {"name": "lm studio", "level": "info", "text": "server up"}],
            units={"launcher.service": {"ActiveState": "failed", "Result": "exit-code", "journal": ["boom"]},
                   "sessions-offer.service": {"ActiveState": "inactive", "Result": "success"},
                   "other.service": {"ActiveState": "failed", "FragmentPath": "/usr/lib/systemd/user/other.service"},
                   "presence.service": {"ActiveState": "failed",
                                        "FragmentPath": os.path.join(H.UNIT_DIR, "presence.service")}},
            journal_user=[entry("launcher.service: Failed with result 'exit-code'.", who="systemd")])
        found, _ = H.analyse(f, self.conf(), now=NOW)
        by = {x.get("unit") or x["kind"]: x for x in found}
        launcher = by["launcher.service"]
        self.assertEqual(launcher["remedy"]["type"], "restart-unit")
        self.assertEqual(launcher["level"], "fail")
        # systemd's journal line about it joined the unit's finding
        self.assertTrue(any("Failed with result" in r for r in launcher["raw"]))
        self.assertFalse(any(x["kind"] == "journal" for x in found))
        self.assertEqual(by["sessions-offer.service"]["level"], "info")
        self.assertIsNone(by["sessions-offer.service"]["remedy"])
        self.assertIsNone(by["other.service"]["remedy"])           # not the desktop's
        self.assertIn("webcam", by["presence.service"]["remedy"]["note"])
        self.assertIn("hypr-guard", by["hyprland"]["words"])
        self.assertEqual(by["disk"]["level"], "warn")
        self.assertNotIn("lm studio", [x["title"] for x in found])

    def test_restart_not_twice_a_day(self):
        f = facts(doctor=[{"name": "units", "level": "fail", "text": "launcher.service: failed",
                           "unit": "launcher.service"}], units={"launcher.service": {"ActiveState": "failed"}})
        fixes = [{"remedy": "restart-unit", "target": "launcher.service", "ok": True, "at": NOW - 3600}]
        found, _ = H.analyse(f, self.conf(), fixes, now=NOW)
        self.assertIn("again", found[0]["remedy"]["note"])

    def test_crashes_bar_caches_logs_generated_broken(self):
        broken = os.path.join(H.HYPR_DIR, "broken-20260101-000000")
        f = facts(coredumps=[{"pid": "4242", "exe": "/usr/bin/waybar", "sig": 6, "time": NOW - 100},
                             {"pid": "7", "exe": "/opt/game", "sig": 11, "time": NOW - 50}],
                  coredump_info={"7": "Stack trace of thread 7:\n#0 0x0 n/a"},
                  journal_user=[e for e in FAKE_USER if "waybar" in str(e["MESSAGE"])],
                  caches=[{"id": "pip", "path": self.home(".cache/pip"), "words": "pip's", "size": 5_000_000_000},
                          {"id": "uv", "path": self.home(".cache/uv"), "words": "uv's", "size": 100},
                          {"id": "npm", "path": self.home(".npm/_cacache"), "words": "npm's", "size": 3_000_000_000,
                           "busy": ["node"]}],
                  logs=[{"path": self.home(".local/state/hypr/x.log"), "size": 300_000_000},
                        {"path": "/run/hypr/a/hyprland.log", "size": 2_000_000_000, "hyprland": True}],
                  generated=[{"path": self.home(".config/waybar/generated/theme.css"), "state": "missing"}],
                  broken=[{"path": broken, "mtime": NOW - 100, "files": 3}])
        found, _ = H.analyse(f, self.conf(), now=NOW)
        kinds = {}
        for x in found:
            kinds.setdefault(x["kind"], []).append(x)
        crash = {x["exe"]: x for x in kinds["crash"]}
        self.assertEqual(crash["waybar"]["level"], "warn")
        self.assertIn("SIGABRT", crash["waybar"]["title"])
        self.assertTrue(any("raise" in r for r in crash["waybar"]["raw"]))     # the journal's stack
        self.assertEqual(crash["game"]["level"], "info")
        self.assertTrue(any("#0" in r for r in crash["game"]["raw"]))           # coredumpctl info's
        self.assertIn("ALT+G", kinds["waybar"][0]["words"])
        caches = {x["sig"]: x for x in kinds["cache"]}
        self.assertEqual(caches["cache|pip"]["remedy"]["type"], "trash-cache")
        self.assertNotIn("cache|uv", caches)
        self.assertIsNone(caches["cache|npm"]["remedy"])
        self.assertIn("node", caches["cache|npm"]["words"])
        logs = {x["sig"]: x for x in kinds["log"]}
        self.assertEqual(logs[f"log|{self.home('.local/state/hypr/x.log')}"]["remedy"]["type"], "rotate-log")
        self.assertIsNone(logs["log|hyprland"]["remedy"])
        self.assertEqual(kinds["generated"][0]["remedy"]["type"], "regen-config")
        self.assertEqual(kinds["broken"][0]["level"], "warn")              # new since the last checkup
        # worst first, then what has a fix
        self.assertEqual(found[0]["level"], "warn")

    def test_noise_count(self):
        _, noise = H.analyse(facts(journal_user=FAKE_USER[:2]), self.conf(), now=NOW)
        self.assertEqual(sum(noise.values()), 2)


class Remedies(Base):
    def test_rotate_and_undo(self):
        log = self.write(self.home(".local/state/hypr/sub/big.log"), b"a" * 2000)
        self.write(log + ".1", b"older")
        conf = self.conf(log_mb=10)
        ok, why, _ = H.apply_remedy({"type": "rotate-log", "target": log}, conf)
        self.assertTrue(ok)
        self.assertIn("under the limit", why)                 # 2 KB is not big
        conf["log_mb"] = 0                                     # (below the setting's range: tests only)
        ok, why, undo = H.apply_remedy({"type": "rotate-log", "target": log}, conf)
        self.assertTrue(ok, why)
        self.assertEqual(os.path.getsize(log), 0)
        self.assertEqual(os.path.getsize(log + ".1"), 2000)
        self.assertEqual(self.trashed, [log + ".1"])            # the old .1 went to the trash, not rm
        H.record_fix({"at": NOW, "run": "r1", "remedy": "rotate-log", "target": log, "ok": True, **undo})
        with open(log, "ab") as handle:
            handle.write(b"new")
        out = H.undo_last()
        self.assertIn("back", out[0])
        with open(log, "rb") as handle:
            self.assertEqual(handle.read(), b"a" * 2000 + b"new")
        self.assertEqual(H.undo_last(), ["nothing to undo"])

    def test_rotate_refuses_other_files(self):
        other = self.write(os.path.join(self.dir, "elsewhere.log"), b"a" * 100)
        data = self.write(self.home(".local/state/hypr/activity.jsonl"), b"a" * 100)
        for path in (other, data, "/etc/passwd"):
            ok, why, _ = H.apply_remedy({"type": "rotate-log", "target": path}, self.conf(log_mb=0))
            self.assertFalse(ok, path)
            self.assertIn("not touched", why)

    def test_trash_cache(self):
        pip = self.home(".cache/pip")
        self.write(os.path.join(pip, "wheel"), b"w" * 10)
        H.du_size = lambda path: 5_000_000_000
        ok, why, undo = H.apply_remedy({"type": "trash-cache", "target": "pip"}, self.conf())
        self.assertTrue(ok, why)
        self.assertFalse(os.path.exists(pip))
        self.assertEqual(undo, {"trashed": os.path.realpath(pip)})
        self.assertIn("trash", why)

    def test_trash_cache_refuses(self):
        H.du_size = lambda path: 5_000_000_000
        self.write(self.home(".cache/pip/x"))
        for target in ("../Documents", "/home", "nope"):
            ok, _, _ = H.apply_remedy({"type": "trash-cache", "target": target}, self.conf())
            self.assertFalse(ok)
        H.cache_holders = lambda path: ["python3"]
        ok, why, _ = H.apply_remedy({"type": "trash-cache", "target": "pip"}, self.conf())
        self.assertFalse(ok)
        self.assertIn("python3", why)
        self.assertEqual(self.trashed, [])
        # a symlinked cache is never followed
        os.makedirs(self.home("Documents"))
        os.makedirs(self.home(".cache"), exist_ok=True)
        shutil.rmtree(self.home(".cache/pip"))
        os.symlink(self.home("Documents"), self.home(".cache/pip"))
        self.assertIsNone(H.cache_target("pip"))

    def test_restart(self):
        calls = []
        state = {"n": 0}

        def sh(*cmd, **k):
            calls.append(cmd)
            if cmd[:3] == ("systemctl", "--user", "is-active"):
                return 0, "active\n", ""
            return 0, "", ""
        H.sh = sh
        H.unit_info = lambda unit: {"ActiveState": "failed", "FragmentPath": "/usr/lib/systemd/user/x.service"}
        orig_sleep, H.time.sleep = H.time.sleep, lambda s: state.update(n=state["n"] + 1)
        try:
            ok, why, _ = H.apply_remedy({"type": "restart-unit", "target": "launcher.service"}, self.conf(),
                                        wanted={"launcher.service"})
            self.assertTrue(ok, why)
            self.assertIn(("systemctl", "--user", "restart", "launcher.service"), calls)
            calls.clear()
            ok, _, _ = H.apply_remedy({"type": "restart-unit", "target": "waybar.service"}, self.conf(),
                                      wanted={"waybar.service"})
            self.assertTrue(ok)
            self.assertIn((H.BAR_RESTART,), calls)               # never a plain restart / SIGUSR2
            calls.clear()
            ok, why, _ = H.apply_remedy({"type": "restart-unit", "target": "dbus-broker.service"}, self.conf(),
                                        wanted=set())
            self.assertFalse(ok)
            self.assertEqual(calls, [])
        finally:
            H.time.sleep = orig_sleep

    def test_regen(self):
        target = self.home(".config/waybar/generated/theme.css")
        H.generated_files = lambda: [target]
        calls = []

        def sh(*cmd, **k):
            calls.append(cmd)
            if cmd[-1] == "ensure":
                self.write(target, b"/* generated */")
            return 0, "", ""
        H.sh = sh
        self.write(target, b"")
        ok, why, _ = H.apply_remedy({"type": "regen-config", "target": target}, self.conf())
        self.assertTrue(ok, why)
        self.assertEqual(self.trashed, [target])                 # the empty one went to the trash first
        self.assertTrue(calls[-1][-2].endswith("theme.py"))
        ok, why, _ = H.apply_remedy({"type": "regen-config", "target": "/etc/fstab"}, self.conf())
        self.assertFalse(ok)

    def test_fix_all_respects_switches(self):
        log = self.write(self.home(".local/state/hypr/big.log"), b"a" * 50)
        found = [H.finding("log", "info", "big", "w", key="log|x",
                           remedy={"type": "rotate-log", "target": log, "label": "Rotate"}),
                 H.finding("unit", "fail", "u", key="unit|presence",
                           remedy={"type": "restart-unit", "target": "presence.service", "label": "R",
                                   "note": "camera"})]
        H.fix_all(found, self.conf(log_mb=0), now=NOW, run_id="r")
        self.assertEqual(found[0]["remedy"]["status"], "proposed")    # auto_rotate_log is off
        self.assertEqual(os.path.getsize(log), 50)
        H.fix_all(found, self.conf(log_mb=0, auto_rotate_log=True, auto_restart_unit=True), now=NOW, run_id="r")
        self.assertEqual(found[0]["remedy"]["status"], "applied")
        self.assertEqual(found[1]["remedy"]["status"], "proposed")    # a note: never by itself
        self.assertEqual(H.read_fixes()[-1]["remedy"], "rotate-log")
        found2 = [H.finding("log", "info", "big", "w", key="log|x",
                            remedy={"type": "rotate-log", "target": log, "label": "Rotate"})]
        H.fix_all(found2, self.conf(log_mb=0, auto_rotate_log=True), dry_run=True, now=NOW, run_id="d")
        self.assertEqual(found2[0]["remedy"]["status"], "would apply")
        self.assertEqual(len(H.read_fixes()), 1)                    # a dry run records nothing


class Explain(Base):
    def unknowns(self, n):
        return [H.finding("journal", "warn" if i < 2 else "info", f"thing {i}", raw=[f"line {i}"], key=f"k{i}",
                          count=i + 1) for i in range(n)]

    def test_budget_model_and_cache(self):
        asked = []

        def ask(prompts):
            asked.append(prompts)
            return [f"**Cause** {i}." for i in range(len(prompts))], "gemma"
        H.ask_model = ask
        found = self.unknowns(5) + [H.finding("cache", "info", "known", "catalog words", key="c")]
        H.explain(found, self.conf(explain_max=3), now=NOW)
        self.assertEqual(len(asked[0]), 3)
        self.assertIn("line 0", asked[0][0])
        self.assertEqual(found[0]["words"], "Cause 0.")                 # no markdown
        self.assertEqual(found[0]["by"], "gemma, local")
        self.assertIn("over explain_max", found[4]["by"])
        self.assertEqual(found[5]["words"], "catalog words")
        again = self.unknowns(3)
        H.explain(again, self.conf(explain_max=3), now=NOW + 60)
        self.assertEqual(again[0]["by"], "gemma, local (kept)")
        self.assertEqual(len(asked), 1)                                  # all three were kept
        crash = [H.finding("crash", "warn", "x crashed", raw=["#0"], key="k0")]
        H.explain(crash, self.conf(), now=NOW + 60)
        self.assertEqual(len(asked), 2)                                  # a crash is asked again

    def test_model_off_and_dry_run(self):
        H.ask_model = lambda prompts: self.fail("asked the model")
        found = self.unknowns(2)
        H.explain(found, self.conf(explain=False), now=NOW)
        self.assertIn("model is off", found[0]["by"])
        self.assertIn("line 0", found[0]["words"])
        found = self.unknowns(2)
        H.explain(found, self.conf(), dry_run=True, now=NOW)
        self.assertIn("dry run", found[0]["by"])

    def test_model_unavailable(self):
        H.ask_model = lambda prompts: ([None] * len(prompts), "gamemode is on")
        found = self.unknowns(1)
        H.explain(found, self.conf(), now=NOW)
        self.assertEqual(found[0]["by"], "plain lines -- gamemode is on")


class Checkup(Base):
    def run_one(self, by="tasks", **conf):
        for key, value in conf.items():
            H.set_setting(key, value)
        f = facts(journal_user=H.parse_journal(journal_text(FAKE_USER)),
                  journal_system=H.parse_journal(journal_text(FAKE_SYSTEM)),
                  caches=[{"id": "pip", "path": self.home(".cache/pip"), "words": "pip's", "size": 5_000_000_000}])
        return H.run_checkup(by, now=NOW, facts=f)

    def test_report_brief_doctor(self):
        rep = self.run_one()
        self.assertTrue(os.path.exists(H.path_for("last.json")))
        with open(H.path_for("report.txt")) as handle:
            text = handle.read()
        self.assertIn("health.py fix", text)
        self.assertNotIn("abcdef123456", text)
        self.assertEqual(rep["summary"]["proposed"], 1)
        self.assertEqual(len(self.notes), 1)                   # by tasks, something needs you
        lines = H.brief_lines(now=NOW + 3600)
        self.assertIn("1 fix to approve", lines[0])
        self.assertTrue(any("[fix waiting]" in l for l in lines))
        checks = H.doctor_checks(light=True, now=NOW + 60)
        self.assertEqual(checks[0]["level"], "warn")
        self.assertEqual(len(checks), 1)
        self.assertGreater(len(H.doctor_checks(light=False, now=NOW + 60)), 1)
        H.dismiss()
        self.assertNotEqual(H.doctor_checks(now=NOW + 60)[0]["level"], "warn")
        self.assertIn("was", H.brief_lines(now=NOW + 5 * 86400)[0])          # stale
        # the next window starts where this one ended
        self.assertEqual(H.window_start(H.last_report(), NOW + 7200), NOW)

    def test_asked_does_not_notify_and_dry_run_keeps_nothing(self):
        self.run_one(by="asked")
        self.assertEqual(self.notes, [])
        os.remove(H.path_for("last.json"))
        rep = H.run_checkup("asked", dry_run=True, now=NOW, facts=facts())
        self.assertTrue(rep["dry_run"])
        self.assertFalse(os.path.exists(H.path_for("last.json")))

    def test_fix_one_rechecks_the_target(self):
        self.run_one()
        rep = H.last_report()
        fid = next(f["id"] for f in rep["findings"] if f.get("remedy"))
        H.du_size = lambda path: 5_000_000_000
        self.write(self.home(".cache/pip/x"))
        ok, why = H.fix_one(fid)
        self.assertTrue(ok, why)
        self.assertEqual(H.last_report()["summary"]["fixed"], 1)
        self.assertEqual(H.read_fixes()[-1]["by"], "you")
        # a report edited to point elsewhere is refused by the catalog check
        rep = H.last_report()
        f = next(f for f in rep["findings"] if f.get("remedy"))
        f["remedy"].update(status="proposed", target="../../")
        H.write_json("last.json", rep)
        ok, why = H.fix_one(fid)
        self.assertFalse(ok)
        with self.assertRaises(ValueError):
            H.fix_one("nope")

    def test_all_good_is_quiet(self):
        H.run_checkup("tasks", now=NOW, facts=facts())
        self.assertEqual(H.brief_lines(now=NOW + 60), [])
        self.assertEqual(self.notes, [])
        self.assertEqual(H.headline(H.last_report()["summary"]), "all good")

    def test_one_at_a_time(self):
        import fcntl
        with open(H.path_for("run.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaises(RuntimeError):
                H.run_checkup("asked", now=NOW, facts=facts())



class ReviewFixes(Base):
    """The review's fixes: a standing proposal is told once, "seen" carries
    over, a unit name can never be a systemctl option, fix/undo wait for a
    running checkup, a unit's lines are not doubled."""
    run_one = Checkup.run_one

    def test_standing_proposal_notifies_once_and_seen_carries_over(self):
        self.run_one()
        self.assertEqual(len(self.notes), 1)
        H.dismiss()
        # the next night: the same findings, the same pip cache still proposed
        f = facts(journal_user=H.parse_journal(journal_text(FAKE_USER)),
                  journal_system=H.parse_journal(journal_text(FAKE_SYSTEM)),
                  caches=[{"id": "pip", "path": self.home(".cache/pip"), "words": "pip's", "size": 5_000_000_000}])
        rep = H.run_checkup("tasks", now=NOW + 86400, facts=f)
        self.assertEqual(rep["summary"]["proposed"], 1)
        self.assertEqual(len(self.notes), 1)                     # not told again
        self.assertTrue(rep["seen"])                             # nothing new: still seen
        self.assertNotEqual(H.doctor_checks(now=NOW + 86400 + 60)[0]["level"], "warn")
        # a new proposal is told, and un-sees the report
        f["caches"].append({"id": "npm", "path": self.home(".npm/_cacache"), "words": "npm's",
                            "size": 5_000_000_000})
        rep = H.run_checkup("tasks", now=NOW + 2 * 86400, facts=f)
        self.assertEqual(len(self.notes), 2)
        self.assertFalse(rep["seen"])

    def test_unit_name_is_never_an_option(self):
        calls = []
        H.sh = lambda *cmd, **k: calls.append(cmd) or (0, "", "")
        for bad in ("--host=evil", "-H.service", "../x.service", "a b.service", "x/y.service", ""):
            ok, _, _ = H.apply_remedy({"type": "restart-unit", "target": bad}, self.conf(), wanted={bad})
            self.assertFalse(ok, bad)
        self.assertEqual(calls, [])                              # systemctl never ran

    def test_fix_and_undo_wait_for_a_running_checkup(self):
        import fcntl
        self.run_one()
        fid = next(f["id"] for f in H.last_report()["findings"] if f.get("remedy"))
        with open(H.path_for("run.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaises(RuntimeError):
                H.fix_one(fid)
            with self.assertRaises(RuntimeError):
                H.undo_last()

    def test_unit_lines_not_doubled(self):
        line = entry("launcher.service: Failed with result 'exit-code'.", who="systemd")
        H.sh = lambda *cmd, **k: (0, journal_text([line]), "")
        raw = H.unit_journal("launcher.service")
        self.assertEqual(raw, [H.raw_line(line)])
        f = facts(doctor=[{"name": "units", "level": "fail", "text": "launcher.service: failed",
                           "unit": "launcher.service"}],
                  units={"launcher.service": {"ActiveState": "failed", "journal": raw}},
                  journal_user=[line])
        found, _ = H.analyse(f, self.conf(), now=NOW)
        self.assertEqual(found[0]["raw"], raw)

    def test_lines_join_the_unit_they_name(self):
        # numbers masked: both units' lines are one journal group
        a = entry("run-p1-i1.service: Failed with result 'exit-code'.", who="systemd", at=NOW - 60)
        b = entry("run-p2-i2.service: Failed with result 'exit-code'.", who="systemd", at=NOW - 30)
        f = facts(doctor=[{"name": "units", "level": "fail", "text": f"{u}: failed", "unit": u}
                          for u in ("run-p1-i1.service", "run-p2-i2.service")],
                  units={}, journal_user=[a, b])
        found, _ = H.analyse(f, self.conf(), now=NOW)
        by = {x["unit"]: x["raw"] for x in found}
        self.assertEqual(by["run-p1-i1.service"], [H.raw_line(a)])
        self.assertEqual(by["run-p2-i2.service"], [H.raw_line(b)])

    def test_crash_plain_words_say_what_crashed(self):
        f = H.finding("crash", "warn", "x crashed", raw=["crash of /usr/bin/x (pid 1)", "#0 a", "ELF object"])
        self.assertIn("crash of /usr/bin/x", H.plain_words(f))


class Settings(Base):
    def test_settings(self):
        self.assertEqual(H.settings(), H.DEFAULTS)
        self.assertFalse(any(H.settings()[r["setting"]] for r in H.REMEDIES.values()))   # off as shipped
        H.set_setting("cache_gb", "5")
        H.set_setting("auto_trash_cache", "on")
        s = H.settings()
        self.assertEqual((s["cache_gb"], s["auto_trash_cache"]), (5, True))
        for key, value in (("cache_gb", "0"), ("auto_trash_cache", "maybe"), ("nope", "1")):
            with self.assertRaises(ValueError):
                H.set_setting(key, value)
        with open(H.CONFIG, "w") as handle:
            json.dump({"settings": {"cache_gb": "lots", "explain": False}}, handle)
        self.assertEqual(H.settings()["cache_gb"], 2)
        self.assertFalse(H.settings()["explain"])

    def test_parse_span(self):
        self.assertEqual(H.parse_span("24h"), 86400)
        self.assertEqual(H.parse_span("2d"), 172800)
        with self.assertRaises(ValueError):
            H.parse_span("soon")


class TaskType(Base):
    def test_builtin_type(self):
        tidy, problems = T.validate({"id": "health-checkup", "name": "x", "type": "nightly-checkup", "params": {}})
        self.assertEqual(problems, [])
        self.assertEqual(tidy["schedule"], "daily 03:30")
        self.assertTrue(T.TYPES["nightly-checkup"]["heavy"])
        self.assertNotIn("nightly-checkup", [t["type"] for t in T.catalog()["types"]])
        self.assertNotIn("nightly-checkup", T.model_prompt("anything"))
        with self.assertRaises(ValueError):
            T.add({"name": "x", "type": "nightly-checkup", "params": {}})
        self.assertTrue(any("health.py" in p for p in T.permissions(tidy)))
        self.assertIn("nightly-checkup", T.JOBS)
        _, problems = T.validate({"id": "h", "type": "nightly-checkup", "params": {}, "schedule": "watch"})
        self.assertTrue(problems)

    def test_ensure_and_set_task(self):
        t = H.ensure_task()
        self.assertEqual((t["id"], t["schedule"], t["enabled"]), ("health-checkup", "daily 03:30", True))
        H.ensure_task()
        self.assertEqual(len(T.load()[0]), 1)
        self.assertEqual(H.set_setting("schedule", "daily 4:00"), "daily 04:00")
        H.set_setting("enabled", "off")
        t = H.task_entry()
        self.assertEqual((t["schedule"], t["enabled"]), ("daily 04:00", False))
        with self.assertRaises(ValueError):
            H.set_setting("schedule", "watch")
        H.ensure_task()                                      # repairs nothing that is fine: keeps the user's
        self.assertEqual(H.task_entry()["schedule"], "daily 04:00")

    def test_job_runs_health(self):
        finished = []
        old_run, old_finish = T.subprocess.run, T.finish

        class Done:
            returncode, stdout, stderr = 0, '{"headline": "all good", "fixed": 0}\n', ""
        T.subprocess.run = lambda cmd, **k: (finished.append(cmd), Done())[1]
        T.finish = lambda task, ok, summary, *a, **k: finished.append((ok, summary, k.get("quiet")))
        try:
            T.job_checkup({"id": "health-checkup", "name": "x"}, T.settings())
        finally:
            T.subprocess.run, T.finish = old_run, old_finish
        self.assertIn("health.py", finished[0][1])
        self.assertEqual(finished[1], (True, "all good", True))


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from settings_pages import health as page          # needs GTK, not a display
        except Exception as exc:                                 # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.health not importable: {exc}")
        cls.page = page

    def test_helpers(self):
        p = self.page
        self.assertEqual(p.schedule_time("daily 03:30"), "03:30")
        self.assertIsNone(p.schedule_time("weekdays 03:30"))
        self.assertIn("Not set up", p.task_text({"task": {"exists": False}}))
        self.assertIn("every day at 03:30", p.task_text({"task": {"exists": True, "schedule": "daily 03:30"},
                                                         "tasks": {"enabled": True, "running": True}}))
        self.assertIn("switched off", p.task_text({"task": {"exists": True, "schedule": "daily 03:30"},
                                                    "tasks": {"enabled": False}}))
        self.assertIn("No checkup", p.report_summary({}, ""))
        s = {"findings": 3, "problems": 1, "fixed": 1, "proposed": 1, "noise": 4}
        self.assertEqual(p.report_summary({"summary": s}, "Checked now"),
                         "Checked now: 1 problem, 1 fixed, 1 fix to approve (3 findings, "
                         "4 harmless lines hidden).")
        sub = p.finding_sub({"words": "w", "by": "gemma, local",
                             "remedy": {"status": "proposed", "note": "camera"}})
        self.assertNotIn("(gemma, local)", sub)               # who wrote it is in the fold
        self.assertIn("camera", sub)
        long = {"words": "First one. " + "More words. " * 10, "by": "gemma, local"}
        self.assertEqual(p.finding_sub(long), "First one.")
        self.assertIn("More words.", p.finding_more(long))
        self.assertIn("(gemma, local)", p.finding_more(long))
        self.assertEqual(p.finding_more({"words": "short", "by": "catalog"}), "")
        self.assertEqual(p.toggled("units,repos", "health", True, ["repos", "units", "health"]),
                         "repos,units,health")


class Integration(unittest.TestCase):
    def test_brief_has_the_section(self):
        brief = helpers.import_script("brief.py", "brief")
        self.assertIn("health", brief.SECTIONS)
        self.assertIn("health", brief.GATHER)
        self.assertEqual(brief.SECTION_TITLES["health"], "Health")

    def test_doctor_reads_it(self):
        doctor = helpers.import_script("doctor.py", "doctor")
        out = doctor.check_health(True)
        self.assertEqual(out[0]["name"], "health")


if __name__ == "__main__":
    unittest.main()
