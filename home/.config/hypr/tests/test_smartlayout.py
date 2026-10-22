"""scripts/smartlayout.py (learned window placements): what a placement is,
the votes and the confidence, the tracker's settling / fighting / pairing
rules under a fake clock, the Lua it would dispatch, arrange's plan and the
commands.

Hermetic: the store is helpers.py's scratch XDG_STATE_HOME, the clients and
monitors are dicts, dispatches are collected instead of sent."""
import os
import unittest

import helpers

SL = helpers.import_script("smartlayout.py")
SL.log = lambda *_a, **_k: None         # not into the real journal

DP1 = {"id": 0, "name": "DP-1", "x": 0, "y": 0, "width": 3440, "height": 1440, "scale": 1, "transform": 0,
       "reserved": [0, 36, 0, 0], "focused": True, "activeWorkspace": {"id": 1, "name": "1"}}
PORTRAIT = {"id": 1, "name": "HDMI-A-1", "x": 3440, "y": 0, "width": 1920, "height": 1080, "scale": 1,
            "transform": 1, "reserved": [0, 0, 0, 0], "focused": False, "activeWorkspace": {"id": 7, "name": "7"}}
MONS = [DP1, PORTRAIT]


def win(addr, cls, ws="1", at=(0, 36), size=(1720, 1404), floating=False, mon=0, focus=5, title="t"):
    return {"address": addr, "class": cls, "title": title, "workspace": {"id": 0, "name": ws}, "at": list(at),
            "size": list(size), "floating": floating, "monitor": mon, "mapped": True, "hidden": False,
            "fullscreen": 0, "pid": 0, "focusHistoryID": focus}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Placement(unittest.TestCase):
    def test_sides(self):
        left = win("0x1", "code")
        right = win("0x2", "firefox", at=(1720, 36))
        full = win("0x3", "kitty", size=(3440, 1404))
        self.assertEqual(SL.describe(left, MONS)["key"], "1|tile|left")
        self.assertEqual(SL.describe(right, MONS)["key"], "1|tile|right")
        self.assertEqual(SL.describe(full, MONS)["key"], "1|tile|full")
        top = win("0x4", "kitty", size=(3440, 700))
        self.assertEqual(SL.side_of(top, DP1), "top")

    def test_portrait_and_floating(self):
        # HDMI-A-1 is portrait: 1080 wide, 1920 tall
        f = win("0x5", "pavucontrol", ws="7", at=(3440 + 700, 100), size=(300, 400), floating=True, mon=1)
        d = SL.describe(f, MONS)
        self.assertEqual(d["key"], "7|float|top-right")
        self.assertAlmostEqual(d["size"][0], round(300 / 1080, 3))
        self.assertEqual(SL.side_of(win("0x6", "x", at=(1400, 500), size=(600, 400), floating=True), DP1), "center")

    def test_left_out(self):
        self.assertEqual(SL.learnable(win("0x1", "")), "not a window yet")
        self.assertEqual(SL.learnable(win("0x1", "kitty", ws="special:scratch")), "a scratchpad")
        self.assertEqual(SL.learnable(win("0x1", "steam_app_123")), "Steam / a game")
        self.assertEqual(SL.learnable(win("0x1", "org.keepassxc.KeePassXC")), "private")
        self.assertEqual(SL.learnable(win("0x1", "firefox", title="Mozilla Firefox Private Browsing")), "private")
        self.assertEqual(SL.learnable(win("0x1", "telegram"), exclude=("telegram",)), "private")
        self.assertEqual(SL.learnable(win("0x1", "x", floating=True, size=(100, 50))), "a popup")
        self.assertEqual(SL.learnable(win("0x1", "x", title="Open File")), "a dialog or picker")
        self.assertIsNone(SL.learnable(win("0x1", "kitty")))
        self.assertIsNone(SL.describe(win("0x1", "kitty", ws="a|b"), MONS))

    def test_words(self):
        self.assertEqual(SL.place_words("3|tile|left", {"monitor": "DP-1"}), "workspace 3 (DP-1) · left side")
        self.assertIn("40 × 50 %", SL.place_words("5|float|top-right", {"size": [0.4, 0.5]}))
        self.assertEqual(SL.split_key("bad"), ("bad", False, ""))


class Votes(unittest.TestCase):
    def test_one_vote_per_window_moves(self):
        data = SL.empty()
        d1 = SL.describe(win("0x1", "code", ws="1"), MONS)
        d5 = SL.describe(win("0x1", "code", ws="5"), MONS)
        SL.vote(data, "code", d1)
        SL.vote(data, "code", d5, old_key=d1["key"])
        places = data["apps"]["code"]["placements"]
        self.assertNotIn("1|tile|left", places)          # back to zero: dropped
        self.assertEqual(places["5|tile|left"]["count"], 1)

    def test_decision_needs_evidence_and_confidence(self):
        data = SL.empty()
        d5 = SL.describe(win("0x1", "code", ws="5"), MONS)
        d2 = SL.describe(win("0x1", "code", ws="2"), MONS)
        for _ in range(2):
            SL.vote(data, "code", d5)
        app = data["apps"]["code"]
        self.assertIsNone(SL.decision(app, 3))
        SL.vote(data, "code", d5)
        self.assertEqual(SL.decision(app, 3)[0], "5|tile|left")
        SL.vote(data, "code", d2)
        SL.vote(data, "code", d2)                        # 3 of 5 = 60 %: still
        self.assertEqual(SL.decision(app, 3)[0], "5|tile|left")
        SL.vote_against(data, "code", "5|tile|left")     # 3 of 6 = 50 %: no more
        self.assertIsNone(SL.decision(app, 3))
        app["locked"] = "2|tile|left"
        self.assertEqual(SL.decision(app, 3)[2], "locked")

    def test_floating_size_is_averaged_and_prune(self):
        data = SL.empty()
        a = SL.describe(win("0x1", "calc", at=(100, 100), size=(400, 400), floating=True), MONS)
        b = SL.describe(win("0x1", "calc", at=(100, 100), size=(600, 400), floating=True), MONS)
        SL.vote(data, "calc", a)
        SL.vote(data, "calc", b)
        size = data["apps"]["calc"]["placements"][a["key"]]["size"]
        self.assertAlmostEqual(size[0], round(500 / 3440, 3), places=2)
        for ws in range(20):
            SL.vote(data, "calc", SL.describe(win("0x1", "calc", ws=str(ws + 10)), MONS))
        self.assertLessEqual(len(data["apps"]["calc"]["placements"]), SL.MAX_PLACES)

    def test_undone(self):
        self.assertTrue(SL.undone("5|tile|left", "5|tile|left", "6|tile|left"))
        self.assertTrue(SL.undone("5|tile|left", "5|tile|left", "5|tile|right"))
        self.assertFalse(SL.undone("5|tile|left", "1|tile|right", "5|tile|left"))      # on its way there
        self.assertFalse(SL.undone("5|tile|left", "5|tile|right", "5|tile|left"))      # the side fix


class FakeStore:
    def __init__(self):
        self.data = SL.empty()

    def __call__(self):
        return self

    def __enter__(self):
        return self.data

    def __exit__(self, *_):
        return False


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.clock, self.store, self.sent = Clock(), FakeStore(), []
        self.t = SL.Tracker(clock=self.clock, wall=lambda: 1.7e9, store=self.store,
                            dispatch=lambda lua: self.sent.append(lua) or True, exclude=lambda: [])
        self.t.load_settings = lambda: self.t.settings
        real, SL.panel = SL.panel, (lambda c: False)
        self.addCleanup(setattr, SL, "panel", real)

    def test_settles_after_min_stay(self):
        clients = [win("0x1", "code", ws="5")]
        self.t.refresh(clients, MONS)
        self.clock.t += SL.MIN_STAY_S - 1
        self.t.refresh(clients, MONS)
        self.assertEqual(self.store.data["apps"], {})
        self.clock.t += 2
        self.t.refresh(clients, MONS)
        self.assertEqual(self.store.data["apps"]["code"]["placements"]["5|tile|left"]["count"], 1)
        self.clock.t += 100
        self.t.refresh(clients, MONS)                    # still one vote
        self.assertEqual(self.store.data["apps"]["code"]["placements"]["5|tile|left"]["count"], 1)

    def test_places_first_window_only_in_mode_on(self):
        for _ in range(3):
            SL.vote(self.store.data, "code", SL.describe(win("0x9", "code", ws="5"), MONS))
        SL.write_store(self.store.data)
        try:
            new = [win("0x1", "code", ws="1", focus=0)]
            self.t.settings = dict(SL.DEFAULTS, mode="learn")
            self.assertIsNone(self.t.opened("0x1", "code", new, MONS, busy=lambda: False))
            self.t.settings = dict(SL.DEFAULTS, mode="on")
            self.assertEqual(self.t.opened("0x1", "code", new, MONS, busy=lambda: False), "5|tile|left")
            self.assertIn('workspace = "5", follow = true', self.sent[-1])
            self.assertEqual(self.t.later[-1][1:], ("0x1", "left"))
            # a second code window opens where you are
            two = new + [win("0x2", "code", ws="1", focus=0)]
            self.assertIsNone(self.t.opened("0x2", "code", two, MONS, busy=lambda: False))
            # ... and nothing while a session is being restored
            self.t.windows.clear()
            self.assertIsNone(self.t.opened("0x1", "code", new, MONS, busy=lambda: True))
        finally:
            os.remove(SL.STORE)

    def test_moving_it_back_counts_against(self):
        self.t.settings = dict(SL.DEFAULTS, mode="on")
        self.t.refresh([win("0x1", "code", ws="5")], MONS)
        w = self.t.windows["0x1"]
        w.update(placed="5|tile|left", placed_at=self.clock.t, own_until=self.clock.t + SL.OWN_S)
        SL.vote(self.store.data, "code", SL.describe(win("0x1", "code", ws="5"), MONS))
        self.clock.t += 10
        self.t.refresh([win("0x1", "code", ws="1")], MONS)
        self.assertEqual(self.store.data["apps"]["code"]["placements"]["5|tile|left"]["against"], 1)
        self.assertIsNone(w["placed"])                   # left alone after that

    def test_side_fix_swaps_when_on_the_wrong_side(self):
        self.t.later = [(self.clock.t, "0x1", "left")]
        self.t.tick([win("0x1", "code", at=(1720, 36)), win("0x2", "firefox")], MONS)
        self.assertIn('direction = "l"', self.sent[-1])

    def test_pairs(self):
        clients = [win("0x1", "code"), win("0x2", "firefox", at=(1720, 36))]
        self.t.refresh(clients, MONS)
        self.clock.t += SL.MIN_STAY_S + 1
        self.t.refresh(clients, MONS)
        self.t.refresh(clients, MONS)
        pair = self.store.data["pairs"][SL.pair_key("code", "firefox")]
        self.assertEqual((pair["count"], pair["sides"]), (1, {"code": "left", "firefox": "right"}))

    def test_private_apps_are_not_learned(self):
        self.t.exclude = lambda: ["code"]
        clients = [win("0x1", "code")]
        self.t.refresh(clients, MONS)
        self.clock.t += 100
        self.t.refresh(clients, MONS)
        self.assertEqual(self.store.data["apps"], {})

    def test_restart_does_not_vote_twice(self):
        path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "test-smartlayout-votes.json")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self.t.votes_file = (path, "inst-a")
        clients = [win("0x1", "code", ws="5"), win("0x2", "firefox", ws="6")]
        self.t.refresh(clients, MONS)
        self.clock.t += SL.MIN_STAY_S + 1
        self.t.refresh(clients, MONS)
        self.assertEqual(self.store.data["apps"]["code"]["placements"]["5|tile|left"]["count"], 1)
        # the service restarts: a new tracker, the votes file of the same Hyprland
        t2 = SL.Tracker(clock=self.clock, wall=lambda: 1.7e9, store=self.store,
                        dispatch=lambda lua: True, exclude=lambda: [])
        t2.load_settings = lambda: t2.settings
        t2.prior = SL.load_votes(path, "inst-a")
        self.assertEqual(SL.load_votes(path, "inst-b"), {})      # another Hyprland: nothing carried
        t2.refresh(clients, MONS)
        self.clock.t += SL.MIN_STAY_S + 1
        t2.refresh(clients, MONS)
        self.assertEqual(self.store.data["apps"]["code"]["placements"]["5|tile|left"]["count"], 1)
        # ... but a class that does not match the address is a new window
        t3 = SL.Tracker(clock=self.clock, wall=lambda: 1.7e9, store=self.store,
                        dispatch=lambda lua: True, exclude=lambda: [])
        t3.load_settings = lambda: t3.settings
        t3.prior = {"0x1": ["other", "5|tile|left"]}
        t3.refresh(clients[:1], MONS)
        self.clock.t += SL.MIN_STAY_S + 1
        t3.refresh(clients[:1], MONS)
        self.assertEqual(self.store.data["apps"]["code"]["placements"]["5|tile|left"]["count"], 2)


class Events(unittest.TestCase):
    def test_openwindow_line(self):
        seen = []

        class T:
            dirty = False

            def opened(self, addr, cls):
                seen.append((addr, cls))
        t = T()
        SL.handle(t, "openwindow>>55aa01,3,org.mozilla.firefox,Mozilla Firefox, with a comma")
        self.assertEqual(seen, [("0x55aa01", "org.mozilla.firefox")])
        SL.handle(t, "movewindowv2>>55aa01,4,4")
        self.assertTrue(t.dirty)


class Lua(unittest.TestCase):
    def test_float_place(self):
        lua = SL.place_lua("0xabc", "1|float|top-right", {"monitor": "DP-1", "size": [0.25, 0.5], "rel": [0.7, 0.1]},
                           MONS, win("0xabc", "calc"), follow=False)
        self.assertIn('hl.get_window("address:0xabc")', lua)
        self.assertIn('action = "enable"', lua)
        self.assertIn("x = 860, y = 702", lua)            # 25 % of 3440, 50 % of 1404
        self.assertNotIn("workspace =", lua)              # already on 1

    def test_locked_float_never_seen_gets_a_default_size(self):
        lua = SL.place_lua("0x1", "1|float|center", {}, MONS, win("0x1", "x"))
        self.assertIn("x = 1720, y = 842", lua)

    def test_tiled_from_floating(self):
        lua = SL.place_lua("0x1", "work|tile|left", {}, MONS, win("0x1", "x", floating=True))
        self.assertIn('workspace = "name:work", follow = false', lua)
        self.assertIn('action = "disable"', lua)


class Arrange(unittest.TestCase):
    def test_brings_partner_and_fixes_sides(self):
        data = SL.empty()
        for _ in range(3):
            SL.vote_pair(data, "code", "left", "firefox", "right")
        clients = [win("0x1", "code", focus=0, size=(3440, 1404)), win("0x2", "firefox", ws="4", focus=1)]
        steps, pair, why = SL.arrange_plan(clients, MONS, data, 3)
        self.assertIsNone(why)
        self.assertIn('workspace = "1", follow = false, window = "address:0x2"', steps[0][0])
        after = [win("0x1", "code", at=(1720, 36), focus=0), win("0x2", "firefox", focus=1)]
        fix = SL.sides_fix(after, MONS, "1", pair, focused="0x1")
        self.assertIn('direction = "l"', fix)
        self.assertIsNone(SL.sides_fix([win("0x1", "code"), win("0x2", "firefox", at=(1720, 36))], MONS, "1", pair))

    def test_nothing_learned(self):
        steps, pair, why = SL.arrange_plan([win("0x1", "code", focus=0)], MONS, SL.empty(), 3)
        self.assertEqual((steps, pair), ([], None))
        self.assertIn("nothing learned", why)


class Commands(unittest.TestCase):
    def tearDown(self):
        for p in (SL.STORE, SL.STORE + ".lock"):
            if os.path.exists(p):
                os.remove(p)

    def test_set_lock_forget(self):
        self.assertEqual(SL.main(["set", "mode", "on"]), 0)
        self.assertEqual(SL.main(["set", "evidence", "5"]), 0)
        self.assertIn("smartlayout:", SL.main(["set", "evidence", "99"]))
        self.assertEqual(SL.main(["lock", "code", "5|tile|left"]), 0)
        self.assertIn("smartlayout:", SL.main(["lock", "code", "nonsense"]))
        st = SL.status()
        self.assertEqual((st["settings"]["mode"], st["settings"]["evidence"]), ("on", 5))
        self.assertEqual(st["apps"][0]["applies"], "5|tile|left")
        SL.main(["unlock", "code"])
        self.assertIsNone(SL.read_store()["apps"]["code"]["locked"])
        SL.main(["forget", "code"])
        self.assertEqual(SL.read_store()["apps"], {})

    def test_broken_store_reads_as_empty(self):
        os.makedirs(os.path.dirname(SL.STORE), exist_ok=True)
        with open(SL.STORE, "w") as handle:
            handle.write("{not json")
        self.assertEqual(SL.read_store(), SL.empty())


class PageWords(unittest.TestCase):
    """settings_pages/layout.py's wording (needs GTK importable, not a display)."""

    @classmethod
    def setUpClass(cls):
        try:
            import gi  # noqa: F401
            from settings_pages import layout as page
        except Exception as exc:   # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.layout not importable: {exc}")
        cls.page = page

    def test_app_sub(self):
        app = {"class": "code", "locked": None, "applies": None,
               "places": [{"key": "2|tile|left", "words": "workspace 2 · left side", "count": 1,
                           "against": 0, "confidence": 1.0}]}
        self.assertIn("2 more to go", self.page.app_sub(app, 3))
        app["applies"] = "2|tile|left"
        app["places"][0].update(count=5, against=2, confidence=0.71)
        text = self.page.app_sub(app, 3)
        self.assertIn("5 times, 71 %", text)
        self.assertIn("undone 2 times", text)
        self.assertIn("used when it opens", text)
        app["locked"] = "2|tile|left"
        self.assertTrue(self.page.app_sub(app, 3).startswith("locked: workspace 2"))

    def test_pair_sub(self):
        text = self.page.pair_sub({"a": "code", "b": "firefox", "count": 1, "ready": False,
                                   "sides": {"code": "left", "firefox": "right"}})
        self.assertEqual(text, "code left, firefox right  ·  1 time  ·  not used yet")


if __name__ == "__main__":
    unittest.main()
