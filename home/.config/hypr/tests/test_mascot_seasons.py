"""The seasons theme's mascot (scripts/mascot_seasons.py): Sorrel the fox kit
in every season (pinned with season_pin, so the real date never matters),
every state and prop kind at a few stage sizes with exact widths and markup
that parses, every mood and scene combo, the head anchor, the voice table
against mascot_mood's live TOPICS (a new topic fails here loudly), the
reaction-sign colours (updated in place per season, each >= 4.5:1 on the
stage card), and the small pure helpers (moon phase, the almanac's date).
Imports the module directly: the registry (mascots.py) is the wiring step's.
Kept to a few seconds: the full `mascots.py --check` is the Integrate
phase's job."""
import datetime
import os
import sys
import unittest
import xml.etree.ElementTree as ET

import helpers

sys.path.insert(0, helpers.SCRIPTS)
import mascot_common  # noqa: E402
import mascot_mood  # noqa: E402
import mascot_seasons as ms  # noqa: E402

SIZES = ((48, 14), (74, 19), (100, 24), (160, 24))
TICKS = (0, 5, 13, 22, 40)


def luminance(hexc):
    """WCAG 2.x relative luminance, as theme.py contrast() computes it."""
    out = []
    for i in (1, 3, 5):
        c = int(hexc[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def pinned(season, cols=74, rows=19):
    m = ms.Mascot(cols, rows)
    m.season_pin = season
    return m


class Render(unittest.TestCase):
    def check(self, cv, cols, rows, where):
        lines = cv.lines()
        self.assertEqual(len(lines), rows, where)
        for i, line in enumerate(lines):
            self.assertEqual(mascot_common.display_width(line), cols, "%s row %d" % (where, i))
        root = ET.fromstring("<m>" + cv.markup() + "</m>")
        self.assertEqual("".join(root.itertext()).split("\n"), lines, where)

    def test_every_state_and_prop(self):
        for season in ms.SEASONS:
            for cols, rows in SIZES:
                m = pinned(season, cols, rows)
                for state, tool in mascot_common.COMBOS:
                    for tick in TICKS:
                        where = "%s %dx%d %s/%s t%d" % (season, cols, rows, state, tool, tick)
                        cv = m._render(state, tick, tool)
                        self.check(cv, cols, rows, where)
                        self.assertTrue(m.head and 0 <= m.head[0] < cols and 0 <= m.head[1] < rows, where)

    def test_every_tick_once(self):
        """A full 0..40 sweep at one size: the frame-dependent bits (blinks,
        wags, falling leaves, the storm flash) all take their turn."""
        m = pinned("summer", 74, 19)
        for tick in range(41):
            for state, tool in (("idle", None), ("writing", None), ("tool", "WebFetch"), ("error", None)):
                self.check(m._render(state, tick, tool, "calm", frozenset({"storm", "night"})), 74, 19,
                           "t%d %s" % (tick, state))

    def test_moods_and_scenes(self):
        for season in ms.SEASONS:
            for cols, rows in ((48, 14), (100, 24)):
                m = pinned(season, cols, rows)
                for state, tool, mood, scene in mascot_common.MOOD_COMBOS:
                    for tick in (3, 80):           # 80: inside the idle fidget window
                        where = "%s %dx%d %s/%s %s %s" % (season, cols, rows, state, tool, mood, sorted(scene))
                        self.check(m._render(state, tick, tool, mood, scene), cols, rows, where)

    def test_emotes_fit(self):
        m = pinned("winter", 48, 14)
        for state in ("idle", "thinking", "done", "error"):
            m._render(state, 4, None, "happy", frozenset({"night"}))
            for text, tone in set(mascot_mood.EMOTES.values()):
                cv = m._render(state, 4, None, "happy", frozenset({"night"}))
                mascot_common.draw_emote(cv, (text, tone, 2.0), m.head, ms.EMOTE_COLOURS)
                self.check(cv, 48, 14, "%s emote %s" % (state, text))

    def test_public_calls_match(self):
        m = pinned("autumn")
        self.assertEqual(m.lines("idle", 7), m._render("idle", 7, None).lines())
        self.assertEqual(m.markup("tool", 7, "Grep"), m._render("tool", 7, "Grep").markup())
        self.assertTrue(m.moods)

    def test_season_changes_the_picture(self):
        frames = {s: pinned(s).markup("idle", 3, None, "calm", frozenset({"night"})) for s in ms.SEASONS}
        self.assertEqual(len(set(frames.values())), 4)
        self.assertIn("AUTUMN - ", pinned("autumn").lines("idle", 3)[-1])
        self.assertIn("WINTER - ", pinned("winter").lines("idle", 3)[-1])


class Voice(unittest.TestCase):
    def test_table_covers_the_live_topics(self):
        self.assertEqual(set(ms.TOPIC_LINES), set(mascot_mood.TOPICS))

    def arity(self, text):
        return len(set(__import__("re").findall(r"\{(\d+)\}", text)))

    def test_argument_counts(self):
        tables = [ms.TOPIC_LINES] + list(ms.SEASON_LINES.values())
        for table in tables:
            for topic, entry in table.items():
                want = self.arity(mascot_mood.DEFAULT_LINES[topic])
                for text in (entry if isinstance(entry, tuple) else (entry,)):
                    self.assertEqual(self.arity(text), want, "%s: %r" % (topic, text))

    def test_say_every_topic(self):
        for season in ms.SEASONS:
            m = pinned(season)
            for topic in mascot_mood.TOPICS:
                args = ("x",) * self.arity(mascot_mood.DEFAULT_LINES[topic])
                line = m.say((topic,) + args)
                self.assertTrue(line, (season, topic))
                self.assertNotIn("{", line, (season, topic))

    def test_season_lines_win(self):
        self.assertEqual(pinned("summer").say(("weekend",)), "Weekend! Go find a lake and some shade.")
        self.assertEqual(pinned("winter").say(("hello",)), "Brr, hi! I saved you a warm spot by the fire.")
        self.assertEqual(pinned("autumn").say(("thanks",)), ms.TOPIC_LINES["thanks"])

    def test_one_emoji_at_most(self):
        """No more than one non-ASCII symbol per line (the ellipsis, the
        degree sign and the dash are punctuation, not emoji)."""
        allowed = set("…°—–’")
        tables = [ms.TOPIC_LINES, ms.MOOD_BUBBLES, ms.Mascot.BUBBLES] + list(ms.SEASON_LINES.values())
        for table in tables:
            for entry in table.values():
                for text in (entry if isinstance(entry, tuple) else (entry,)):
                    symbols = [c for c in text if ord(c) > 127 and c not in allowed]
                    self.assertLessEqual(len(symbols), 1, text)
                    for c in symbols:
                        self.assertLess(ord(c), 0x10000, "%r: astral emoji has no text fallback" % text)

    def test_bubbles(self):
        m = pinned("spring")
        self.assertEqual(m.bubble("idle", mood="curious"), ms.MOOD_BUBBLES["curious"])
        self.assertEqual(m.bubble("tool", "WebSearch"), ms.Mascot.TOOL_BUBBLES["WebSearch"])
        self.assertIn("thing", m.bubble("tool", "mcp__x__thing"))


class Colours(unittest.TestCase):
    def test_emote_tones_per_season(self):
        seen = []
        for season in ms.SEASONS:
            m = pinned(season)
            m._render("idle", 0, None)
            self.assertEqual(set(ms.EMOTE_COLOURS), set(mascot_mood.EMOTE_TONES))
            seen.append(dict(ms.EMOTE_COLOURS))
            for tone, colour in ms.EMOTE_COLOURS.items():
                self.assertGreaterEqual(contrast(colour, ms.PANEL), 4.5, (season, tone, colour))
        self.assertEqual(len({c["accent"] for c in seen}), 4)

    def test_updated_in_place(self):
        """mascots.emote_markup reads the module attribute when it draws, so
        the dict must be the same object, its contents changed."""
        ref = ms.EMOTE_COLOURS
        pinned("spring")._render("idle", 0, None)
        spring = ref["accent"]
        pinned("winter")._render("idle", 0, None)
        self.assertIs(ms.EMOTE_COLOURS, ref)
        self.assertNotEqual(ref["accent"], spring)
        self.assertEqual(ref["accent"], ms.PALETTES["winter"]["accent"])

    def test_text_on_the_strip(self):
        """The almanac strip's words on its background, every season."""
        for season, p in ms.PALETTES.items():
            self.assertGreaterEqual(contrast(p["hue2"], p["rule"]), 4.5, season)
            self.assertGreaterEqual(contrast(p["dim"], p["raised"]), 4.5, season)
            self.assertGreaterEqual(contrast(p["text"], p["rule"]), 4.5, season)
            self.assertGreaterEqual(contrast(p["ink"], p["warn"]), 4.5, season)


class Season(unittest.TestCase):
    def test_pin_wins(self):
        m = ms.Mascot()
        m.season_pin = "spring"
        self.assertEqual(m._season(), "spring")

    def test_env_through_theme(self):
        """Without a pin it asks theme.py, which honours $HYPR_SEASON; a
        missing seasons theme (theme.season() == "") means the default."""
        old = os.environ.get("HYPR_SEASON")
        os.environ["HYPR_SEASON"] = "summer"
        try:
            got = ms.current_season()
        finally:
            if old is None:
                os.environ.pop("HYPR_SEASON", None)
            else:
                os.environ["HYPR_SEASON"] = old
        self.assertIn(got, ("summer", ms.DEFAULT_SEASON))

    def test_recheck_is_rate_limited(self):
        calls = []
        real = ms.current_season
        ms.current_season = lambda: calls.append(1) or "winter"
        try:
            m = ms.Mascot()
            for _ in range(5):
                self.assertEqual(m._season(), "winter")
            self.assertEqual(len(calls), 1)
            m._season_at -= ms.SEASON_RECHECK_S + 1
            m._season()
            self.assertEqual(len(calls), 2)
        finally:
            ms.current_season = real


class Helpers(unittest.TestCase):
    def test_moon(self):
        new = ms.MOON_EPOCH
        self.assertEqual(ms.moon_glyph(new), ".")
        self.assertEqual(ms.moon_glyph(new + datetime.timedelta(days=7)), ")")
        self.assertEqual(ms.moon_glyph(new + datetime.timedelta(days=14.8)), "O")
        self.assertEqual(ms.moon_glyph(new + datetime.timedelta(days=22)), "(")
        self.assertEqual(ms.moon_glyph(new + datetime.timedelta(days=ms.SYNODIC * 100)), ".")

    def test_almanac_date(self):
        self.assertEqual(ms.almanac_date("autumn", datetime.date(2026, 10, 24)), "AUTUMN - 24 OCT")
        self.assertEqual(ms.almanac_date("winter", datetime.date(2027, 1, 3)), "WINTER - 3 JAN")
        self.assertTrue(all(mascot_common.dw(c) == 1 for c in ms.almanac_date("spring")))


if __name__ == "__main__":
    unittest.main()
