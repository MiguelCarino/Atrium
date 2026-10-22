"""nightlight.sh through its own test hooks: NL_STATE_DIR (scratch state),
NL_NOW (the clock), NL_DRY (record what would be applied, change nothing)."""
import calendar
import os
import subprocess
import tempfile
import unittest

import helpers

SCRIPT = os.path.join(helpers.SCRIPTS, "nightlight.sh")


def epoch(h, m=0):
    # TZ=UTC below, so a UTC epoch is the wall-clock time the script sees
    return calendar.timegm((2026, 10, 20, h, m, 0))


class NightLight(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(dir=helpers.SCRATCH)

    def run_nl(self, *args, now):
        env = dict(os.environ, NL_STATE_DIR=self.state, NL_NOW=str(now), NL_DRY="1", TZ="UTC",
                   NL_CONF=os.path.join(self.state, "nightlight.conf"))
        out = subprocess.run([SCRIPT, *args], capture_output=True, text=True, env=env, timeout=10)
        return out.returncode, out.stdout + out.stderr

    def schedule(self):
        start = end = None
        with open(SCRIPT) as handle:
            for line in handle:
                if line.startswith('START="'):
                    start = int(line.split('"')[1].split(":")[0])
                elif line.startswith('END="'):
                    end = int(line.split('"')[1].split(":")[0])
        return start, end

    def test_status_follows_schedule(self):
        start, end = self.schedule()
        _, out = self.run_nl("status", now=epoch((start + 1) % 24))
        self.assertIn("night light on", out)
        _, out = self.run_nl("status", now=epoch((end + 2) % 24))
        self.assertIn("night light off", out)

    def test_auto_applies_dry(self):
        start, _ = self.schedule()
        rc, out = self.run_nl("auto", now=epoch((start + 1) % 24))
        self.assertEqual(rc, 0)
        self.assertIn("DRY apply on", out)

    def test_override_lasts_until_next_boundary(self):
        start, end = self.schedule()
        night = epoch((start + 1) % 24)
        self.run_nl("off", now=night)
        _, out = self.run_nl("status", now=night + 60)
        self.assertIn("off", out.split("(")[0])
        self.assertIn("override", out)

    def test_bad_temperature(self):
        rc, _ = self.run_nl("on", "99999", now=epoch(12))
        self.assertEqual(rc, 2)

    def test_json_status(self):
        import json
        _, out = self.run_nl("status", "--json", now=epoch(12))
        info = json.loads(out.strip().splitlines()[-1])
        self.assertIn(info["class"], ("on", "off"))


if __name__ == "__main__":
    unittest.main()
