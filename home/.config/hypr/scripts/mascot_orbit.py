#!/usr/bin/env python3
"""The orbit theme's mascot: Pip, a little probe in low orbit -- a dish on
top, a gold-foil body with a face, a solar panel either side, a status LED
that blinks -- floating over the curve of a planet, with a console's
telemetry strip along the bottom of the stage. Same API as
moe_mascot.Mascot (mascots.py picks it). Our own drawing: no agency's
spacecraft, logo or patch.

    space     painted as cell backgrounds, the console floor (#070b14) at the
              top fading into the stage card (#0e1626 = PANEL, the stage in
              themes/orbit/llm-chat.css) at the limb; stars twinkle in it
    the limb  ONE wide arc of planet across the bottom: an ocean fill with
              land masses drifting by (the planet turns, a cell every eight
              ticks) under an edge drawn in _ . - ' by how high the arc
              reaches into each cell, in the telemetry teal -- the thin
              line of air seen from orbit. By night the ocean is darker and
              the land shows a few amber city lights
    strip     the bottom row: a T+ mission clock (the tick, as MM:SS), a
              status word (STBY, PROC, EXEC, DNLK, GO, NO-GO), signal bars
              when there is room, the real HH:MM at the right
    Pip       19 x 6 cells: the dish (it sweeps left and right while
              thinking), the LED at its feed, the body with eyes and a
              mouth, a 3 x 2 grid of solar cells either side on struts, a
              glint running across them now and then; it bobs one row
    props     to its right, console cards (a header row with an uppercase
              label and a status word, a teal tab at its left, the body
              under it): "> cmd" lines for Bash, a page with a highlight bar
              for Read, a page filling up for Edit/Write, a query and a hit
              list for the searches, a small planet and a progress bar for
              WebFetch, two relay drones and a RELAY card for Task/Agent, a
              checklist for TodoWrite, a comet and sparkles otherwise.
              Thinking is an oscilloscope trace rolling across a COMPUTE
              card (radio rings rising off the dish), writing a DOWNLINK card
              filling with words while signal dots fly to it, done ALL
              SYSTEMS GO with a green v/ (Pip hops), an error a MASTER
              CAUTION card, the LED red, the panels sagging, a sweat drop

  mood      one of mascot_mood.MOODS. Idle, it is the whole face: happy
              ^ ^ w, excited starry eyes and hops, shy > < with cheeks and
              eyes turned away, curious o O and a "?", focused and worried
              brows (worried sweats), sad dots and sagging panels, sleepy
              shut eyes, z's and a dim LED (safe mode). At work only the
              accents show (brows, sweat, cheeks, a twinkle) over the work
              face; sleepy works focused. calm (or None) is its usual face.
              The idle fidget at the end of each 9-second round (a dish
              sweep, a ping off the dish, a glint across the panels, a
              panel wave, a yawn) is picked by the noise and weighted by the
              mood.
  scene     a set of mascot_mood.SCENES: day (the lit side of the planet),
              night (the dark side, city lights, more stars), sun (a small
              sun at the top right, flaring), cloud (cloud bands on the
              planet, the stars dimmer), rain and storm (heavier bands; a
              storm flashes lightning inside them now and then, as seen from
              orbit), snow (an ice cap along the limb), fog (haze bands over
              the planet), hot (heat shimmer off the panels, a sweat drop),
              cold (frost on the panels' corners), music (notes drifting by,
              a bob to the beat, a note in the strip), game (a controller
              card in the idle slot), party (a party hat on the dish,
              confetti), festive (papel picado along the top), clock (the
              strip's clock flashes amber and a (!) card pops up over it).

Navy and slate with one teal; the light cells are small (the eyes, the
dish, a glint, a card's few words). Every glyph is single-column.
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import STATES, BaseMascot, Canvas, blink, lcg, prop_kind, stream_lines  # noqa: E402
from mascot_mood import MOODS, word  # noqa: E402

THEME = "orbit"
PANEL = "#0e1626"

# the console (the theme's palette)
BASE = "#070b14"
RAISED = "#16223a"
RULE = "#2a3a57"
RULE_HI = "#3d5478"
HEAD = "#1c2a45"            # a card's header row
TEXT = "#dbe4f0"
TEXT_DIM = "#8a9bb4"
ACCENT = "#5cc8db"
ACCENT_DIM = "#3a8796"
ON_ACCENT = "#04121a"
GOOD = "#4fd18b"
WARN = "#f2b13c"
BAD = "#f0565a"
BAD_DIM = "#9a3a40"
# Pip
FOIL = "#c8a24a"            # the body's gold foil
FOIL_DIM = "#9c8648"        # sad / error / safe mode
OUTLINE = "#8a9bb4"
DISH = "#dbe4f0"
INK = "#1a1408"
CHEEK = "#f08a8a"
CELL = "#1d3f7a"            # a solar cell
CELL_DIM = "#18305a"
CELL_LINE = "#4a76b8"
GLINT = "#6aa7ff"
LED_OFF = "#1f4a33"
# the planet and the sky
OCEAN = "#0f2c4c"
OCEAN_DIM = "#0d2440"       # overcast
OCEAN_NIGHT = "#0a1424"
LAND = "#1f3d33"
LAND_NIGHT = "#101c1c"
LIMB_NIGHT = "#3d5478"
CITY = "#f2b13c"
CLOUD = "#b7c4d6"
CLOUD_GREY = "#7d8ba0"
STAR = "#c9d3e0"
STAR_DIM = "#5a6b86"
SUN = "#ffe08a"
RAIN = "#6aa7ff"
SNOW = "#eef4fb"
FOG = "#3d5478"
FLASH = "#e8edf5"
SWEAT = "#9fd0ff"
NOTE = ("#5cc8db", "#4fd18b")
CONFETTI = ("#f08a8a", "#ffe08a", "#4fd18b", "#6aa7ff", "#c792ea")
PICADO = ("#ff6fae", "#ffa94d", "#7fd46f", "#6fb6ff", "#c58bff", "#ffd84d")
OVERCAST = frozenset(("cloud", "rain", "storm", "snow", "fog"))

PW, PH = 19, 6
DISH_ROW = "\\_____/"       # 7 cells, over the body (cols 6..12)
PROBE = [
    None,                           # the dish, drawn on its own (it sweeps)
    "         |         ",
    "      .-----.      ",
    "     =|     |=     ",
    "      |     |      ",
    "      '-----'      ",
]
PANEL_ROWS = ("+---+", "|:::|", "|:::|", "+---+")
PANEL_X = (0, 14)
EYES = (8, 10)              # row 3
MOUTH = (4, 9)              # row 4
LED = (9, 0)                # the dish's feed

COMP_W = PW + 2 + 17
WORDS = ("copy", "that", "all", "go", "signal", "is", "clean", "and", "the", "data",
         "looks", "good", "on", "track", "nominal", "a", "it", "so", "ready", "now")
CMDS = ("ping", "status", "uplink", "ls", "sync", "diag")
TODO = ("Pre-flight", "Uplink", "Verify")
FILES = ("telemetry", "flightplan", "orbit.css", "notes.txt")

# Per mood, idle: (left eye, right eye, mouth, cheeks). calm: its usual face.
MOOD_FACE = {
    "happy": ("^", "^", "w", "~"),
    "excited": ("*", "*", "D", "~"),
    "shy": (">", "<", "~", "/"),
    "curious": ("o", "O", "o", ""),
    "focused": ("o", "o", "-", ""),
    "worried": ("o", "o", "~", ""),
    "sad": (".", ".", "n", ""),
    "sleepy": ("-", "-", ".", ""),
}
# Brows on the body's top edge above each eye (row 2): left, right.
BROWS = {"focused": ("\\", "/"), "worried": ("/", "\\"), "sad": ("/", "\\")}
# The idle fidget a mood favours: (name, weight); "rest" is none at all.
FIDGETS = {
    "calm": (("sweep", 2), ("ping", 2), ("glint", 2), ("wave", 1), ("rest", 2)),
    "happy": (("wave", 3), ("ping", 2), ("glint", 1)),
    "excited": (("wave", 3), ("ping", 2), ("sweep", 2)),
    "shy": (("sweep", 2), ("rest", 3)),
    "curious": (("sweep", 3), ("ping", 2)),
    "focused": (("glint", 3), ("rest", 2)),
    "worried": (("sweep", 2), ("rest", 2)),
    "sad": (("rest", 1),),
    "sleepy": (("yawn", 3), ("rest", 2)),
}

MOOD_BUBBLES = {
    "happy": "Green board, all stations! What's next?",
    "excited": "New mission? Tanks full, I'm GO!",
    "shy": "Oh! You weren't on my scope… hi ☺",
    "curious": "Unknown signal. Let's take a closer look!",
    "focused": "Locked on. Listening.",
    "worried": "Telemetry looks a little off…",
    "sad": "Low power today. Running on reserves…",
    "sleepy": "Pip in safe mode… zz",
}
# mascot_mood topics in its words, a flight controller's voice (str.format
# with the topic's arguments).
TOPIC_LINES = {
    "thanks": "Copy, thanks! Logging that one as a win.",
    "worried": "Reading something off-nominal. Run a check?",
    "frustrated": "Still no lock? Reset, new approach, go again.",
    "relieved": "And we have signal! Back to nominal.",
    "determined": "Long burn ahead. I'll hold the telemetry steady.",
    "proud": "Mission complete. Clean landing!",
    "sad": "Copy… drifting quietly on the night side for a bit.",
    "happy": "Woo! Green lights!",
    "curious": "Interesting data. Send more?",
    "rain": "Rain over your sector. Good day to stay docked.",
    "storm": "Storm cells on the ground track. Save your work!",
    "snow": "Snow down there! Keep warm, crew ❄",
    "fog": "Low visibility on the ground. Go easy.",
    "sun": "Full sun on the panels. Power is great ☀",
    "hot": "{0} outside. Watch your thermals!",
    "cold": "{0}! Heaters on, crew.",
    "gpu_hot": "GPU at {0}°C. Thermal limit approaching!",
    "cpu_hot": "CPU at {0}°C! Throttle back a bit?",
    "music": "Good tunes on the loop ♪",
    "game": "Sim time! The checklist can wait.",
    "event": "Heads up: {0} in {1} min.",
    "event_now": "Mark: {0}, now.",
    "birthday": "Happy launch day, {0}! 🎈",
    "holiday": "{0} today. Console's on standby!",
    "go_home": "{0} already. End of shift, head home!",
    "bedtime": "{0}. Crew rest period. Power down?",
    "morning": "Morning! Today's flight plan is loaded.",
    "lunch": "Time to refuel? Lunch break!",
    "weekend": "Weekend: no launches on the board. Go enjoy it!",
    # conversation and stage events (a tuple: variants, said in turn)
    "friday": "Friday PM. Final orbit of the week!",
    "hello": ("Pip online. Ready for tasking.",
              "Comms check: hi! What's the mission?",
              "Good to hear you, ground. Go ahead."),
    "welcome_back": "Welcome back, ground! Held orbit for you.",
    "wake": ("Exiting safe mode… systems coming up!",
             "Huh? Signal reacquired. I'm up!"),
    "long_prompt": ("Big uplink! Buffering…",
                    "That's a full payload. Copy all."),
    "code": ("Code uplink received. Parsing.",
             "Source on the wire. Checking it."),
    "image": ("Imagery received! Nice frame.",
              "Incoming image. Downlinking pixels."),
    "aborted": ("Abort, abort! Burn cut.",
                "Copy, aborting. All stop."),
    "tests_pass": ("Tests are GO! Green board.",
                   "All checks nominal ✓",
                   "Test sequence complete. GO!"),
    "tests_fail": ("Tests NO-GO. Pulling telemetry.",
                   "Test failure. Holding the count."),
    "commit": ("Commit confirmed. Payload away!",
               "Pushed! Clean separation.",
               "Logged to the flight record ✓"),
    "fast": ("Fast burn! Nice.",
             "In and out. Textbook.",
             "Quick hop. Nominal!"),
    "busy": ("Lots of traffic on the loop…",
             "Busy pass! Juggling the uplinks."),
    "model": ("New flight computer: {0}.",
              "Handover to {0}. Copy."),
    "poke": ("Ping received! Pong.",
             "Hey! You nudged my orbit.",
             "Comms check? Loud and clear!",
             "Pip here. Standing by.",
             "Careful, that's a thruster!",
             "Roger, ground. Need something?"),
    "poke_spam": ("Easy! You're knocking me out of orbit!",
                  "Stop, stop! Attitude control failing!",
                  "Mayday! Too many pings!"),
    "pet": ("Aww… panels at full power ☺",
            "Warm fuzzies on all sensors.",
            "That's a GO for cuddles.",
            "Best ground crew in the fleet."),
}
# The reaction sign over its head (mascot_mood.EMOTE_TONES) in the
# console's palette, each >= 4.5:1 on the stage card and the console floor.
EMOTE_COLOURS = {"accent": ACCENT, "warn": WARN, "bad": BAD,
                 "good": GOOD, "love": "#ff8fc0", "dim": TEXT_DIM}
# The strip's status word per state.
STATUS = {"idle": ("STBY", TEXT_DIM), "thinking": ("PROC", ACCENT), "tool": ("EXEC", ACCENT),
          "writing": ("DNLK", ACCENT), "done": ("GO", GOOD), "error": ("NO-GO", BAD)}


def _mix(a, b, f):
    """The colour f of the way from hex a to hex b."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * f)) for x, y in zip(pa, pb))


class Mascot(BaseMascot):
    BUBBLES = {
        "idle": "Pip here. All systems nominal. Standing by.",
        "thinking": "Crunching the numbers…",
        "writing": "Downlinking your answer…",
        "done": "Copy that. All systems GO ✓",
        "error": "Off-nominal. Recycle and try again?",
    }
    TOOL_BUBBLES = {
        "Bash": "Executing command sequence…",
        "Read": "Pulling the file up on screen…",
        "Edit": "Uplinking the changes…",
        "MultiEdit": "Uplinking the changes…",
        "Write": "Uplinking the changes…",
        "NotebookEdit": "Uplinking the changes…",
        "Grep": "Scanning the files…",
        "Glob": "Scanning the files…",
        "WebSearch": "Sweeping the net for a signal…",
        "WebFetch": "Receiving downlink…",
        "Task": "Calling in the relay drones…",
        "Agent": "Calling in the relay drones…",
        "TodoWrite": "Updating the checklist…",
    }
    OTHER = "Bringing %s online…"
    moods = True

    def __init__(self, cols=64, rows=18):
        self.cols = max(int(cols), COMP_W + 2)
        self.rows = max(int(rows), PH + 8)
        self.cx = (self.cols - COMP_W) // 2
        self.bottom = self.rows - 2           # the planet's lowest row (the strip is under it)
        # The limb: a wide arc of a big circle, highest at the middle of the
        # stage, a faint wobble (clouds and terrain) so it is not ruled.
        # Heights are floats (cells above the bottom row); the fraction picks
        # the edge glyph. Cells are about twice as tall as wide, hence the
        # 0.5 on the rise.
        peak = 3.6 if self.rows >= 18 else 2.8
        mid = self.cols / 2.0
        radius = max(self.cols * 1.6, 80.0)
        self._h = []
        for x in range(self.cols):
            dx = x + 0.5 - mid
            sag = (radius - math.sqrt(max(0.0, radius * radius - dx * dx))) * 0.5
            self._h.append(max(0.6, peak - sag) + 0.12 * math.sin(x * 0.13 + 0.7))
        hc = self.cx + PW / 2.0
        # the first row of planet under Pip's middle: it floats a row above it
        self.ground = self.bottom - int(self._h[int(hc)])
        # land masses: a smooth noise around the planet's circumference,
        # wider than the stage, so it can turn under the probe
        self._span = self.cols * 3
        self._land = [lcg(181, x // 4)() * 0.6 + lcg(181, x // 4 + 1)() * 0.4 for x in range(self._span + 4)]
        self._city = [lcg(191, x)() for x in range(self._span + 4)]
        self._stream = stream_lines(WORDS, 12, seed=73)
        self._stars = []
        for i in range(self.cols * self.rows // 28):
            r = lcg(167, i)
            self._stars.append((int(r() * self.cols), int(r() * max(2, self.ground - 1)),
                                20 + int(r() * 30), int(r() * 50)))
        self._bands = []
        for i in range(max(2, self.cols // 18)):
            r = lcg(173, i, self.cols)
            self._bands.append((r() * self.cols, r(), 3 + int(r() * 6), 0.04 + r() * 0.04))

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

    def _edge(self, x):
        """The row of the limb's edge glyph at column x."""
        return self.bottom - int(self._h[max(0, min(self.cols - 1, x))])

    # -- composition ---------------------------------------------------------------

    def _render(self, state, tick, tool, mood=None, scene=()):
        if state not in STATES:
            state = "idle"
        if mood not in MOODS:
            mood = "calm"
        if mood == "sleepy" and state in ("thinking", "tool", "writing"):
            mood = "focused"            # no safe mode on the job
        scene = frozenset(scene or ())
        tick = int(tick)
        cv = Canvas(self.cols, self.rows)
        kind = prop_kind(tool) if state == "tool" else None
        idle = state == "idle"
        fidget = self._fidget(tick, mood) if idle else None
        self._space(cv, state, tick, scene)
        if "festive" in scene:
            self._banner(cv, tick)
        self._planet(cv, tick, scene)
        if "party" in scene:
            self._confetti(cv, tick)
        self._strip(cv, state, tick, scene)
        if state == "done":
            hover = (0, 1, 2, 2, 1, 0, 0, 0)[tick % 8]      # a happy hop
        elif idle and mood == "excited" and (tick // 30) % 2:
            hover = (0, 1, 2, 2, 1, 0)[tick % 6]
        elif state == "error" or (idle and mood in ("sad", "sleepy")):
            hover = 0                   # drifting low
        elif "music" in scene:
            hover = (tick // 4) % 2     # bobbing to the beat
        else:
            hover = 1 if math.sin(tick / 7.0) > 0 else 0
        top = self.ground - PH - 1 - hover
        ox = self.cx
        if kind == "helpers":
            self._helpers(cv, tick)
        # the reaction sign's anchor: the dish row, just right of the dish's
        # widest sweep, over the right panel -- where its "?" and z's float
        self.head = (min(ox + 14, self.cols - 3), max(0, top))
        self._probe(cv, state, tick, ox, top, mood, scene, fidget)
        self._mood_marks(cv, state, tick, ox, top, mood, scene, fidget)
        if "party" in scene:
            self._hat(cv, tick, ox, top)
        px, py = self.cx + PW + 2, self.ground - 8
        if state == "thinking":
            self._rings(cv, tick, ox, top)
            self._scope(cv, tick, px, py)
        elif state == "writing":
            self._signal(cv, tick, ox, top, px, py)
            self._doc(cv, tick, px, py, stream=True, title="DOWNLINK")
        elif state == "done":
            self._go(cv, tick, px, py)
        elif state == "error":
            self._caution(cv, tick, px, py)
        elif kind and kind != "helpers":
            getattr(self, "_prop_" + kind)(cv, tick, px, py)
        elif kind == "helpers":
            pass
        elif "game" in scene:
            self._controller(cv, tick, px, py)
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

    # -- space and the planet ------------------------------------------------------

    def _space(self, cv, state, tick, scene=frozenset()):
        """The console floor at the top fading into the card at the limb,
        the stars over it (fewer behind cloud, more at night), the sun at
        the top right on a clear day."""
        overcast = bool(scene & OVERCAST)
        night = "night" in scene
        span = max(1, self.ground)
        for y in range(self.bottom + 1):
            bg = _mix(BASE, PANEL, min(1.0, y / float(span)))
            for x in range(self.cols):
                cv.recolour(x, y, bg=bg)
        y0 = 2 if "festive" in scene else 0
        sun = not night and not overcast and state != "error" and scene & {"day", "sun"} and self.cols >= 48
        for x, y, period, ph in self._stars:
            if overcast and (x + y) % 3:
                continue            # dimmed: only every third one shows
            if not night and (x * 7 + y) % 2:
                continue            # by day the glare hides half of them
            if sun and x >= self.cols - 8 and y < y0 + 4:
                continue
            if y < y0 or cv.get(x, y) != " ":
                continue
            t = (tick + ph) % period
            cv.cell(x, y, ".+*+."[t] if t < 5 else ".", STAR if t < 5 else STAR_DIM)
        if sun:
            self._sun(cv, tick, y0)

    def _planet(self, cv, tick, scene=frozenset()):
        """The limb: the ocean fill with land drifting by under the edge
        glyph (_ low, . - ' higher, in the air's teal; white with an ice
        cap in the snow scene), then the weather on it."""
        night = "night" in scene
        overcast = bool(scene & OVERCAST)
        ocean = OCEAN_NIGHT if night else (OCEAN_DIM if overcast else OCEAN)
        land = LAND_NIGHT if night else LAND
        turn = tick // 8
        for x in range(self.cols):
            h = self._h[x]
            top = self.bottom - int(h)
            k = (x + turn) % self._span
            for y in range(top + 1, self.bottom + 1):
                ground = self._land[k + (y % 2)] > 0.62
                cv.cell(x, y, " ", None, land if ground else ocean)
                if night and ground and self._city[(k + y) % self._span] < 0.18:
                    cv.cell(x, y, ".", CITY, land)
            frac = h - int(h)
            glyph = "_.-'"[min(3, int(frac * 4))]
            colour = SNOW if "snow" in scene else (LIMB_NIGHT if night else ACCENT)
            cv.cell(x, top, glyph, colour)
        if scene & {"cloud", "rain", "storm"}:
            self._bands_on(cv, tick, heavy=bool(scene & {"rain", "storm"}), storm="storm" in scene)
        if "fog" in scene:
            self._haze(cv, tick)

    def _bands_on(self, cv, tick, heavy=False, storm=False):
        """Cloud bands drifting over the planet's face: ~ on the ocean, a
        lightning flash inside them now and then in a storm."""
        colour = CLOUD_GREY if heavy else CLOUD
        for x0, yf, w, speed in self._bands:
            x = int(x0 + tick * speed) % (self.cols + w) - w
            for c in range(w * (2 if heavy else 1)):
                xx = x + c
                if not 0 <= xx < self.cols:
                    continue
                top = self._edge(xx)
                depth = self.bottom - top
                if depth < 1:
                    continue
                y = top + 1 + int(yf * depth)
                if y <= self.bottom:
                    cv.cell(xx, y, "~" if (c + tick // 6) % 3 else "-", colour)
        if storm:
            cyc, t = divmod(tick, 37)
            if t < 3:
                x = int(lcg(193, cyc)() * (self.cols - 2)) + 1
                y = min(self.bottom, self._edge(x) + 1)
                cv.cell(x, y, "*" if t != 1 else "+", FLASH)

    def _haze(self, cv, tick):
        for k in range(2):
            off = (tick // (7 + k * 3) + k * 5) % 10
            for x in range(self.cols):
                y = self._edge(x) - k
                if (x + off) % 10 < 4 and cv.get(x, y) == " ":
                    cv.cell(x, y, "~", FOG)

    def _strip(self, cv, state, tick, scene=frozenset()):
        """The telemetry strip: T+MM:SS from the tick, the status word,
        signal bars, a note in the music scene, the real HH:MM (flashing
        amber in the clock scene, a (!) card above it)."""
        y = self.rows - 1
        cv.fill(0, y, self.cols, 1, RAISED, occupy=False)
        cv.recolour(0, y, bg=ACCENT)
        m, s = divmod((tick // 10) % 3600, 60)
        cv.put(1, y, " T+%02d:%02d " % (m, s), TEXT, bg=RAISED)
        word_, colour = STATUS.get(state, STATUS["idle"])
        cv.put(11, y, " " + word_ + " ", colour, bg=HEAD)
        clock = time.strftime(" %H:%M ")   # the real time: it reacts to it anyway
        ring = "clock" in scene and (tick // 5) % 2
        cx = self.cols - len(clock)
        cv.put(cx, y, clock, ON_ACCENT if ring else TEXT, bg=WARN if ring else HEAD)
        x = cx - 2
        if "music" in scene:
            cv.cell(x, y, "d", NOTE[0], RAISED)
            x -= 2
        if self.cols >= 60:
            # signal bars: a lock while working, one bar dropping out on error
            n = 1 if state == "error" else (3 if state == "idle" else 2 + (tick // 4) % 2)
            for i in range(3):
                cv.cell(x - 3 + i, y, "|", (GOOD if state != "error" else BAD) if i < n else RULE_HI, RAISED)
            cv.put(x - 8, y, "SIG", TEXT_DIM, bg=RAISED)
        if "clock" in scene and (tick // 10) % 3:
            text = " (!) REMINDER "
            bx = max(0, self.cols - len(text) - 1)
            cv.put(bx, y - 2, text, ON_ACCENT, bg=WARN)
            cv.cell(self.cols - 4, y - 1, "V", WARN)

    # -- the scene (mascot_mood.SCENES) ------------------------------------------------

    def _sun(self, cv, tick, y=0):
        """A small sun at the top right, its flare turning."""
        x = self.cols - 7
        rays = ("\\ | /", "  |  ", "\\   /")[(tick // 8) % 3]
        cv.put(x, y, rays, SUN)
        cv.put(x, y + 1, "-(O)-", SUN)
        cv.put(x, y + 2, "/ | \\" if rays[0] == "\\" else "  |  ", SUN)

    def _banner(self, cv, tick):
        """Papel picado: a cord along the top row, cut-paper flags in the
        Mexican colours hanging under it, fluttering."""
        for x in range(self.cols):
            cv.cell(x, 0, "-", TEXT_DIM)
            k = x % 4
            if k < 3:
                flutter = (tick // 4 + x // 4) % 2
                cv.cell(x, 1, ("o.o", ".o.")[flutter][k], PANEL, PICADO[(x // 4) % len(PICADO)])

    def _confetti(self, cv, tick):
        span = self.rows + 2
        for i in range(max(4, self.cols * self.rows // 90)):
            r = lcg(197, i)
            pos = r() * span + tick * (0.10 + r() * 0.08)
            fall = int(pos // span)
            y = int(pos - fall * span) - 1
            x = int(lcg(199, i, fall)() * self.cols) + (tick // 4 + i) % 2
            if y < self.rows - 1 and cv.get(x, y) == " ":
                cv.cell(x, y, ",'.*"[(tick // 3 + i) % 4], CONFETTI[i % len(CONFETTI)])

    def _hat(self, cv, tick, ox, top):
        """A party hat on the dish."""
        x = ox + 9
        cv.cell(x, top - 3, "*+"[(tick // 4) % 2], SUN)
        cv.put(x - 1, top - 2, "/:\\", CONFETTI[0])
        cv.put(x - 2, top - 1, "/_:_\\", CONFETTI[3])
        cv.cell(x, top - 2, ":", SUN)
        cv.cell(x, top - 1, ":", SUN)

    def _controller(self, cv, tick, x, y):
        """Sim time: a little pad on a card, its buttons lighting in turn."""
        self._card(cv, x, y + 1, 16, 6, "SIM", "GO")
        cv.put(x + 3, y + 3, ".-----.", TEXT_DIM, bg=RAISED)
        cv.put(x + 2, y + 4, "( +  oo )", TEXT_DIM, bg=RAISED)
        cv.put(x + 3, y + 5, "'-' '-'", TEXT_DIM, bg=RAISED)
        cv.cell(x + 4, y + 4, "+", TEXT, RAISED)
        cv.cell(x + 7, y + 4, "o", GOOD, RAISED)
        cv.cell(x + 8, y + 4, "o", (ACCENT, BAD, GOOD, WARN)[(tick // 3) % 4], RAISED)

    # -- Pip -------------------------------------------------------------------------

    def _probe(self, cv, state, tick, x0, top, mood="calm", scene=frozenset(), fidget=None):
        idle = state == "idle"
        tired = state == "error" or (idle and mood in ("sad", "sleepy"))
        foil = FOIL_DIM if tired else FOIL
        cell = CELL_DIM if tired else CELL
        t = tick % 90 - 72
        # the solar panels first, so the struts sit over their inner edges;
        # they sag a row when it is tired or worried, and one waves
        sag = 1 if tired or (idle and mood == "worried") else 0
        for side, px in enumerate(PANEL_X):
            dy = sag
            if fidget == "wave" and side == 1:
                dy = -((tick // 3) % 2)
            for i, r in enumerate(PANEL_ROWS):
                cv.sprite(x0 + px, top + 2 + dy + i, r, OUTLINE)
            for i in (1, 2):
                for c in range(1, 4):
                    cv.recolour(x0 + px + c, top + 2 + dy + i, CELL_LINE, cell)
            # the glint running across the cells (the glint fidget, and now
            # and then by itself)
            g = None
            if fidget == "glint":
                g = t // 2 - side * 4
            elif not tired and tick % 120 < 8:
                g = (tick % 120) - side * 4
            if g is not None and 0 <= g < 4:
                for i in (1, 2):
                    cv.recolour(x0 + px + 1 + min(2, g), top + 2 + dy + i, bg=GLINT)
            if "cold" in scene:
                cv.cell(x0 + px + (1 if side == 0 else 3), top + 2 + dy + 2, "*", SNOW, cell)
        for i, r in enumerate(PROBE):
            if r is not None:
                cv.sprite(x0, top + i, r, OUTLINE)
        for i in (3, 4):
            for c in range(7, 12):
                cv.recolour(x0 + c, top + i, bg=foil)
        # the dish: it sweeps while thinking and in the sweep fidget
        gaze_d = 0
        if state == "thinking":
            gaze_d = (0, 1, 0, -1)[(tick // 10) % 4]
        elif fidget == "sweep":
            gaze_d = -1 if t < 9 else 1
        cv.put(x0 + 6 + gaze_d, top, DISH_ROW, DISH, solid=True)
        # the LED at its feed: a slow green blink; steady while it works,
        # red on error, a dim amber pulse in safe mode
        if state == "error":
            led = BAD if (tick // 3) % 2 else BAD_DIM
        elif idle and mood == "sleepy":
            led = WARN if tick % 40 < 4 else LED_OFF
        elif state in ("thinking", "tool", "writing", "done"):
            led = GOOD
        else:
            led = GOOD if tick % 16 < 3 else LED_OFF
        cv.cell(x0 + LED[0] + gaze_d, top + LED[1], "o", led)
        # face
        eye = "^" if state == "done" else "o"
        gaze = 1 if state in ("tool", "writing") else 0
        if state == "thinking":
            gaze = gaze_d
        mouth = {"done": "D", "error": "~", "thinking": "o"}.get(state, "v")
        if state == "writing":
            mouth = "o-o-v-"[(tick // 2) % 6]
        left = right = eye
        cheek = "~" if state in ("done", "idle") else ""
        if idle and mood in MOOD_FACE:
            left, right, mouth, cheek = MOOD_FACE[mood]
            if mood == "shy":
                gaze = -1                   # looking away
            elif mood == "curious":
                gaze = 1                    # at the "?"
            elif mood == "worried":
                gaze = (0, -1, 0, 1)[(tick // 8) % 4]
        elif mood == "shy" and state != "error":
            cheek = "/"                     # at work only the accents
        elif mood in ("happy", "excited") and state != "error":
            cheek = "~"
            if mood == "excited" and state != "done" and tick % 20 < 3:
                left = right = "*"          # a twinkle in the eye
        if state == "error":
            left, right = "x", "x"
        if fidget == "sweep":
            gaze = gaze_d
        elif fidget == "yawn":
            left = right = "-"
            mouth = "O" if 3 <= t < 14 else "o"
        elif fidget == "ping":
            mouth = "o"
        shut = blink(tick, 47) and state not in ("done", "error")
        for ex, ch in zip(EYES, (left, right)):
            cv.cell(x0 + ex + gaze, top + 3, "-" if shut else ch, INK, foil)
        cv.cell(x0 + MOUTH[1] + gaze, top + MOUTH[0], mouth, INK, foil)
        if mood in BROWS and state != "done":
            for ex, ch in zip(EYES, BROWS[mood]):
                cv.cell(x0 + ex + gaze, top + 2, ch, OUTLINE)
        if cheek:
            cv.cell(x0 + 7, top + 4, cheek, CHEEK, foil)
            cv.cell(x0 + 11, top + 4, cheek, CHEEK, foil)
        # sweat / a tear
        if state == "error" or ((mood == "worried" or "hot" in scene) and state != "done"):
            s = (tick // 5) % 4
            if s < 3:
                cv.cell(x0 + 13, top + s, "',."[s], SWEAT)
        if mood == "sad" and idle:
            s = (tick // 6) % 3
            if s < 2:
                cv.cell(x0 + EYES[0] + gaze, top + 4 + s, ",'"[s], SWEAT, foil if s == 0 else None)

    def _mood_marks(self, cv, state, tick, ox, top, mood, scene, fidget):
        """What floats around it for its mood and scene: z's, a "?", "!"s,
        a ping off the dish, music notes, heat shimmer."""
        idle = state == "idle"
        t = tick % 90 - 72
        if idle and mood == "sleepy":
            s = tick % 36
            for j in range(3):
                if s // 9 > j:
                    cv.cell(ox + 14 + j, top - j, "zzZ"[j], TEXT_DIM if j < 2 else TEXT)
        elif idle and mood == "curious" and (tick // 5) % 4:
            cv.cell(ox + 14, top, "?", ACCENT)
        elif idle and mood == "excited" and (tick // 3) % 4 < 2:
            cv.cell(ox + 4, top, "!", WARN)
            cv.cell(ox + 14, top, "!", WARN)
        elif mood == "excited" and state in ("thinking", "tool", "writing", "done"):
            if (tick // 3) % 4 == 0:
                cv.cell(ox + 14, top, "+", SUN)
        if fidget == "ping" and t >= 2:
            s = (t - 2) // 3
            if s < 3:
                w = 3 + 2 * s
                cv.put(ox + 9 - w // 2, top - 1 - s, "-" * w, ACCENT if s < 2 else ACCENT_DIM)
            if t >= 8:
                cv.put(ox + 12, top - 2, "PING", TEXT_DIM)
        if "music" in scene:
            for j in range(2):
                s = (tick + j * 12) % 24
                if s < 20:
                    cv.cell(ox - 1 - s // 6 - j * 2, top + 5 - s // 5, "db"[j], NOTE[j])
        if "hot" in scene:
            for side, px in enumerate(PANEL_X):
                if lcg(211, side, tick // 3)() < 0.6:
                    cv.cell(ox + px + 1 + (tick // 3 + side) % 3, top + 1, "~", WARN)

    # -- things beside it ------------------------------------------------------------

    def _card(self, cv, x, y, w, h, title, status=None, status_colour=GOOD, body=RAISED):
        """A console card: a header row (a teal tab at the left, the label
        in uppercase, a status word at the right), the body under it."""
        cv.fill(x, y, w, h, body)
        cv.fill(x, y, w, 1, HEAD)
        cv.recolour(x, y, bg=ACCENT)
        cv.put(x + 2, y, title[:w - 3], TEXT_DIM, bg=HEAD)
        if status and len(title) + len(status) + 4 <= w:
            cv.put(x + w - len(status) - 1, y, status, status_colour, bg=HEAD)

    def _rings(self, cv, tick, ox, top):
        """Radio rings rising off the dish while it thinks."""
        s = (tick // 3) % 4
        if s < 3:
            w = 3 + 2 * s
            cv.put(ox + 9 - w // 2, top - 1 - s, "-" * w, ACCENT if s < 2 else ACCENT_DIM)

    def _scope(self, cv, tick, x, y):
        """Thinking: an oscilloscope trace rolling across a COMPUTE card."""
        self._card(cv, x, y, 16, 7, "COMPUTE", "PROC", ACCENT)
        for c in range(14):
            v = math.sin((c + tick * 0.6) / 2.0) * 1.6 + math.sin((c * 3 + tick) / 5.0) * 0.4
            r = max(-2, min(2, int(round(v))))
            nxt = math.sin((c + 1 + tick * 0.6) / 2.0) * 1.6
            ch = "-" if abs(nxt - v) < 0.4 else ("/" if nxt > v else "\\")
            cv.cell(x + 1 + c, y + 3 - r, ch, ACCENT, RAISED)
        cv.put(x + 1, y + 6, ("PROC" + "." * ((tick // 4) % 4)).ljust(14), TEXT_DIM, bg=RAISED)

    def _doc(self, cv, tick, x, y, stream=False, title="READ", status=None):
        """A card holding lines of text: older lines dim, the newest bright."""
        self._card(cv, x, y, 16, 7, title, status, ACCENT)
        lines = self._stream
        if stream:
            total = tick % (len(lines) * 12)
            li, col = divmod(total, 12)
        else:
            li, col = tick // 6, 12
        for k in range(5):
            j = li - 4 + k
            if j < 0:
                continue
            text = lines[j % len(lines)] if j < li else lines[j % len(lines)][:col]
            cv.put(x + 2, y + 1 + k, text, TEXT if k == 4 else TEXT_DIM, bg=RAISED)
        if stream and (tick // 3) % 2:
            cv.cell(x + 2 + min(col, 11), y + 5, "_", ACCENT, RAISED)

    def _signal(self, cv, tick, ox, top, px, py):
        """Signal dots flying from the dish over to the card: each one an
        arc from the dish's rim to the card's edge."""
        x0, y0 = ox + 13, top
        x1, y1 = px, py + 2
        for k in range(3):
            s = ((tick + k * 6) % 18) / 18.0
            x = int(round(x0 + (x1 - x0) * s))
            y = int(round(y0 + (y1 - y0) * s - 2.0 * math.sin(s * math.pi)))
            if cv.get(x, y) == " ":
                cv.cell(x, y, "*" if k == 0 else ".", ACCENT)

    def _go(self, cv, tick, x, y):
        """Done: a STATUS card, ALL SYSTEMS GO and a green check."""
        self._card(cv, x, y + 1, 16, 5, "STATUS", "GO")
        cv.put(x + 1, y + 3, "v/", GOOD, bg=RAISED)
        cv.put(x + 4, y + 3, "ALL SYSTEMS", TEXT, bg=RAISED)
        cv.put(x + 4, y + 4, "GO", GOOD, bg=RAISED)
        cv.put(x + 7, y + 4, "NOMINAL", TEXT_DIM, bg=RAISED)
        r = lcg(203, tick // 3)
        for _ in range(4):
            sx, sy = x + int(r() * 16), y + int(r() * 7)
            if cv.get(sx, sy) == " ":
                cv.cell(sx, sy, "+*."[int(r() * 3)], STAR)

    def _caution(self, cv, tick, x, y):
        """An error: a MASTER CAUTION card, its header blinking amber."""
        on = (tick // 4) % 2
        cv.fill(x, y + 1, 16, 5, RAISED)
        cv.fill(x, y + 1, 16, 1, WARN if on else HEAD)
        cv.put(x + 1, y + 1, "MASTER CAUTION", ON_ACCENT if on else WARN, bg=WARN if on else HEAD)
        cv.put(x + 1, y + 3, "(x)", BAD if on else BAD_DIM, bg=RAISED)
        cv.put(x + 5, y + 3, "NO-GO", BAD, bg=RAISED)
        cv.put(x + 5, y + 4, "Recycle?", TEXT_DIM, bg=RAISED)

    def _sparkles(self, cv, tick, x, y, n=5):
        for j in range(n):
            r = lcg(207, j)
            period = 24 + int(r() * 16)
            t = (tick + int(r() * period)) % period
            sx = x + int(r() * 12)
            sy = y - int(r() * 5)
            if t < period * 2 // 3 and cv.get(sx, sy) == " ":
                cv.cell(sx, sy, "*+."[(t // 4 + j) % 3], (SUN, STAR, ACCENT)[j % 3])

    def _prop_bash(self, cv, tick, x, y):
        self._card(cv, x, y, 16, 7, "TERMINAL", "EXEC", ACCENT, body=BASE)
        cyc = tick // 30
        cmd = CMDS[cyc % len(CMDS)]
        n = min(len(cmd), (tick % 30) // 2)
        for k in range(3):
            prev = CMDS[(cyc - 3 + k) % len(CMDS)]
            cv.put(x + 1, y + 1 + k, ("> " + prev)[:14], TEXT_DIM, bg=BASE)
        cv.put(x + 1, y + 5, ("> " + cmd[:n])[:14], TEXT, bg=BASE)
        if (tick // 3) % 2:
            cv.cell(x + 3 + n, y + 5, "_", ACCENT, BASE)

    def _prop_book(self, cv, tick, x, y):
        self._doc(cv, tick, x, y, title="READ")
        hot = (tick // 3) % 5
        for c in range(14):
            cv.recolour(x + 1 + c, y + 1 + hot, TEXT, RULE_HI)

    def _prop_pad(self, cv, tick, x, y):
        self._doc(cv, tick, x, y, stream=True, title="EDIT", status="UPLK")

    def _prop_lens(self, cv, tick, x, y):
        self._card(cv, x, y, 16, 7, "SCAN", "EXEC", ACCENT)
        cv.fill(x + 1, y + 1, 14, 1, BASE)
        q = "files"
        n = min(len(q), (tick % 40) // 3)
        cv.put(x + 2, y + 1, ">" + q[:n], TEXT, bg=BASE)
        hit = (tick // 5) % 4
        for k, f in enumerate(FILES):
            cv.put(x + 3, y + 2 + k, f.ljust(12), TEXT if k == hit else TEXT_DIM,
                   bg=RULE_HI if k == hit else RAISED)
        cv.put(x + 1, y + 2 + hit, ">", ACCENT, bg=RAISED)

    def _prop_globe(self, cv, tick, x, y):
        self._card(cv, x, y, 16, 7, "DOWNLINK", "AOS")
        cv.put(x + 1, y + 2, ("(@)", "(o)", "(@)", "(O)")[(tick // 4) % 4], ACCENT, bg=RAISED)
        cv.put(x + 5, y + 2, "page.html", TEXT, bg=RAISED)
        pct = (tick * 2) % 101
        cv.put(x + 5, y + 3, ("%d%%" % pct).ljust(5), TEXT_DIM, bg=RAISED)
        bx, by, bw = x + 1, y + 5, 14
        cv.fill(bx, by, bw, 1, BASE)
        filled = int(pct / 100.0 * bw)
        for c in range(bw):
            cv.cell(bx + c, by, "=" if c < filled else "-", ACCENT if c < filled else RULE_HI, BASE)

    def _helpers(self, cv, tick):
        """Two relay drones bobbing either side, and a RELAY card."""
        for n, x in enumerate((max(0, self.cx - 7), min(self.cols - 6, self.cx + COMP_W + 1))):
            y = self.ground - 5 - (1 if math.sin(tick / 5.0 + n * 2) > 0 else 0)
            cv.put(x, y, "  _  ", DISH)
            cv.put(x, y + 1, "=[o]=", OUTLINE)
            cv.cell(x + 2, y + 1, "o", INK, FOIL)
            cv.cell(x + 2, y, "_", GOOD if (tick // 4 + n) % 3 == 0 else DISH)
        px, py = self.cx + PW + 2, self.ground - 8
        self._card(cv, px, py, 16, 5, "RELAY", "AOS")
        k = (tick // 8) % 3
        cv.put(px + 1, py + 2, ("handover" + "." * k).ljust(11), TEXT, bg=RAISED)
        cv.put(px + 1, py + 3, "2 drones", TEXT_DIM, bg=RAISED)

    def _prop_todo(self, cv, tick, x, y):
        self._card(cv, x, y, 16, 5, "CHECKLIST")
        done = 1 + (tick // 12) % len(TODO)
        for k, item in enumerate(TODO):
            mark = "[x]" if k < done else "[ ]"
            cv.put(x + 1, y + 1 + k, mark, GOOD if k < done else TEXT_DIM, bg=RAISED)
            cv.put(x + 5, y + 1 + k, item, TEXT_DIM if k < done else TEXT, bg=RAISED)

    def _prop_wand(self, cv, tick, x, y):
        """Anything else: a comet streaking by, sparkles in its wake."""
        s = tick % 30
        cx = x + min(13, s // 2)
        cy = y + 5 - min(4, s // 6)
        cv.put(cx - 3, cy, "~~~", ACCENT_DIM)
        cv.cell(cx, cy, "*", SUN)
        self._sparkles(cv, tick, x + 2, y + 5, n=6)
