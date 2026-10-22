"""sound-settings.py's pure parts (volumes, balance, the level meter's scale,
the status document) and the over-amplification switch, against the scratch
state helpers.py sets up. pactl is never run: the status is built from
canned pactl JSON, and set_boost's device sweep is stubbed to see nothing."""
import json
import os
import unittest

import helpers

S = helpers.import_script("sound-settings.py")
OSD = helpers.import_script("osd.py")


def chans(**values):
    """chans(front_left=65536, ...) -> pactl's per-channel volume dict."""
    return {k.replace("_", "-"): {"value": v} for k, v in values.items()}


def sink(index, name, nick, volume=None, default_port="analog-output", available="availability unknown", **extra):
    return {"index": index, "name": name, "description": f"{nick} long description",
            "properties": {"node.nick": nick, "device.name": "alsa_card." + name},
            "volume": volume or chans(front_left=65536, front_right=65536), "mute": False,
            "active_port": default_port,
            "ports": [{"name": default_port, "description": "Port", "availability": available}], **extra}


class Volumes(unittest.TestCase):
    def test_percent_of_full_is_100(self):
        self.assertEqual(S.percent_of(65536), 100)
        self.assertEqual(S.percent_of(36047), 55)

    def test_volume_is_the_loudest_channel(self):
        self.assertEqual(S.volume_of(chans(front_left=32768, front_right=65536)), 100)
        self.assertEqual(S.volume_of({}), 0)

    def test_balance_sign_follows_the_louder_side(self):
        self.assertEqual(S.balance_of(chans(front_left=65536, front_right=45875)), -30)
        self.assertEqual(S.balance_of(chans(front_left=45875, front_right=65536)), 30)
        self.assertEqual(S.balance_of(chans(front_left=100, front_right=100)), 0)

    def test_mono_has_no_balance(self):
        self.assertEqual(S.balance_of(chans(mono=40000)), 0)

    def test_channel_volumes_round_trip(self):
        names = ["front-left", "front-right", "lfe"]
        for balance in (-100, -45, 0, 20, 100):
            per = S.channel_volumes(names, 80, balance)
            self.assertEqual(per[2], 80)                    # neither side: untouched
            back = S.balance_of({n: {"value": round(v * 655.36)} for n, v in zip(names, per)})
            self.assertAlmostEqual(back, balance, delta=1)
            self.assertEqual(max(per[:2]), 80)              # the louder side keeps the volume

    def test_channel_volumes_clamps_balance(self):
        self.assertEqual(S.channel_volumes(["front-left", "front-right"], 50, 250), [0, 50])

    def test_clamp_respects_the_limit(self):
        self.assertEqual(S.clamp(130, 1.0), 100)
        self.assertEqual(S.clamp(130, 1.5), 130)
        self.assertEqual(S.clamp(200, 1.5), 150)
        self.assertEqual(S.clamp(-5, 1.0), 0)


class Meter(unittest.TestCase):
    def test_silence_is_zero(self):
        self.assertEqual(S.level_percent([0] * 100), 0)
        self.assertEqual(S.level_percent([]), 0)

    def test_full_scale_is_100(self):
        self.assertEqual(S.level_percent([0, -32768, 10]), 100)

    def test_minus_30_db_is_halfway(self):
        self.assertEqual(S.level_percent([round(32768 * 10 ** (-30 / 20))]), 50)

    def test_below_the_floor_is_zero(self):
        self.assertEqual(S.level_percent([1]), 0)


class Labels(unittest.TestCase):
    def test_bluetooth_profiles_in_words(self):
        self.assertEqual(S.profile_label("a2dp-sink-aac", "High Fidelity Playback (A2DP Sink, codec AAC)"),
                         "High quality (A2DP) · AAC")
        self.assertEqual(S.profile_label("a2dp-sink", "High Fidelity Playback (A2DP Sink)"), "High quality (A2DP)")
        self.assertEqual(S.profile_label("headset-head-unit-msbc", "Headset Head Unit (HSP/HFP, codec mSBC)"),
                         "Headset with microphone (HFP)")
        self.assertEqual(S.profile_label("output:hdmi-stereo", "Digital Stereo (HDMI) Output"),
                         "Digital Stereo (HDMI) Output")

    def test_app_name_fallbacks(self):
        self.assertEqual(S.app_name({"application.name": "Firefox"}), "Firefox")
        self.assertEqual(S.app_name({"application.process.binary": "mpv"}), "mpv")
        self.assertEqual(S.app_name({}), "Unknown application")


class Status(unittest.TestCase):
    def build(self, **over):
        sinks = [sink(59, "alsa_output.usb-X.analog-stereo-output", "USB Audio CODEC"),
                 sink(60, "alsa_output.pci-Y.hdmi-stereo", "Acme", default_port="hdmi-output-0",
                      available="not available"),
                 sink(61, "bluez_output.AA_BB.1", "Headphones")]
        sources = [sink(70, "alsa_input.usb-X.mono", "Webcam"),
                   dict(sink(71, "alsa_output.usb-X.analog-stereo-output.monitor", "Monitor"),
                        properties={"device.class": "monitor"})]
        inputs = [{"index": 900, "sink": 59, "mute": True, "corked": True, "volume": chans(mono=32768),
                   "properties": {"application.name": "Player", "media.name": "song"}}]
        outputs = [{"properties": {"application.name": "Recorder"}},
                   {"properties": {"application.name": S.METER_NAME}},
                   {"properties": {"application.name": "pavucontrol", "media.name": "Peak detect"}}]
        cards = [{"name": "alsa_card.usb-X", "active_profile": "output:analog-stereo-output",
                  "properties": {"device.description": "USB card"},
                  "profiles": {"off": {"description": "Off", "available": True, "priority": 0}}},
                 {"name": "bluez_card.AA_BB", "active_profile": "a2dp-sink",
                  "properties": {"device.description": "Headphones"},
                  "profiles": {"a2dp-sink": {"description": "High Fidelity Playback (A2DP Sink)", "priority": 2}}}]
        args = dict(sinks=sinks, sources=sources, inputs=inputs, outputs=outputs, cards=cards,
                    defaults={"sink": "alsa_output.usb-X.analog-stereo-output", "source": "alsa_input.usb-X.mono"},
                    state={}, theme_sounds="on")
        args.update(over)
        return S.build_status(**args)

    def test_devices_defaults_and_monitors(self):
        data = self.build()
        self.assertEqual([s["label"] for s in data["sinks"]], ["Acme", "Headphones", "USB Audio CODEC"])
        self.assertEqual([s["name"] for s in data["sinks"] if s["default"]], ["alsa_output.usb-X.analog-stereo-output"])
        self.assertEqual([s["label"] for s in data["sources"]], ["Webcam"])   # the monitor is left out
        acme = next(s for s in data["sinks"] if s["label"] == "Acme")
        self.assertFalse(acme["available"])
        self.assertEqual(acme["kind"], "unplugged")
        self.assertTrue(next(s for s in data["sinks"] if s["label"] == "Headphones")["bluetooth"])

    def test_apps_name_their_output(self):
        app = self.build()["apps"][0]
        self.assertEqual((app["name"], app["sink_label"], app["volume"], app["mute"], app["paused"]),
                         ("Player", "USB Audio CODEC", 50, True, True))

    def test_recording_leaves_out_meters(self):
        self.assertEqual(self.build()["recording"], ["Recorder"])

    def test_bluetooth_cards_first(self):
        cards = self.build()["cards"]
        self.assertTrue(cards[0]["bluetooth"])
        self.assertEqual(cards[0]["profiles"][0]["label"], "High quality (A2DP)")

    def test_same_nick_falls_back_to_description(self):
        two = [sink(1, "a", "Same"), sink(2, "b", "Same")]
        labels = [s["label"] for s in self.build(sinks=two)["sinks"]]
        self.assertEqual(labels, ["Same long description", "Same long description"])

    def test_boost_sets_the_limit(self):
        self.assertEqual(self.build()["limit"], 1.0)
        self.assertEqual(self.build(state={"boost": True})["limit"], 1.5)

    def test_document_is_json(self):
        json.dumps(self.build())


class Boost(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: os.path.exists(S.STATE) and os.remove(S.STATE))
        self.real = S.pactl_json
        S.pactl_json = lambda *_a: []                   # no devices: nothing is run
        self.addCleanup(setattr, S, "pactl_json", self.real)

    def test_state_is_scratch(self):
        self.assertTrue(S.STATE.startswith(helpers.SCRATCH))

    def test_on_off_and_the_keys_follow(self):
        self.assertEqual(S.limit(), 1.0)
        self.assertEqual(OSD.vol_limit(), "1.0")
        S.set_boost(True)
        self.assertEqual(S.limit(), 1.5)
        self.assertEqual(OSD.vol_limit(), "1.5")
        S.set_boost(False)
        self.assertEqual(S.limit(), 1.0)
        self.assertEqual(OSD.vol_limit(), "1.0")

    def test_off_brings_loud_devices_down(self):
        loud = sink(5, "loud", "Loud", volume=chans(front_left=85196, front_right=85196))
        S.pactl_json = lambda what: [loud] if what == "sinks" else []
        done = []
        real_set = S.set_volume
        S.set_volume = lambda ref, pct, cap=None: done.append((ref, pct, cap))
        self.addCleanup(setattr, S, "set_volume", real_set)
        S.set_boost(False)
        self.assertEqual(done, [("loud", 100, 1.0)])

    def test_broken_state_file_is_off(self):
        os.makedirs(os.path.dirname(S.STATE), exist_ok=True)
        with open(S.STATE, "w") as handle:
            handle.write("[not json")
        self.assertEqual(S.limit(), 1.0)
        self.assertEqual(OSD.vol_limit(), "1.0")


class Pactl(unittest.TestCase):
    """pactl runs in the C locale: `pactl info`'s "Default Sink:" is
    translated otherwise, and some versions print JSON decimals with a comma."""

    def test_c_locale_and_defaults_parsed(self):
        seen = {}

        def fake_run(argv, **kw):
            seen.update(argv=argv, env=kw.get("env"))
            return S.subprocess.CompletedProcess(argv, 0, "Server Name: x\nDefault Sink: out.a\n"
                                                 "Default Source: in.b\n", "")
        real = S.subprocess.run
        S.subprocess.run = fake_run
        try:
            self.assertEqual(S.defaults(), {"sink": "out.a", "source": "in.b"})
        finally:
            S.subprocess.run = real
        self.assertEqual(seen["argv"], ["pactl", "info"])
        self.assertEqual(seen["env"]["LC_ALL"], "C")


if __name__ == "__main__":
    unittest.main()
