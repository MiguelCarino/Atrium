"""record.sh follows Settings > Screenshots & recording's "Video encoder"
(capture.conf rec_encoder), and REC_ENCODER still beats it. Same stand-in
gpu-screen-recorder as test_record_encoder; nothing records the screens."""
import os
import unittest

import test_record_encoder as base


class RecordEncoderPage(base.RecordEncoder):
    # Only the tests below: the inherited ones already run in test_record_encoder.
    test_nvidia_keeps_nvenc_as_before = None
    test_amd_uses_vaapi_without_the_nvenc_tune = None
    test_no_hardware_encoder_falls_to_x264 = None
    test_override = None

    def write_conf(self, text):
        conf = os.path.join(self.env["XDG_STATE_HOME"], "hypr", "capture.conf")
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        with open(conf, "w") as handle:
            handle.write(text)

    def test_page_setting_picks_the_cpu(self):
        self.write_conf("rec_encoder=cpu\n")
        _out, argv = self.capture("nvidia")
        self.assertEqual(self.value(argv, "-encoder"), "cpu")

    def test_environment_beats_the_page(self):
        self.write_conf("rec_encoder=cpu\n")
        _out, argv = self.capture("nvidia", REC_ENCODER="gpu")
        self.assertEqual(self.value(argv, "-encoder"), "gpu")
        self.assertEqual(self.value(argv, "-tune"), "quality")

    def test_page_auto_keeps_the_detected_card(self):
        self.write_conf("rec_encoder=auto\n")
        _out, argv = self.capture("nvidia")
        self.assertEqual(self.value(argv, "-encoder"), "gpu")


if __name__ == "__main__":
    unittest.main()
