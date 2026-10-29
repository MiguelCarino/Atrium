"""The toolbox card's open/closed state and what closes it: toolbox.sh asks
Hyprland (the card is open while its layer surface is on top or overlay;
waybar hides a bar by sending it to the bottom layer), and
toolbox_dismiss.py folds it away when you move to another workspace, window
or fullscreen; and toolbox.sh status hides the sliders pill while the dock
has the toolbox button. Hermetic: hyprctl is a stub on PATH; no card is opened."""
import importlib.util
import json
import os
import socket
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401  (scratch XDG dirs)

WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
TOOLBOX = os.path.join(WAYBAR_SCRIPTS, "toolbox.sh")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(WAYBAR_SCRIPTS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def layers(level):
    return ('{"DP-1": {"levels": {"%s": [{"namespace": "waybar-toolbox", "w": 198}],'
            ' "0": [{"namespace": "wallpaper"}]}}}' % level)


class Shown(unittest.TestCase):
    """toolbox.sh's shown(), run with a hyprctl that prints the given layers."""

    def shown(self, out):
        with tempfile.TemporaryDirectory() as tmp:
            stub = os.path.join(tmp, "hyprctl")
            with open(stub, "w") as fh:
                fh.write("#!/bin/sh\ncat <<'EOF'\n%s\nEOF\n" % out)
            os.chmod(stub, stat.S_IRWXU)
            script = ('source <(sed -n "/^shown()/,/^}/p" "$1"); shown')
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"])
            return subprocess.run(["bash", "-c", script, "_", TOOLBOX], env=env).returncode == 0

    def test_overlay_is_open(self):
        self.assertTrue(self.shown(layers(3)))
        self.assertTrue(self.shown(layers(2)))

    def test_bottom_is_hidden(self):
        self.assertFalse(self.shown(layers(1)))

    def test_no_toolbox_or_no_answer(self):
        self.assertFalse(self.shown('{"DP-1": {"levels": {"3": []}}}'))
        self.assertFalse(self.shown(""))


class Status(unittest.TestCase):
    """toolbox.sh status, the sliders pill's text: empty (waybar hides the
    pill) while the dock runs with its own toolbox button -- its record in
    $XDG_RUNTIME_DIR with a live pid -- and the pill otherwise."""

    def status(self, record=None):
        with tempfile.TemporaryDirectory() as tmp:
            if record is not None:
                with open(os.path.join(tmp, "dock-toolbox.json"), "w") as fh:
                    fh.write(record)
            env = dict(os.environ, XDG_RUNTIME_DIR=tmp)
            out = subprocess.run(["bash", TOOLBOX, "status"], env=env, capture_output=True, text=True)
            return json.loads(out.stdout)

    def test_no_dock_shows_the_pill(self):
        got = self.status()
        self.assertNotEqual(got["text"], "")
        self.assertEqual(got["class"], "closed")

    def test_running_dock_hides_it(self):
        got = self.status(json.dumps({"pid": os.getpid(), "output": "DP-1", "position": "bottom"}))
        self.assertEqual((got["text"], got["class"]), ("", "docked"))

    def test_a_crashed_docks_file_does_not(self):
        self.assertNotEqual(self.status('{"pid": 999999999, "output": "DP-1"}')["text"], "")
        self.assertNotEqual(self.status("garbage")["text"], "")

    def test_refit_is_a_command(self):
        with open(TOOLBOX) as fh:
            text = fh.read()
        self.assertIn("    refit)", text)
        self.assertIn("systemctl --user try-restart waybar-toolbox.service", text)


class Elsewhere(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.D = load("toolbox_dismiss")

    def feed(self, data):
        a, b = socket.socketpair()
        try:
            if data is not None:
                a.sendall(data)
            else:
                a.close()
            with mock.patch.object(self.D, "dismiss") as dismiss:
                keep = self.D.on_event(b, None)
            return keep, dismiss.called
        finally:
            a.close()
            b.close()

    def test_moving_on_closes(self):
        for line in (b"workspacev2>>3,3\n", b"activewindowv2>>55ab\n", b"fullscreen>>1\n"):
            self.assertEqual(self.feed(line), (False, True), line)

    def test_other_events_keep_it(self):
        self.assertEqual(self.feed(b"openlayer>>panel-dismiss\nfocusedmon>>DP-1,2\n"), (True, False))

    def test_relay_gone_stops_listening_only(self):
        self.assertEqual(self.feed(None), (False, False))


if __name__ == "__main__":
    unittest.main()
