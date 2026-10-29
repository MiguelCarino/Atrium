"""toolbox_fit.py: the card's right edge follows the click on the sliders pill."""
import os
import sys
import unittest
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
