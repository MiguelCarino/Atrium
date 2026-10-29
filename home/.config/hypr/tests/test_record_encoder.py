"""record.sh on any card: a stand-in gpu-screen-recorder (its --info answers
like an NVIDIA, an AMD or a card-less machine; a capture writes its argv
and waits for SIGINT) shows which encoder, tune, frame rate and codec the
script hands it. Nothing records the real screens: REC_MONITOR names a
screen, REC_QUIET keeps notifications off, every path is scratch."""
import os
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest

import helpers

RECORD = os.path.join(helpers.SCRIPTS, "record.sh")

INFO = {
    "nvidia": "section=gpu_info\nvendor|nvidia\nsection=video_codecs\nh264\nhevc\nhevc_hdr\nh264_software\n",
    "amd": "section=gpu_info\nvendor|amd\nsection=video_codecs\nh264\nhevc\nh264_software\n",
    "none": "section=gpu_info\nvendor|unknown\nsection=video_codecs\nh264_software\n",
}

# Python, not bash: a background job of a non-interactive shell starts with
# SIGINT ignored, and bash cannot trap a signal ignored at entry -- the real
# recorder (and Python) install their handler anyway.
GSR = textwrap.dedent("""\
    #!/usr/bin/env python3
    import os, signal, sys, time
    if sys.argv[1:2] == ["--info"]:
        sys.stdout.write(os.environ.get("FAKE_GSR_INFO", ""))
        sys.exit(0)
    with open(os.environ["FAKE_GSR_ARGS"], "w") as handle:
        handle.write("\\n".join(sys.argv[1:]) + "\\n")
    out = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else None
    def stop(*_):
        if out:
            with open(out, "w") as handle:
                handle.write("data")
        sys.exit(0)
    signal.signal(signal.SIGINT, stop)
    time.sleep(10)
    """)


@unittest.skipUnless(shutil.which("jq") and shutil.which("flock"), "record.sh needs jq and flock")
class RecordEncoder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="rec-", dir=helpers.SCRATCH)
        bindir = os.path.join(self.dir, "bin")
        os.makedirs(bindir)
        gsr = os.path.join(bindir, "gpu-screen-recorder")
        with open(gsr, "w") as handle:
            handle.write(GSR)
        os.chmod(gsr, 0o755)
        self.args = os.path.join(self.dir, "args")
        run = os.path.join(self.dir, "run")
        os.makedirs(run)
        self.env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"],
                        XDG_RUNTIME_DIR=run, XDG_STATE_HOME=os.path.join(self.dir, "state"),
                        REC_DIR=os.path.join(self.dir, "out"), REC_MONITOR="DP-9", REC_QUIET="1",
                        FAKE_GSR_ARGS=self.args)

    def tearDown(self):
        subprocess.run(["bash", RECORD, "stop"], env=self.env, capture_output=True, timeout=30)
        shutil.rmtree(self.dir, ignore_errors=True)

    def capture(self, card, **env):
        e = dict(self.env, FAKE_GSR_INFO=INFO[card], **env)
        res = subprocess.run(["bash", RECORD, "monitor"], env=e, capture_output=True, text=True, timeout=30)
        for _ in range(30):
            if os.path.exists(self.args):
                break
            time.sleep(0.1)
        with open(self.args) as handle:
            argv = handle.read().split("\n")
        return res.stdout, argv

    def value(self, argv, flag):
        return argv[argv.index(flag) + 1] if flag in argv else None

    def test_nvidia_keeps_nvenc_as_before(self):
        _out, argv = self.capture("nvidia")
        self.assertEqual(self.value(argv, "-encoder"), "gpu")
        self.assertEqual(self.value(argv, "-tune"), "quality")
        self.assertEqual(self.value(argv, "-f"), "60")
        self.assertEqual(self.value(argv, "-k"), "h264")
        self.assertEqual(self.value(argv, "-q"), "ultra")

    def test_amd_uses_vaapi_without_the_nvenc_tune(self):
        _out, argv = self.capture("amd")
        self.assertEqual(self.value(argv, "-encoder"), "gpu")
        self.assertNotIn("-tune", argv)

    def test_no_hardware_encoder_falls_to_x264(self):
        out, argv = self.capture("none")
        self.assertEqual(self.value(argv, "-encoder"), "cpu")
        self.assertEqual(self.value(argv, "-f"), "30")
        self.assertEqual(self.value(argv, "-q"), "high")
        self.assertIn("Recording with the CPU", out)

    def test_override(self):
        _out, argv = self.capture("nvidia", REC_ENCODER="cpu")
        self.assertEqual(self.value(argv, "-encoder"), "cpu")


class CapturePageLine(unittest.TestCase):
    """Settings > Screenshots & recording's "Video encoder" line."""

    def test_lines(self):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from settings_pages import capture                    # needs GTK, not a display
        except Exception as exc:                                    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.capture not importable: {exc}")
        self.assertEqual(capture.encoder_text({"encoder": "gpu", "api": "nvenc", "hdr": True}),
                         "the graphics card (NVENC)")
        self.assertIn("no HDR", capture.encoder_text({"encoder": "gpu", "api": "vaapi", "hdr": False}))
        self.assertIn("the CPU (x264)", capture.encoder_text({"encoder": "cpu", "api": "x264"}))
        self.assertIn("did not answer", capture.encoder_text(None))


if __name__ == "__main__":
    unittest.main()
