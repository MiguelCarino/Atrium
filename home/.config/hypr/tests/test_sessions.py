"""sessions.py (workspace sessions), closed-windows.py (reopen the last
closed window), the Settings page's helpers and the launcher's session
items. Hermetic: Hyprland is a fake clients/monitors list, /proc is stubbed
per test, .desktop entries live in a scratch folder, and nothing is
launched -- spawn and hyprctl eval only record what they were asked."""
import json
import os
import tempfile
import time
import unittest

import helpers

S = helpers.import_script("sessions.py")
CW = helpers.import_script("closed-windows.py")
CW.sessions = S         # its own `import sessions` is another copy: the stubs go on this one
CW.desklog.log = lambda *a, **k: None   # not into the real journal

MONITORS = [{"id": 0, "name": "DP-1", "x": 0, "y": 0, "width": 3440, "height": 1440, "scale": 1, "transform": 0},
            {"id": 1, "name": "HDMI-A-1", "x": 3440, "y": 0, "width": 1920, "height": 1080, "scale": 1,
             "transform": 1}]


def client(addr, cls, pid, ws="1", at=(10, 50), size=(800, 600), floating=False, title="t", **kw):
    c = {"address": addr, "class": cls, "initialClass": cls, "pid": pid, "title": title, "mapped": True,
         "workspace": {"id": int(ws) if ws.lstrip("-").isdigit() else -98, "name": ws}, "monitor": 0,
         "at": list(at), "size": list(size), "floating": floating, "fullscreen": 0, "fullscreenClient": 0,
         "pinned": False}
    c.update(kw)
    return c


class Fake(unittest.TestCase):
    """A scratch state folder, a scratch applications folder, and stubbed
    /proc, Hyprland and launching."""

    PROCS = {}

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.saved = {k: getattr(S, k) for k in (
            "STATE_DIR", "APP_DIRS", "LOCK", "OFFERED", "cmdline", "proc_cwd", "children", "exe_name",
            "foreground", "scope_app", "is_game_process", "hypr_json", "hypr_eval", "spawn", "instance",
            "private_classes", "mpv_state")}
        self.saved_stack = CW.STACK
        S.STATE_DIR = os.path.join(self.dir, "sessions")
        S.LOCK = os.path.join(self.dir, "lock")
        S.OFFERED = os.path.join(self.dir, "offered")
        CW.STACK = os.path.join(self.dir, "closed.json")
        apps = os.path.join(self.dir, "applications")
        os.makedirs(apps)
        for did, body in (("org.mozilla.firefox", "Name=Firefox\nExec=firefox %u\nStartupWMClass=firefox\n"),
                          ("org.gnome.Nautilus", "Name=Files\nExec=nautilus --new-window %U\n"),
                          ("com.vscodium.codium", "Name=VSCodium\nExec=/usr/bin/flatpak run com.vscodium.codium\n"
                                                  "StartupWMClass=VSCodium\n"),
                          ("org.gnome.Calculator", "Name=Calculator\nExec=gnome-calculator\n"),
                          ("kitty", "Name=kitty\nExec=kitty\n"),
                          ("kitty-open", "Name=kitty URL Launcher\nExec=kitty +open %U\nNoDisplay=true\n")):
            with open(os.path.join(apps, did + ".desktop"), "w") as handle:
                handle.write("[Desktop Entry]\nType=Application\n" + body)
        S.APP_DIRS = [apps]
        S._INDEX["stamp"] = None
        self.procs = dict(self.PROCS)     # pid -> {"argv", "cwd", "kids", "exe", "fg", "scope"}
        S.cmdline = lambda pid: self.procs.get(pid, {}).get("argv", [])
        S.proc_cwd = lambda pid: self.procs.get(pid, {}).get("cwd")
        S.children = lambda pid: self.procs.get(pid, {}).get("kids", [])
        S.exe_name = lambda pid: self.procs.get(pid, {}).get("exe", "")
        S.foreground = lambda pid: self.procs.get(pid, {}).get("fg")
        S.scope_app = lambda pid: self.procs.get(pid, {}).get("scope")
        S.is_game_process = lambda pid: self.procs.get(pid, {}).get("game", False)
        S.private_classes = lambda: set()
        S.mpv_state = lambda pid: self.procs.get(pid, {}).get("mpv", (None, None))
        S.instance = lambda: "inst-now"
        self.clients, self.evals, self.spawned = [], [], []
        S.hypr_json = lambda what: {"clients": self.clients, "monitors": MONITORS}[what]
        S.hypr_eval = lambda lua: (self.evals.append(lua), True)[1]
        S.spawn = lambda launch: (self.spawned.append(launch), 1)[1]

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(S, k, v)
        CW.STACK = self.saved_stack
        S._INDEX["stamp"] = None


class Secrets(unittest.TestCase):
    def test_secret_argv(self):
        for argv in (["app", "--password=hunter2"], ["app", "--token", "x"], ["curl", "https://u:p@host/x"],
                     ["mysql", "-psecret"], ["gh", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"],
                     ["tool", "--api-key=1"], ["x", "https://h/?a=1&token=abc"],
                     ["x", "aB3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0eF"]):
            self.assertTrue(S.has_secret(argv), argv)

    def test_plain_argv(self):
        for argv in (["kitty", "--directory", "/home/u/Projects"], ["mpv", "/v/Movie (2001).mkv"],
                     ["nvim", "passwords.md"], ["code", "/home/u/src/authors"], ["htop"],
                     ["mpv", "/media/0123456789abcdef0123456789abcdef/clip.mkv"]):
            self.assertFalse(S.has_secret(argv), argv)

    def test_names(self):
        self.assertTrue(S.valid_name("work"))
        self.assertTrue(S.valid_name("Deep work 2"))
        for bad in ("", "_auto", ".x", "a/b", " x", "x" * 41):
            self.assertFalse(S.valid_name(bad), bad)
        self.assertTrue(S.session_path("a b?").endswith("a b%3F.json"))


class Scope(unittest.TestCase):
    def test_scope_names(self):
        saved = S.read
        try:
            for line, want in (
                    ("0::/user.slice/.../app-graphical.slice/app-flatpak-com.google.Chrome-431942825.scope",
                     "com.google.Chrome"),
                    ("0::/.../app-Hyprland-org.mozilla.firefox-3dddd4ba.scope", "org.mozilla.firefox"),
                    ("0::/.../app-Hyprland-foo\\x2dbar-1a2b.scope", "foo-bar"),
                    ("0::/user.slice/user@1000.service/session.slice/wayland-wm@hyprland.desktop.service", None)):
                S.read = lambda path, mode="r", l=line: l
                self.assertEqual(S.scope_app(1), want, line)
        finally:
            S.read = saved


class Capture(Fake):
    def test_terminal_cwd_and_safe_command(self):
        self.procs = {10: {"argv": ["kitty"], "kids": [11], "exe": "kitty"},
                      11: {"argv": ["-bash"], "cwd": "/home/u/proj", "fg": ["nvim", "a.py"]}}
        rec, why = S.capture(client("0x1", "kitty", 10), MONITORS)
        self.assertIsNone(why)
        self.assertEqual(rec["kind"], "terminal")
        self.assertEqual(rec["launch"]["argv"][:3], ["kitty", "--directory", "/home/u/proj"])
        self.assertIn("nvim a.py", rec["launch"]["argv"][-1])
        self.assertEqual(rec["key"], "term|kitty|/home/u/proj|nvim a.py")

    def test_terminal_unsafe_command_only_noted(self):
        self.procs = {10: {"argv": ["kitty"], "kids": [11], "exe": "kitty"},
                      11: {"argv": ["bash"], "cwd": "/srv", "fg": ["git", "push"]}}
        rec, _ = S.capture(client("0x1", "kitty", 10), MONITORS)
        self.assertEqual(rec["launch"]["argv"], ["kitty", "--directory", "/srv"])
        self.assertIn("git push", rec["note"])

    def test_terminal_secret_command_not_shown(self):
        self.procs = {10: {"argv": ["foot"], "kids": [11], "exe": "foot"},
                      11: {"argv": ["bash"], "cwd": "/srv", "fg": ["ssh", "--password=x", "h"]}}
        rec, _ = S.capture(client("0x1", "foot", 10), MONITORS)
        self.assertEqual(rec["launch"]["argv"], ["foot", "-D", "/srv"])
        self.assertNotIn("password", json.dumps(rec))

    def test_single_instance_terminal_uses_title(self):
        self.procs = {10: {"argv": ["kitty"], "kids": [11, 12], "exe": "kitty"},
                      11: {"argv": ["bash"]}, 12: {"argv": ["bash"]}}
        rec, _ = S.capture(client("0x1", "kitty", 10, title=f"u@h:{S.HOME} — kitty"), MONITORS)
        self.assertEqual(rec["launch"]["cwd"], S.HOME)

    def test_cosmic_term(self):
        self.procs = {10: {"argv": ["cosmic-term"], "kids": [11]}, 11: {"argv": ["bash"], "cwd": "/tmp"}}
        rec, _ = S.capture(client("0x1", "com.system76.CosmicTerm", 10), MONITORS)
        self.assertEqual(rec["launch"]["argv"], ["cosmic-term", "--working-directory", "/tmp"])

    def test_browser_is_just_reopened(self):
        self.procs = {20: {"argv": ["/usr/lib64/firefox/firefox", "--token=abc"], "exe": "firefox",
                           "scope": "org.mozilla.firefox"}}
        rec, _ = S.capture(client("0x2", "org.mozilla.firefox", 20), MONITORS)
        self.assertEqual(rec["launch"], {"desktop": "org.mozilla.firefox"})
        self.assertEqual(rec["kind"], "browser")
        self.assertNotIn("token", json.dumps(rec))

    def test_editor_folder_from_argv(self):
        self.procs = {30: {"argv": ["codium", S.HOME], "exe": "codium"}}
        rec, _ = S.capture(client("0x3", "VSCodium", 30), MONITORS)
        self.assertEqual(rec["launch"], {"desktop": "com.vscodium.codium", "args": [S.HOME]})

    def test_files_folder_from_title(self):
        self.procs = {40: {"argv": ["nautilus"], "exe": "nautilus"}}
        rec, _ = S.capture(client("0x4", "org.gnome.Nautilus", 40, title="Home"), MONITORS)
        self.assertEqual(rec["launch"], {"desktop": "org.gnome.Nautilus", "args": [S.HOME]})

    def test_mpv_file_and_position(self):
        self.procs = {50: {"argv": ["mpv"], "exe": "mpv", "mpv": ("/v/a.mkv", 754.2)}}
        rec, _ = S.capture(client("0x5", "mpv", 50), MONITORS)
        self.assertEqual(rec["launch"]["argv"], ["mpv", "--start=754", "/v/a.mkv"])

    def test_mpv_stream_with_secret_skipped(self):
        self.procs = {50: {"argv": ["mpv"], "exe": "mpv", "mpv": ("https://h/live?token=abc", 3)}}
        rec, why = S.capture(client("0x5", "mpv", 50), MONITORS)
        self.assertIsNone(rec)

    def test_unknown_app_from_desktop_then_argv(self):
        self.procs = {60: {"argv": ["gnome-calculator"], "exe": "gnome-calculator"},
                      61: {"argv": ["sh", "-c", "x"], "exe": "sh", "cwd": "/tmp"},
                      62: {"argv": ["sh", "--password", "x"], "exe": "sh"}}
        rec, _ = S.capture(client("0x6", "org.gnome.Calculator", 60), MONITORS)
        self.assertEqual(rec["launch"], {"desktop": "org.gnome.Calculator"})
        rec, _ = S.capture(client("0x7", "weird-tool", 61), MONITORS)
        self.assertEqual(rec["launch"], {"argv": ["sh", "-c", "x"], "cwd": "/tmp"})
        rec, why = S.capture(client("0x8", "weird-tool", 62), MONITORS)
        self.assertIsNone(rec)
        self.assertIn("secret", why)

    def test_found_by_executable_keeps_its_command_line(self):
        self.procs = {90: {"argv": ["kitty", "--class", "x-test", "sleep", "40"], "exe": "kitty"}}
        rec, _ = S.capture(client("0xf", "x-test", 90), MONITORS)
        self.assertEqual(rec["launch"]["argv"], ["kitty", "--class", "x-test", "sleep", "40"])
        self.assertEqual(rec["app"], "x-test")
        self.assertEqual(S.desktop_index()["exe"]["kitty"]["id"], "kitty")

    def test_scope_of_a_terminal_is_not_the_app(self):
        """A program started in kitty sits in kitty's scope: not kitty.desktop."""
        self.procs = {70: {"argv": ["gnome-calculator"], "exe": "gnome-calculator", "scope": "kitty"}}
        rec, _ = S.capture(client("0x9", "org.gnome.Calculator", 70), MONITORS)
        self.assertEqual(rec["launch"], {"desktop": "org.gnome.Calculator"})

    def test_skipped(self):
        self.procs = {80: {"argv": ["steam"], "exe": "steam"}, 81: {"argv": ["game.exe"], "game": True}}
        for c, reason in ((client("0xa", "steam_app_123", 80), "game"),
                          (client("0xb", "anything", 81), "game"),
                          (client("0xc", "org.mozilla.firefox", 20, title="Save As"), "dialog"),
                          (client("0xd", "xdg-desktop-portal-gtk", 20), "dialog"),
                          (client("0xe", "kitty", 10, ws="special:magic"), "scratchpad")):
            rec, why = S.capture(c, MONITORS)
            self.assertIsNone(rec)
            self.assertIn(reason, why.lower())

    def test_games_when_asked(self):
        self.procs = {80: {"argv": ["steam"], "exe": "steam"}}
        rec, _ = S.capture(client("0xa", "steam_app_123", 80), MONITORS, {"games": True})
        self.assertEqual(rec["launch"], {"argv": ["steam", "steam://rungameid/123"]})

    def test_geometry_relative_to_monitor(self):
        self.procs = {60: {"argv": ["gnome-calculator"], "exe": "gnome-calculator"}}
        rec, _ = S.capture(client("0x6", "org.gnome.Calculator", 60, at=(3500, 100), floating=True,
                                  monitor=1), MONITORS)
        self.assertEqual((rec["monitor"], rec["rel"], rec["floating"]), ("HDMI-A-1", [60, 100], True))

    def test_private_title_dropped(self):
        self.procs = {20: {"argv": ["firefox"], "exe": "firefox", "scope": "org.mozilla.firefox"}}
        rec, _ = S.capture(client("0x2", "org.mozilla.firefox", 20, title="x — Private Browsing"), MONITORS)
        self.assertEqual(rec["title"], "")


class Snapshots(Fake):
    def setUp(self):
        super().setUp()
        self.procs = {20: {"argv": ["firefox"], "exe": "firefox", "scope": "org.mozilla.firefox"},
                      10: {"argv": ["kitty"], "kids": [11], "exe": "kitty"},
                      11: {"argv": ["bash"], "cwd": "/srv"}}
        self.clients = [client("0x2", "org.mozilla.firefox", 20, ws="2"),
                        client("0x3", "org.mozilla.firefox", 20, ws="1"),
                        client("0x1", "kitty", 10, ws="1", at=(900, 50))]

    def test_order_and_shared(self):
        snap = S.snapshot()
        self.assertEqual([w["class"] for w in snap["windows"]], ["org.mozilla.firefox", "kitty", "org.mozilla.firefox"])
        self.assertEqual([bool(w.get("shared")) for w in snap["windows"]], [False, False, True])
        self.assertEqual(snap["instance"], "inst-now")

    def test_plan_skips_open(self):
        recs = S.snapshot()["windows"]
        # firefox open (both of its windows go with it), the terminal not
        launch, wait, skipped = S.plan(recs, [client("0x9", "org.mozilla.firefox", 99)], MONITORS)
        self.assertEqual([r["class"] for r in launch], ["kitty"])
        self.assertEqual(len(skipped), 2)
        # nothing open: firefox once, its second window waited for
        launch, wait, skipped = S.plan(recs, [], MONITORS)
        self.assertEqual([r["class"] for r in launch], ["org.mozilla.firefox", "kitty"])
        self.assertEqual(len(wait), 3)

    def test_place_lua(self):
        rec = {"workspace": "3", "floating": True, "size": [800, 600], "monitor": "DP-1", "rel": [3000, 100],
               "fullscreen": 0, "pinned": True}
        lua = S.place_lua("0xab", rec, MONITORS, {"workspace": {"name": "1"}, "floating": False})
        self.assertIn('hl.get_window("address:0xab")', lua)
        self.assertIn('workspace = "3", follow = false, window = "address:0xab"', lua)
        self.assertIn('float({ action = "enable"', lua)
        self.assertIn("resize({ x = 800, y = 600", lua)
        self.assertIn("move({ x = 2640, y = 100", lua)        # kept on the monitor
        self.assertIn("pin(", lua)
        tiled = S.place_lua("0xab", {"workspace": "name:mail", "floating": False, "fullscreen": 1},
                            MONITORS, {"workspace": {"name": "1"}, "floating": True})
        self.assertIn('float({ action = "disable"', tiled)
        self.assertIn("fullscreen_state({ internal = 1, client = 1", tiled)
        self.assertNotIn("resize", tiled)
        same = S.place_lua("0xab", {"workspace": "1"}, MONITORS, {"workspace": {"name": "1"}})
        self.assertNotIn("workspace =", same)

    def test_restore_matches_new_windows(self):
        recs = S.snapshot()["windows"]
        before = [client("0xold", "kitty", 5, ws="9")]
        later = before + [client("0xk", "kitty", 10), client("0xf1", "org.mozilla.firefox", 20),
                          client("0xf2", "org.mozilla.firefox", 20)]
        polls = iter([before, before, later])
        S.hypr_json = lambda what: MONITORS if what == "monitors" else next(polls, later)
        t = [0.0]
        result = S.restore_records(recs, "test", sleep=lambda s: t.__setitem__(0, t[0] + s),
                                   clock=lambda: t[0])
        self.assertEqual(len(self.spawned), 2)          # firefox once, kitty
        self.assertEqual(len(result["placed"]), 3)
        self.assertEqual(result["missing"], [])
        self.assertTrue(any("0xk" in lua for lua in self.evals))
        self.assertFalse(any("0xold" in lua for lua in self.evals))

    def test_restore_reports_missing(self):
        recs = S.snapshot()["windows"]
        S.hypr_json = lambda what: MONITORS if what == "monitors" else []
        t = [0.0]
        result = S.restore_records(recs, "test", wait_s=5, sleep=lambda s: t.__setitem__(0, t[0] + s),
                                   clock=lambda: t[0])
        self.assertEqual({r["class"] for r in result["missing"]}, {"kitty", "org.mozilla.firefox"})
        self.assertIn("no window from", S.result_text(result))


class Autosave(Fake):
    def setUp(self):
        super().setUp()
        self.procs = {10: {"argv": ["kitty"], "kids": [11], "exe": "kitty"}, 11: {"argv": ["bash"], "cwd": "/a"}}
        self.clients = [client("0x1", "kitty", 10), client("0x2", "kitty", 10, at=(900, 0))]

    def test_rotation_on_new_instance(self):
        S.instance = lambda: "old"
        S.autosave()
        self.assertIsNone(S.last_session())             # same instance: nothing from "before"
        S.instance = lambda: "new"
        self.assertEqual(len(S.last_session()["windows"]), 2)   # _auto from before this login
        self.clients = []
        S.autosave()                                    # first save of the new instance
        prev = S.last_session()
        self.assertEqual((prev["instance"], len(prev["windows"])), ("old", 2))

    def test_exit_guard(self):
        S.autosave()
        self.clients = self.clients[:1]
        S.autosave(exit_mode=True)                      # half-closed at logout: dropped
        self.assertEqual(len(S.load_session(S.AUTO)["windows"]), 2)
        S.autosave()                                    # the timer: you closed one, fine
        self.assertEqual(len(S.load_session(S.AUTO)["windows"]), 1)

    def test_autosave_off(self):
        S.save_settings({"autosave": False})
        S.autosave()
        self.assertIsNone(S.load_session(S.AUTO))

    def test_sessions_listing(self):
        S.write_json(S.session_path("work"), S.snapshot())
        S.autosave()
        rows = S.sessions()
        self.assertEqual([r["name"] for r in rows], ["work"])
        self.assertEqual(rows[0]["apps"], "2× kitty")


class Closed(Fake):
    def setUp(self):
        super().setUp()
        self.procs = {20: {"argv": ["firefox"], "exe": "firefox", "scope": "org.mozilla.firefox"},
                      10: {"argv": ["kitty"], "kids": [11], "exe": "kitty"},
                      11: {"argv": ["bash"], "cwd": "/srv"},
                      12: {"argv": ["kitty"], "kids": [13], "exe": "kitty"},
                      13: {"argv": ["bash"], "cwd": "/tmp"}}
        self.t = [100.0]
        self.tracker = CW.Tracker(clock=lambda: self.t[0])
        self.clients = [client("0x1", "kitty", 10), client("0x2", "org.mozilla.firefox", 20)]
        self.tracker.refresh()

    def event(self, line):
        CW.handle(self.tracker, line)

    def test_closed_window_is_kept_and_reopened(self):
        self.clients = self.clients[1:]
        self.event("closewindow>>1")
        with CW.Stack() as st:
            self.assertEqual(st.items[-1]["record"]["launch"]["argv"], ["kitty", "--directory", "/srv"])
        recorded = []
        saved = S.restore_records
        S.restore_records = lambda recs, label, skip_open=True, **kw: (
            recorded.append((recs, skip_open)), {"placed": recs, "missing": [], "skipped": []})[1]
        try:
            self.assertEqual(CW.reopen(), 0)
        finally:
            S.restore_records = saved
        self.assertEqual(recorded[0][0][0]["class"], "kitty")
        self.assertFalse(recorded[0][1])                # reopen never skips "already open"
        with CW.Stack() as st:
            self.assertEqual(st.items, [])

    def test_short_lived_window_not_kept(self):
        self.event("openwindow>>3,1,kitty,x")
        self.clients.append(client("0x3", "kitty", 12))
        self.tracker.refresh()
        self.t[0] += 1
        self.event("closewindow>>3")
        with CW.Stack() as st:
            self.assertEqual(st.items, [])
        self.event("openwindow>>4,1,kitty,x")
        self.clients.append(client("0x4", "kitty", 12))
        self.tracker.refresh()
        self.t[0] += 5
        self.event("closewindow>>4")
        with CW.Stack() as st:
            self.assertEqual(len(st.items), 1)

    def test_secondary_window_and_popup_not_kept(self):
        self.event("openwindow>>5,1,org.mozilla.firefox,x")
        self.clients.append(client("0x5", "org.mozilla.firefox", 20))
        self.event("openwindow>>6,1,org.mozilla.firefox,x")
        self.clients.append(client("0x6", "org.mozilla.firefox", 20, floating=True, size=(150, 80)))
        self.tracker.refresh()
        self.t[0] += 10
        self.assertEqual(self.tracker.closed("0x5")[1], "a secondary window of an app still open")
        self.assertEqual(self.tracker.closed("0x6")[1], "a popup")

    def test_terminals_are_never_secondary(self):
        self.event("openwindow>>7,1,kitty,x")
        self.clients.append(client("0x7", "kitty", 10))
        self.tracker.refresh()
        self.t[0] += 10
        rec, why = self.tracker.closed("0x7")
        self.assertIsNotNone(rec, why)

    def test_stack_is_capped(self):
        for i in range(CW.KEEP + 5):
            CW.push({"app": str(i)})
        with CW.Stack() as st:
            self.assertEqual(len(st.items), CW.KEEP)
            self.assertEqual(st.items[-1]["record"]["app"], str(CW.KEEP + 4))

    def test_gone_window_waits_for_its_event(self):
        """A refresh between the window going and its closewindow keeps it."""
        self.clients = self.clients[1:]
        self.tracker.refresh()
        self.event("closewindow>>1")
        with CW.Stack() as st:
            self.assertEqual(len(st.items), 1)


class Page(unittest.TestCase):
    def test_saved_text(self):
        from settings_pages import sessions as page
        now = time.mktime((2026, 10, 21, 15, 0, 0, 0, 0, -1))
        self.assertEqual(page.saved_text(now - 3600, now), "today 14:00")
        self.assertEqual(page.saved_text(now - 86400, now), "yesterday 15:00")
        self.assertTrue(page.session_sub({"windows": 1, "saved": now, "apps": "kitty"}, now)
                        .startswith("1 window  ·  today"))


class Launcher(Fake):
    def test_items(self):
        L = helpers.import_script("launcher.py", "launcher")
        L.session_store = S
        self.procs = {10: {"argv": ["kitty"], "kids": [11], "exe": "kitty"}, 11: {"argv": ["bash"], "cwd": "/a"}}
        self.clients = [client("0x1", "kitty", 10)]
        S.write_json(S.session_path("Deep work"), S.snapshot())
        names = [i.name for i in L.session_items("sessions")]
        self.assertIn("Session: Deep work", names)
        self.assertEqual([i.name for i in L.session_items("sesión deep")], ["Session: Deep work"])
        self.assertEqual([i.name for i in L.session_items("save session Evening")], ["Save session: Evening"])
        self.assertEqual(L.session_items("save session _x"), [])
        self.assertEqual(L.session_items("firefox"), [])
        S.instance = lambda: "old"
        S.autosave()
        S.instance = lambda: "new"
        self.assertEqual([i.name for i in L.session_items("where was I")], ["Where was I: restore the last session"])


if __name__ == "__main__":
    unittest.main()
