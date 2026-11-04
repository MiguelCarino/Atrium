"""Safe mode (hypr-guard.py): which `hyprctl configerrors` lines count as a
broken config. Hermetic: hyprctl is stubbed, nothing is saved or restored."""
import json
import subprocess
import unittest
from unittest import mock

import helpers

guard = helpers.import_script("hypr-guard.py", "hypr_guard")


def fake_errors(lines):
    done = subprocess.CompletedProcess([], 0, stdout=json.dumps(lines), stderr="")
    return mock.patch.object(guard.subprocess, "run", return_value=done)


class Errors(unittest.TestCase):
    def test_real_errors_count(self):
        with fake_errors(["/c/lua/binds.lua:12: attempt to call a nil value", ""]):
            self.assertEqual(guard.errors(), ["/c/lua/binds.lua:12: attempt to call a nil value"])

    def test_plugin_not_loaded_is_not_a_broken_config(self):
        # The first login after a Hyprland update: the plugins' options are
        # unknown until plugins-check.sh rebuilds and loads them.
        lines = ["/c/lua/overview.lua:36: unknown config key 'plugin.hyprview.margin'",
                 "/c/lua/cube.lua:73: unknown config key 'plugin.hypr_cube.fov'"]
        with fake_errors(lines):
            self.assertEqual(guard.errors(), [])

    def test_other_unknown_keys_still_count(self):
        line = "/c/lua/settings.lua:5: unknown config key 'general.gaps_inn'"
        with fake_errors([line, "/c/lua/cube.lua:73: unknown config key 'plugin.hypr_cube.fov'"]):
            self.assertEqual(guard.errors(), [line])

    def test_hyprctl_missing(self):
        with mock.patch.object(guard.subprocess, "run", side_effect=OSError):
            self.assertEqual(guard.errors(), [])


if __name__ == "__main__":
    unittest.main()
