#!/usr/bin/env python3
"""The orchard theme's mascot: Hum, a round little honeybee who tends the
orchard -- a blossom tree on the left, a straw hive on the right, a strip of
meadow along the bottom. Same API as moe_mascot.Mascot (mascots.py picks
it). Our own character: a bee, never a fruit, nothing borrowed.

    stage     the panel (#c4c4ca, themes/orchard/llm-chat.css paints the same
              on #stage), a faint sky tint in the top two rows, a meadow row
              (grass tufts on a soft green) over a row of soil
    tree      12 cells on the left: a rounded canopy in a pale leaf green with
              a dark-green edge and pink blossoms (✿), a trunk down to the
              grass. Blossoms -- a cherry-like tree, never one with fruit
    Hum       13 x 8 cells in the middle: two antennae, a round amber head
              and body with two dark stripes, a face, a pollen satchel (@) at
              the hip, and two pale wings that flutter -- a wing is two cells
              on a light ground that hop one row up and down. He hovers,
              bobbing a row; the wing beat follows his mood (fast when
              excited or alert, slow when sad, folded when asleep)
    hive      12 cells on the right: a straw skep in honey stripes with a
              round door, and the work above it on a little card: a dark
              terminal (>_) for Bash, an open book for Read, a note and a
              pencil for Edit/Write, a magnifier sliding over a blossom for
              the searches, a globe that turns for WebFetch, two worker
              bees leaving the hive for Task/Agent, a honeycomb checklist
              for TodoWrite, pollen sparkles otherwise. Whatever the tool,
              he carries a grain of it in his satchel (a different glyph per
              tool). Thinking is Hum hovering from one blossom to the other
              and back, writing a leaf-scroll filling with words, done a jar
              of honey (and sparkles), an error a spilt jar and a "!"

  mood      one of mascot_mood.MOODS: the face (calm sleepy-content eyes,
              happy ^ ^, excited wide eyes and a twinkle, shy a blush,
              curious o O and a "?", focused narrowed eyes, worried a sweat
              drop, sad ; ;, sleepy shut eyes and a "z" with his wings
              folded), the antennae (up, perked with tips, or drooping) and
              the wing beat. At work only the accents show over the work
              face; sleepy works focused. The idle fidget at the end of each
              9-second round (an antenna twitch, a little loop, a look
              round) is picked by the noise and weighted by the mood.
  scene     a set of mascot_mood.SCENES: day (a sun in the corner), night
              (a crescent and stars, a deeper tint), sun (the sun with rays),
              cloud, rain and storm (drops over the meadow; a bolt now and
              then), snow (flakes, snow on the hive and the canopy), fog
              (drifting bands), hot (shimmer over the grass, a sweat drop),
              cold (a red scarf, breath puffs), music (notes, a bob to the
              beat), game (a handheld in his legs, idle), party (a party hat,
              confetti), festive (a string of lights along the top), clock
              (a little alarm clock on the hive, ringing).

The stage is LIGHT, so every visible element has a dark outline or stripe
(#1d1d1f and dark greens / browns); the coloured cells are small (the bee,
the blossoms, the hive) and the large ones stay near the panel's grey, as
the theme's HDR rule wants. mascot_orchard_dark.py binds the DARK palette
below to the same drawing. Every glyph is single-column (mascot_common.dw).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import STATES, BaseMascot, Canvas, blink, lcg, prop_kind, stream_lines  # noqa: E402
from mascot_mood import MOODS, word  # noqa: E402

THEME = "orchard"
PANEL = "#c4c4ca"

# Colour roles, light appearance: dark glyphs on light grounds (>= 4.5:1
# on the panel for the lines, >= 3:1 for the small accents).
LIGHT = {
    "panel": PANEL,
    "sky": ("#bfc5cf", "#c2c6cd"), "sky_night": ("#b3b7c6", "#babdc8"),
    "line": "#1d1d1f", "dim": "#4f4f54",
    "body": "#e6a800", "stripe_bg": "#1d1d1f", "stripe": "#e6a800", "eye": "#1d1d1f",
    "wing_bg": "#dfe6f0", "wing": "#33415a", "satchel": "#7a4a00",
    "blush": "#e69aa8", "sweat": "#1f4f9a",
    "leaf_bg": "#a2ba93", "leaf": "#2a542c", "blossom": "#a3245f", "trunk": "#55361c",
    "grass_bg": "#aab89c", "grass": "#2a542c", "soil_bg": "#b2a794", "soil": "#55452f",
    "hive_bg": "#d2a04a", "hive": "#4f300c", "door_bg": "#3a2408",
    "card_bg": "#dadade", "card": "#1d1d1f", "card_dim": "#4f4f54",
    "term_bg": "#1e1e1e", "term": "#e5e5e5", "term_ok": "#32d74b",
    "honey_bg": "#e6a800", "honey": "#4f300c",
    "accent": "#0058c4", "good": "#248a3d", "warn": "#b25000", "bad": "#d70015",
    "love": "#d30f45",
    "sun": "#8a5600", "moon": "#5e5018", "star": "#43437a",
    "cloud_bg": "#d3d6dc", "cloud": "#4f5666", "rain": "#1f4f9a", "snow": "#3f4f6e",
    "snow_bg": "#e3e7ee", "fog": "#6e7480", "flash": "#8a6a00",
    "scarf_bg": "#b02a3a", "scarf": "#ffffff", "hat_bg": "#0062cc", "hat": "#ffffff",
    "notes": ("#6a2a9a", "#0058c4"),
    "confetti": ("#d70015", "#0058c4", "#248a3d", "#8944ab", "#b25000"),
    "bulbs": ("#d70015", "#b25000", "#248a3d", "#0058c4", "#8944ab"),
    "game_bg": "#3a3a3c", "game": "#e5e5ea",
}
# Dark appearance (mascot_orchard_dark.py): light lines on #232325.
DARK = {
    "panel": "#232325",
    "sky": ("#1d2130", "#202229"), "sky_night": ("#151722", "#1a1b23"),
    "line": "#d8d8dc", "dim": "#a1a1a6",
    "body": "#e6a800", "stripe_bg": "#1d1d1f", "stripe": "#e6a800", "eye": "#1d1d1f",
    "wing_bg": "#3a4658", "wing": "#d4e2f6", "satchel": "#ffcf6a",
    "blush": "#a04a60", "sweat": "#7ab0ff",
    "leaf_bg": "#2c472e", "leaf": "#93c48c", "blossom": "#ff8fc0", "trunk": "#c49470",
    "grass_bg": "#26342a", "grass": "#8fc08a", "soil_bg": "#2e2a26", "soil": "#968670",
    "hive_bg": "#6a4a1a", "hive": "#f0c070", "door_bg": "#1a1206",
    "card_bg": "#3a3a3c", "card": "#ebebf0", "card_dim": "#a1a1a6",
    "term_bg": "#121212", "term": "#e5e5e5", "term_ok": "#32d74b",
    "honey_bg": "#e6a800", "honey": "#3a2408",
    "accent": "#409cff", "good": "#30d158", "warn": "#ff9f0a", "bad": "#ff453a",
    "love": "#ff375f",
    "sun": "#ffd060", "moon": "#f2e2a0", "star": "#e0dcff",
    "cloud_bg": "#34363c", "cloud": "#b0b4be", "rain": "#7ab0ff", "snow": "#f2f2f7",
    "snow_bg": "#4a4e58", "fog": "#7c808a", "flash": "#ffe066",
    "scarf_bg": "#c03a4a", "scarf": "#ffffff", "hat_bg": "#0071e3", "hat": "#ffffff",
    "notes": ("#d070ff", "#409cff"),
    "confetti": ("#ff453a", "#409cff", "#30d158", "#bf5af2", "#ff9f0a"),
    "bulbs": ("#ff453a", "#ff9f0a", "#30d158", "#409cff", "#bf5af2"),
    "game_bg": "#0b0b0c", "game": "#e5e5ea",
}
# The reaction sign over his head (mascot_mood.EMOTE_TONES): the theme's
# own accent text and status colours, >= 4.5:1 on the panel and the sky.
EMOTE_COLOURS = {"accent": "#0058c4", "warn": "#b25000", "bad": "#d70015", "good": "#248a3d",
                 "love": "#d30f45", "dim": "#4f4f54"}
OVERCAST = frozenset(("cloud", "rain", "storm", "snow", "fog"))

TW = 12             # the tree
HW = 22             # Hum's air: he is 13 wide and travels between two blossoms
RW = 12             # the hive and the work card above it
COMP_W = TW + 1 + HW + 1 + RW       # 48: the smallest stage, exactly
BW, BH = 13, 8      # Hum

WORDS = ("nectar", "bloom", "pollen", "honey", "comb", "buzz", "petal", "sun", "hive",
         "sweet", "dew", "leaf", "row", "tree", "warm", "done", "neat", "tidy")
CMDS = (">_ ls", "> make", "> git", "> cat", "> ping", "> cd ~")

# Per mood, idle: (left eye, right eye, mouth).
MOOD_FACE = {
    "calm": ("ᵕ", "ᵕ", "w"),
    "happy": ("^", "^", "w"),
    "excited": ("O", "O", "D"),
    "shy": ("o", "o", "~"),
    "curious": ("o", "O", "o"),
    "focused": ("-", "-", "_"),
    "worried": ("o", "o", "~"),
    "sad": (";", ";", "n"),
    "sleepy": ("-", "-", "_"),
}
# Wing beat: ticks per half-beat (0 = folded, still).
WING_BEAT = {"calm": 3, "happy": 2, "excited": 1, "shy": 3, "curious": 2, "focused": 2,
             "worried": 1, "sad": 5, "sleepy": 0}
# Antennae: "up" (tips o), "perk" (tips *), "droop" (bent down).
ANTENNAE = {"calm": "up", "happy": "up", "excited": "perk", "shy": "up", "curious": "perk",
            "focused": "up", "worried": "droop", "sad": "droop", "sleepy": "droop"}
FIDGETS = {
    "calm": (("twitch", 3), ("loop", 1), ("look", 2), ("rest", 2)),
    "happy": (("loop", 3), ("twitch", 2), ("look", 1)),
    "excited": (("loop", 4), ("twitch", 2)),
    "shy": (("look", 2), ("rest", 3)),
    "curious": (("look", 4), ("twitch", 2)),
    "focused": (("rest", 3), ("twitch", 1)),
    "worried": (("look", 3), ("twitch", 2)),
    "sad": (("rest", 3), ("twitch", 1)),
    "sleepy": (("rest", 4),),
}
# The grain of the work he carries in his satchel, per prop kind.
CARRY = {"bash": ">", "book": "=", "pad": "/", "lens": "o", "globe": "@", "helpers": "8",
         "todo": "+", "wand": "*"}

MOOD_BUBBLES = {
    "calm": "bzz… the orchard's quiet. what shall we tend?",
    "happy": "bzz! everything's in bloom. what's next?",
    "excited": "bzzz! a new flower! let's go!",
    "shy": "oh… you caught me napping on a petal.",
    "curious": "hm? what's that one? tell me more…",
    "focused": "wings steady. ready when you are.",
    "worried": "bzz… something's not right in the rows?",
    "sad": "a grey sort of day… stay a while?",
    "sleepy": "zz… one more minute in the blossom…",
}
# mascot_mood topics in his words (str.format with the topic's arguments):
# gentle, tidy, a gardener's voice.
TOPIC_LINES = {
    "thanks": "bzz~ my pleasure.",
    "worried": "hm… that row doesn't look right.",
    "frustrated": "again? deep breath, we'll replant it…",
    "relieved": "phew. back to the blossoms ~",
    "determined": "a long row. I'll keep at it.",
    "proud": "all tended, and neatly too ~",
    "sad": "sorry… *antennae down*",
    "happy": "bzz~",
    "curious": "ooh, a new flower…",
    "rain": "rain on the orchard… good for the roots.",
    "storm": "a storm… everyone back to the hive.",
    "snow": "snow on the hive. we'll stay in and keep warm.",
    "fog": "foggy rows today. I'll fly slowly.",
    "sun": "sunshine! the blossoms are wide open.",
    "hot": "it's {0}… the hive's fanning its wings.",
    "cold": "brr, {0} out. scarf on.",
    "gpu_hot": "the GPU's at {0}°C. warm as a summer hive.",
    "cpu_hot": "the CPU's at {0}°C… let it rest a moment?",
    "music": "a tune! I'll buzz along ~",
    "game": "game time? I'll keep the flowers company.",
    "event": "bzz, {0} in {1} min.",
    "event_now": "{0} is starting now!",
    "birthday": "happy birthday, {0}! fresh honey for you.",
    "holiday": "it's {0} today ~",
    "go_home": "it's {0}. the orchard can wait till tomorrow.",
    "bedtime": "it's {0}… even bees sleep.",
    "morning": "good morning! the dew's still on the petals.",
    "lunch": "lunch? I know where the nectar is.",
    "weekend": "it's the weekend. a slow day in the garden ~",
    "friday": "friday afternoon… the rows are nearly done ~",
    # conversation and stage events (tuples rotate: a new one each time)
    "hello": ("bzz, hello ~ what shall we grow?", "oh, hi! the orchard's ready.",
              "hello you. a tidy session?"),
    "welcome_back": "you're back ~ I kept the blossoms open.",
    "wake": "bzz…? oh, I'm up. mostly ~",
    "long_prompt": ("that's a long row… I'll settle in.", "lots to read ~ more nectar, then."),
    "code": "code ~ let me take a closer look.",
    "image": "ooh, a picture. let me see ~",
    "aborted": "okay, stopping ~",
    "tests_pass": ("tests are green ~ like new leaves.", "all passing. honey break?",
                   "green rows ~ nice and tidy."),
    "tests_fail": ("a few tests wilted… we'll tend them ~", "red ones… let's look again."),
    "commit": ("committed ~ off to the hive.", "shipped. a sweet little win ~",
               "pushed ~ time to stretch the wings."),
    "fast": ("quick one ~", "done before the dew dried.", "that was fast ~ bzz."),
    "busy": ("busy as a bee today…", "so many tools… I'll keep up ~"),
    "model": "a new voice in the orchard: {0} ~",
    "poke": ("bzz?", "hm? oh, hi ~", "*wing flutter*", "you called? ~",
             "boop ~ right back at you.", "bzz, I was almost dozing…"),
    "poke_spam": ("bzz! careful, I'm small ~", "okay okay, I'm awake! ~",
                  "*buzzes in a circle*… please stop ~"),
    "pet": ("bzzz~", "*happy wiggle* ~", "mm, right between the wings ~",
            "*a slow little twirl* ~"),
    # railguard.py's notifications (mascot_notify.py says them, voice on)
    "rg_memory": "the hive was crowded: {0} was hoarding the honey (memory), so I moved it out.",
    "rg_vram": "{0} filled the GPU's comb. I cleared it out ~",
    "rg_game_vram": "{0} is filling the GPU's comb… lower the textures?",
    "rg_panic": "done: {0} is gone. back to the blossoms ~",
    "rg_stuck": "the memory's nearly full and I can't find who took it…",
    "rg_agents": "all the agents' jobs stopped. the sessions are safe in the hive.",
}


class Mascot(BaseMascot):
    BUBBLES = {
        "idle": "bzz… the orchard's quiet. what shall we tend?",
        "thinking": "hmm… flying it over, flower to flower",
        "writing": "writing it on a leaf…",
        "done": "all done ~ fresh honey",
        "error": "bzz?! that didn't work. try again?",
    }
    TOOL_BUBBLES = {
        "Bash": "tapping the little terminal…",
        "Read": "reading, a page at a time…",
        "Edit": "a small, tidy edit…",
        "MultiEdit": "a few tidy edits…",
        "Write": "writing it down…",
        "NotebookEdit": "tidying the notebook…",
        "Grep": "looking flower by flower…",
        "Glob": "flying the rows…",
        "WebSearch": "asking the other gardens…",
        "WebFetch": "fetching it from afar…",
        "Task": "sending the workers out…",
        "Agent": "sending the workers out…",
        "TodoWrite": "ticking the comb…",
    }
    OTHER = "gathering %s…"
    moods = True
    PAL = LIGHT

    def __init__(self, cols=64, rows=18):
        self.cols = max(int(cols), COMP_W)
        self.rows = max(int(rows), 14)
        g = max(0, min(4, (self.cols - COMP_W) // 8))
        comp = COMP_W + 2 * g
        self.cx = (self.cols - comp) // 2
        self.tx = self.cx                       # the tree's left edge
        self.hx = self.tx + TW + 1 + g          # Hum's air, left edge
        self.rx = self.hx + HW + 1 + g          # the hive column's left edge
        self.ground = self.rows - 2             # the meadow row; soil under it
        self.base_y = max(1, self.ground - BH - 1)   # Hum's top row at rest
        self.head = (self.hx + 10, max(0, self.base_y - 1))
        self._stream = stream_lines(WORDS, 8, seed=97)
        self._grass = [lcg(311, x)() for x in range(self.cols)]
        self._stars = [(int(lcg(313, i)() * self.cols), int(lcg(317, i)() * 3),
                        20 + int(lcg(331, i)() * 30), int(lcg(337, i)() * 50))
                       for i in range(max(6, self.cols // 9))]

    def lines(self, state, tick, tool=None, mood=None, scene=()):
        return self._render(state, tick, tool, mood, scene).lines()

    def markup(self, state, tick, tool=None, mood=None, scene=()):
        return self._render(state, tick, tool, mood, scene).markup()

    def say(self, topic):
        return word(TOPIC_LINES, topic)

    def bubble(self, state, tool=None, mood=None):
        if state == "idle" and mood in MOOD_BUBBLES:
            return MOOD_BUBBLES[mood]
        return BaseMascot.bubble(self, state, tool)

    # -- composition -----------------------------------------------------------------

    def _render(self, state, tick, tool, mood=None, scene=()):
        if state not in STATES:
            state = "idle"
        if mood not in MOODS:
            mood = "calm"
        if mood == "sleepy" and state in ("thinking", "tool", "writing"):
            mood = "focused"            # no dozing on the job
        scene = frozenset(scene or ())
        tick = int(tick)
        p = self.PAL
        cv = Canvas(self.cols, self.rows)
        kind = prop_kind(tool) if state == "tool" else None
        fidget = self._fidget(tick, mood) if state == "idle" else None

        self._sky(cv, scene)
        self._weather_sky(cv, tick, scene)
        self._meadow(cv, tick, scene)
        self._tree(cv, scene)
        self._hive(cv, tick, scene)
        if "festive" in scene:
            self._lights(cv, tick)
        if "clock" in scene:
            self._alarm(cv, tick)
        self._blossoms(cv, tick)
        # the work on the card over the hive
        if state == "writing":
            self._scroll(cv, tick)
        elif state == "done":
            self._jar(cv, tick)
        elif state == "error":
            self._jar(cv, tick, spilt=True)
        elif kind == "helpers":
            self._workers(cv, tick)
        elif kind:
            getattr(self, "_prop_" + kind)(cv, tick)
        self._hum(cv, state, tick, kind, mood, scene, fidget)
        if "music" in scene or state == "done":
            self._notes(cv, tick)
        if "party" in scene:
            self._confetti(cv, tick)
        if scene & {"rain", "storm", "snow"}:
            self._falling(cv, tick, scene)
        return cv

    def _fidget(self, tick, mood):
        """One fidget per 90-tick round, in its last 14 ticks, picked by the
        round's noise from what the mood favours; None otherwise."""
        if tick % 90 < 76:
            return None
        table = FIDGETS.get(mood, FIDGETS["calm"])
        pick = lcg(347, tick // 90)() * sum(w for _, w in table)
        for name, weight in table:
            pick -= weight
            if pick < 0:
                return None if name == "rest" else name
        return None

    # -- the stage ---------------------------------------------------------------------

    def _sky(self, cv, scene):
        p = self.PAL
        tint = p["sky_night"] if "night" in scene else p["sky"]
        for y, bg in enumerate(tint):
            cv.fill(0, y, self.cols, 1, bg, occupy=False)
        if "fog" in scene:
            for y in range(2, self.ground - 1, 3):
                for x in range(self.cols):
                    if (x + y * 3) % 7 < 3:
                        cv.cell(x, y, "~", p["fog"])

    def _weather_sky(self, cv, tick, scene):
        p = self.PAL
        right = self.cols - 3
        if "night" in scene:
            for x, y, period, phase in self._stars:
                if (tick + phase) % period < period - 3 and cv.get(x, y) == " ":
                    cv.cell(x, y, "✦" if (x + y) % 3 else "⋆", p["star"])
            cv.put(right - 1, 0, "(", p["moon"])
            cv.put(right - 1, 1, "(", p["moon"])
        elif ("day" in scene or "sun" in scene) and not scene & OVERCAST:
            cv.cell(right, 0, "☼", p["sun"])
            if "sun" in scene:
                cv.put(right - 2, 0, "-", p["sun"])
                cv.cell(right - 1, 1, "/", p["sun"])
                cv.cell(right, 1, "|", p["sun"])
                cv.cell(right + 1, 1, "\\", p["sun"])
        if scene & {"cloud", "rain", "storm"}:
            for i, x0 in enumerate((self.cx + 4, self.cx + self.cols // 2, self.cols - 14)):
                x = (x0 + tick // (12 + 4 * i)) % max(1, self.cols - 6)
                cv.put(x, i % 2, "(~~~)", p["cloud"], bg=p["cloud_bg"])
        if "storm" in scene and tick % 47 in (0, 1, 2):
            x = self.hx + HW // 2 + (tick // 47) % 7 - 3
            for i, ch in enumerate("/\\/"):
                cv.cell(x + (1 if i == 1 else 0), 2 + i, ch, p["flash"])

    def _falling(self, cv, tick, scene):
        p = self.PAL
        snow = "snow" in scene
        n = max(6, self.cols * self.rows // (60 if snow else 40))
        for i in range(n):
            r = lcg(353, i)
            x0, speed = int(r() * self.cols), 1 + int(r() * 2)
            y = (int(r() * self.ground) + tick // (3 if snow else 1) * speed) % max(1, self.ground)
            x = x0 + ((tick // 6 + i) % 3 - 1 if snow else 0)
            if cv.get(x, y) == " ":
                cv.cell(x, y, "*" if snow else ("'" if i % 2 else ","), p["snow"] if snow else p["rain"])

    def _meadow(self, cv, tick, scene):
        p = self.PAL
        y = self.ground
        cv.fill(0, y, self.cols, 1, p["grass_bg"], occupy=False)
        for x in range(self.cols):
            v = self._grass[x]
            if v < 0.35:
                sway = (tick // 9 + x) % 5 == 0
                cv.cell(x, y, ("/" if sway else ",") if v < 0.2 else ("'" if v < 0.28 else "\""), p["grass"])
        for yy in range(y + 1, self.rows):
            cv.fill(0, yy, self.cols, 1, p["soil_bg"], occupy=False)
            for x in range(self.cols):
                if self._grass[(x * 7) % self.cols] < 0.12:
                    cv.cell(x, yy, ".", p["soil"])
        if "hot" in scene:
            for x in range(self.cols):
                if (x + tick // 3) % 6 == 0:
                    cv.cell(x, y - 1, "~", p["dim"])

    def _tree(self, cv, scene):
        """A rounded canopy over a trunk, blossoms (never fruit)."""
        p = self.PAL
        x, base = self.tx, self.ground - 1
        top = max(2, base - 8)
        canopy = (" .-~~~~-.  ",
                  "(  ✿   ✿ ) ",
                  "( ✿  ✿   ✿)",
                  "(✿   ✿  ✿ )",
                  " `-.__.-'  ")
        snowy = "snow" in scene
        for i, row in enumerate(canopy):
            yy = top + i
            first, last = len(row) - len(row.lstrip()), len(row.rstrip())
            for j in range(first, last):
                ch = row[j]
                # the edge rows are outline only; the middle ones leafy inside
                bg = p["leaf_bg"] if 0 < i < len(canopy) - 1 else None
                if ch == "✿":
                    cv.cell(x + j, yy, ch, p["blossom"], bg=p["leaf_bg"])
                elif ch == " ":
                    if bg:
                        cv.cell(x + j, yy, " ", None, bg=bg)
                else:
                    cv.cell(x + j, yy, ch, p["leaf"], bg=bg)
        if snowy:
            cv.put(x + 1, top - 1, "_.---._", p["snow"], bg=p["snow_bg"])
        for yy in range(top + len(canopy), base + 1):
            cv.put(x + 4, yy, "||", p["trunk"])
        cv.put(x + 3, base, "/||\\", p["trunk"])

    def _hive(self, cv, tick, scene):
        """A straw skep in honey stripes, the door at the bottom."""
        p = self.PAL
        x, base = self.rx + 1, self.ground - 1
        rows = ("  _...._  ",
                " /======\\ ",
                "|========|",
                "|===()===|",
                "'--------'")
        top = base - len(rows) + 1
        for i, row in enumerate(rows):
            yy = top + i
            for j, ch in enumerate(row):
                if ch == " ":
                    continue
                if ch == "=":
                    cv.cell(x + j, yy, "=" if (j + i) % 2 else "-", p["hive"], bg=p["hive_bg"])
                elif ch in "()":
                    cv.cell(x + j, yy, ch, p["hive"], bg=p["door_bg"])
                else:
                    cv.cell(x + j, yy, ch, p["hive"])
        if "snow" in scene:
            cv.put(x + 2, top - 1, "_.--._", p["snow"], bg=p["snow_bg"])
        self.card_x, self.card_y = self.rx, max(0, top - 6)

    def _blossoms(self, cv, tick):
        """The two flowers he flies between, at the ends of his air."""
        p = self.PAL
        y = self.ground - 1
        for x in (self.hx + 1, self.hx + HW - 2):
            cv.cell(x, y - 1, "✿", p["blossom"])
            cv.cell(x, y, "|", p["grass"])
            cv.cell(x - 1, y, "\\" if (tick // 20) % 2 else ",", p["grass"])

    # -- Hum -------------------------------------------------------------------------------

    def _hum(self, cv, state, tick, kind, mood, scene, fidget):
        p = self.PAL
        y = self.base_y
        # hover bob: a row up and down every ~1.6 s (sleepy: settled)
        if mood != "sleepy" or state != "idle":
            beat = 4 if "music" in scene else 8
            y += 1 if (tick // beat) % 2 else 0
        x = self.hx + (HW - BW) // 2
        if state == "thinking":
            # flower to flower and back: 6 s a round trip, eased at each end
            span = HW - BW
            t = (tick % 60) / 60.0
            x = self.hx + int(round(span * (0.5 - 0.5 * math.cos(2 * math.pi * t))))
        elif state in ("tool", "writing", "done", "error"):
            x = self.hx + HW - BW               # over by the hive, at work
        elif fidget == "loop":
            x += (-1, 0, 1, 0)[(tick // 3) % 4]
            y += (0, -1, 0, 1)[(tick // 3) % 4] if y > 1 else 0
        y = max(1, min(y, self.ground - BH))

        face = MOOD_FACE.get(mood, MOOD_FACE["calm"])
        work = state != "idle"
        if work:
            face = {"thinking": ("o", "o", "-"), "tool": ("o", "o", "_"), "writing": ("-", "-", "_"),
                    "done": ("^", "^", "w"), "error": ("x", "x", "o")}[state]
        if state == "idle" and mood not in ("sleepy",) and blink(tick):
            face = ("-", "-", face[2])
        if fidget == "look" and mood != "sleepy":
            face = (face[0], face[1], face[2]) if (tick // 4) % 2 else (face[1], face[0], face[2])

        antennae = ANTENNAE.get(mood, "up") if not work else ("droop" if state == "error" else "up")
        if fidget == "twitch" and (tick // 2) % 2:
            antennae = "perk"
        a = p["line"]
        if antennae == "droop":
            cv.put(x + 2, y + 1, "~", a)
            cv.put(x + 10, y + 1, "~", a)
            cv.put(x + 3, y + 1, "\\", a)
            cv.put(x + 9, y + 1, "/", a)
        else:
            tip = "*" if antennae == "perk" else "o"
            cv.cell(x + 2, y, tip, a)
            cv.cell(x + 10, y, tip, a)
            cv.cell(x + 3, y + 1, "\\", a)
            cv.cell(x + 9, y + 1, "/", a)
        # head / body, outline then the amber inside
        body = (("   .-~~~-.   ", None),
                ("  (e     e)  ", "head"),
                ("  (   m   )  ", "head"),
                ("  (=======)  ", "stripe"),
                ("  (       )@ ", "body"),
                ("   `=====´   ", "stripe_end"))
        for i, (row, role) in enumerate(body):
            yy = y + 2 + i
            for j, ch in enumerate(row):
                xx = x + j
                inner = 2 < j < 10
                if role is None:
                    if ch != " ":
                        cv.cell(xx, yy, ch, a)
                    continue
                if role == "stripe_end":
                    if j == 3:
                        cv.cell(xx, yy, "`", a)
                    elif 3 < j < 9:
                        cv.cell(xx, yy, "=", p["stripe"], bg=p["stripe_bg"])
                    elif j == 9:
                        cv.cell(xx, yy, "'", a)
                    continue
                if ch in "()":
                    cv.cell(xx, yy, ch, a)
                elif ch == "@":
                    carry = CARRY.get(kind, "@") if kind else "@"
                    cv.cell(xx, yy, carry, p["satchel"])
                elif inner and role == "stripe":
                    cv.cell(xx, yy, "=", p["stripe"], bg=p["stripe_bg"])
                elif inner:
                    glyph = " "
                    if ch == "e":
                        glyph = face[0] if j < 6 else face[1]
                    elif ch == "m":
                        glyph = face[2]
                    cv.cell(xx, yy, glyph, p["eye"], bg=p["body"])
                    if glyph == " ":
                        cv.fill(xx, yy, 1, 1, p["body"])
        # the eyes sit at j=3 and j=9 in the pattern: move them inside
        ey = y + 3
        cv.cell(x + 3, ey, " ", None, bg=p["body"])
        cv.cell(x + 9, ey, " ", None, bg=p["body"])
        cv.cell(x + 4, ey, face[0], p["eye"], bg=p["body"])
        cv.cell(x + 8, ey, face[1], p["eye"], bg=p["body"])
        if mood == "shy" and state == "idle":
            cv.cell(x + 3, y + 4, " ", None, bg=p["blush"])
            cv.cell(x + 9, y + 4, " ", None, bg=p["blush"])
        # wings: two cells each side, a row up then down with the beat
        speed = WING_BEAT.get(mood, 3) if not work else (1 if state in ("thinking", "tool") else 2)
        if state == "error":
            speed = 0
        up = speed and (tick // speed) % 2 == 0
        wy = y + (2 if up else 3)
        if not speed:
            wy = y + 4                          # folded along his sides
        for i in range(2):
            cv.cell(x, wy + i, "(" if i == 0 else "(", p["wing"], bg=p["wing_bg"])
            cv.cell(x + 1, wy + i, "~" if i == 0 else "_", p["wing"], bg=p["wing_bg"])
            cv.cell(x + 11, wy + i, "~" if i == 0 else "_", p["wing"], bg=p["wing_bg"])
            cv.cell(x + 12, wy + i, ")", p["wing"], bg=p["wing_bg"])
        # accents
        hx, hy = x + 11, max(0, y - 1)
        self.head = (min(hx, self.cols - 1), hy)
        if mood == "sleepy" and state == "idle":
            z = (tick // 8) % 3
            cv.put(x + 11, max(0, y + 1 - z), "z" if z < 2 else "Z", p["dim"])
        if mood == "curious" and state == "idle":
            cv.cell(x + 11, y, "?", p["accent"])
        if mood == "excited" and (tick // 3) % 2:
            cv.cell(x + 12, y + 1, "✦", p["warn"])
        if mood == "worried" or "hot" in scene or state == "error":
            cv.cell(x + 10, y + 2, "'", p["sweat"])
        if state == "thinking":
            dots = "." * (1 + (tick // 5) % 3)
            cv.put(x + 11, y + 1, dots, p["dim"])
        if state == "error":
            cv.cell(x + 12, y + 1, "!", p["bad"])
        if "cold" in scene:
            cv.put(x + 3, y + 5, "~~~~~~~", p["scarf"], bg=p["scarf_bg"])
            if (tick // 6) % 3 == 0:
                cv.cell(x + 1, y + 4, "o", p["dim"])
        if "party" in scene:
            cv.cell(x + 5, y + 1, "/", p["hat"], bg=p["hat_bg"])
            cv.cell(x + 6, y + 0, "*", p["warn"])
            cv.cell(x + 6, y + 1, "^", p["hat"], bg=p["hat_bg"])
            cv.cell(x + 7, y + 1, "\\", p["hat"], bg=p["hat_bg"])
        if "game" in scene and state == "idle":
            cv.put(x + 4, y + 8, "[=o]", p["game"], bg=p["game_bg"])

    # -- the work, on a card over the hive -------------------------------------------------

    def _card(self, cv, w=10, h=4):
        """A small light card with a hairline: the work's table."""
        p = self.PAL
        x, y = self.card_x + 1, self.card_y
        cv.fill(x, y, w, h, p["card_bg"])
        cv.put(x, y, "." + "-" * (w - 2) + ".", p["card_dim"], bg=p["card_bg"])
        cv.put(x, y + h - 1, "'" + "-" * (w - 2) + "'", p["card_dim"], bg=p["card_bg"])
        for yy in range(y + 1, y + h - 1):
            cv.cell(x, yy, "|", p["card_dim"], bg=p["card_bg"])
            cv.cell(x + w - 1, yy, "|", p["card_dim"], bg=p["card_bg"])
        return x, y

    def _prop_bash(self, cv, tick):
        p = self.PAL
        x, y = self.card_x + 1, self.card_y
        cv.fill(x, y, 10, 4, p["term_bg"])
        cv.put(x + 1, y, "o o o", p["card_dim"], bg=p["term_bg"])
        cmd = CMDS[(tick // 25) % len(CMDS)]
        n = min(len(cmd), (tick % 25) // 2 + 1)
        cv.put(x + 1, y + 1, cmd[:n].ljust(8)[:8], p["term"], bg=p["term_bg"])
        cv.put(x + 1, y + 2, ">", p["term_ok"], bg=p["term_bg"])
        if (tick // 4) % 2:
            cv.cell(x + 2, y + 2, "_", p["term"], bg=p["term_bg"])

    def _prop_book(self, cv, tick):
        p = self.PAL
        x, y = self._card(cv)
        page = (tick // 12) % 3
        for i in range(2):
            cv.put(x + 1, y + 1 + i, ("~~~ ", "~~  ", "~ ~ ")[(page + i) % 3], p["card"], bg=p["card_bg"])
            cv.put(x + 5, y + 1 + i, ("~~~", " ~~", "~~ ")[(page + i + 1) % 3], p["card"], bg=p["card_bg"])
        cv.cell(x + 4, y + 1, "|", p["card_dim"], bg=p["card_bg"])
        cv.cell(x + 4, y + 2, "|", p["card_dim"], bg=p["card_bg"])

    def _prop_pad(self, cv, tick):
        p = self.PAL
        x, y = self._card(cv)
        n = (tick // 3) % 14
        line1 = "~~~~~~"[:min(6, n)]
        line2 = "~~~~"[:max(0, min(4, n - 6))]
        cv.put(x + 1, y + 1, line1.ljust(7), p["card"], bg=p["card_bg"])
        cv.put(x + 1, y + 2, line2.ljust(7), p["card"], bg=p["card_bg"])
        px = x + 1 + (len(line1) if n < 6 else len(line2))
        py = y + 1 if n < 6 else y + 2
        cv.cell(px, py, "/", p["warn"], bg=p["card_bg"])

    def _prop_lens(self, cv, tick):
        p = self.PAL
        x, y = self._card(cv)
        cv.put(x + 1, y + 2, "✿ ✿ ✿ ✿", p["blossom"], bg=p["card_bg"])
        lx = x + 1 + (tick // 4) % 6
        cv.put(lx, y + 1, "O-", p["card"], bg=p["card_bg"])

    def _prop_globe(self, cv, tick):
        p = self.PAL
        x, y = self._card(cv)
        cv.put(x + 3, y + 1, ("(@)", "(#)", "(%)")[(tick // 5) % 3], p["accent"], bg=p["card_bg"])
        waves = ")" * (1 + (tick // 4) % 3)
        cv.put(x + 6, y + 1, waves.ljust(3), p["card_dim"], bg=p["card_bg"])
        cv.put(x + 1, y + 2, "........"[: 1 + (tick // 2) % 8].ljust(8), p["good"], bg=p["card_bg"])

    def _prop_todo(self, cv, tick):
        p = self.PAL
        x, y = self._card(cv, 11, 5)
        done = (tick // 15) % 4
        for i, item in enumerate(("nectar", "pollen", "honey")):
            mark = "x" if i < done else " "
            cv.put(x + 1, y + 1 + i, f"[{mark}]{item}"[:9], p["card"], bg=p["card_bg"])
            if mark == "x":
                cv.cell(x + 2, y + 1 + i, "x", p["good"], bg=p["card_bg"])

    def _prop_wand(self, cv, tick):
        p = self.PAL
        x, y = self.card_x + 1, self.card_y
        for i in range(6):
            r = lcg(359, i, tick // 6)
            cv.cell(x + int(r() * 10), y + int(r() * 4), "✦⋆*"[i % 3], (p["warn"], p["accent"], p["blossom"])[i % 3])

    def _workers(self, cv, tick):
        """Task / Agent: two worker bees leave the hive on errands."""
        p = self.PAL
        door_x, door_y = self.rx + 5, self.ground - 2
        for j in range(2):
            s = (tick + j * 17) % 34
            x = door_x + (s // 2 if j else -(s // 3))
            y = door_y - 1 - s // 6
            if 0 <= y:
                cv.put(x, y, "~8>" if j else "<8~", p["line"])
                cv.cell(x + 1, y, "8", p["stripe_bg"], bg=p["body"])

    def _scroll(self, cv, tick):
        """Writing: a leaf-scroll filling with words."""
        p = self.PAL
        x, y = self._card(cv, 10, 4)
        n = len(self._stream)
        top = (tick // 6) % max(1, n - 1)
        for i in range(2):
            cv.put(x + 1, y + 1 + i, self._stream[(top + i) % n][:8], p["card"], bg=p["card_bg"])

    def _jar(self, cv, tick, spilt=False):
        """Done: a jar of honey (sparkles); error: the jar tipped over."""
        p = self.PAL
        x, y = self.card_x + 3, self.card_y
        if spilt:
            cv.put(x - 1, y + 2, "\\___/", p["line"])
            cv.put(x - 1, y + 3, " ~~~~~", p["honey"], bg=p["honey_bg"])
            cv.cell(x + 5, y + 1, "!", p["bad"])
            return
        cv.put(x, y, "[___]", p["line"])
        cv.put(x, y + 1, "|", p["line"])
        cv.put(x + 1, y + 1, "~~~", p["honey"], bg=p["honey_bg"])
        cv.put(x + 4, y + 1, "|", p["line"])
        cv.put(x, y + 2, "|", p["line"])
        cv.put(x + 1, y + 2, "   ", None, bg=p["honey_bg"])
        cv.put(x + 4, y + 2, "|", p["line"])
        cv.put(x, y + 3, "`---'", p["line"])
        for i in range(3):
            if (tick // 4 + i) % 3 == 0:
                cv.cell(x - 1 + i * 3, max(0, y - 1), "✦", (p["warn"], p["accent"], p["good"])[i])

    def _alarm(self, cv, tick):
        """clock: a little alarm clock on the hive, ringing."""
        p = self.PAL
        x, y = self.rx + 4, self.ground - 6
        cv.put(x, y, "(:)", p["line"], bg=p["card_bg"])
        if (tick // 3) % 2:
            cv.cell(x - 1, y, "!", p["bad"])
            cv.cell(x + 3, y, "!", p["bad"])

    def _lights(self, cv, tick):
        p = self.PAL
        for x in range(self.cols):
            if x % 4 == 1:
                cv.cell(x, 0, "o", p["bulbs"][((x // 4) + tick // 6) % len(p["bulbs"])])
            elif cv.get(x, 0) == " ":
                cv.cell(x, 0, "-", p["dim"])

    def _notes(self, cv, tick):
        p = self.PAL
        x0, y0 = self.hx + 3, self.base_y + 2
        for j in range(2):
            s = (tick + j * 11) % 22
            if s < 14:
                y = y0 - s // 5
                x = x0 + j * 13 + (1 if (s // 4) % 2 else 0)
                if 0 <= y and cv.get(x, y) == " ":
                    cv.cell(x, y, "♫", p["notes"][j])

    def _confetti(self, cv, tick):
        p = self.PAL
        for i in range(max(4, self.cols * self.rows // 140)):
            r = lcg(367, i)
            x = int(r() * self.cols)
            y = (int(r() * self.ground) + tick // 3) % max(1, self.ground)
            if cv.get(x, y) == " ":
                cv.cell(x, y, "*+'"[i % 3], p["confetti"][i % len(p["confetti"])])


if __name__ == "__main__":
    import mascots
    mascots.main(sys.argv[1:], default_theme=THEME)
