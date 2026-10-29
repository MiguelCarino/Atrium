"""notify_source.py: which window a notification came from (by its process
chain, else by its names against window classes and the installed app), when
it opens the app instead, the button's words, and the command that goes
there. Hermetic: clients, apps and /proc are built here."""
import unittest

import helpers

ns = helpers.import_script("notify_source.py")

FIREFOX_APP = {"id": "org.mozilla.firefox.desktop", "name": "Firefox", "wmclass": "firefox",
               "exec": "firefox", "hidden": False}
FILES_APP = {"id": "org.gnome.Nautilus.desktop", "name": "Files", "wmclass": "", "exec": "nautilus",
             "hidden": False}
SIGNAL_APP = {"id": "signal-desktop.desktop", "name": "Signal", "wmclass": "Signal", "exec": "signal-desktop",
              "hidden": False}
APPS = [FIREFOX_APP, FILES_APP, SIGNAL_APP]


def client(addr, cls, pid=100, focus=1, initial=None):
    return {"address": addr, "class": cls, "initialClass": initial or cls, "pid": pid,
            "focusHistoryID": focus, "mapped": True}


def item(app="", entry="", actions=(), pids=()):
    return {"app": app, "desktop_entry": entry, "actions": list(actions), "pids": list(pids)}


class Names(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(ns.variants("org.gnome.Nautilus.desktop"),
                         {"org.gnome.nautilus", "nautilus", "orggnomenautilus"})
        self.assertEqual(ns.variants("notify-send"), set())
        self.assertEqual(ns.variants(""), set())

    def test_resolve_by_entry_then_name(self):
        self.assertIs(ns.resolve_app(item(entry="org.mozilla.firefox"), APPS), FIREFOX_APP)
        self.assertIs(ns.resolve_app(item(app="Firefox"), APPS), FIREFOX_APP)
        self.assertIs(ns.resolve_app(item(app="nautilus"), APPS), FILES_APP)
        self.assertIsNone(ns.resolve_app(item(app="Railguard"), APPS))
        self.assertIsNone(ns.resolve_app(item(app="notify-send"), APPS))


class Window(unittest.TestCase):
    def test_by_class_and_reverse_dns(self):
        clients = [client("0x1", "kitty"), client("0x2", "org.mozilla.firefox")]
        self.assertEqual(ns.find_window(item("Firefox"), clients)["address"], "0x2")
        # the installed app's StartupWMClass bridges a name and a class
        clients = [client("0x3", "Signal")]
        self.assertEqual(ns.find_window(item(entry="signal-desktop"), clients,
                                        ns.resolve_app(item(entry="signal-desktop"), APPS))["address"], "0x3")

    def test_most_recent_of_several(self):
        clients = [client("0x1", "firefox", focus=4), client("0x2", "firefox", focus=1),
                   client("0x3", "firefox", focus=-1)]
        self.assertEqual(ns.find_window(item("firefox"), clients)["address"], "0x2")

    def test_process_chain_beats_names(self):
        # a script in a terminal: its parent is the terminal's process
        clients = [client("0x1", "kitty", pid=50), client("0x2", "org.mozilla.firefox", pid=60)]
        self.assertEqual(ns.find_window(item("Firefox", pids=[900, 800, 50, 2]), clients)["address"], "0x1")

    def test_pid_walked_through_proc(self):
        parents = {900: 800, 800: 50, 50: 1}
        clients = [client("0x1", "kitty", pid=50)]
        it = {"app": "", "desktop_entry": "", "pid": 900}
        self.assertEqual(ns.find_window(it, clients, ppid_of=lambda p: parents.get(p, 0))["address"], "0x1")
        self.assertEqual(ns.ancestors(900, lambda p: parents.get(p, 0)), [900, 800, 50])
        self.assertEqual(ns.ancestors(5, lambda p: 5), [5])           # a loop ends

    def test_nothing(self):
        self.assertIsNone(ns.find_window(item("notify-send"), [client("0x1", "kitty")]))
        self.assertIsNone(ns.find_window(item("Firefox"), []))


class Target(unittest.TestCase):
    def test_window(self):
        tgt = ns.target(item("Firefox", "org.mozilla.firefox"), [client("0x2", "org.mozilla.firefox")], APPS)
        self.assertEqual(tgt, {"kind": "window", "address": "0x2", "label": "Firefox"})
        self.assertEqual(ns.button_label(tgt), "Go to Firefox")

    def test_generic_app_name_takes_the_window_class(self):
        tgt = ns.target(item("notify-send", pids=[9, 50]), [client("0x1", "kitty", pid=50)], [])
        self.assertEqual(tgt["label"], "kitty")

    def test_launch_only_without_a_default_action(self):
        tgt = ns.target(item("Signal"), [], APPS)
        self.assertEqual(tgt, {"kind": "launch", "app_id": "signal-desktop.desktop", "label": "Signal"})
        self.assertEqual(ns.button_label(tgt), "Open Signal")
        self.assertIsNone(ns.target(item("Signal", actions=[("default", "Open")]), [], APPS))
        hidden = dict(SIGNAL_APP, hidden=True)
        self.assertIsNone(ns.target(item("Signal"), [], [hidden]))

    def test_long_label_cut(self):
        self.assertEqual(ns.button_label({"kind": "window", "label": "A very long application name"}),
                         "Go to A very long appli…")
        self.assertEqual(ns.button_label(None), "")


class Argv(unittest.TestCase):
    def test_focus(self):
        self.assertEqual(ns.go_argv({"kind": "window", "address": "0x55ab"}),
                         ["hyprctl", "dispatch", "hl.dsp.focus({ window = 'address:0x55ab' })"])

    def test_bad_address_is_refused(self):
        self.assertIsNone(ns.go_argv({"kind": "window", "address": "0x1' }) os.execute('x"}))
        self.assertIsNone(ns.go_argv({"kind": "window", "address": "0x"}))
        self.assertIsNone(ns.go_argv(None))

    def test_launch(self):
        argv = ns.go_argv({"kind": "launch", "app_id": "signal-desktop.desktop"})
        self.assertEqual(argv[-1], "signal-desktop.desktop")
        self.assertIn(argv[0], ("uwsm", "gtk-launch"))


if __name__ == "__main__":
    unittest.main()
