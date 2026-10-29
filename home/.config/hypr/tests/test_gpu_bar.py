"""The bar's GPU pill and panel on any card: gpu_usage.sh's JSON from a
stand-in gpu.py stream (a full NVIDIA/AMD line, an iGPU with no VRAM or
temperature, a missed sample, no card at all -> hidden pill), and the
sensors panel's app table grouped from gpu.py's process rows. Nothing reads
the real card."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

import helpers

WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
PILL = os.path.join(WAYBAR_SCRIPTS, "gpu_usage.sh")


def stand_in(lines, code=0):
    """A fake gpu.py that prints `lines` for `stream` and exits with `code`."""
    fd, path = tempfile.mkstemp(suffix=".py", dir=helpers.SCRATCH)
    with os.fdopen(fd, "w") as handle:
        handle.write(textwrap.dedent(f"""\
            import sys
            for line in {lines!r}:
                print(line, flush=True)
            sys.exit({code})
            """))
    return path


def pill(lines, code=0, watch=False):
    env = dict(os.environ, GPU_PY=stand_in(lines, code), HOME=helpers.SCRATCH)
    argv = ["timeout", "2", "bash", PILL] + (["watch"] if watch else [])
    out = subprocess.run(argv, capture_output=True, text=True, env=env).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


class Pill(unittest.TestCase):
    def test_full_line(self):
        (out,) = pill(["42, 61, 3072, 16384, 187, 40"])
        self.assertEqual((out["class"], out["percentage"]), ("normal", 42))
        self.assertIn("61°", out["text"])
        self.assertIn("3.0G", out["text"])

    def test_hot_card_is_critical(self):
        (out,) = pill(["99, 85, 1024, 8192, 300, 90"])
        self.assertEqual(out["class"], "critical")

    def test_igpu_leaves_out_what_it_does_not_report(self):
        (out,) = pill(["7, N/A, N/A, N/A, N/A, N/A"])
        self.assertEqual(out["percentage"], 7)
        self.assertNotIn("°", out["text"])
        self.assertNotIn("G<", out["text"] + "<")      # no VRAM field
        self.assertFalse(out["text"].endswith("G"))

    def test_no_card_hides_the_pill(self):
        self.assertEqual(pill(["none"], code=3), [{"text": "", "class": "none"}])

    def test_watch_survives_a_missed_sample_and_idles_without_a_card(self):
        outs = pill(["N/A, N/A, N/A, N/A, N/A, N/A", "12, 50, 2048, 8192, 80, 30"], watch=True)
        self.assertEqual(outs[0]["class"], "unavailable")
        self.assertEqual(outs[1]["percentage"], 12)
        self.assertEqual(pill(["none"], code=3, watch=True), [{"text": "", "class": "none"}])


_spec = importlib.util.spec_from_file_location("sensors_panel_gpu", os.path.join(WAYBAR_SCRIPTS, "sensors_panel.py"))
sys.path.insert(0, WAYBAR_SCRIPTS)
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


class PanelTable(unittest.TestCase):
    def test_grouped_by_name(self):
        rows = [{"pid": 1, "name": "kitty", "mib": 80, "sm": None},
                {"pid": 2, "name": "kitty", "mib": 1000, "sm": None},
                {"pid": 3, "name": "game", "mib": 6000, "sm": 70},
                {"pid": 4, "name": "Hyprland", "mib": 400, "sm": 5}]
        got = S.group_gpu_rows(rows)
        self.assertEqual([r["name"] for r in got], ["game", "Hyprland", "kitty"])
        self.assertEqual(got[0]["values"], ["70%", "5.9G"])
        self.assertEqual(got[2]["values"], ["-", "1.1G"])
        self.assertEqual(got[2]["pids"], [1, 2])

    def test_rows_limit(self):
        rows = [{"pid": i, "name": f"p{i}", "mib": i, "sm": None} for i in range(20)]
        self.assertEqual(len(S.group_gpu_rows(rows, 5)), 5)


if __name__ == "__main__":
    unittest.main()
