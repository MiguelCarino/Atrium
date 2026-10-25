"""themes/tools/statebar.py: which screen the test bar is drawn on. With the
main screen unplugged or off the bar used to name an output waybar could not
find, and `shot` died in geometry() -- pick_output() falls back."""
import importlib.util
import os
import unittest

import helpers  # noqa: F401  (scratch state, no hyprctl: set before the import below)

TOOLS = os.path.expanduser("~/.config/themes/tools")
_spec = importlib.util.spec_from_file_location("statebar", os.path.join(TOOLS, "statebar.py"))
statebar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(statebar)


class PickOutput(unittest.TestCase):
    def test_primary_when_connected(self):
        self.assertEqual(statebar.pick_output("", "DP-1", ["DP-2", "DP-1"]), "DP-1")

    def test_first_connected_when_primary_is_gone(self):
        self.assertEqual(statebar.pick_output("", "DP-1", ["HDMI-A-1", "DP-2"]), "HDMI-A-1")

    def test_override_wins(self):
        self.assertEqual(statebar.pick_output("DP-3", "DP-1", ["DP-1", "DP-3"]), "DP-3")

    def test_nothing_connected_keeps_primary(self):
        # hyprctl unreachable (as in these tests): the old behaviour.
        self.assertEqual(statebar.pick_output("", "DP-1", []), "DP-1")


if __name__ == "__main__":
    unittest.main()
