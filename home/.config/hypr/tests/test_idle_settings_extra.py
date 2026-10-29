"""idle-settings.py's later additions: the NVIDIA suspend helper state (no
unit is "no NVIDIA", not "off"), the idle lock command (loginctl
lock-session unless a grace period needs hyprlock itself), the companion
listeners (screentime-idle) added once, and Keep awake redrawing its pill
when it ends. Power page: the same NVIDIA reading."""
import unittest

import helpers

idle = helpers.import_script("idle-settings.py")

BARE = "general {\n    lock_cmd = pidof hyprlock || hyprlock\n}\n"


class Nvidia(unittest.TestCase):
    def test_states(self):
        self.assertEqual(idle.nvidia_suspend_state("enabled\n"), "enabled")
        self.assertEqual(idle.nvidia_suspend_state("disabled\n"), "disabled")
        for nothing in ("", "\n", "not-found\n", None):
            self.assertIsNone(idle.nvidia_suspend_state(nothing))

    def test_power_page_reads_the_same(self):
        try:
            from settings_pages import common  # noqa: F401  (Gtk 3 first, as settings.py does)
            from settings_pages import power
        except Exception as exc:                         # noqa: BLE001
            self.skipTest(f"settings_pages.power not importable: {exc}")
        self.assertIsNone(power.nvidia_state("not-found"))
        self.assertIsNone(power.nvidia_state(None))
        self.assertEqual(power.nvidia_state("disabled"), "disabled")


class Lock(unittest.TestCase):
    def test_lock_command(self):
        self.assertEqual(idle.lock_command(0), "loginctl lock-session")
        self.assertEqual(idle.lock_command(5), "pidof hyprlock || hyprlock --grace 5")

    def test_rendered_lock_reads_back(self):
        parsed = idle.parse(BARE)
        for grace in (0, 3):
            v = idle.apply_changes(idle.values_from(parsed), ["lock", "10", "grace", str(grace)])
            text = idle.render(v, parsed)
            again = idle.values_from(idle.parse(text))
            self.assertEqual((again["lock"], again["grace"]), (600, grace))
            self.assertIn("loginctl lock-session" if not grace else "hyprlock --grace 3", text)


class Companions(unittest.TestCase):
    def test_added_once(self):
        parsed = idle.parse(BARE)
        text = idle.render(idle.values_from(parsed), parsed)
        self.assertEqual(text.count("screentime-idle on"), 1)
        again = idle.parse(text)
        self.assertEqual(idle.missing_companions(again), [])
        self.assertEqual(idle.render(idle.values_from(again), again).count("screentime-idle on"), 1)

    def test_kept_as_written(self):
        own = BARE + "listener {\n    timeout = 90\n    on-timeout = ~/.config/hypr/scripts/screentime-idle on\n}\n"
        parsed = idle.parse(own)
        text = idle.render(idle.values_from(parsed), parsed)
        self.assertIn("timeout = 90", text)
        self.assertEqual(text.count("screentime-idle on"), 1)


class Awake(unittest.TestCase):
    def test_redraw_command_names_the_pill(self):
        self.assertTrue(idle.AWAKE_REDRAW.endswith("bar_signals.py poke awake"))


if __name__ == "__main__":
    unittest.main()
