"""display_panel.py's screens map: where a dragged screen lands (snap()) and
which screens it draws (map_screens()). Pure: no window, no display.py."""
import importlib.util
import os
import sys
import unittest

import helpers  # noqa: F401  (scratch HOME, paths)

WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
sys.path.insert(0, WAYBAR_SCRIPTS)
_spec = importlib.util.spec_from_file_location("display_panel", os.path.join(WAYBAR_SCRIPTS, "display_panel.py"))
D = importlib.util.module_from_spec(_spec)
_argv, sys.argv = sys.argv, ["display_panel.py"]
try:
    _spec.loader.exec_module(D)
finally:
    sys.argv = _argv

MAIN = (0, 0, 3440, 1440)
TOP = (0, -1350, 3200, 1350)
TALL = (3440, 0, 1080, 1920)


class SnapTest(unittest.TestCase):
    def test_lands_against_the_nearest_edge(self):
        # dropped a little left of and below the main screen: to its left, top lined up
        self.assertEqual(D.snap((-1700, 60, 1600, 900), [MAIN, TOP, TALL]), (-1600, 0))
        # dropped under the main screen, near its middle: centred below it
        self.assertEqual(D.snap((950, 1500, 1600, 900), [MAIN, TOP, TALL]), (920, 1440))

    def test_never_overlaps(self):
        x, y = D.snap((3500, 100, 1600, 900), [MAIN, TOP, TALL])
        for other in (MAIN, TOP, TALL):
            self.assertFalse(D.overlaps((x, y, 1600, 900), other))

    def test_free_slide_when_not_near_an_alignment(self):
        self.assertEqual(D.snap((4520, 700, 1600, 900), [MAIN, TALL]), (4520, 700))

    def test_nothing_to_snap_to(self):
        self.assertIsNone(D.snap((0, 0, 100, 100), []))

    def test_short_name(self):
        self.assertEqual(D.short_name("Zenith Technologies Zenith Z205H ZZL0W0154332"), "Zenith Z205H")
        self.assertEqual(D.short_name("ORN Orion OV2283 ET46P00409SL0"), "Orion OV2283")
        self.assertEqual(D.short_name("Nova Corporation Nova monitor 5505810045741"), "Nova monitor")

    def test_map_screens_skips_off_and_mirrors(self):
        outs = [{"name": "DP-1", "description": "Acme Corp Acme Wide 1234567", "x": 0, "y": 0, "w": 10, "h": 5},
                {"name": "DP-2", "enabled": False},
                {"name": "DP-3", "mirror_of": "DP-1"}]
        self.assertEqual(D.map_screens(outs),
                         [{"name": "DP-1", "label": "Acme Wide", "primary": None, "rect": (0, 0, 10, 5)}])


if __name__ == "__main__":
    unittest.main()
