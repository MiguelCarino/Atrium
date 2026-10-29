"""Settings > Machines' Wake-on-LAN helpers (settings_pages/machines.py):
which saved machine a paired one is, and which saved ones are listed on
their own. Needs GTK to import, not a display; skipped without it."""
import unittest

import helpers  # noqa: F401  (scratch XDG dirs, scripts on sys.path)

try:
    from settings_pages import machines as page
except Exception:                                        # noqa: BLE001
    page = None

DESK = {"name": "Desk", "mac": "aa:bb:cc:00:11:22", "peer": "P1"}
LAPTOP = {"name": "laptop", "mac": "aa:bb:cc:00:11:33"}
NAS = {"name": "NAS", "mac": "aa:bb:cc:00:11:44"}


@unittest.skipIf(page is None, "settings_pages.machines not importable")
class Wake(unittest.TestCase):
    def test_by_peer_id_then_name(self):
        machines = [DESK, LAPTOP, NAS]
        self.assertIs(page.wake_entry(machines, {"id": "P1", "name": "Renamed"}), DESK)
        self.assertIs(page.wake_entry(machines, {"id": "P2", "name": "Laptop"}), LAPTOP)
        self.assertIsNone(page.wake_entry(machines, {"id": "P3", "name": "Tablet"}))

    def test_a_peer_bound_entry_is_not_taken_by_name(self):
        self.assertIsNone(page.wake_entry([DESK], {"id": "P9", "name": "Desk"}))

    def test_other_machines(self):
        peers = [{"id": "P1", "name": "Desk"}, {"id": "P2", "name": "Laptop"}]
        self.assertEqual(page.other_machines([DESK, LAPTOP, NAS], peers), [NAS])
        self.assertEqual(page.other_machines([DESK, NAS], []), [DESK, NAS])


if __name__ == "__main__":
    unittest.main()
