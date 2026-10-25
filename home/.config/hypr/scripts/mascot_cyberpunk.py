#!/usr/bin/env python3
"""The cyberpunk theme's mascot: a neon android with a visor, in front of a
rainy night skyline. Same API as moe_mascot.Mascot (mascots.py picks it).

    city      the stage card (#07090f in llm-chat.css, with CSS
              scanlines over it): a skyline along the bottom painted as cell
              backgrounds, its windows lit in cyan, magenta and yellow and
              now and then flickering, a neon sign, thin slanted rain, a
              hover car crossing the sky; a scan line sweeps down the
              picture, brightening what it passes
    android   21 x 11 cells: antenna, a helmet with a visor -- a strip of
              dark cells the eyes are drawn on, which is also the scanner
              that sweeps across it while it thinks -- a mouth grille, a
              chest core that pulses cyan to magenta, plated arms
    props     a holo panel to its right (bg-filled cells, cyan frame): a
              shell for Bash, a data shard and hex for Read, code being
              rewritten for Edit/Write, a targeting reticle over the data
              for the searches, a turning wireframe globe and packets for
              WebFetch, the gig list for TodoWrite, ICE-breaker sparks for
              anything else; two drones hover in for Task/Agent; thinking
              fills the neural-net bars, done says JOB DONE
    glitch    a frame or two of torn rows and magenta ghosts every few
              seconds; on error most frames, the visor's eyes red Xs and the
              panel SIGNAL LOST

mood= and scene= (mascot_mood.py) are drawn:

    mood      the visor is the face: its glyphs and colour per mood -- calm
              o o cyan, happy ^ ^ green, excited * * yellow (it bounces, "!"
              sparks), shy > < magenta with // blush and a <3 rising,
              curious o O and a "?", focused \\o o/ bright with lock-on marks,
              worried /o o\\ yellow with a coolant drip, sad T T violet,
              tears and a drooping antenna, sleepy - - dim with z's; the
              grille, the core and the holo's status line follow. At work
              the visor keeps the work face in the mood's colour and accents
              (blush, drip, tears); sleepy is never shown working. The idle
              fidget each 9-second round (a visor scan, a wave, an antenna
              ping, a twitch, a power dip) is weighted by the mood.
    scene     day (windows off, a smog sun) and night (a moon), sun (an
              outrun sun behind the towers), cloud (smog banks), rain and
              storm (a downpour in front, a holo umbrella on the antenna,
              lightning), snow, fog (drifting bands), hot (shimmer, a drip,
              THERMAL on the holo), cold (a neon scarf, breath), music
              (headphones, notes, an EQ), game (invaders on the holo, idle),
              party (a party hat, confetti), festive (neon papel picado
              along the top), clock (an ALARM tab on the holo and a ringing
              sign when there is room).

Neon cyan #00f0ff and magenta #ff2a6d on the dark, yellow #f9f002 for
sparks, the theme's grey-blue #c8d3e6 for steel.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import STATES, BaseMascot, Canvas, blink, lcg, prop_kind, stream_lines  # noqa: E402
from mascot_mood import ACTIVE, MOODS, word  # noqa: E402

THEME = "cyberpunk"
PANEL = "#07090f"

CYAN = "#00f0ff"
CYAN_DIM = "#0a8f9c"
MAGENTA = "#ff2a6d"
MAGENTA_DIM = "#8f1a44"
YELLOW = "#f9f002"
VIOLET = "#b026ff"
GREEN = "#39ff14"
STEEL = "#c8d3e6"
STEEL_DIM = "#5a6478"
BRIGHT = "#e6fcff"
RAIN = "#1d5f6e"
BUILDING = ("#0d1424", "#111a30", "#0b1020")
VISOR = "#1e0a22"
HOLO = "#04161e"
PINK = "#ff6ec7"

# The reaction sign over the head (mascot_mood.EMOTE_TONES), all >= 4.4:1 on
# PANEL and on the towers behind the anchor (BUILDING).
EMOTE_COLOURS = {"accent": CYAN, "warn": YELLOW, "bad": MAGENTA, "good": GREEN,
                 "love": PINK, "dim": CYAN_DIM}

W, H = 21, 11
DROID = [
    "         _|_         ",
    "      .-'---'-.      ",
    "     /  _____  \\     ",
    "    |  [     ]  |    ",
    "    |   \\___/   |    ",
    "     \\  '---'  /     ",
    "  .---'-.___.-'---.  ",
    " /  |  [     ]  |  \\ ",
    "|_  |  [_____]  |  _|",
    "  \\_|   |   |   |_/  ",
    "    |___|   |___|    ",
]
VISOR_X, VISOR_Y, VISOR_W = 8, 3, 5      # the five cells inside [ ]
CORE = (7, 10)

PW, PH = 16, 8                            # the holo panel
COMP_W = W + 1 + PW
DRONE = (" _-_ ", "=(o)=", " ' ' ")

CODE = ("jack", "in", "ice", "0xff", "run", "net", "chrome", "if", "ok", "go",
        "sys", "{", "}", "=>", "fn", "ret", "edge", "neon")
CMDS = ("nmap -sV", "ssh v@c", "make", "ls -la", "./ice", "ping 0")
GIGS = ("jack in", "find data", "break ICE", "get paid")

# Per mood: the idle visor (five cells), its colour, the grille (three cells,
# None: as drawn) and the holo's status line.
MOOD_FACE = {
    "calm": ("o   o", CYAN, None, ("SYS:ONLINE", CYAN)),
    "happy": ("^   ^", GREEN, "_v_", ("MOOD:PREEM", GREEN)),
    "excited": ("*   *", YELLOW, "=-=", ("MOOD:NOVA!!", YELLOW)),
    "shy": (">   <", MAGENTA, "...", ("VISOR:HOT", MAGENTA)),
    "curious": ("o   O", CYAN, "_o_", ("QUERY?", YELLOW)),
    "focused": ("\\o o/", BRIGHT, "---", ("TGT:LOCKED", BRIGHT)),
    "worried": ("/o o\\", YELLOW, "~~~", ("! WARNING", YELLOW)),
    "sad": ("T   T", VIOLET, "-^-", ("SIGNAL:LOW", VIOLET)),
    "sleepy": ("-   -", CYAN_DIM, None, ("LOW POWER", CYAN_DIM)),
}
# ... and at work (tool), the eyes glancing at the panel.
WORK_FACE = {
    "happy": " ^  ^", "excited": " *  *", "shy": " >  <", "curious": " o  O",
    "focused": "\\o o/", "worried": "/o o\\", "sad": " T  T",
}
# The idle fidget a mood favours: (name, weight); "rest" is none at all.
FIDGETS = {
    "calm": (("scan", 1),),
    "happy": (("wave", 3), ("scan", 1), ("ping", 1)),
    "excited": (("wave", 2), ("ping", 2), ("twitch", 1)),
    "shy": (("scan", 1), ("rest", 3)),
    "curious": (("scan", 3), ("ping", 2)),
    "focused": (("scan", 2), ("rest", 3)),
    "worried": (("scan", 2), ("twitch", 2), ("rest", 1)),
    "sad": (("rest", 3), ("twitch", 1)),
    "sleepy": (("dip", 2), ("rest", 2)),
}
CONFETTI = (CYAN, MAGENTA, YELLOW, GREEN, VIOLET)

# A holo umbrella on the antenna (rain, storm), aligned to the droid's columns.
UMBRELLA = ("    .-~~~~~~~~~-.    ",
            "   /_/_/_/|\\_\\_\\_\\   ")

MOOD_BUBBLES = {
    "happy": "[SYS] mood.exe: preem. Ready when you are, choom.",
    "excited": "Overclocked and buzzing! What's the gig, choom?",
    "shy": "Visor's running hot... d-don't stare, choom.",
    "curious": "Query pending... what's next on the grid?",
    "focused": "Target locked. Feed me the next job.",
    "worried": "[WARN] Something's off in the net...",
    "sad": "Signal's weak. Like tears in rain...",
    "sleepy": "Low power mode... zz... ping me if you need me.",
}
# mascot_mood topics in its words (str.format with the topic's arguments).
TOPIC_LINES = {
    "thanks": "No sweat, choom. That's what the chrome's for.",
    "worried": "[WARN] That didn't go nova...",
    "frustrated": "Delta again?! Rerouting... one more run.",
    "relieved": "Signal's back. All green, choom.",
    "determined": "Long run. Holding the line.",
    "proud": "Gig's done. Preem work, if I say so myself.",
    "sad": "Sorry, choom... my bad.",
    "happy": "Nova! mood.exe maxed out.",
    "curious": "Hmm. Running a query on that...",
    "rain": "Rain on the neon. Grab an umbrella, choom.",
    "storm": "Storm's frying the grid. Stay inside.",
    "snow": "Snow on the chrome. Static from the sky.",
    "fog": "Smog's thick tonight. Visibility: delta.",
    "sun": "Sun's out. Even the neon looks washed out.",
    "hot": "[SYS] thermal warning: {0} outside.",
    "cold": "Coolant's freezing: {0} outside.",
    "gpu_hot": "[SYS] GPU thermal warning: {0}°C",
    "cpu_hot": "[SYS] CPU thermal warning: {0}°C",
    "music": "Preem track. Turning up the bass.",
    "game": "Game time. Let's frag some ICE.",
    "event": "[REMINDER] {0} in {1} min, choom.",
    "event_now": "[ALERT] {0} is starting. Jack in.",
    "birthday": "It's {0}'s birthday. Nova!",
    "holiday": "Today's {0}. Neon's on the house.",
    "go_home": "{0}. Shift's over, choom -- jack out, go home.",
    "bedtime": "{0}. Low power mode recommended: go to bed.",
    "morning": "Morning, choom. Systems booting.",
    "lunch": "Lunch break? Even androids recharge.",
    "weekend": "Weekend. No gigs, just neon.",
    "friday": "Friday night. The neon's calling, choom.",
    "hello": ("Online. What's the gig, choom?", "[SYS] link up. Ready to run.",
              "Hey, choom. Jack in, let's work."),
    "welcome_back": "Welcome back, choom. Kept the neon warm.",
    "wake": "[SYS] exiting low power... I'm up!",
    "long_prompt": "Big data dump. Buffering, choom...",
    "code": "Code-chrome incoming. Scanning it.",
    "image": ("Optics engaged. Nice pic, choom.", "Running it through the optics..."),
    "aborted": "[ABORT] Jacking out. Run killed.",
    "tests_pass": ("Tests green. Preem.", "[OK] All checks passed. Nova!",
                   "ICE cleared: the suite's green."),
    "tests_fail": ("[FAIL] Tests flatlined, choom.", "Red on the board. Rerouting..."),
    "commit": ("Pushed to the net. Shipped.", "Commit burned to shard. Preem.",
               "[SYS] payload delivered."),
    "fast": ("Quick hack. Too easy.", "In and out. Zero trace.",
             "Done before the ICE woke up."),
    "busy": "Running a dozen daemons at once...",
    "model": "[SYS] new wetware loaded: {0}",
    "poke": ("Hey! Watch the chrome, choom.", "[PING] ...pong.", "Easy, the visor's sensitive.",
             "Need something? I'm all sensors.", "Tap registered. Hi, choom.",
             "Careful. I bite in binary."),
    "poke_spam": ("[ALERT] Input flood! Back off, choom!", "Poke me again and I call MaxTac."),
    "pet": ("...preem. Keep that up, choom.", "[SYS] affection.exe: running.",
            "Visor's going pink... d-don't stop."),
}


class Mascot(BaseMascot):
    BUBBLES = {
        "idle": "Systems online. Awaiting input, choom.",
        "thinking": "Running the neural net…",
        "writing": "Uploading thoughts to the grid…",
        "done": "Job's done. Preem work.",
        "error": "ERR::SIGNAL LOST. Rebooting…",
    }
    TOOL_BUBBLES = {
        "Bash": "Jacking into the shell…",
        "Read": "Scanning a data shard…",
        "Edit": "Rewriting the code-chrome…",
        "MultiEdit": "Rewriting the code-chrome…",
        "Write": "Burning a new shard…",
        "NotebookEdit": "Patching the notebook…",
        "Grep": "Tracing the pattern through the net…",
        "Glob": "Sweeping the file grid…",
        "WebSearch": "Pinging the net…",
        "WebFetch": "Pulling data off the net…",
        "Task": "Deploying drones…",
        "Agent": "Deploying drones…",
        "TodoWrite": "Updating the gig list…",
    }
    OTHER = "Running %s.exe…"
    moods = True        # draws mascot_mood's moods and scenes (the frontend asks)

    def __init__(self, cols=64, rows=18):
        self.cols = max(int(cols), COMP_W + 2)
        self.rows = max(int(rows), H + 2)
        self.cx = (self.cols - COMP_W) // 2
        self.top = self.rows - 1 - H
        self._stream = stream_lines(CODE, PW - 3, seed=67)
        # the skyline: buildings of random width and height
        self._city = []
        x, i = 0, 0
        while x < self.cols:
            r = lcg(113, i, self.cols)
            w = 3 + int(r() * 6)
            h = 3 + int(r() * max(3, self.rows // 2 - 1))
            self._city.append((x, w, h, i))
            x += w + (1 if r() < 0.3 else 0)
            i += 1
        self._sign = self._city[len(self._city) * 3 // 4] if len(self._city) > 2 else None

    # -- public ----------------------------------------------------------------------

    def lines(self, state, tick, tool=None, mood=None, scene=()):
        return self._render(state, tick, tool, mood, scene).lines()

    def markup(self, state, tick, tool=None, mood=None, scene=()):
        return self._render(state, tick, tool, mood, scene).markup()

    def say(self, topic):
        return word(TOPIC_LINES, topic)

    def bubble(self, state, tool=None, mood=None):
        if state == "idle" and mood in MOOD_BUBBLES:
            return MOOD_BUBBLES[mood]
        return BaseMascot.bubble(self, state, tool, mood)

    # -- composition ---------------------------------------------------------------

    def _render(self, state, tick, tool, mood=None, scene=()):
        if state not in STATES:
            state = "idle"
        if mood not in MOODS:
            mood = "calm"
        if mood == "sleepy" and state in ACTIVE:
            mood = "focused"        # never dozes on the job
        scene = frozenset(scene or ())
        tick = int(tick)
        cv = Canvas(self.cols, self.rows)
        kind = prop_kind(tool) if state == "tool" else None
        idle = state == "idle"
        wet = bool(scene & {"rain", "storm"})
        # the band of sky the papel picado takes
        sky = 3 if "festive" in scene else 0

        # vertical position: done hops, excited bounces, music bobs
        dy = 0
        if state == "done":
            dy = (0, 1, 1, 0, 0, 0)[tick % 6]
        elif idle and mood == "excited" and (tick // 30) % 2:
            dy = (0, 1, 1, 0, 0, 0)[tick % 6]
        elif idle and "music" in scene and mood not in ("sad", "sleepy"):
            dy = (tick // 4) % 2
        top = self.top - min(dy, self.top - 1)
        # the emote anchor: just right of the helmet's crown, clear of the
        # visor, under the umbrella's rim; never up in the papel picado band
        self.head = (self.cx + 15, max(top + 1, sky))

        self._sky(cv, tick, scene, sky)
        self._skyline(cv, tick, day="day" in scene)
        if "storm" in scene:
            self._lightning(cv, tick, sky)
        if "fog" in scene:
            self._fog(cv, tick)
        self._car(cv, tick, sky)
        if "snow" in scene:
            self._snow(cv, tick)
        # the umbrella (rain, storm), when its lower row is on the stage,
        # and where it keeps dry
        party = "party" in scene
        umbrella = wet and top - (3 if party else 2) >= 0
        dry = self._dry(top, party) if umbrella else None
        if wet or not scene & {"sun", "snow"}:
            self._rain(cv, tick, dry)
        if "festive" in scene:
            self._banner(cv, tick)
        if "hot" in scene:
            self._shimmer(cv, tick)
        if kind == "helpers":
            self._drones(cv, tick)
        if "clock" in scene:
            self._alarm(cv, tick)
        self._droid(cv, state, tick, kind, top, mood, scene)
        self._holo(cv, state, tick, kind, mood, scene)

        if umbrella:
            self._umbrella(cv, top, party)
        if party:
            self._hat(cv, tick, top, star=not umbrella)
        if wet and state != "error":
            self._downpour(cv, tick, dry, heavy="storm" in scene)
        if "party" in scene:
            self._confetti(cv, tick)
        self._mood_marks(cv, state, tick, top, mood, scene)
        self._scanline(cv, tick)
        if state == "error" or tick % 47 in (0, 1) or (idle and self._fidget(tick, mood) == "twitch"
                                                       and tick % 3 == 0):
            self._glitch(cv, tick, heavy=state == "error")
        return cv

    def _fidget(self, tick, mood):
        """The idle fidget now: one per 90-tick round, in its last 9 ticks,
        picked by the round's noise from what the mood favours; None the
        rest of the time (and for "rest")."""
        if tick % 90 <= 80:
            return None
        table = FIDGETS.get(mood, FIDGETS["calm"])
        pick = lcg(43, tick // 90)() * sum(w for _, w in table)
        for name, weight in table:
            pick -= weight
            if pick < 0:
                return None if name == "rest" else name
        return None

    # -- the city -------------------------------------------------------------------

    def _skyline(self, cv, tick, day=False):
        bottom = self.rows - 1
        for x, w, h, i in self._city:
            bg = BUILDING[i % len(BUILDING)]
            top = bottom - h + 1
            cv.fill(x, top, w, h, bg, occupy=False)
            r = lcg(127, i)
            for yy in range(top + 1, bottom + 1, 2):
                for xx in range(x + 1, x + w - 1, 2):
                    v = r()
                    # by day most windows are dark
                    if v < (0.82 if day else 0.45):
                        continue
                    colour = (CYAN_DIM, MAGENTA_DIM, "#8f8a10", STEEL_DIM)[int(v * 97) % 4]
                    # a window that flickers
                    if v > 0.93 and (tick // 3 + xx) % 7 == 0:
                        continue
                    cv.cell(xx, yy, ".", colour, bg)
            cv.cell(x, top, "_" if w > 3 else ".", STEEL_DIM, bg)
            if h > 5 and i % 3 == 0:
                # an antenna light, blinking red
                cv.cell(x + w // 2, top - 1, "'", MAGENTA if (tick // 8 + i) % 3 else MAGENTA_DIM)
        if self._sign:
            x, w, h, i = self._sign
            top = bottom - h + 1
            word_ = "OPEN" if w >= 4 else "24"
            on = (tick // 2) % 23 not in (0, 3)
            cv.put(x + (w - len(word_)) // 2, top + 1, word_, MAGENTA if on else MAGENTA_DIM,
                   bg=BUILDING[i % len(BUILDING)])

    def _car(self, cv, tick, sky=0):
        period = 160
        t = tick % period
        if t > self.cols + 8:
            return
        y = sky + (1 if (tick // period) % 2 else 2)
        x = (t - 6) if (tick // period) % 2 == 0 else (self.cols - t)
        cv.put(x, y, "<=o=>", STEEL)
        cv.cell(x + 2, y, "o", CYAN)
        cv.cell(x - 1 if (tick // period) % 2 == 0 else x + 5, y, "~", MAGENTA_DIM)

    def _rain(self, cv, tick, dry=None):
        x_a, x_b, y_dry = dry or (0, -1, 0)
        n = self.cols * self.rows // 40
        for j in range(n):
            r = lcg(131, j)
            speed = 0.8 + r() * 0.5
            x0 = int(r() * (self.cols + self.rows))
            span = self.rows + 2
            y = int(r() * span + tick * speed) % span
            x = x0 - y // 2
            if y >= y_dry and x_a <= x <= x_b:
                continue
            if 0 <= x < self.cols and 0 <= y < self.rows and cv.get(x, y) == " ":
                cv.cell(x, y, "/" if j % 3 else ",", RAIN, cv.bg[y][x])

    def _scanline(self, cv, tick):
        """A bright line sweeping down the picture every few seconds."""
        period = self.rows + 30
        y = tick % period
        if y >= self.rows:
            return
        for x in range(self.cols):
            if cv.get(x, y) != " ":
                cv.recolour(x, y, BRIGHT)

    # -- the scene (mascot_mood.SCENES) ------------------------------------------------

    def _sky(self, cv, tick, scene, y):
        """Behind the towers: an outrun sun, a smog sun by day, a moon by
        night, smog banks when it is overcast."""
        overcast = bool(scene & {"cloud", "rain", "storm", "snow", "fog"})
        if "sun" in scene:
            rows = ("  .-~-.  ", " /=====\\ ", "(-------)")
            for k, r in enumerate(rows):
                cv.put(2, y + k, r, (YELLOW, YELLOW, MAGENTA)[k])
            # the stripes scroll down through it
            band = (tick // 6) % 3
            cv.put(4, y + 1, "=====" if band else "-----", MAGENTA if band == 1 else YELLOW)
        elif "day" in scene and not overcast:
            cv.put(2, y, ".-.", STEEL_DIM)
            cv.put(2, y + 1, "( )", STEEL_DIM)
            cv.put(2, y + 2, "'-'", STEEL_DIM)
        elif "night" in scene and not overcast:
            x = self.cols - 6
            cv.put(x, y, " _", STEEL)
            cv.put(x, y + 1, "( ", STEEL)
            cv.put(x, y + 2, " `-", STEEL)
        if overcast:
            self._clouds(cv, tick, y)

    def _clouds(self, cv, tick, y0):
        span = self.cols + 16
        for i in range(max(2, self.cols // 28)):
            r = lcg(47, i)
            y = y0 + (int(r() * 2) if self.rows >= 16 else 0)
            x = int(r() * span + tick / (9 + i * 3)) % span - 14
            cv.put(x, y, "  .-~~-.   ", STEEL_DIM)
            cv.put(x, y + 1, " (  ~~  )-.", STEEL_DIM)
            cv.put(x, y + 2, "(_________)", STEEL_DIM)

    def _lightning(self, cv, tick, y0):
        cyc, t = divmod(tick, 37)
        if t > 3:
            return
        x = int(lcg(53, cyc)() * (self.cols - 4)) + 1
        colour = YELLOW if t % 2 == 0 else BRIGHT
        # a zigzag of backslashes, against the rain's slant
        for k, (dx, ch) in enumerate(((0, "\\"), (1, "\\"), (1, "/"), (1, "\\"), (2, "\\"))):
            cv.cell(x + dx, y0 + 1 + k, ch, colour)
        if t == 0:
            # the flash: the whole sky lights up for a frame
            for yy in range(self.rows // 2):
                for xx in range(self.cols):
                    cv.recolour(xx, yy, BRIGHT)

    def _fog(self, cv, tick):
        for k, y in enumerate((self.rows // 3, self.rows // 2 + 1, self.rows - 3)):
            off = (tick // (6 + k * 2) + k * 7) % 12
            for x in range(self.cols):
                if (x + off) % 12 < 6 and (x + off) % 12 != 2:
                    cv.cell(x, y, "~-"[(x + k) % 2], STEEL_DIM)

    def _snow(self, cv, tick):
        span = self.rows + 2
        for i in range(max(6, self.cols * self.rows // 60)):
            r = lcg(59, i)
            speed = 0.05 + r() * 0.06
            pos = r() * span + tick * speed
            fall = int(pos // span)
            y = int(pos - fall * span) - 1
            x = int(lcg(61, i, fall)() * self.cols + (0, 1, 1, 0, 0, -1, -1, 0)[(tick // 5 + i) % 8])
            if cv.get(x, y) in (" ", "."):
                cv.cell(x, y, "*.+"[i % 3], BRIGHT if i % 2 else STEEL)

    def _banner(self, cv, tick):
        """Papel picado in neon: a cord along the top row, cut-paper flags
        (lit cells with a dark pattern) under it, their zigzag edge below."""
        for x in range(self.cols):
            cv.cell(x, 0, "~", STEEL_DIM)
        for n, x in enumerate(range(1, self.cols - 2, 5)):
            colour = CONFETTI[n % len(CONFETTI)]
            cut = ("o*o", "*o*", "x+x", "+x+")[(n + tick // 6) % 4]
            cv.put(x, 1, cut, PANEL, bg=colour)
            cv.put(x, 2, "VvV" if (tick // 4 + n) % 2 else "vVv", colour)

    def _shimmer(self, cv, tick):
        for y in (self.rows - 2, self.rows - 4):
            for x in range(self.cols):
                if lcg(67, x, y, tick // 3)() < 0.1 and cv.get(x, y) == " ":
                    cv.cell(x, y, "~", (YELLOW, MAGENTA_DIM)[x % 2], cv.bg[y][x])

    def _alarm(self, cv, tick):
        """An event soon: a ringing neon ALARM sign at the droid's feet on
        the left, when there is room for it (the holo carries a tab too)."""
        x, y = self.cx - 9, self.rows - 4
        if x < 2:
            return
        ring = (tick // 2) % 10 < 5
        shake = tick % 2 if ring else 0
        cv.sprite(x + shake, y, ".-----.", MAGENTA, bg=HOLO)
        cv.sprite(x + shake, y + 1, "|     |", MAGENTA, bg=HOLO)
        cv.put(x + shake + 1, y + 1, "ALARM" if ring or tick % 4 else "     ", YELLOW, bg=HOLO)
        cv.sprite(x + shake, y + 2, "'-----'", MAGENTA, bg=HOLO)
        if ring:
            cv.put(x - 2, y + 1, "((", YELLOW)
            cv.put(x + 8, y + 1, "))", YELLOW)

    def _hat(self, cv, tick, top, star=True):
        """A party hat in place of the antenna."""
        x = self.cx
        if star:
            cv.cell(x + 10, top - 2, "*+"[(tick // 4) % 2], YELLOW)
        cv.sprite(x + 9, top - 1, "/:\\", MAGENTA)
        cv.cell(x + 10, top - 1, ":", YELLOW)
        cv.sprite(x + 8, top, "/_:_\\", CYAN)
        cv.cell(x + 10, top, ":", YELLOW)

    def _dry(self, top, party=False):
        """The columns the umbrella keeps dry and the row below it."""
        return self.cx + 3, self.cx + 17, top - (2 if party else 1)

    def _umbrella(self, cv, top, party=False):
        """A holo umbrella with the antenna for its shaft (or over the party
        hat)."""
        x = self.cx
        y = top - (4 if party else 3)
        cv.sprite(x, y, UMBRELLA[0], CYAN)
        cv.sprite(x, y + 1, UMBRELLA[1], CYAN)
        cv.cell(x + 4, y, ".", MAGENTA)
        cv.cell(x + 16, y, ".", MAGENTA)
        cv.cell(x + 10, y + 1, "|", STEEL)
        cv.cell(x + 10, top - (2 if party else 1), "|", STEEL)

    def _downpour(self, cv, tick, dry, heavy=False):
        """Rain in front of everything, on the cells nothing covers, none
        under the umbrella; splashes along the bottom."""
        x_a, x_b, y_dry = dry or (0, -1, 0)
        span = self.rows + 2
        for j in range(self.cols * self.rows // (12 if heavy else 20)):
            r = lcg(73, j)
            speed = (1.2 if heavy else 0.9) + r() * 0.4
            x0 = int(r() * (self.cols + self.rows))
            y = int(r() * span + tick * speed) % span
            x = x0 - y // 2
            if y >= y_dry and x_a <= x <= x_b:
                continue
            if 0 <= x < self.cols and 0 <= y < self.rows and not cv.occ[y][x] and cv.get(x, y) == " ":
                cv.cell(x, y, "/" if j % 4 else "'", CYAN_DIM, cv.bg[y][x])
        y = self.rows - 1
        for x in range(self.cols):
            if lcg(79, x, tick // 2)() < (0.1 if heavy else 0.05) and cv.get(x, y) == " " \
                    and not cv.occ[y][x] and not x_a <= x <= x_b:
                cv.cell(x, y, "o."[tick % 2], CYAN_DIM, cv.bg[y][x])

    def _confetti(self, cv, tick):
        span = self.rows + 2
        for i in range(self.cols * self.rows // 70):
            r = lcg(83, i)
            y = int(r() * span + tick * (0.3 + r() * 0.2)) % span - 1
            x = int(r() * self.cols) + (0, 1, 0, -1)[(tick // 4 + i) % 4]
            if 0 <= x < self.cols and 0 <= y < self.rows and not cv.occ[y][x] and cv.get(x, y) == " ":
                cv.cell(x, y, "*,'."[i % 4], CONFETTI[i % len(CONFETTI)])

    # -- the android -----------------------------------------------------------------

    def _droid(self, cv, state, tick, kind, top, mood="calm", scene=frozenset()):
        x0 = self.cx
        idle = state == "idle"
        fidget = self._fidget(tick, mood) if idle else None
        low = mood in ("sad", "sleepy") and state not in ("done", "error")
        for i, r in enumerate(DROID):
            cv.sprite(x0, top + i, r, STEEL if i not in (6, 7, 8) else STEEL_DIM)
        # neon trim: helmet edge cyan, shoulders magenta (dim when low)
        for c in (6, 7, 13, 14):
            cv.recolour(x0 + c, top + 1, CYAN_DIM if low else CYAN)
        for c in (2, 3, 4, 5, 15, 16, 17, 18):
            cv.recolour(x0 + c, top + 6, MAGENTA_DIM if low else MAGENTA)
        # the antenna tip
        tip, tip_col = ("*" if (tick // 5) % 2 else "+"), MAGENTA
        if state == "error":
            tip_col = YELLOW
        elif mood == "sad" and state != "done":
            # drooping
            cv.cell(x0 + 10, top, "\\", STEEL)
            tip, tip_col = ".", MAGENTA_DIM
        elif mood == "sleepy":
            tip_col = MAGENTA_DIM
        elif mood == "excited":
            tip, tip_col = "*", CONFETTI[tick % 3]
        elif mood == "curious" and idle:
            tip, tip_col = "?", YELLOW
        if "clock" in scene and (tick // 3) % 2 and state != "error":
            tip, tip_col = "!", YELLOW
        cv.cell(x0 + (11 if mood == "sad" and state not in ("done", "error") else 10), top - 1, tip, tip_col)
        if fidget == "ping":
            t = tick % 90 - 81
            cv.put(x0 + 8 - t // 3, top - 1, "(", CYAN_DIM)
            cv.put(x0 + 12 + t // 3, top - 1, ")", CYAN_DIM)
        # hands: tapping while it works (or plays, or frets)
        tap = state in ("tool", "writing") or (idle and ("game" in scene or mood == "worried"))
        if tap and (tick // 3) % 2:
            cv.put(x0, top + 8, "|=", CYAN)
            cv.put(x0 + 19, top + 8, "=|", CYAN)
        if state == "done" or (idle and mood == "excited" and (tick // 30) % 2 and (tick // 6) % 2):
            cv.put(x0, top + 7, "\\o", CYAN)
            cv.put(x0 + 19, top + 7, "o/", CYAN)
        elif fidget == "wave":
            cv.put(x0 + 19, top + 7, "o/" if (tick // 2) % 2 else "o_", CYAN)
        # the chest core
        core = CYAN if (tick // 6) % 2 else MAGENTA
        if state == "error":
            core = MAGENTA if (tick // 2) % 2 else MAGENTA_DIM
        elif mood == "excited":
            core = CONFETTI[(tick // 2) % 3]
        elif low:
            core = CYAN_DIM if (tick // 12) % 2 else MAGENTA_DIM
        cv.put(x0 + 8, top + 7, "     ", STEEL, bg=VISOR)
        cv.cell(x0 + CORE[1], top + CORE[0], "@" if state in ("done", "tool") else "o", core, VISOR)
        if "cold" in scene:
            # a neon scarf at the neck
            for k, c in enumerate("=~=~=~="):
                cv.cell(x0 + 7 + k, top + 6, c, (MAGENTA, CYAN)[k % 2])
        if "music" in scene:
            # headphones
            for k in (3, 4):
                cv.cell(x0 + 3, top + k, "[", MAGENTA)
                cv.cell(x0 + 17, top + k, "]", MAGENTA)
        self._visor(cv, state, tick, x0 + VISOR_X, top + VISOR_Y, mood, fidget,
                    "game" in scene and idle)
        # the grille: glows while it talks, shaped by the mood when idle
        grille = MOOD_FACE[mood][2] if idle else None
        if idle and mood == "sleepy" and tick % 70 < 10:
            grille = "_O_"      # a yawn
        if grille:
            cv.put(x0 + 9, top + 4, grille, MOOD_FACE[mood][1])
        elif state in ("writing", "done") and (tick // 2) % 2:
            cv.put(x0 + 9, top + 4, "___", CYAN)
        if mood == "shy" and state != "error":
            cv.put(x0 + 5, top + 4, "//", MAGENTA)
            cv.put(x0 + 14, top + 4, "//", MAGENTA)

    def _visor(self, cv, state, tick, x, y, mood="calm", fidget=None, game=False):
        cells = [" "] * VISOR_W
        colour = CYAN if mood == "calm" else MOOD_FACE[mood][1]
        if state == "thinking":
            # the scanner: a bright dot sweeping to and fro, a tail behind it
            p = (tick // 2) % (VISOR_W * 2 - 2)
            pos = p if p < VISOR_W else VISOR_W * 2 - 2 - p
            for k in range(VISOR_W):
                d = abs(k - pos)
                cells[k] = "o" if d == 0 else ("=" if d == 1 else "-")
            colour = MAGENTA if mood == "calm" else colour
        elif state == "error":
            cells = list("x   x")
            colour = MAGENTA
        elif state == "done":
            cells = list({"excited": "*   *", "shy": ">   <"}.get(mood, "^   ^"))
        elif state == "writing":
            cells = ["=-_~"[int(lcg(137, k, tick // 2)() * 4)] for k in range(VISOR_W)]
        elif state == "tool" or game:
            cells = list(WORK_FACE.get(mood, " o  o"))
        else:
            cells = list(MOOD_FACE[mood][0])
            if mood == "sleepy" and (tick // 25) % 5 == 0:
                cells = list("o   o")     # awake, for a moment
            if fidget == "scan":
                p = (tick % 90) - 81
                cells = ["-"] * VISOR_W
                cells[min(VISOR_W - 1, p // 2)] = "o"
            elif fidget == "dip":
                # low power: the visor flickers out
                cells = list("_   _") if tick % 3 else [" "] * VISOR_W
        if blink(tick, 59) and state in ("idle", "tool"):
            cells = ["-" if c in "oO*^" else c for c in cells]
        for k, c in enumerate(cells):
            cv.cell(x + k, y, c, colour, VISOR)

    def _mood_marks(self, cv, state, tick, top, mood, scene):
        """What floats around it for its mood and scene: z's, a "?", "!"s,
        a <3, tears, a coolant drip, lock-on marks, notes, breath."""
        x0 = self.cx
        idle = state == "idle"
        if idle and mood == "sleepy":
            t = tick % 36
            for j in range(3):
                if t // 9 > j:
                    cv.cell(x0 + 18 + j, top + 2 - j, "zzZ"[j], CYAN_DIM if j < 2 else CYAN)
        elif idle and mood == "curious" and (tick // 5) % 4:
            cv.cell(x0 + 15, top, "?", YELLOW)
        elif idle and mood == "excited" and (tick // 3) % 4 < 2:
            cv.cell(x0 + 2, top + 1, "!", YELLOW)
            cv.cell(x0 + 18, top + 1, "!", YELLOW)
        elif idle and mood == "focused" and (tick // 10) % 3:
            cv.cell(x0 + 2, top + 3, ">", CYAN_DIM)
            cv.cell(x0 + 18, top + 3, "<", CYAN_DIM)
        elif mood in ("shy", "happy") and idle:
            t = tick % (30 if mood == "shy" else 60)
            if t < 12:
                cv.put(x0 + 17, top + 3 - t // 4, "<3", MAGENTA if mood == "shy" else GREEN)
        if mood == "sad" and state not in ("done", "error") and tick % 40 < 16:
            # tears down the face, from under the visor
            t = (tick % 40) // 4
            cv.cell(x0 + 7, top + 4 + t % 2, ",'"[t % 2], CYAN_DIM)
            if state == "idle":
                cv.cell(x0 + 13, top + 4 + (t + 1) % 2, ",'"[(t + 1) % 2], CYAN_DIM)
        if (mood == "worried" and state != "done") or "hot" in scene:
            # a coolant drip down the helmet
            t = tick % 16
            if t < 10:
                cv.cell(x0 + 17, top + 2 + (t >= 5), "'" if t < 5 else ",", CYAN)
        if "music" in scene and state != "error":
            for j in range(2):
                t = (tick + j * 12) % 24
                if t < 20:
                    cv.cell(x0 - 1 - t // 6 - j * 2, top + 5 - t // 5, "db"[j], (YELLOW, MAGENTA)[j])
        if "cold" in scene and idle:
            t = tick % 40
            if t < 12:
                cv.cell(x0 + 17 + t // 4, top + 4 - t // 6, ".oO"[min(2, t // 4)], BRIGHT)

    # -- the holo panel -----------------------------------------------------------------

    def _holo(self, cv, state, tick, kind, mood="calm", scene=frozenset()):
        x, y = self.cx + W + 1, self.top + 1
        frame = MAGENTA if state == "error" else CYAN_DIM
        cv.fill(x, y, PW, PH, HOLO)
        cv.put(x, y, "+" + "-" * (PW - 2) + "+", frame, bg=HOLO)
        cv.put(x, y + PH - 1, "+" + "-" * (PW - 2) + "+", frame, bg=HOLO)
        for k in range(1, PH - 1):
            cv.cell(x, y + k, "|", frame, HOLO)
            cv.cell(x + PW - 1, y + k, "|", frame, HOLO)
        if "clock" in scene:
            # an event soon: a tab on the frame, blinking
            cv.put(x + 2, y, "[!ALARM]", YELLOW if (tick // 3) % 2 else MAGENTA, bg=HOLO)
        tx, ty, tw = x + 2, y + 1, PW - 4

        def line(k, text, colour=STEEL):
            cv.put(tx, ty + k, text[:tw], colour, bg=HOLO)

        if state == "thinking":
            line(0, "NEURAL//NET", MAGENTA)
            for k in range(3):
                n = int((lcg(139, k, tick // 3)() * 0.5 + 0.5) * (tw - 2))
                line(2 + k, "|" * n, (CYAN, VIOLET, MAGENTA)[k])
            line(5, "-\\|/"[tick % 4] + " sync", CYAN_DIM)
        elif state == "writing":
            lines = self._stream
            total = tick % (len(lines) * tw)
            li, col = divmod(total, tw)
            for k in range(6):
                j = li - 5 + k
                if j < 0:
                    continue
                text = lines[j] if j < li else lines[j][:col]
                line(k, text, CYAN if k == 5 else STEEL_DIM)
            if (tick // 3) % 2:
                cv.cell(tx + min(col, tw - 1), ty + 5, "_", MAGENTA, HOLO)
        elif state == "done":
            line(0, "> gig://exit 0", CYAN_DIM)
            on = (tick // 3) % 4 != 0
            line(2, "  JOB DONE", YELLOW if on else CYAN)
            line(4, "+500 eddies", GREEN)
        elif state == "error":
            if (tick // 2) % 3:
                line(1, "ERR::", MAGENTA)
                line(2, "SIGNAL LOST", MAGENTA)
            r = lcg(149, tick)
            line(4, "".join("#%@&*!"[int(r() * 6)] for _ in range(tw)), MAGENTA_DIM)
            line(5, "rebooting" + "." * (tick % 4), STEEL_DIM)
        elif state == "tool":
            getattr(self, "_holo_" + kind)(line, cv, tx, ty, tw, tick)
        elif "game" in scene:
            self._holo_game(line, cv, tx, ty, tw, tick)
        else:
            status, colour = MOOD_FACE[mood][3]
            line(0, status, colour)
            line(2, "> _" if (tick // 5) % 2 else ">", STEEL)
            if "music" in scene:
                r = lcg(173, tick // 2)
                line(4, "eq   ", MAGENTA_DIM)
                for k in range(tw - 5):
                    cv.cell(tx + 5 + k, ty + 4, " .:|"[int(r() * 4)], (MAGENTA, CYAN)[k % 2], HOLO)
            else:
                line(4, "net  " + "|" * (2 + (tick // 7) % 6), MAGENTA_DIM)
            if "hot" in scene and (tick // 4) % 2:
                line(5, "THERMAL WARN", YELLOW)
            elif "cold" in scene:
                line(5, "tmp  low *", CYAN)
            elif mood == "sleepy":
                line(5, "pwr  " + "|" * (1 + (tick // 20) % 2), MAGENTA_DIM)
            elif mood == "excited":
                line(5, "pwr  " + "|" * 7 + "+" * ((tick // 3) % 2), YELLOW)
            else:
                line(5, "pwr  " + "|" * 7, CYAN_DIM)

    def _holo_game(self, line, cv, tx, ty, tw, tick):
        """Idle with a game running: neon invaders on the holo."""
        line(0, "SCORE %04d" % (tick * 10 % 10000), YELLOW)
        sway = (0, 1, 2, 1)[(tick // 6) % 4]
        for k in range(3):
            cv.put(tx + sway + k * 4, ty + 1, "/o\\" if (tick // 3) % 2 else "\\o/", (GREEN, MAGENTA, CYAN)[k],
                   bg=HOLO)
        ship = (tick // 2) % (tw - 2)
        ship = ship if (tick // 2) // (tw - 2) % 2 == 0 else tw - 3 - ship
        shot = 4 - (tick % 4)
        cv.cell(tx + ship + 1, ty + shot, "|", YELLOW, HOLO)
        line(5, " " * tw, STEEL)
        cv.put(tx + ship, ty + 5, "_A_", CYAN, bg=HOLO)

    def _holo_bash(self, line, cv, tx, ty, tw, tick):
        cyc = tick // 30
        cmd = CMDS[cyc % len(CMDS)]
        n = min(len(cmd), (tick % 30) // 2)
        line(0, "SHELL", MAGENTA)
        for k in range(3):
            line(1 + k, "> " + CMDS[(cyc - 3 + k) % len(CMDS)], STEEL_DIM)
        line(5, "> " + cmd[:n], CYAN)
        if (tick // 3) % 2:
            cv.cell(tx + 2 + n, ty + 5, "_", MAGENTA, HOLO)

    def _holo_book(self, line, cv, tx, ty, tw, tick):
        line(0, "[#]== SHARD", YELLOW)
        off = tick // 3
        for k in range(1, 6):
            r = lcg(151, off + k)
            hexs = " ".join("%02X" % int(r() * 256) for _ in range(4))
            line(k, hexs, CYAN if k == 1 + (tick // 2) % 5 else STEEL_DIM)

    def _holo_pad(self, line, cv, tx, ty, tw, tick):
        line(0, "REWRITE", MAGENTA)
        t = tick % 60
        n, part = divmod(t, 12)
        edits = (("-", "old_chrome"), ("+", "new_chrome"), ("-", "if ice:"), ("+", "if ok:"), ("+", " jack()"))
        for k in range(min(5, n + 1)):
            sign, text = edits[k]
            shown = text if k < n else text[:part]
            line(1 + k, sign + " " + shown, GREEN if sign == "+" else MAGENTA_DIM)

    def _holo_lens(self, line, cv, tx, ty, tw, tick):
        line(0, "TRACE", MAGENTA)
        for k in range(1, 6):
            r = lcg(157, k, tick // 40)
            line(k, "".join("abcdef0123:."[int(r() * 12)] for _ in range(tw)), STEEL_DIM)
        rx = tx + (tick // 2) % (tw - 4)
        ry = ty + 1 + (tick // 8) % 4
        cv.put(rx, ry, "[+]", YELLOW if (tick // 2) % 2 else CYAN, bg=HOLO)
        if (tick // 8) % 4 == 3:
            line(5, "MATCH", GREEN)

    def _holo_globe(self, line, cv, tx, ty, tw, tick):
        line(0, "NET//PULL", MAGENTA)
        meridian = (tick // 2) % 4
        rows = (" .-:-. ", "( :|: )", "(-:+:-)", "( :|: )", " '-:-' ")
        for k, r in enumerate(rows):
            s = r
            if meridian in (1, 3):
                s = s.replace(":", "|")
            cv.put(tx, ty + 1 + k, s, CYAN_DIM if k % 2 else CYAN, bg=HOLO)
        pct = (tick * 3) % 101
        cv.put(tx + 8, ty + 2, "%3d%%" % pct, STEEL, bg=HOLO)
        for j in range(3):
            px = tx + 7 + ((tick + j * 3) % 5)
            cv.cell(px, ty + 4, "<", MAGENTA if j == 0 else MAGENTA_DIM, HOLO)

    def _holo_helpers(self, line, cv, tx, ty, tw, tick):
        line(0, "DRONES", MAGENTA)
        n = 1 + (tick // 10) % 2
        for k in range(n):
            line(2 + k, "drone_%d  [up]" % (k + 1), CYAN)
        line(5, "link " + "=" * (2 + tick % 6), CYAN_DIM)

    def _holo_todo(self, line, cv, tx, ty, tw, tick):
        line(0, "GIGS", MAGENTA)
        done = (tick // 12) % (len(GIGS) + 1)
        for k, gig in enumerate(GIGS):
            box = "[x]" if k < done else ("[>]" if k == done and (tick // 3) % 2 else "[ ]")
            line(1 + k, box + " " + gig, STEEL_DIM if k < done else STEEL)
            if k < done:
                cv.put(tx, ty + 1 + k, box, GREEN, bg=HOLO)

    def _holo_wand(self, line, cv, tx, ty, tw, tick):
        line(0, "ICE BREAKER", MAGENTA)
        r = lcg(163, tick // 2)
        for k in range(1, 5):
            off = int(r() * 3)
            bolt = "".join("\\/"[(c + k + tick) % 2] for c in range(tw - off))
            cv.put(tx + off, ty + k, bolt, (YELLOW, MAGENTA, VIOLET, CYAN)[k - 1], bg=HOLO)
        line(5, ">> breach", CYAN)

    def _drones(self, cv, tick):
        for n, x in enumerate((max(0, self.cx - 6), min(self.cols - 5, self.cx + COMP_W + 1))):
            y = self.top + 2 + (1 if ((tick // 4) + n) % 2 else 0)
            rotor = (" _-_ ", " -_- ")[(tick + n) % 2]
            cv.sprite(x, y, rotor, STEEL_DIM)
            cv.sprite(x, y + 1, DRONE[1], STEEL)
            cv.cell(x + 2, y + 1, "o", CYAN if (tick // 3 + n) % 2 else MAGENTA)
            cv.sprite(x, y + 2, DRONE[2], CYAN_DIM)

    # -- glitch -------------------------------------------------------------------------

    def _glitch(self, cv, tick, heavy):
        if heavy and tick % 6 == 0:
            return
        r = lcg(167, tick)
        for _ in range(2 + int(r() * (4 if heavy else 2))):
            y = int(r() * self.rows)
            cv.shift_row(y, int(r() * 7) - 3)
        # magenta / cyan ghosts: a cell copied a column over in a channel colour
        for _ in range(self.cols // (3 if heavy else 6)):
            x, y = int(r() * (self.cols - 1)), int(r() * self.rows)
            c = cv.get(x, y)
            if c not in (" ", None) and cv.get(x + 1, y) == " ":
                cv.cell(x + 1, y, c, MAGENTA if r() < 0.5 else CYAN)
