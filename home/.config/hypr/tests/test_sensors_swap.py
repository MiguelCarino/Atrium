"""sensors_panel.py's swap Clear: which devices, and the one command that
turns each off and on again by name (zram is not in fstab, so `swapon -a`
would leave it off). Pure: nothing is run, /proc/swaps is a scratch copy."""
import importlib.util
import os
import sys
import tempfile
import unittest

import helpers  # noqa: F401  (scratch HOME, paths)

WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
sys.path.insert(0, WAYBAR_SCRIPTS)
_spec = importlib.util.spec_from_file_location("sensors_panel", os.path.join(WAYBAR_SCRIPTS, "sensors_panel.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

SWAPS = """Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority
/dev/zram0                              partition\t8388604\t\t8297828\t\t100
/swap\\040file                           file\t\t1048572\t\t0\t\t-2
"""


class SwapClearTest(unittest.TestCase):
    def test_devices_and_command(self):
        with tempfile.NamedTemporaryFile("w", suffix=".swaps", delete=False) as handle:
            handle.write(SWAPS)
        try:
            found = S.swap_devices(handle.name)
        finally:
            os.unlink(handle.name)
        self.assertEqual(found, [("/dev/zram0", 100), ("/swap file", -2)])
        self.assertEqual(S.swap_clear_cmd(found),
                         ["pkexec", "sh", "-c", "swapoff /dev/zram0 && swapon -p 100 /dev/zram0 && "
                          "swapoff '/swap file' && swapon '/swap file'"])

    def test_nothing_on(self):
        self.assertIsNone(S.swap_clear_cmd([]))
        self.assertEqual(S.swap_devices("/nonexistent"), [])


if __name__ == "__main__":
    unittest.main()
