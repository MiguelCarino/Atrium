"""toolbox_fit.py: the card's right edge follows the click on the sliders
pill; while the dock or the taskbar runs, the card is a bottom bar placed
next to their toolbox button (above it, or beside a side dock), and stays
put while that button only slides a little. Hermetic: the generated file,
the cache and the dock's record are scratch files; hyprctl is never run."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401  (scratch XDG dirs, before toolbox_fit reads them)

sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
import toolbox_fit as fit  # noqa: E402

MON = {"name": "DP-1", "x": 0, "y": 0, "width": 3440, "height": 1440, "scale": 1, "transform": 0}


def at(x, y):
    return mock.patch.object(fit.subprocess, "run",
                             return_value=mock.Mock(stdout=f"{x}, {y}\n"))


class RightMargin(unittest.TestCase):
    def test_click_on_pill_moves_edge(self):
        with at(3388, 15):
            self.assertEqual(fit.right_margin(MON, 3440, 58), 37)

    def test_small_move_keeps_edge(self):
        with at(3380, 15):
            self.assertEqual(fit.right_margin(MON, 3440, 37), 37)

    def test_click_below_bar_keeps_edge(self):
        with at(3388, 400):
            self.assertEqual(fit.right_margin(MON, 3440, 58), 58)

    def test_other_screen_keeps_edge(self):
        with at(-500, 10):
            self.assertEqual(fit.right_margin(MON, 3440, 58), 58)


class Tray(unittest.TestCase):
    def test_five_icons_fit_the_rows(self):
        self.assertEqual(fit.tray_extra(5), 0)
        self.assertEqual(fit.tray_extra(7), 2 * fit.PER_ICON - fit.SPACING - fit.ROW_W + 5 * fit.PER_ICON)



def record(layout="taskbar", position="bottom", bar=(0, 1400, 3440, 40), button=(3300, 1403, 34, 34),
           reserved=40, pid=4242, output="DP-1"):
    return {"pid": pid, "output": output, "layout": layout, "position": position,
            "monitor": [0, 0, 3440, 1440], "bar": list(bar), "button": list(button), "reserved": reserved}


def live(rec):
    return fit.live_dock(rec, lambda pid: True)


class Placement(unittest.TestCase):
    def test_margin_text_round_trips(self):
        place = {"position": "bottom", "margin": (0, 106, 6, 3136)}
        self.assertEqual(fit.parse_margin(fit.margin_text(place)), place)
        # The file from before the dock: no position, a top one.
        self.assertEqual(fit.parse_margin('{ "margin": "4 62 0 3180" }'),
                         {"position": "top", "margin": (4, 62, 0, 3180)})
        self.assertIsNone(fit.parse_margin(""))

    def test_top_place(self):
        self.assertEqual(fit.top_place(3440, 62, 198), {"position": "top", "margin": (4, 62, 0, 3180)})

    def test_live_dock_needs_a_whole_record_and_a_live_pid(self):
        self.assertIsNotNone(live(record()))
        self.assertIsNone(fit.live_dock(record(), lambda pid: False))
        self.assertIsNone(live(dict(record(), position="top")))
        self.assertIsNone(live(dict(record(), button=[1, 2])))
        self.assertIsNone(live({"pid": "x"}))
        self.assertIsNone(live(None))

    def test_taskbar_above_its_button(self):
        # The taskbar reserves its 40 px: the card's bottom edge is GAP above it,
        # its right edge flush with the button's.
        top, right, bottom, left = fit.dock_place(live(record()), 198)["margin"]
        self.assertEqual((top, right, bottom), (0, 3440 - 3334, fit.GAP))
        self.assertEqual(left, 3440 - right - 198)

    def test_hiding_dock_is_cleared_by_its_own_height(self):
        rec = record(layout="dock", bar=(1500, 1340, 440, 92), button=(1880, 1345, 58, 82), reserved=0)
        _t, right, bottom, _l = fit.dock_place(live(rec), 198)["margin"]
        self.assertEqual(right, 3440 - 1938)
        self.assertEqual(bottom, 1440 - 1340 + fit.GAP)
        # One that never hides reserves its strip: only the gap again.
        rec["reserved"] = 100
        self.assertEqual(fit.dock_place(live(rec), 198)["margin"][2], 1440 - 100 - 1340 + fit.GAP)

    def test_side_docks_beside_the_button(self):
        left_dock = record(layout="dock", position="left", bar=(8, 500, 92, 440), button=(13, 860, 82, 58),
                           reserved=0)
        _t, right, bottom, left = fit.dock_place(live(left_dock), 198)["margin"]
        self.assertEqual(left, 8 + 92 + fit.GAP)
        self.assertEqual(bottom, 1440 - (860 + 58))
        self.assertEqual(3440 - left - right, 198)
        # Reserving its strip, the dock moves the toolbox's left edge itself.
        left_dock["reserved"] = 100
        _t, right, _b, left = fit.dock_place(live(left_dock), 198)["margin"]
        self.assertEqual(left, 8 + 92 + fit.GAP - 100)
        self.assertEqual(3440 - 100 - left - right, 198)
        right_dock = record(layout="dock", position="right", bar=(3340, 500, 92, 440),
                            button=(3345, 860, 82, 58), reserved=0)
        _t, right, bottom, left = fit.dock_place(live(right_dock), 198)["margin"]
        self.assertEqual(right, 3440 - (3340 - fit.GAP))
        self.assertEqual(3440 - left - right, 198)

    def test_card_stays_while_the_button_slides_a_little(self):
        now = fit.dock_place(live(record(layout="dock", bar=(1500, 1340, 440, 92),
                                         button=(1880, 1345, 58, 82), reserved=0)), 198)
        moved = record(layout="dock", bar=(1471, 1340, 498, 92), button=(1909, 1345, 58, 82), reserved=0)
        self.assertEqual(fit.dock_place(live(moved), 198, now), now)
        far = record(layout="dock", bar=(1300, 1340, 840, 92), button=(2080, 1345, 58, 82), reserved=0)
        self.assertNotEqual(fit.dock_place(live(far), 198, now)["margin"][1], now["margin"][1])
        # From the top bar's placement: always the dock's own.
        top = {"position": "top", "margin": (4, 62, 0, 3180)}
        self.assertEqual(fit.dock_place(live(moved), 198, top), fit.dock_place(live(moved), 198))

    def test_never_off_screen(self):
        rec = record(button=(10, 1403, 34, 34))
        _t, right, _b, left = fit.dock_place(live(rec), 198)["margin"]
        self.assertGreaterEqual(left, fit.EDGE - 1)
        self.assertEqual(3440 - left - right, 198)


class Fit(unittest.TestCase):
    """fit() end to end: where the card goes with and without the dock."""

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.root, True)
        paths = {name: os.path.join(self.root, name) for name in ("OUT", "CACHE", "DOCK_BUTTON", "DISPLAY_STATE")}
        for name, path in paths.items():
            patcher = mock.patch.object(fit, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.paths = paths
        for name, value in (("toolbox_monitor", MON), ("tray_items", 1), ("pid_alive", True)):
            patcher = mock.patch.object(fit, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with open(paths["CACHE"], "w") as handle:
            json.dump({"": 198}, handle)

    def written(self):
        with open(self.paths["OUT"]) as handle:
            return fit.parse_margin(handle.read())

    def test_top_then_dock_then_top_again(self):
        with mock.patch.object(fit, "right_margin", return_value=62):
            self.assertTrue(fit.fit())
        self.assertEqual(self.written(), {"position": "top", "margin": (4, 62, 0, 3180)})
        with open(self.paths["DOCK_BUTTON"], "w") as handle:
            json.dump(record(), handle)
        self.assertTrue(fit.fit())
        self.assertEqual(self.written()["position"], "bottom")
        self.assertFalse(fit.fit())              # nothing moved: no restart
        os.unlink(self.paths["DOCK_BUTTON"])
        # Back under the pill, at the edge it had (the cache keeps it), no click needed.
        self.assertTrue(fit.fit(follow_click=False))
        self.assertEqual(self.written(), {"position": "top", "margin": (4, 62, 0, 3180)})

    def test_dock_on_another_screen_keeps_the_top(self):
        with open(self.paths["DOCK_BUTTON"], "w") as handle:
            json.dump(record(output="HDMI-A-1"), handle)
        with mock.patch.object(fit, "right_margin", return_value=58):
            fit.fit()
        self.assertEqual(self.written()["position"], "top")


class ToolboxConfig(unittest.TestCase):
    def test_position_comes_from_the_include(self):
        with open(fit.CONFIG) as handle:
            text = handle.read()
        self.assertNotRegex(text, r'(?m)^\s*"position"\s*:')
        self.assertIn('"include": ["~/.config/waybar/generated/toolbox-margin.jsonc"]', text)




class CardKey(unittest.TestCase):
    """card_key: a width per theme and per dock layout / top bar."""
    def test_keys(self):
        from unittest import mock
        with mock.patch.object(fit, "theme", lambda: "matrix"):
            self.assertEqual(fit.card_key({}), "matrix")
            self.assertEqual(fit.card_key({"enabled": False, "layout": "dock"}), "matrix")
            self.assertEqual(fit.card_key({"enabled": True, "layout": "dock", "top_bar": True}), "matrix|dock")
            self.assertEqual(fit.card_key({"enabled": True, "layout": "taskbar", "top_bar": False}),
                             "matrix|taskbar|nobar")


if __name__ == "__main__":
    unittest.main()
