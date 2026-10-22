"""startup.py (the "Startup & background" Settings page's backend) and the
page's own wording helpers. Everything runs on scratch folders and stubbed
systemctl: no unit is enabled, disabled, started or stopped."""
import os
import tempfile
import time
import unittest

import helpers

startup = helpers.import_script("startup.py")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


class Scratch(unittest.TestCase):
    """A scratch config folder (units, autostart, lua) and a recording
    systemctl stub."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.saved = {k: getattr(startup, k) for k in (
            "UNIT_DIR", "USER_AUTOSTART", "SYSTEM_AUTOSTART", "LUA_DIR", "DISABLED", "STATE_DIR",
            "systemctl", "KNOWN")}
        startup.UNIT_DIR = os.path.join(self.dir, "systemd", "user")
        startup.USER_AUTOSTART = os.path.join(self.dir, "autostart")
        startup.SYSTEM_AUTOSTART = [os.path.join(self.dir, "etc", "autostart")]
        startup.LUA_DIR = os.path.join(self.dir, "lua")
        startup.STATE_DIR = os.path.join(self.dir, "state")
        startup.DISABLED = os.path.join(self.dir, "state", "startup-disabled")
        startup.KNOWN = ["waybar.service"]
        self.calls = []
        startup.systemctl = lambda *a, **k: (self.calls.append(a), (0, "", ""))[1]

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(startup, k, v)


class Pure(unittest.TestCase):
    def test_paths_are_scratch(self):
        self.assertTrue(startup.DISABLED.startswith(helpers.SCRATCH))

    def test_parse_show_keeps_repeated_keys(self):
        text = ("Id=a.timer\nTimersCalendar={ OnCalendar=x ; }\nTimersCalendar={ OnCalendar=y ; }\n\n"
                "Id=b.service\nActiveState=active\n")
        units = startup.parse_show(text)
        self.assertEqual(units["a.timer"]["TimersCalendar"].splitlines(),
                         ["{ OnCalendar=x ; }", "{ OnCalendar=y ; }"])
        self.assertEqual(units["b.service"]["ActiveState"], "active")

    def test_has_install(self):
        self.assertTrue(startup.has_install("[Unit]\n[Install]\nWantedBy=graphical-session.target\n"))
        self.assertFalse(startup.has_install("[Unit]\nWantedBy=x\n[Service]\nExecStart=y\n"))
        self.assertFalse(startup.has_install("[Install]\n# WantedBy=x\n"))

    def test_schedule_words(self):
        cal = "{ OnCalendar=*-*-* *:00/15:00 ; next_elapse=@1 }"
        mono = "{ OnActiveUSec=20s ; next_elapse=1h }"
        self.assertEqual(startup.schedule_text(cal, mono), "every 15 min, 20 s after login")
        self.assertEqual(startup.schedule_text("{ OnCalendar=*-*-* 21:30:00 ; next_elapse=@1 }", ""),
                         "every day at 21:30")
        self.assertEqual(startup.schedule_text("", "{ OnUnitActiveUSec=5min ; next_elapse=1h }\n"
                                               "{ OnActiveUSec=30s ; next_elapse=1h }"),
                         "every 5 min, 30 s after login")
        self.assertEqual(startup.calendar_text("*-*-* *:00:00"), "every hour")
        self.assertEqual(startup.calendar_text("Mon *-*-* 09:00:00"), "Mon at 09:00")
        self.assertEqual(startup.schedule_text("", ""), "?")

    def test_span_text(self):
        self.assertEqual(startup.span_text("5min"), "5 min")
        self.assertEqual(startup.span_text("1h 30min"), "1.5 h")
        self.assertEqual(startup.span_text("20s"), "20 s")

    def test_service_state(self):
        self.assertEqual(startup.service_state({"ActiveState": "active", "SubState": "running"}), ("running", True))
        self.assertEqual(startup.service_state({"ActiveState": "active", "SubState": "exited"}), ("done", True))
        self.assertEqual(startup.service_state({"ActiveState": "failed", "Result": "exit-code"}),
                         ("failed (exit-code)", False))
        self.assertEqual(startup.service_state({"ActiveState": "inactive", "Type": "simple"}), ("stopped", False))
        self.assertFalse(startup.service_state({"LoadState": "not-found"})[1])

    def test_escape_unit_matches_systemd(self):
        self.assertEqual(startup.app_unit("geoclue-demo-agent.desktop"),
                         "app-geoclue\\x2ddemo\\x2dagent@autostart.service")
        self.assertEqual(startup.app_unit("org.kde.kdeconnect.daemon"),
                         "app-org.kde.kdeconnect.daemon@autostart.service")
        self.assertEqual(startup.escape_unit("a b"), "a\\x20b")


class Judge(unittest.TestCase):
    which = staticmethod(lambda p: "/usr/bin/x" if "present" in p else None)

    def judge(self, **entry):
        return startup.judge(entry, which=self.which)

    def test_rules(self):
        self.assertEqual(self.judge(), (True, True, ""))
        self.assertEqual(self.judge(NotShowIn="GNOME;Hyprland;")[:2], (False, True))
        self.assertEqual(self.judge(Hidden="true")[:2], (False, True))
        self.assertEqual(self.judge(OnlyShowIn="GNOME;Unity;"), (False, False, "only for GNOME, Unity"))
        self.assertEqual(self.judge(OnlyShowIn="Hyprland;COSMIC;"), (True, True, ""))
        self.assertEqual(self.judge(**{"X-systemd-skip": "true"})[:2], (False, False))
        self.assertEqual(self.judge(TryExec="/usr/bin/missing")[:2], (False, False))
        self.assertEqual(self.judge(TryExec="present"), (True, True, ""))
        # X-GNOME-Autostart-enabled is not one of the generator's rules
        self.assertEqual(self.judge(**{"X-GNOME-Autostart-enabled": "false"}), (True, True, ""))


class Rewrite(unittest.TestCase):
    BASE = "[Desktop Entry]\nName=A\nName[de]=B\nExec=a\n\n[Desktop Action x]\nExec=b\n"

    def test_off_adds_notshowin_inside_the_entry_group(self):
        out = startup.rewrite(self.BASE, on=False)
        entry = startup.read_entry(out)
        self.assertEqual(entry["NotShowIn"], "Hyprland;")
        self.assertLess(out.index("NotShowIn"), out.index("[Desktop Action x]"))
        self.assertIn("Name[de]=B", out)

    def test_off_keeps_other_desktops_and_does_not_repeat(self):
        out = startup.rewrite("[Desktop Entry]\nNotShowIn=GNOME;Hyprland;\n", on=False)
        self.assertEqual(startup.read_entry(out)["NotShowIn"], "GNOME;Hyprland;")

    def test_on_removes_only_hyprland_and_unhides(self):
        out = startup.rewrite("[Desktop Entry]\nNotShowIn=GNOME;Hyprland;\nHidden=true\n", on=True)
        entry = startup.read_entry(out)
        self.assertEqual(entry["NotShowIn"], "GNOME;")
        self.assertEqual(entry["Hidden"], "false")
        out = startup.rewrite("[Desktop Entry]\nNotShowIn=Hyprland;\n", on=True)
        self.assertNotIn("NotShowIn", out)

    def test_round_trip(self):
        off = startup.rewrite(self.BASE, on=False)
        self.assertEqual(startup.judge(startup.read_entry(off), which=lambda p: p)[0], False)
        on = startup.rewrite(off, on=True)
        self.assertEqual(startup.judge(startup.read_entry(on), which=lambda p: p)[0], True)


class Units(Scratch):
    def test_desktop_units(self):
        unit_dir = startup.UNIT_DIR
        write(os.path.join(unit_dir, "a.service"), "[Install]\nWantedBy=graphical-session.target\n")
        write(os.path.join(unit_dir, "b.service"), "[Service]\nType=oneshot\n")          # a timer's job
        write(os.path.join(unit_dir, "t@.service"), "[Install]\nWantedBy=x\n")             # template
        os.makedirs(os.path.join(unit_dir, "graphical-session.target.wants"))
        os.symlink("/usr/lib/systemd/user/mako.service",
                   os.path.join(unit_dir, "graphical-session.target.wants", "mako.service"))
        startup.remember("gone.service", True)
        self.assertEqual(startup.desktop_units(unit_dir),
                         ["mako.service", "a.service", "waybar.service", "gone.service"])
        startup.remember("gone.service", False)
        self.assertNotIn("gone.service", startup.desktop_units(unit_dir))

    def test_essential_needs_force(self):
        startup.KNOWN = ["waybar.service", "osd.service"]
        with self.assertRaises(SystemExit):
            startup.switch("waybar", False)
        self.assertEqual(self.calls, [])
        startup.switch("waybar", False, force=True)
        self.assertIn(("disable", "--now", "waybar.service"), self.calls)
        self.assertIn("waybar.service", startup.remembered())
        startup.switch("waybar", True)
        self.assertIn(("enable", "--now", "waybar.service"), self.calls)
        self.assertNotIn("waybar.service", startup.remembered())

    def test_route_failure_is_not_remembered(self):
        """A timer switched through its owner script: when that script
        fails, the switch says so and nothing is recorded as off."""
        startup.KNOWN = ["theme-schedule.timer"]
        saved = startup.ROUTES
        startup.ROUTES = {"theme-schedule.timer": (["false"], ["false"])}
        try:
            with self.assertRaises(SystemExit):
                startup.switch("theme-schedule.timer", False)
        finally:
            startup.ROUTES = saved
        self.assertNotIn("theme-schedule.timer", startup.remembered())

    def test_unknown_unit_refused(self):
        with self.assertRaises(SystemExit):
            startup.switch("sshd.service", False)
        self.assertEqual(self.calls, [])


class Autostart(Scratch):
    def test_user_file_wins_and_switch_writes_override(self):
        sysdir = startup.SYSTEM_AUTOSTART[0]
        write(os.path.join(sysdir, "app-one.desktop"), "[Desktop Entry]\nName=One\nExec=one\n")
        write(os.path.join(sysdir, "gnome.desktop"), "[Desktop Entry]\nName=G\nOnlyShowIn=GNOME;\n")
        write(os.path.join(startup.USER_AUTOSTART, "mine.desktop"),
              "[Desktop Entry]\nName=Mine\nNotShowIn=Hyprland;\n")
        rows = {e["id"]: e for e in startup.autostart_entries(which=lambda p: p)}
        self.assertEqual((rows["app-one.desktop"]["on"], rows["app-one.desktop"]["where"]), (True, "system"))
        self.assertEqual((rows["mine.desktop"]["on"], rows["mine.desktop"]["where"]), (False, "yours"))
        self.assertFalse(rows["gnome.desktop"]["switchable"])

        startup.autostart_switch("app-one", False)
        override = os.path.join(startup.USER_AUTOSTART, "app-one.desktop")
        with open(override) as handle:
            self.assertIn("NotShowIn=Hyprland;", handle.read())
        self.assertIn(("daemon-reload",), self.calls)
        self.assertIn(("stop", "--no-block", "app-app\\x2done@autostart.service"), self.calls)
        rows = {e["id"]: e for e in startup.autostart_entries(which=lambda p: p)}
        self.assertEqual((rows["app-one.desktop"]["on"], rows["app-one.desktop"]["where"]),
                         (False, "system, changed by you"))
        with open(os.path.join(sysdir, "app-one.desktop")) as handle:
            self.assertNotIn("NotShowIn", handle.read())        # the system file is never touched

        with self.assertRaises(SystemExit):
            startup.autostart_switch("gnome.desktop", True)


class Lua(Scratch):
    def test_execs(self):
        write(os.path.join(startup.LUA_DIR, "autostart.lua"),
              'local fallback_daemons = {\n    "waybar",\n    "mako",\n}\n'
              'hl.on("hyprland.start", function()\n'
              '    for _, cmd in ipairs(fallback_daemons) do hl.exec_cmd(cmd) end\n'
              '    -- Japanese input.\n    -- More words.\n    hl.exec_cmd("fcitx5 -d")\n'
              '    -- hl.exec_cmd("commented out")\nend)\n')
        write(os.path.join(startup.LUA_DIR, "night.lua"),
              'x = { boot = hl.timer(function() hl.exec_cmd("n.sh auto") end,\n'
              '        { timeout = 3000, type = "oneshot" }),\n'
              '  tick = hl.timer(function() hl.exec_cmd("n.sh auto") end,\n'
              '        { timeout = 300000, type = "repeat" }) }\n')
        rows = startup.lua_execs(startup.LUA_DIR)
        self.assertEqual([r["cmd"] for r in rows if r["fallback"]], ["waybar", "mako"])
        login = [r for r in rows if r["when"] == "once at login"]
        self.assertEqual([(r["cmd"], r["why"]) for r in login], [("fcitx5 -d", "Japanese input. More words.")])
        self.assertEqual([r["when"] for r in rows if r["cmd"] == "n.sh auto"],
                         ["3 s after every config load", "every 5 min"])


class PageWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """The page's word helpers, taken out of settings_pages/startup.py
        without importing it: the module needs GTK 3, and another test (or
        the interpreter) may already hold GTK 4."""
        import ast
        import types
        path = os.path.join(helpers.SCRIPTS, "settings_pages", "startup.py")
        with open(path) as handle:
            tree = ast.parse(handle.read())
        names = {"duration", "size", "when", "service_sub", "timer_sub", "autostart_sub", "short_why",
                 "own_unit", "hits_me", "call"}
        body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        cls.page = types.SimpleNamespace()
        import subprocess
        scope = {"time": time, "subprocess": subprocess}
        exec(compile(ast.Module(body=body, type_ignores=[]), path, "exec"), scope)
        for name in names:
            setattr(cls.page, name, scope[name])

    def test_duration_and_size(self):
        self.assertEqual(self.page.duration(30), "30 s")
        self.assertEqual(self.page.duration(600), "10 min")
        self.assertEqual(self.page.duration(7200), "2 h")
        self.assertEqual(self.page.duration(3 * 86400), "3 days")
        self.assertEqual(self.page.size(15 * 1048576), "15 MB")
        self.assertEqual(self.page.size(None), "")

    def test_when(self):
        now = time.mktime((2026, 10, 20, 3, 30, 0, 0, 0, -1))
        self.assertEqual(self.page.when(now + 15 * 60, now), "03:45 (in 15 min)")
        self.assertEqual(self.page.when(now + 18 * 3600, now), "21:30 (in 18 h)")
        self.assertEqual(self.page.when(now - 6 * 3600, now), "yesterday 21:30 (6 h ago)")
        self.assertEqual(self.page.when(None, now), "")

    def test_subs(self):
        s = {"unit": "x.service", "state": "running", "since_s": 120, "memory": 2 * 1048576, "restarts": 2,
             "enabled": True, "owner": "this desktop's unit", "essential": "the bar", "log": ""}
        text = self.page.service_sub(s)
        self.assertIn("running for 2 min", text)
        self.assertIn("restarted 2×", text)
        self.assertIn("Essential: the bar", text)
        t = {"schedule": "every day at 21:30", "on": False, "next": None, "last": None, "job": "j.service",
             "job_title": "Job", "job_result": "", "route": "", "note": ""}
        self.assertIn("off", self.page.timer_sub(t))
        self.assertIn("not run yet", self.page.timer_sub(t))
        self.assertEqual(self.page.short_why("One. " + "word " * 60).split(".")[0], "One")


    def test_own_unit_and_restart_confirm(self):
        cg = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/waybar-toolbox.service\n"
        self.assertEqual(self.page.own_unit(cg), "waybar-toolbox.service")
        self.assertEqual(self.page.own_unit("0::/user.slice/x/app.slice/run-r1.scope\n"), "")
        me = "waybar-toolbox.service"
        self.assertTrue(self.page.hits_me({"unit": me}, me))
        self.assertTrue(self.page.hits_me({"unit": "waybar.service", "parts": [me]}, me))
        self.assertFalse(self.page.hits_me({"unit": "mako.service", "parts": []}, me))
        self.assertFalse(self.page.hits_me({"unit": "mako.service"}, ""))

    def test_call_reports_stderr(self):
        self.assertEqual(self.page.call("true"), "")
        self.assertEqual(self.page.call("sh", "-c", "echo 'startup.py: no such unit' >&2; exit 1"),
                         "no such unit")


if __name__ == "__main__":
    unittest.main()
