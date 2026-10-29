#!/usr/bin/env python3
"""The lofi theme's mascot: Miso, a sleepy ginger cat on a cushion in a cosy
room at night -- a rainy window on the left, a little desk with a lamp on
the right, a record player on the floor. Same API as moe_mascot.Mascot
(mascots.py picks it).

    room      the back wall (#241e3a, a shade above the stage's #1c1830 in
              themes/lofi/llm-chat.css), a darker floor row with boards
    window    13 x 7 cells on the left: a frame and cross muntins in plum,
              the sky inside painted as cell backgrounds (dusk by default,
              night, a pale dusk by day, grey when overcast), a skyline with
              a few lit windows along its bottom, and the weather on the
              glass: stars and a crescent, rain streaks, snow, fog, cloud, a
              lightning flash
    Miso      18 x 6..9 cells in the middle, a tabby loaf: ears, green eyes,
              a pink nose, whiskers, flank stripes, a tail that curls and
              flicks, a lilac cushion under her. Idle she breathes (the head
              rises one row every two seconds); at work she sits up and
              reaches a paw over to the desk
    desk      15 cells on the right, a lamp at its end (its glow is a few
              #4a3628 cell backgrounds, never a large area), a shelf above
              it (books and a plant; the alarm clock in the clock scene), and
              the work on its top: a tiny CRT with a blinking _ for Bash, an
              open book (paw on the page) for Read, a notebook and pencil
              scribbles for Edit/Write, a magnifier sliding over a page for
              the searches, a radio sending ((~)) waves for WebFetch, two
              kittens peeking (one by the record player, one under the desk)
              for Task/Agent, sticky notes being ticked for TodoWrite, a ball
              of yarn unrolling otherwise. Thinking is a cassette whose reels
              turn, writing a notebook filling up over a mini keyboard, done a
              steaming mug (and the record spinning, notes rising), an error a
              tipped mug and a puffed-up cat with flat ears and a berry "!"
    floor     the record player under the window (it spins in the music
              scene and when a job is done), and a slot beside it for a kitten
              or a fan; on a wide stage a crate of records and a plant

  mood      one of mascot_mood.MOODS. Idle, it is her whole face and pose:
              calm is a content loaf with sleepy eyes and a slow z, happy ^ ^
              and a purr ~, excited wide eyes, her tail up and a twinkle,
              shy a paw over her face and a blush, curious a head tilt and a
              "?", focused headphones and narrowed eyes, worried ears back
              and a sweat drop, sad a droop (and heavier rain on the window),
              sleepy fast asleep with Zz. At work only the accents show
              (headphones, purr, twinkle, blush, sweat, the "?") over the
              work face; sleepy works focused. The idle fidget at the end of
              each 9-second round (a tail flick, an ear twitch, a look round,
              a yawn, washing a paw) is picked by the noise and weighted by
              the mood.
  scene     a set of mascot_mood.SCENES: day (a pale dusk window, the lamp
              off), night (stars and a crescent, the lamp on), sun (a warm sky
              and a warm beam across the room), cloud, rain (streaks on the
              glass), storm (and a flash in the window), snow (flakes, snow on
              the sill), fog, hot (idle she sprawls out flat; a fan on the
              floor), cold (a blanket over her, breath puffs), music (the
              record spins, notes rise), game (a handheld in her paws, idle),
              party (a party hat, a little confetti), festive (string lights
              along the top), clock (an alarm clock on the shelf, ringing).

Dusky violets and a warm ginger; the light cells are small (eyes, the lamp
shade, a few lit windows). Every glyph is single-column (mascot_common.dw).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import STATES, BaseMascot, Canvas, blink, lcg, prop_kind, stream_lines  # noqa: E402
from mascot_mood import MOODS, word  # noqa: E402

THEME = "lofi"
PANEL = "#1c1830"

# the room
WALL = "#241e3a"
FLOOR_MARK = "#2e2648"
FRAME = "#3a2f55"
BEAM = "#2e2440"           # the sun's beam: a wall cell a touch warmer
DESK = "#3a2a3a"
DESK_EDGE = "#7a6070"
SHELF = "#33263a"
LAMP_GLOW = "#4a3628"
SCREEN = "#141128"
CUSHION = "#3a2f55"
BLANKET = "#33284a"
BLANKET_MARK = "#7d7392"
# Miso
FUR = "#e8a470"
STRIPE = "#b8744c"
EYE = "#a6d6a0"
NOSE = "#f4a3b0"
BLUSH = "#f58a98"
WHISKER = "#bfaebf"
KITTEN = ("#c3b8d0", "#e8c49a")
# words, props and accents
TEXT = "#e8dccb"
TEXT_HI = "#f3e9dc"
DIM = "#bfaebf"
HAZE = "#a091aa"
PEACH = "#f2a477"
PEACH_LT = "#f6b48c"
LILAC = "#b9a3ea"
RAIN = "#8fbfe0"
TEAL = "#84cbc8"
SAGE = "#a6d6a0"
HONEY = "#e8d77a"
BERRY = "#f58a98"
YARN = "#f4a3b0"
LEAF = "#86b088"
SNOW = "#eae4f2"
STAR = "#d6c8ff"
STAR_DIM = "#6a6090"
MOON = "#f2d49a"
SUN = "#f0b080"
CLOUD = "#8a80a6"
FLASH = "#8a80a6"
LIT = ("#f2b88a", "#e8c49a")       # lit windows in the skyline
BUILDING = "#1a1428"
NOTE_BG = ("#4a4030", "#4a3040", "#30404a")   # sticky notes, dimmed pastels
SLEEVES = ("#f2a477", "#b9a3ea", "#8fbfe0", "#a6d6a0", "#f58a98", "#e8d77a")
BULBS = ("#f2a477", "#e8d77a", "#b9a3ea", "#8fbfe0", "#84cbc8", "#f4a3b0")
CONFETTI = ("#f2a477", "#b9a3ea", "#8fbfe0", "#e8d77a", "#f4a3b0")
# The reaction sign over her head (mascot_mood.EMOTE_TONES): >= 3.8:1 on the
# panel, the wall, the sunbeam, the shelf and the lamp glow.
EMOTE_COLOURS = {"accent": PEACH, "warn": HONEY, "bad": BERRY, "good": SAGE,
                 "love": YARN, "dim": HAZE}
# the window's sky, one colour per inner row (top first)
SKY = {
    "dusk": ("#2a2348", "#33284f", "#3e2d56", "#4e3458", "#5e3c5a"),
    "night": ("#120f24", "#151229", "#18142e", "#1c1733", "#211a38"),
    "day": ("#4a3d64", "#544469", "#5e4a6c", "#6e526e", "#7e5a6c"),
    "sun": ("#4e4064", "#644a68", "#7a5468", "#8e5e66", "#9a6866"),
    "grey": ("#2e2a40", "#332e45", "#38324a", "#3d364e", "#423a52"),
    "grey_night": ("#18162a", "#1b182e", "#1e1b32", "#211d35", "#241f38"),
}
FOG_BG = "#3e3854"
OVERCAST = frozenset(("cloud", "rain", "storm", "snow", "fog"))

WW, WH = 13, 7      # the window, frame included
CW = 18             # Miso: 17 cells of cat and a column for the tail
DW = 15             # the desk: 10 cells of work, 5 of lamp
COMP_W = WW + 1 + CW + 1 + DW       # 48: the smallest stage, exactly

WORDS = ("the", "rain", "is", "soft", "and", "warm", "tea", "on", "a", "slow",
         "night", "so", "it", "works", "now", "all", "good", "here", "page", "done")
SCRIBBLES = ("~~", "~", "~~~", "-~", "~-~", "~~-")
CMDS = ("ls", "cd ~", "make", "git st", "cat", "ping")

# Ears, the head's top row: cells 3..13 of the cat, the head centred on 8.
EARS = {
    "up": "/\\_,,,_/\\",
    "twitch": "/'_,,,_/\\",
    "back": "'\\_,,,_/'",
    "flat": "_-._,,,_.-_",
}
# Per mood, idle: (left eye, right eye, mouth). calm: sleepy-content eyes.
MOOD_FACE = {
    "calm": ("ᵕ", "ᵕ", "ᴥ"),
    "happy": ("^", "^", "ᴥ"),
    "excited": ("O", "O", "ᴥ"),
    "shy": ("o", "o", "ᴥ"),
    "curious": ("o", "O", "ᴥ"),
    "focused": ("-", "-", "ᴥ"),
    "worried": ("o", "o", "~"),
    "sad": (";", ";", "ᴥ"),
    "sleepy": ("-", "-", "ᴥ"),
}
# The idle fidget a mood favours: (name, weight); "rest" is none at all.
FIDGETS = {
    "calm": (("tail", 3), ("ear", 2), ("look", 1), ("wash", 1), ("rest", 2)),
    "happy": (("tail", 3), ("wash", 2), ("ear", 1)),
    "excited": (("tail", 3), ("look", 2), ("ear", 2)),
    "shy": (("ear", 2), ("rest", 3)),
    "curious": (("look", 4), ("ear", 2)),
    "focused": (("rest", 3), ("ear", 1)),
    "worried": (("look", 3), ("ear", 2)),
    "sad": (("rest", 2), ("tail", 1)),
    "sleepy": (("yawn", 2), ("rest", 3), ("ear", 1)),
}

MOOD_BUBBLES = {
    "calm": "mrrp… lo-fi beats and you. what's up?",
    "happy": "purr~ everything's cosy. what's next?",
    "excited": "mrrp! ooh, let's make something!",
    "shy": "oh… you saw me nap. hi ☺",
    "curious": "hm? what's that? tell me more…",
    "focused": "headphones on. ready when you are.",
    "worried": "mrow… something feel off?",
    "sad": "rainy kind of day… stay a while?",
    "sleepy": "zz… five more minutes…",
}
# mascot_mood topics in her words (str.format with the topic's arguments).
TOPIC_LINES = {
    "thanks": "purr~ anytime.",
    "worried": "mrow… that doesn't look right.",
    "frustrated": "again? deep breath, one more go…",
    "relieved": "phew. back to the beats ~",
    "determined": "long one. i'll keep the tea warm…",
    "proud": "all done, and nicely too ~",
    "sad": "sorry… *ears down*",
    "happy": "purr~",
    "curious": "ooh, interesting…",
    "rain": "rain on the window… perfect study weather.",
    "storm": "a storm… let's stay in where it's warm.",
    "snow": "snow outside. blanket time ❄",
    "fog": "foggy out. slow day, slow tea.",
    "sun": "a warm sunbeam… i call dibs.",
    "hot": "it's {0}… i'm melting into the cushion.",
    "cold": "brr, {0} out. under the blanket we go.",
    "gpu_hot": "the GPU's toasty: {0}°C. warm enough to nap on.",
    "cpu_hot": "the CPU's at {0}°C… give it a breather?",
    "music": "ooh, this one's a vibe ♫",
    "game": "game time? i'll watch ~",
    "event": "mrrp, {0} in {1} min.",
    "event_now": "{0} is starting now!",
    "birthday": "happy birthday, {0}! ♫",
    "holiday": "it's {0} today ~",
    "go_home": "it's {0}. time to log off and rest.",
    "bedtime": "it's {0}… the lamp says bedtime.",
    "morning": "mrrp… good morning. coffee first.",
    "lunch": "lunch? i heard fish.",
    "weekend": "it's the weekend. nap o'clock ~",
    "friday": "friday afternoon… the week winds down ~",
    # conversation and stage events (tuples rotate: a new one each time)
    "hello": ("mrrp, hi ~ what are we making?", "oh, hello. the tea's on ~",
              "hey you. cosy session?"),
    "welcome_back": "you're back ~ i kept the cushion warm.",
    "wake": "mrr…? oh, i'm up. mostly ~",
    "long_prompt": ("that's a long one… i'll get comfy.", "lots to read ~ more tea, then."),
    "code": "code ~ let me pad over and look.",
    "image": "ooh, a picture. let me see ~",
    "aborted": "okay, stopping ~",
    "tests_pass": ("tests are green ~ purr.", "all passing. tea break?",
                   "green lights ~ nice and calm."),
    "tests_fail": ("tests failed… we'll fix it ~", "red ones… one more listen."),
    "commit": ("committed ~ off it goes.", "shipped. a quiet little win ~",
               "pushed ~ time to stretch."),
    "fast": ("quick one ~", "done before the kettle boiled.", "that was fast ~ back to napping."),
    "busy": ("busy paws today…", "so many tools… i'll keep up ~"),
    "model": "a new voice on the radio: {0} ~",
    "poke": ("mrrp?", "hm? oh, hi ~", "*tail flick*", "you rang? ~",
             "boop ~ right back at you.", "mrow, i was almost asleep…"),
    "poke_spam": ("mrow! paws off, please ~", "okay okay, i'm awake! ~",
                  "*hiss*… kidding. but stop it ~"),
    "pet": ("purrrr~", "*kneads the cushion* ~", "mm, right behind the ears ~",
            "slow blink ~ that means i like you."),
    # railguard.py's notifications (mascot_notify.py says them, voice on)
    "rg_memory": "{0} ate all the memory… I nudged it off the shelf.",
    "rg_vram": "{0} hogged the GPU. pawed it away ~",
    "rg_game_vram": "{0} is filling the GPU… maybe lower the textures?",
    "rg_panic": "mrrp. {0} is gone. back to the beats ~",
    "rg_stuck": "mrow… memory's almost gone and I can't find who did it.",
    "rg_agents": "all the agents' jobs stopped. the sessions are still napping safely.",
}


class Mascot(BaseMascot):
    BUBBLES = {
        "idle": "mrrp… lo-fi beats and you. what's up?",
        "thinking": "hmm… let me think on that, slowly",
        "writing": "scribbling it down…",
        "done": "all done ~ time for tea",
        "error": "mrow?! that didn't work. try again?",
    }
    TOOL_BUBBLES = {
        "Bash": "tapping the terminal…",
        "Read": "reading, paws on the page…",
        "Edit": "a little edit…",
        "MultiEdit": "a little edit…",
        "Write": "writing it down…",
        "NotebookEdit": "tidying the notebook…",
        "Grep": "sniffing around…",
        "Glob": "pawing through files…",
        "WebSearch": "tuning the radio…",
        "WebFetch": "fetching it…",
        "Task": "calling the kittens…",
        "Agent": "calling the kittens…",
        "TodoWrite": "sticky notes…",
    }
    OTHER = "batting at %s…"
    moods = True

    def __init__(self, cols=64, rows=18):
        self.cols = max(int(cols), COMP_W)
        self.rows = max(int(rows), 14)
        # a wider stage spreads the three a little apart (up to 4 cells)
        g = max(0, min(4, (self.cols - COMP_W) // 8))
        comp = COMP_W + 2 * g
        self.cx = (self.cols - comp) // 2
        self.right = self.cx + comp            # one past the desk
        self.wx = self.cx
        self.kx = self.wx + WW + 1 + g         # Miso's left edge
        self.dx = self.kx + CW + 1 + g         # the desk's left edge
        self.floor = self.rows - 2             # the cushion's row; under it the floor
        self.wy = max(1, self.floor - 11)      # the window's top
        self.py = self.floor - 8               # the top of the work area over the desk
        self._stream = stream_lines(WORDS, 8, seed=67)
        self._scribble = stream_lines(SCRIBBLES, 6, seed=71)
        # the skyline in the window: a height (0..2 rows) per inner column
        self._city = [int(lcg(173, i)() * 3) for i in range(WW)]
        self._lit = [lcg(179, i)() for i in range(WW * 2)]
        self._stars = [(1 + int(lcg(181, i)() * (WW - 2)), 1 + int(lcg(183, i)() * 4),
                        20 + int(lcg(187, i)() * 30), int(lcg(191, i)() * 50)) for i in range(7)]
        self._boards = [lcg(193, x)() for x in range(self.cols)]

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

    # -- composition ---------------------------------------------------------------

    def _render(self, state, tick, tool, mood=None, scene=()):
        if state not in STATES:
            state = "idle"
        if mood not in MOODS:
            mood = "calm"
        if mood == "sleepy" and state in ("thinking", "tool", "writing"):
            mood = "focused"            # she does not doze off on the job
        scene = frozenset(scene or ())
        tick = int(tick)
        cv = Canvas(self.cols, self.rows)
        kind = prop_kind(tool) if state == "tool" else None
        idle = state == "idle"
        fidget = self._fidget(tick, mood) if idle else None
        spinning = "music" in scene or state == "done"

        self._room(cv)
        self._window(cv, tick, mood, scene)
        if "sun" in scene and not scene & OVERCAST:
            self._beam(cv)
        if "festive" in scene:
            self._lights(cv, tick)
        if self.cx >= 8:
            self._decor(cv)
        if self.floor >= 15:
            self._poster(cv)
        self._shelf(cv, tick, "clock" in scene)
        self._desk(cv, lamp="night" in scene or "day" not in scene)
        self._record_player(cv, tick, spinning)
        if kind == "helpers":
            self._kittens(cv, tick)
        elif "hot" in scene:
            self._fan(cv, tick)
        top = self._miso(cv, state, tick, kind, mood, scene, fidget)
        # the work on the desk
        if state == "thinking":
            self._cassette(cv, tick)
        elif state == "writing":
            self._notebook(cv, tick)
        elif state == "done":
            self._mug(cv, tick)
        elif state == "error":
            self._mug(cv, tick, tipped=True)
        elif kind and kind != "helpers":
            getattr(self, "_prop_" + kind)(cv, tick)
        if state in ("tool", "writing") and kind not in ("helpers", "globe", "wand") and top is not None:
            self._reach(cv, tick, top + 3)      # her paw on the work, over it
        if spinning:
            self._notes(cv, tick)
        if "party" in scene:
            self._confetti(cv, tick)
        return cv

    def _fidget(self, tick, mood):
        """The idle fidget now: one per 90-tick round, in its last 18 ticks,
        picked by the round's noise from what the mood favours; None the
        rest of the time (and for "rest")."""
        if tick % 90 < 72:
            return None
        table = FIDGETS.get(mood, FIDGETS["calm"])
        pick = lcg(199, tick // 90)() * sum(w for _, w in table)
        for name, weight in table:
            pick -= weight
            if pick < 0:
                return None if name == "rest" else name
        return None

    # -- the room ----------------------------------------------------------------------

    def _room(self, cv):
        """The back wall down to the cushion's row, the floor under it: a
        darker row with a few board joints."""
        cv.fill(0, 0, self.cols, self.floor + 1, WALL, occupy=False)
        y = self.floor + 1
        for x in range(self.cols):
            v = self._boards[x]
            if v < 0.12:
                cv.cell(x, y, "_" if v < 0.06 else ".", FLOOR_MARK)
        for yy in range(y + 1, self.rows):
            for x in range(self.cols):
                if self._boards[(x * 7 + yy) % self.cols] < 0.08:
                    cv.cell(x, yy, ".", FLOOR_MARK)

    def _beam(self, cv):
        """Sunlight from the window falling across the room: wall cells a
        touch warmer, in a slanting band (behind Miso and the desk)."""
        for y in range(self.wy + WH, self.floor + 1):
            for k in range(3):
                x = self.wx + 6 + (y - self.wy - WH) * 2 + k
                if 0 <= x < self.cols and cv.bg[y][x] == WALL:
                    cv.recolour(x, y, bg=BEAM)

    def _lights(self, cv, tick):
        """String lights along the top row: a cord, a bulb every third cell,
        the colours twinkling in turn."""
        for x in range(self.cols):
            if x % 3 == 1:
                on = (x // 3 + tick // 6) % 4 != 0
                cv.cell(x, 0, "o" if on else "∙", BULBS[(x // 3) % len(BULBS)] if on else HAZE)
            else:
                cv.cell(x, 0, "-", FRAME)

    def _decor(self, cv):
        """A wide stage: a crate of records left of the window, a plant right
        of the desk, both on the floor."""
        x, y = self.cx - 8, self.floor - 2
        for i in range(5):
            cv.cell(x + 1 + i, y, "▐", SLEEVES[i % len(SLEEVES)])
        cv.sprite(x, y + 1, "|=====|", DESK_EDGE)
        cv.sprite(x, y + 2, "|_____|", DESK_EDGE)
        px, y = self.right + 2, self.floor - 3
        if px + 5 <= self.cols:
            cv.sprite(px, y, ",\\|/,", LEAF)
            cv.sprite(px, y + 1, " \\|/ ", LEAF)
            cv.sprite(px, y + 2, ".---.", STRIPE)
            cv.sprite(px, y + 3, "|___|", STRIPE)

    def _poster(self, cv):
        """A tall stage: a little framed print on the wall over Miso, above
        everything she can float (hat, z's, thought dots)."""
        x, y = self.kx + 4, self.floor - 14
        cv.sprite(x, y, ".-------.", FRAME)
        cv.sprite(x, y + 1, "|       |", FRAME)
        cv.sprite(x, y + 2, "'-------'", FRAME)
        cv.cell(x + 2, y + 1, "☾", LILAC)
        cv.cell(x + 4, y + 1, "♫", PEACH_LT)
        cv.cell(x + 6, y + 1, "✦", HONEY)

    # -- the window --------------------------------------------------------------------

    def _window(self, cv, tick, mood, scene):
        x0, y0 = self.wx, self.wy
        overcast = bool(scene & OVERCAST)
        night = "night" in scene
        if overcast:
            sky = SKY["grey_night" if night else "grey"]
        elif night:
            sky = SKY["night"]
        elif "sun" in scene:
            sky = SKY["sun"]
        elif "day" in scene:
            sky = SKY["day"]
        else:
            sky = SKY["dusk"]
        flash = "storm" in scene and tick % 47 < 2
        fog = "fog" in scene
        # the sky, then the skyline along the bottom panes
        for iy in range(1, WH - 1):
            for ix in range(1, WW - 1):
                bg = FLASH if flash else (FOG_BG if fog else sky[iy - 1])
                cv.cell(x0 + ix, y0 + iy, " ", None, bg)
        for ix in range(1, WW - 1):
            h = self._city[ix]
            for k in range(h):
                y = y0 + WH - 2 - k
                cv.recolour(x0 + ix, y, bg=BUILDING)
                lit = self._lit[ix * 2 + k]
                if lit < 0.35 and "day" not in scene and not flash:
                    on = (tick // 40 + ix) % 7 != 0
                    if on:
                        cv.cell(x0 + ix, y, "∙", LIT[k % 2], BUILDING)
        # what is in the sky
        if night and not overcast and not flash:
            for ix, iy, period, ph in self._stars:
                if self._city[ix] >= WH - 1 - iy:
                    continue
                if cv.get(x0 + ix, y0 + iy) != " ":
                    continue
                t = (tick + ph) % period
                cv.cell(x0 + ix, y0 + iy, "+" if t < 3 else ".", STAR if t < 3 else STAR_DIM)
            cv.cell(x0 + 9, y0 + 1, "☾", MOON)
        elif not overcast and not flash and scene & {"sun", "day"}:
            cv.cell(x0 + 3, y0 + 1, "O" if "sun" in scene else "o", SUN)
        if overcast and not fog or "cloud" in scene:
            self._clouds(cv, tick, x0, y0, "storm" in scene)
        rain = scene & {"rain", "storm"}
        if rain or mood == "sad":
            heavy = "storm" in scene or (bool(rain) and mood == "sad")
            self._streaks(cv, tick, x0, y0, 12 if heavy else 6)
        if "snow" in scene:
            self._flakes(cv, tick, x0, y0)
        if fog:
            for iy in (2, 4):
                off = (tick // 8 + iy * 3) % 6
                for ix in range(1, WW - 1):
                    if (ix + off) % 6 < 4:
                        cv.cell(x0 + ix, y0 + iy, "~", HAZE)
        if flash:
            for k, (dx, ch) in enumerate(((8, "/"), (7, "/"), (8, "\\"), (7, "/"))):
                if k < WH - 3:
                    cv.cell(x0 + dx, y0 + 1 + k, ch, TEXT_HI)
        # the frame and the muntins over it all
        cv.put(x0, y0, "." + "-" * (WW - 2) + ".", FRAME)
        for iy in range(1, WH - 1):
            cv.cell(x0, y0 + iy, "|", FRAME)
            cv.cell(x0 + WW - 1, y0 + iy, "|", FRAME)
            cv.cell(x0 + WW // 2, y0 + iy, "+" if iy == 3 else "|", FRAME)
        for ix in range(1, WW - 1):
            if ix != WW // 2:
                cv.cell(x0 + ix, y0 + 3, "-", FRAME)
        cv.put(x0, y0 + WH - 1, "'" + "=" * (WW - 2) + "'", SNOW if "snow" in scene else FRAME)

    def _clouds(self, cv, tick, x0, y0, storm):
        for i, (row, speed) in enumerate(((1, 0.05), (2, 0.035))):
            x = int(lcg(197, i)() * 13 + tick * speed) % (WW + 4) - 3
            for k, ch in enumerate("(~~)"):
                ix = x + k
                if 1 <= ix < WW - 1:
                    cv.cell(x0 + ix, y0 + row, ch, HAZE if storm else CLOUD)

    def _streaks(self, cv, tick, x0, y0, n):
        """Rain on the glass: drops sliding down, drifting a column to the
        left every second row (the 8-12 degree slant of the wallpaper)."""
        for i in range(n):
            r = lcg(211, i)
            pos = r() * 20 + tick * (0.3 + r() * 0.2)
            iy = 1 + int(pos) % (WH - 2)
            ix = 1 + (int(r() * 11) - int(pos) // 2) % (WW - 2)
            if ix == WW // 2 or iy == 3:
                continue
            cv.cell(x0 + ix, y0 + iy, "'" if i % 3 else ",", RAIN)

    def _flakes(self, cv, tick, x0, y0):
        for i in range(6):
            r = lcg(223, i)
            pos = r() * 20 + tick * (0.08 + r() * 0.05)
            iy = 1 + int(pos) % (WH - 2)
            ix = 1 + (int(r() * 11) + (int(pos) // 3) % 2) % (WW - 2)
            if ix == WW // 2 or iy == 3:
                continue
            cv.cell(x0 + ix, y0 + iy, "*."[i % 2], SNOW)

    # -- the desk, the shelf, the floor --------------------------------------------------

    def _desk(self, cv, lamp=True):
        x, top = self.dx, self.floor - 3
        cv.fill(x, top, DW, 1, DESK, ch="=", colour=DESK_EDGE)
        for y in range(top + 1, self.floor + 1):
            cv.cell(x + 1, y, "|", DESK_EDGE)
            cv.cell(x + DW - 2, y, "|", DESK_EDGE)
        cv.put(x + 4, top + 1, "[_o_]", HAZE)
        # the lamp at the end of the desk
        lx, ly = x + 10, top - 4
        shade = PEACH if lamp else HAZE
        cv.sprite(lx, ly, " ___ ", shade)
        cv.sprite(lx, ly + 1, "/___\\", shade)
        cv.sprite(lx, ly + 2, "  |  ", DIM)
        cv.sprite(lx, ly + 3, " _|_ ", DIM)
        if lamp:
            for c in (1, 2, 3):
                cv.recolour(lx + c, ly + 2, bg=LAMP_GLOW)
            for c in range(5):
                cv.recolour(lx + c, top, bg=LAMP_GLOW)

    def _shelf(self, cv, tick, clock=False):
        """A shelf over the desk: books and a little plant, or the alarm
        clock ringing (an event soon)."""
        x, y = self.dx, self.floor - 9
        cv.fill(x, y, DW, 1, SHELF, ch="_", colour=FRAME)
        for i, c in enumerate((SLEEVES[1], SLEEVES[3], SLEEVES[0], SLEEVES[2])):
            cv.cell(x + 1 + i, y - 1, "▐", c)
        cv.cell(x + 2, y - 2, "▐", SLEEVES[5])
        cv.cell(x + 3, y - 2, "▐", SLEEVES[4])
        if not clock:
            cv.sprite(x + 11, y - 2, "\\|/", LEAF)
            cv.sprite(x + 11, y - 1, "(_)", STRIPE)
        else:
            ring = (tick // 2) % 10 < 5
            shake = tick % 2 if ring else 0
            cx = x + 6 + shake
            cv.sprite(cx, y - 2, "o.-.o", DIM)
            cv.cell(cx, y - 2, "o", PEACH)
            cv.cell(cx + 4, y - 2, "o", PEACH)
            cv.sprite(cx, y - 1, "(   )", DIM)
            cv.cell(cx + 2, y - 1, "|/-\\"[(tick // 3) % 4], TEXT_HI)
            if ring:
                cv.cell(cx - 1, y - 2, "(", PEACH_LT)
                cv.cell(cx + 5, y - 2, ")", PEACH_LT)

    def _record_player(self, cv, tick, spinning):
        """On the floor under the window: a box, a record, a tone arm; the
        record turns when the music plays."""
        x, y = self.wx, self.floor - 2
        cv.sprite(x, y, " _____ ", DIM)
        cv.sprite(x, y + 1, "|     |", DIM)
        cv.sprite(x, y + 2, "'-----'", DIM)
        centre = "-\\|/"[(tick // 2) % 4] if spinning else "-"
        cv.cell(x + 1, y + 1, "(", TEXT)
        cv.cell(x + 2, y + 1, centre, PEACH)
        cv.cell(x + 3, y + 1, ")", TEXT)
        if spinning:
            cv.cell(x + 4, y + 1, "/", LILAC)       # the tone arm on the record
        else:
            cv.cell(x + 5, y + 1, "'", LILAC)       # lifted, at rest

    def _fan(self, cv, tick):
        x, y = self.wx + 8, self.floor - 3
        cv.sprite(x, y, " .-. ", DIM)
        cv.sprite(x, y + 1, "(   )", DIM)
        cv.cell(x + 2, y + 1, "+x"[(tick // 2) % 2], RAIN)
        cv.sprite(x, y + 2, " `|' ", DIM)
        cv.sprite(x, y + 3, " _|_ ", DIM)

    def _kittens(self, cv, tick):
        """Two kittens peeking: one beside the record player, one from under
        the desk, each bobbing up and ducking in its own time."""
        for n, x in enumerate((self.wx + 8, self.dx + 5)):
            up = math.sin(tick / 6.0 + n * 2.1) > -0.3
            y = self.floor - (1 if up else 0)
            cv.sprite(x, y, "/\\_/\\", KITTEN[n])
            if up:
                eye = "-" if blink(tick + n * 17, 41) else "o"
                cv.sprite(x, y + 1, "(   )", KITTEN[n])
                cv.cell(x + 1, y + 1, eye, EYE)
                cv.cell(x + 2, y + 1, ".", NOSE)
                cv.cell(x + 3, y + 1, eye, EYE)
        if (tick // 10) % 3 == 0:
            cv.put(self.wx + 8, self.floor - 2, "mew", HAZE)

    def _notes(self, cv, tick):
        """Music notes rising off the record."""
        x0, y0 = self.wx + 3, self.floor - 3
        for j in range(2):
            s = (tick + j * 13) % 26
            if s < 15:
                y = y0 - s // 5             # three rows up, under the sill
                x = x0 + j * 2 + (1 if (s // 4) % 2 else 0)
                if cv.get(x, y) == " ":
                    cv.cell(x, y, "♫", (PEACH_LT, LILAC)[j])

    def _confetti(self, cv, tick):
        span = self.floor
        for i in range(max(4, self.cols * self.rows // 140)):
            r = lcg(227, i)
            pos = r() * span + tick * (0.1 + r() * 0.08)
            fall = int(pos // span)
            y = int(pos - fall * span)
            x = int(lcg(229, i, fall)() * self.cols)
            if cv.get(x, y) == " ":
                cv.cell(x, y, ",'∙"[(tick // 3 + i) % 3], CONFETTI[i % len(CONFETTI)])

    # -- Miso ----------------------------------------------------------------------------

    def _miso(self, cv, state, tick, kind, mood, scene, fidget):
        idle = state == "idle"
        x = self.kx
        p = self.floor - 1                      # her paws' row
        # the cushion
        cv.fill(x, self.floor, CW - 1, 1, CUSHION, ch="~", colour=LILAC)
        cv.cell(x, self.floor, "(", LILAC, CUSHION)
        cv.cell(x + CW - 2, self.floor, ")", LILAC, CUSHION)
        if idle and "hot" in scene:
            self._sprawl(cv, tick, x, p, mood, fidget)
            self.head = (x + 7, p - 3)          # just right of the flat ears
            return None
        # how many body rows: the breath, sitting up, the stretch
        if idle:
            if mood == "sad":
                n = 0
            elif mood == "sleepy":
                n = (tick // 30) % 2
            else:
                n = 1 + (tick // 20) % 2
        elif state == "done":
            n = 3 if (tick // 10) % 4 in (1, 2) else 2
        else:
            n = 2
        top = p - n - 4
        stretch = state == "done" and n == 3
        puffed = state == "error"
        tilt = 0
        if state == "thinking":
            tilt = (tick // 15) % 2
        elif idle and mood == "curious":
            tilt = 1
        # ears
        ears = "up"
        if puffed or (idle and mood == "sad"):
            ears = "flat"
        elif mood == "worried" and state != "done":
            ears = "back"
        elif fidget == "ear" or ("music" in scene and (tick // 5) % 4 == 0):
            ears = "twitch"
        e = EARS[ears]
        cv.sprite(x + 8 + tilt - len(e) // 2, top, e, FUR)
        for i, ch in enumerate(e):
            if ch == ",":
                cv.recolour(x + 8 + tilt - len(e) // 2 + i, top, STRIPE)
        # the head
        cv.sprite(x + 3 + tilt, top + 1, "/         \\", FUR)
        cv.sprite(x + 2 + tilt, top + 2, "(           )", FUR)
        # the neck and shoulders, the body, the paws
        neck = "{`--.___.--'}" if puffed else "/`--.___.--'\\"
        cv.sprite(x + 2, top + 3, neck, FUR)
        for k in range(n):
            y = top + 4 + k
            if puffed:
                cv.sprite(x + 1, y, "{  ^^^   ^^^  }", FUR)
            else:
                cv.sprite(x + 1, y, "(             )", FUR)
                for c in (5, 6):
                    cv.cell(x + c, y, ")", STRIPE)
                for c in (10, 11):
                    cv.cell(x + c, y, "(", STRIPE)
        cv.sprite(x, p, "{^^,,^^^^^^^,,^^}" if puffed else "(__,,_______,,__)", FUR)
        # the tail, beside her on the right
        if puffed:
            tail = ((17, p, "}"), (17, p - 1, "{"), (17, p - 2, "}"))
        elif mood == "excited" and state != "error":
            tail = ((16, p - 1, "|"), (17, p - 2, ")"), (17, p - 3, "("))
        elif fidget == "tail" or (idle and mood == "happy" and (tick // 8) % 3 == 0):
            tail = ((17, p, ")"), (17, p - 1, ")"), (17, p - 2, "'"))
        elif idle and mood in ("sleepy", "sad"):
            tail = ((17, p, "~"),)
        else:
            tail = ((17, p - 1, "("), (17, p, ")"))
        for dx, y, ch in tail:
            cv.cell(x + dx, y, ch, FUR)
        if stretch:
            # front paws up over her head
            for dx, dy, ch in ((1, 2, "\\"), (0, 1, "\\"), (0, 0, ","), (15, 2, "/"), (16, 1, "/"), (16, 0, ",")):
                cv.cell(x + dx, top + dy, ch, FUR)
        if idle and "cold" in scene:
            # a knitted blanket over her back, the head peeking out
            for y in range(top + 3, p + 1):
                for c in range(1, 16):
                    if cv.get(x + c, y) is not None:
                        cv.cell(x + c, y, "x" if (c + y) % 2 else "+", BLANKET_MARK, BLANKET)
        self._face(cv, state, tick, kind, mood, scene, fidget, x + tilt, top)
        if idle and "game" in scene and mood != "sleepy":
            cv.put(x + 6, p, "[+", RAIN, bg=SCREEN)
            cv.cell(x + 8, p, "▐", (TEAL, PEACH, LILAC)[(tick // 4) % 3], SCREEN)
            cv.put(x + 9, p, "o]", RAIN, bg=SCREEN)
        if mood == "focused":
            self._headphones(cv, x + tilt, top)
        if "party" in scene:
            cv.cell(x + 8 + tilt, top - 2, "*", HONEY)
            cv.cell(x + 7 + tilt, top - 1, "/", BERRY)
            cv.cell(x + 8 + tilt, top - 1, ":", HONEY)
            cv.cell(x + 9 + tilt, top - 1, "\\", BERRY)
        self._marks(cv, state, tick, mood, scene, fidget, x + tilt, top)
        # the reaction sign's anchor: up and right of her right ear, where
        # the curious "?" floats -- it follows the breath and the tilt.
        self.head = (x + tilt + 15, max(0, top - 1))
        return top

    def _face(self, cv, state, tick, kind, mood, scene, fidget, x, top):
        idle = state == "idle"
        left, right, mouth = MOOD_FACE["calm"]
        if idle:
            left, right, mouth = MOOD_FACE.get(mood, MOOD_FACE["calm"])
        elif state == "done":
            left, right, mouth = "^", "^", "ᴥ"
        elif state == "error":
            left, right, mouth = "O", "O", "~"
        elif mood == "focused":
            left = right = "-"
        else:
            left = right = "o"
            if kind == "lens":
                right = "O"                 # peering through the glass
        gaze = 0
        if state in ("tool", "writing"):
            gaze = 1                        # at the desk
        t = tick % 90 - 72
        if fidget == "look":
            left = right = "o"
            gaze = -1 if t < 9 else 1
        elif fidget == "yawn":
            mouth = "O" if 3 <= t < 14 else "o"
        shut = blink(tick, 47) and left in ("o", "O") and state not in ("done", "error")
        for ex, ch in ((6, left), (10, right)):
            cv.cell(x + ex + gaze, top + 1, "-" if shut else ch, EYE)
        cv.cell(x + 8, top + 2, mouth, NOSE)
        cv.cell(x + 5, top + 2, "=", WHISKER)
        cv.cell(x + 11, top + 2, "=", WHISKER)
        if mood == "shy" and state != "error":
            cv.cell(x + 4, top + 2, "/", BLUSH)
            cv.cell(x + 12, top + 2, "/", BLUSH)
            if idle:
                cv.put(x + 5, top + 1, "(,,)", FUR)     # a paw over her face
        elif mood == "happy" and state != "error":
            cv.cell(x + 4, top + 2, "~", BLUSH)
            cv.cell(x + 12, top + 2, "~", BLUSH)
        if fidget == "wash" and t % 6 < 4:
            cv.put(x + 9, top + 2, "(,)", FUR)          # washing a paw

    def _headphones(self, cv, x, top):
        cv.put(x + 4, top - 1, ".-------.", LILAC)
        cv.cell(x + 3, top + 1, "[", LILAC)
        cv.cell(x + 13, top + 1, "]", LILAC)

    def _reach(self, cv, tick, y):
        """A paw over to the desk at its top's height, tapping."""
        x0 = self.kx + 15
        tap = (tick // 3) % 2
        for x in range(x0, self.dx + 1):
            if cv.get(x, y) == " ":
                cv.cell(x, y, "_", FUR)
        cv.cell(self.dx + 1 + tap, y, ",", FUR)

    def _sprawl(self, cv, tick, x, p, mood, fidget):
        """Too hot for a loaf: flat out on the cushion, head on her paws."""
        cv.sprite(x, p - 2, "  /\\_/\\           ", FUR)
        cv.sprite(x, p - 1, " (     )`-------. ", FUR)
        cv.sprite(x, p, "(,,_ _,,)______,)~", FUR)
        sleepy = mood in ("sleepy", "calm", "sad")
        eye = "-" if sleepy or blink(tick, 47) else "o"
        cv.cell(x + 3, p - 1, eye, EYE)
        cv.cell(x + 5, p - 1, eye, EYE)
        cv.cell(x + 4, p, "ᴥ", NOSE)
        s = (tick // 5) % 4
        if s < 3:
            cv.cell(x, p - 2 + (s > 1), "',"[s > 1], RAIN)     # sweat
        if sleepy:
            self._zs(cv, tick, x + 9, p - 2, big=mood == "sleepy")

    def _zs(self, cv, tick, x, y, big=False):
        if big:
            s = tick % 36
            for j in range(3):
                if s // 9 > j:
                    cv.cell(x + j, y - j, "zzZ"[j], DIM if j < 2 else TEXT_HI)
        else:
            # one slow z drifting up and off
            s = tick % 60
            if s < 40:
                cv.cell(x + s // 20, y - s // 14, "z", HAZE)

    def _marks(self, cv, state, tick, mood, scene, fidget, x, top):
        """What floats around her for her mood and scene: z's, a "?", a
        twinkle, a sweat drop, a purr, thought dots, "!", breath puffs."""
        idle = state == "idle"
        if idle and mood == "sleepy":
            self._zs(cv, tick, x + 14, top, big=True)
        elif idle and mood == "calm" and fidget is None:
            self._zs(cv, tick, x + 14, top)
        if mood == "curious" and (idle or (tick // 20) % 3 == 0) and (tick // 5) % 4:
            cv.cell(x + 15, top - 1, "?", PEACH_LT)
        if mood == "excited" and state != "error":
            on = (tick // 3) % 4
            if on < 2 or idle:
                cv.cell(x + 1, top, "✦" if on % 2 else "✧", HONEY)
                if idle:
                    cv.cell(x + 15, top - 1, "✧" if on % 2 else "✦", HONEY)
        if (mood == "worried" or "hot" in scene) and state != "done":
            s = (tick // 5) % 4
            if s < 3 and cv.get(x + 15, top + 1 + (s > 1)) == " ":
                cv.cell(x + 15, top + 1 + (s > 1), "',"[s > 1], RAIN)
        if mood == "happy" and state != "error" and (tick // 6) % 3:
            for px in (self.kx, self.kx + 16):          # the purr
                if cv.get(px, top + 3) == " ":
                    cv.cell(px, top + 3, "~", BLUSH)
        if state == "thinking":
            for j, ch in enumerate("∙◦o"):
                if (tick // 6) % 4 > j:
                    cv.cell(x + 14 + j, top - j, ch, DIM)
        elif state == "error" and (tick // 4) % 3:
            cv.cell(self.kx, top, "!", BERRY)
            cv.cell(self.kx + 16, top, "!", BERRY)
        elif state == "done":
            # Sparkles only in the three rows ABOVE the ears: the blank cells
            # inside her outline are spaces too, so a free-cell test alone let
            # them land in her face and broke the clean ^ᴥ^ stretch.
            r = lcg(233, tick // 4)
            for _ in range(3):
                sx, sy = self.kx + int(r() * CW), top - 3 + int(r() * 3)
                if cv.get(sx, sy) == " ":
                    cv.cell(sx, sy, "✧", PEACH_LT)
        if "cold" in scene and state in ("idle", "done"):
            s = tick % 40
            if s < 12:
                cv.cell(x + 15 + s // 4, top + 2 - s // 6, ".oO"[min(2, s // 4)], SNOW)

    # -- the work on the desk -------------------------------------------------------------

    def _cassette(self, cv, tick):
        """Thinking: a cassette on the desk, its reels turning."""
        x, y = self.dx, self.py
        cv.sprite(x, y + 2, ".--------.", DIM)
        cv.sprite(x, y + 3, "|(o)==(o)|", DIM)
        cv.sprite(x, y + 4, "'--------'", DIM)
        reel = "oO0O"[(tick // 3) % 4]
        cv.cell(x + 2, y + 3, reel, PEACH)
        cv.cell(x + 7, y + 3, reel, PEACH)
        cv.cell(x + 4, y + 3, "=", LILAC)
        cv.cell(x + 5, y + 3, "=", LILAC)
        cv.put(x + 2, y + 2, "side A", HAZE)

    def _notebook(self, cv, tick):
        """Writing: a notebook filling up line by line over a mini keyboard
        whose keys light up."""
        x, y = self.dx, self.py
        cv.sprite(x, y, ".--------.", DIM)
        cv.sprite(x, y + 1, "|        |", DIM)
        cv.sprite(x, y + 2, "|        |", DIM)
        cv.sprite(x, y + 3, "'--------'", DIM)
        lines = self._stream
        total = tick % (len(lines) * 8)
        li, col = divmod(total, 8)
        for k in range(2):
            j = li - 1 + k
            if j < 0:
                continue
            text = lines[j % len(lines)] if k == 0 else lines[j % len(lines)][:col]
            cv.put(x + 1, y + 1 + k, text, TEXT if k else DIM)
        cv.put(x, y + 4, "[::::::::]", HAZE)
        key = 1 + int(lcg(239, tick // 2)() * 8)
        cv.cell(x + key, y + 4, ":", TEXT_HI, FRAME)

    def _mug(self, cv, tick, tipped=False):
        x, y = self.dx + 4, self.py + 4
        if tipped:
            cv.put(x - 1, y, "(=]", DIM)
            cv.put(x + 2, y, "~~,.", STRIPE)
            return
        cv.put(x, y, "[_])", PEACH_LT)
        for k in range(2):
            s = (tick // 4 + k) % 3
            if s < 2:
                cv.cell(x + 1 + (s + k) % 2, y - 1 - k, "∿" if k else "~", HAZE)

    def _prop_bash(self, cv, tick):
        """A tiny CRT: the last command dim, the next one typed, a blinking _."""
        x, y = self.dx, self.py
        cv.sprite(x, y, " .------. ", DIM)
        cv.sprite(x, y + 1, " |      | ", DIM)
        cv.sprite(x, y + 2, " |      | ", DIM)
        cv.sprite(x, y + 3, " '------' ", DIM)
        cv.sprite(x, y + 4, "  /____\\  ", HAZE)
        cv.fill(x + 2, y + 1, 6, 2, SCREEN)
        cyc = tick // 24
        prev, cmd = CMDS[(cyc - 1) % len(CMDS)], CMDS[cyc % len(CMDS)]
        n = min(len(cmd), (tick % 24) // 3)
        cv.put(x + 2, y + 1, ("$" + prev)[:6], HAZE, bg=SCREEN)
        cv.put(x + 2, y + 2, ("$" + cmd[:n])[:6], SAGE, bg=SCREEN)
        if (tick // 4) % 2 and n + 1 < 6:
            cv.cell(x + 3 + n, y + 2, "_", SAGE, SCREEN)

    def _prop_book(self, cv, tick):
        """An open book, a line lit as she reads; the page turns now and then."""
        x, y = self.dx, self.py
        cv.sprite(x, y + 2, " ___ ___ ", DIM)
        cv.sprite(x, y + 3, "|~~~|~~~|", DIM)
        cv.sprite(x, y + 4, "|___|___|", DIM)
        hot = (tick // 4) % 6
        cv.recolour(x + 1 + hot + (hot > 2), y + 3, TEXT_HI)
        if tick % 60 < 6:
            cv.cell(x + 6, y + 2, "/", TEXT)        # a page turning

    def _prop_pad(self, cv, tick):
        """A notebook, scribbles appearing and the pencil following them."""
        x, y = self.dx, self.py
        cv.sprite(x, y + 1, ".------.", DIM)
        cv.sprite(x, y + 2, "|      |", DIM)
        cv.sprite(x, y + 3, "|      |", DIM)
        cv.sprite(x, y + 4, "'------'", DIM)
        lines = self._scribble
        total = tick % (len(lines) * 6)
        li, col = divmod(total, 6)
        prev = lines[(li - 1) % len(lines)] if li else ""
        cv.put(x + 1, y + 2, prev, HAZE)
        cv.put(x + 1, y + 3, lines[li % len(lines)][:col], TEXT)
        cv.cell(x + 1 + min(col, 6), y + 2, "/", PEACH_LT)

    def _prop_lens(self, cv, tick):
        """A magnifier sliding to and fro over a page on the desk."""
        x, y = self.dx, self.py
        cv.put(x, y + 4, "[~~ ~~~ ~]", DIM)
        mx = x + int(round((math.sin(tick / 8.0) + 1) * 2.5))
        cv.sprite(mx + 1, y + 1, ".-.", PEACH_LT)
        cv.cell(mx, y + 2, "(", PEACH_LT)
        cv.cell(mx + 4, y + 2, ")", PEACH_LT)
        cv.put(mx + 1, y + 2, "~~~", TEXT_HI, bg=FRAME)
        cv.sprite(mx + 1, y + 3, "`-'", PEACH_LT)
        cv.cell(mx + 4, y + 3, "\\", DIM)

    def _prop_globe(self, cv, tick):
        """A little radio on the desk, waves going out from its aerial."""
        x, y = self.dx, self.py
        wave = (" ∿ ", "(∿)", "((∿))")[(tick // 4) % 3]
        cv.put(x + 3 - len(wave) // 2, y + 1, wave, LILAC)
        cv.cell(x + 3, y + 2, "\\", DIM)
        cv.sprite(x, y + 3, ".--------.", DIM)
        cv.sprite(x, y + 4, "|        |", DIM)
        cv.cell(x + 1, y + 4, "o", PEACH)
        level = (tick // 2) % 6
        for c in range(5):
            cv.cell(x + 3 + c, y + 4, ":", SAGE if c < level else HAZE)

    def _prop_todo(self, cv, tick):
        """Sticky notes on the wall over the desk, ticked off one by one."""
        x, y = self.dx, self.py
        done = (tick // 10) % 7
        for k in range(6):
            nx, ny = x + (k % 3) * 3, y + 1 + (k // 3) * 2
            bg = NOTE_BG[k % 3]
            cv.fill(nx, ny, 3, 2, bg)
            cv.put(nx, ny, "--", HAZE, bg=bg)
            cv.cell(nx + 1, ny + 1, "v" if k < done else " ", SAGE, bg)

    def _prop_wand(self, cv, tick):
        """A ball of yarn rolling off along the desk, unrolling behind it."""
        x, y = self.dx, self.py
        k = (tick // 3) % 8              # the ball stays clear of the lamp
        for c in range(k):
            cv.cell(x + c, y + 4, "~", LILAC)
        cv.cell(x + k, y + 3, ".", YARN)
        cv.put(x + k, y + 4, "(" + "@oO"[tick % 3] + ")", YARN)
