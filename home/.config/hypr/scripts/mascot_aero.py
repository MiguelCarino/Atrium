#!/usr/bin/env python3
"""The aero theme's mascot: a glossy glass orb buddy floating over rolling
green hills, under a Windows 7 sky with an aurora. Same API as
moe_mascot.Mascot (mascots.py picks it).

    sky       the stage card (#12325a in themes/aero/llm-chat.css, a
              gradient there) with an aurora: two ribbons of ~ along a slow
              wave, their colours sliding through teal, green, sky and
              violet -- the shimmer -- and cotton clouds drifting by
    hills     two rolling ranges along the bottom, painted as cell
              backgrounds (far blue-green, near green) under an edge of
              slope glyphs, grass tufts on the near one
    the orb   15 x 8 cells of Aero glass: an outline in sky blue, the inside
              filled lighter in its top half than its bottom (the gloss of
              every Windows 7 button), a shine at its top left, a friendly
              face; it bobs, and its shadow on the hill grows and shrinks
    props     to its right, small glass windows: cmd for Bash, a document
              for Read, the document and a pencil for Edit/Write, the search
              box for the searches, a globe and the green Windows 7
              progress bar for WebFetch, two little orbs for Task/Agent, a
              checklist for TodoWrite, rising bubbles otherwise; thinking is
              the busy ring, done a green check, an error a red tint and
              the amber warning triangle

  mood      one of mascot_mood.MOODS. Idle, it is the whole face: happy
              ^w^, excited starry eyes and little hops, shy >~< with pink
              cheeks, looking away, curious o.O and a "?", focused and
              worried brows (worried sweats and glances about), sad dots, a
              tear and greyer glass resting on the hill, sleepy shut eyes,
              z's and the same rest. At work only the accents show (brows,
              sweat, cheeks, a twinkle) over the work face; sleepy works
              focused. calm (or None) is the face it always had. The idle
              fidget at the end of each 9-second round (a look round, a bubble
              blown, a gloss glint across the glass, a Messenger nudge, a
              yawn) is picked by the noise and weighted by the mood.
  scene     a set of mascot_mood.SCENES: day (a light sky, wisps for the
              aurora, the sun and its lens flare), night (a brighter aurora,
              stars, a crescent moon), sun, cloud (more clouds; any overcast
              tag dims the aurora and hides the sun), rain and storm (rain
              over the stage, a bead running down the glass, lightning), snow
              (flakes, snowcaps on the hills), fog (drifting bands), hot (heat
              shimmer, a sweat drop), cold (frost on the glass, breath puffs),
              music (notes, a bob to the beat), game (a glossy controller in
              the idle slot), party (a party hat, confetti), festive (papel
              picado along the top), clock (an alarm clock gadget ringing on
              the hill to the left).

Sky blues and greens; the brightest cells are small (eyes, shine). No
large light area: the glass is mid blue, the hills mid green.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import STATES, BaseMascot, Canvas, blink, lcg, prop_kind, stream_lines  # noqa: E402
from mascot_mood import MOODS, word  # noqa: E402

THEME = "aero"
PANEL = "#12325a"

SKY = "#8cc8ff"
MIST = "#c4d8ee"
SHINE = "#eef6ff"
GLASS_HI = "#3f86cf"
GLASS_LO = "#22599c"
GLASS_RED_HI = "#b04a5a"
GLASS_RED_LO = "#7c2a3a"
GREEN = "#8fe07a"
GREEN_DARK = "#2f7a3a"
GREEN_MID = "#4f9a3f"
FAR_HILL = "#1d5660"
FAR_EDGE = "#5fa8b0"
AMBER = "#ffc46b"
BAD = "#ff6b78"
WIN_BAR = "#2f68a8"
WIN_BODY = "#0f2848"
CMD_BODY = "#070c14"
TEXT = "#e4eefa"
TEXT_DIM = "#8fa8c4"
SEL = "#2f6db5"
BAR_GREEN = "#3a9a3a"
BAR_SHINE = "#7fd46f"
AURORA = ("#6cf0c8", "#8fe07a", "#7fd0ff", "#b99cff", "#7fd0ff", "#8fe07a")
# the aurora's glow: cell backgrounds only a little lighter than the sky
AURORA_GLOW = ("#123c54", "#13424a", "#15395e", "#1c3460", "#15395e", "#13424a")
AURORA_DIM = "#1a3550"
# the scene's colours
DAY_SKY = ("#1d5490", "#1b4d86", "#19467c", "#173f72")   # top rows, lightest first
DAY_GLOW = ("#1f5a96", "#21609c", "#235f9a", "#1f5a96")
GLASS_DIM_HI = "#3d6a9a"     # sad / sleepy: greyer glass
GLASS_DIM_LO = "#284b74"
BLUSH = "#ff9cc0"
SUN = "#ffe08a"
MOON = "#f3e3a8"
STAR = "#c4d8ee"
STAR_DIM = "#5f7fa4"
CLOUD_GREY = "#7f97b3"
CLOUD_STORM = "#5f7894"
RAIN = "#8cc8ff"
SNOW = "#f2f8ff"
FOG = "#5a7898"
NOTE = ("#ffe08a", "#8fe07a")
CONFETTI = ("#ff6fae", "#ffc46b", "#8fe07a", "#7fd0ff", "#b99cff")
PICADO = ("#ff6fae", "#ffa94d", "#7fd46f", "#6fb6ff", "#c58bff", "#ffd84d")
OVERCAST = frozenset(("cloud", "rain", "storm", "snow", "fog"))

OW, OH = 15, 8
ORB = [
    "    _.---._    ",
    "  .'       '.  ",
    " /           \\ ",
    "|             |",
    "|             |",
    " \\           / ",
    "  '._     _.'  ",
    "     '---'     ",
]
EYES = (4, 10)          # row 3
MOUTH = (4, 7)

COMP_W = OW + 2 + 17
WORDS = ("the", "sky", "is", "clear", "and", "all", "set", "your", "file", "ok", "to",
         "glass", "now", "done", "a", "it", "works", "so")
CMDS = ("dir", "ver", "ping", "cls", "tree", "ipconfig")
TODO = ("Back up", "Update", "Tidy up", "Share")

# Per mood, idle: (left eye, right eye, mouth, cheeks). calm: the face it
# always had.
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
# Brows on the glass above each eye (row 2): left, right.
BROWS = {"focused": ("\\", "/"), "worried": ("/", "\\"), "sad": ("/", "\\")}
# The idle fidget a mood favours: (name, weight); "rest" is none at all.
FIDGETS = {
    "calm": (("look", 2), ("bubble", 2), ("glint", 2), ("nudge", 1), ("rest", 2)),
    "happy": (("bubble", 3), ("glint", 2), ("nudge", 1)),
    "excited": (("nudge", 3), ("bubble", 2), ("glint", 2)),
    "shy": (("look", 2), ("rest", 3)),
    "curious": (("look", 4), ("bubble", 1)),
    "focused": (("rest", 3), ("glint", 1)),
    "worried": (("look", 3), ("rest", 2)),
    "sad": (("rest", 1),),
    "sleepy": (("yawn", 3), ("rest", 2)),
}

MOOD_BUBBLES = {
    "happy": "Everything is in sync ✓ What's next?",
    "excited": "Wow! Let's make something amazing today!",
    "shy": "Oh! You nudged me… hi there ☺",
    "curious": "Ooh, what's that? Tell me more!",
    "focused": "Status: Busy. Ready when you are.",
    "worried": "Hmm… let's run a quick check-up.",
    "sad": "Feeling a little cloudy today…",
    "sleepy": "Status: Away… zz",
}
# mascot_mood topics in its words (str.format with the topic's arguments).
TOPIC_LINES = {
    "thanks": "You're welcome! Glad I could help ✓",
    "worried": "Uh-oh… let's troubleshoot that.",
    "frustrated": "Still not working? Let's try once more!",
    "relieved": "Phew! Problem solved ✓",
    "determined": "Big job! Hang tight, still in progress…",
    "proud": "All done! Everything is up to date ✓",
    "sad": "Sorry about that…",
    "happy": "Awesome! ✓",
    "curious": "Ooh, interesting…",
    "rain": "The weather gadget says rain. Grab an umbrella!",
    "storm": "Storm warning! Better stay inside.",
    "snow": "It's snowing! ❄",
    "fog": "Foggy out there. Take it slow!",
    "sun": "Clear skies and sunshine today ☀",
    "hot": "Toasty out there: {0}. Stay cool!",
    "cold": "Brr, {0} outside. Bundle up!",
    "gpu_hot": "Your GPU is running warm: {0}°C",
    "cpu_hot": "Your CPU is running warm: {0}°C",
    "music": "Now Playing… great song! ♪",
    "game": "Game on! Have fun!",
    "event": "Reminder: {0} in {1} min",
    "event_now": "Reminder: {0} is starting now!",
    "birthday": "Happy birthday, {0}! 🎂",
    "holiday": "Today is {0}! 🎉",
    "go_home": "It's {0}. Time to sign out and head home!",
    "bedtime": "It's {0}… time to shut down for the night.",
    "morning": "Good morning! Your desktop is ready ☀",
    "lunch": "Lunch break? You've earned it!",
    "weekend": "It's the weekend! Enjoy ✓",
    "friday": "Friday afternoon! Weekend sync in progress ✓",
    # conversation and stage events (tuples: a new variant each time round)
    "hello": ("Hi there! Ready when you are ✓",
              "Hello! Fresh desktop, clear skies ☀",
              "Welcome! Let's make something shiny"),
    "welcome_back": ("Welcome back! All right where you left it ✓",
                     "You're back! Resuming your session…"),
    "wake": ("Oh! Waking from sleep mode… I'm up!",
             "Resuming… hi! I was only dimmed"),
    "long_prompt": ("Big one! Loading all of it…",
                    "Whoa, that's a lot. Reading it all!"),
    "code": ("Code! Let me take a clear look",
             "Ooh, code. Opening it in glass view"),
    "image": ("A picture! Opening Photo Viewer…",
              "Ooh, nice image. Let me see!"),
    "aborted": ("Stopped! Ready for the next one ✓",
                "Cancelled. No harm done!"),
    "tests_pass": ("All tests passed ✓ Looking good!",
                   "Green across the board ✓",
                   "Tests: all clear skies ☀"),
    "tests_fail": ("Some tests failed… let's take a look",
                   "Tests didn't pass. We'll fix it!"),
    "commit": ("Changes saved and synced ✓",
               "Committed! Your work is backed up ✓",
               "Shipped! Off it floats to the cloud ☁"),
    "fast": ("Done in a blink ✓",
             "That was quick! ✓",
             "Speedy! Already finished ✓"),
    "busy": ("Lots of tasks running… on it!",
             "Busy busy! Multitasking like a pro"),
    "model": ("Switched to {0} ✓",
              "Now running on {0}. Shiny!"),
    "poke": ("Hi! That tickles the glass ☺",
             "Boop! Still shiny ✓",
             "Hey there! Need anything?",
             "Ooh, a click! Hello ✓",
             "*wobbles* Wheee!",
             "You found me! Hi ☺"),
    "poke_spam": ("Whoa, easy! You'll smudge the glass",
                  "Too many clicks! Glass overheating…",
                  "Hey! I'm getting fingerprints!"),
    "pet": ("Aww… polishing my glow ✓",
            "Hehe, that's nice ☺",
            "So smooth… thank you!",
            "Mmm, extra gloss ✓"),
    # railguard.py's notifications (mascot_notify.py says them, voice on)
    "rg_memory": "{0} was using too much memory, so I closed it ✓",
    "rg_vram": "{0} filled the graphics memory, so I closed it ✓",
    "rg_game_vram": "{0} is using almost all graphics memory. Lower its textures?",
    "rg_panic": "Done! {0} has been closed ✓",
    "rg_stuck": "Memory is running low… I couldn't find what to close.",
    "rg_agents": "All agent tasks stopped. Your sessions are fine ✓",
}
# The reaction sign over the head (mascot_mood.EMOTE_TONES) in its palette:
# each >= 3:1 on PANEL and on every sky the sign can float over (the day
# rows and the aurora glow; the palest, #21609c, is the worst case).
EMOTE_COLOURS = {
    "accent": "#7fd0ff",    # aurora sky:   7.6 on PANEL, 3.8 on #21609c
    "warn": AMBER,          # #ffc46b:      8.2,          4.2
    "bad": "#ffa0a8",       # a light rose-red: 6.7,      3.4
    "good": GREEN,          # #8fe07a:      8.1,          4.1
    "love": BLUSH,          # #ff9cc0:      6.6,          3.4
    "dim": "#a8bcd4",       # misted glass: 6.6,          3.4
}


class Mascot(BaseMascot):
    BUBBLES = {
        "idle": "Hi there! What shall we do today?",
        "thinking": "Working on it…",
        "writing": "Writing your answer…",
        "done": "All done. Everything's up to date.",
        "error": "Something went wrong. Let's try that again.",
    }
    TOOL_BUBBLES = {
        "Bash": "Running a command…",
        "Read": "Opening the file…",
        "Edit": "Making changes…",
        "MultiEdit": "Making changes…",
        "Write": "Saving your file…",
        "NotebookEdit": "Updating the notebook…",
        "Grep": "Searching…",
        "Glob": "Looking through your files…",
        "WebSearch": "Searching the web…",
        "WebFetch": "Downloading…",
        "Task": "Asking my friends to help…",
        "Agent": "Asking my friends to help…",
        "TodoWrite": "Updating your tasks…",
    }
    OTHER = "Working with %s…"
    moods = True

    def __init__(self, cols=64, rows=18):
        self.cols = max(int(cols), COMP_W + 2)
        self.rows = max(int(rows), OH + 6)
        self.cx = (self.cols - COMP_W) // 2
        self.ground = self.rows - 3           # first row of the near hills
        self._hn = [int(self._hill(x, 0.21, 1.3, 7)) for x in range(self.cols)]
        self._hf = [int(self._hill(x, 0.13, 1.6, 3) + 1.4) for x in range(self.cols)]
        self._tufts = [lcg(89, x)() for x in range(self.cols)]
        self._stream = stream_lines(WORDS, 12, seed=61)
        self._clouds = []
        for i in range(max(2, self.cols // 30)):
            r = lcg(79, i, self.cols)
            self._clouds.append((r() * self.cols, int(r() * max(2, self.rows // 3)), 0.02 + r() * 0.03))
        # overcast: as many again, from their own noise
        self._grey = []
        for i in range(max(2, self.cols // 26)):
            r = lcg(83, i, self.cols)
            self._grey.append((r() * self.cols, int(r() * max(2, self.rows // 3)) - 1, 0.03 + r() * 0.03))
        self._stars = []
        for i in range(self.cols * self.rows // 40):
            r = lcg(97, i)
            self._stars.append((int(r() * self.cols), int(r() * max(2, self.ground - 6)),
                                20 + int(r() * 30), int(r() * 50)))

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

    def _hill(self, x, freq, amp, seed):
        """Height above the bottom row of a hill range at column x (float)."""
        r = lcg(seed)
        a, b = r() * 6.28, r() * 6.28
        return amp * (1 + 0.6 * math.sin(x * freq + a) + 0.4 * math.sin(x * freq * 2.3 + b))

    # -- composition ---------------------------------------------------------------

    def _render(self, state, tick, tool, mood=None, scene=()):
        if state not in STATES:
            state = "idle"
        if mood not in MOODS:
            mood = "calm"
        if mood == "sleepy" and state in ("thinking", "tool", "writing"):
            mood = "focused"            # it does not doze off on the job
        scene = frozenset(scene or ())
        tick = int(tick)
        cv = Canvas(self.cols, self.rows)
        kind = prop_kind(tool) if state == "tool" else None
        idle = state == "idle"
        fidget = self._fidget(tick, mood) if idle else None
        self._sky(cv, state, tick, scene)
        if "festive" in scene:
            self._banner(cv, tick)
        self._hills(cv, tick, scene)
        if "fog" in scene:
            self._fog(cv, tick)
        if "snow" in scene:
            self._snow(cv, tick)
        if scene & {"rain", "storm"}:
            self._weather_rain(cv, tick, heavy="storm" in scene)
        if "hot" in scene:
            self._shimmer(cv, tick)
        if "party" in scene:
            self._confetti(cv, tick)
        hover = 0
        if state == "done":
            hover = (0, 1, 2, 2, 1, 0, 0, 0)[tick % 8]
        elif idle and mood == "excited" and (tick // 30) % 2:
            hover = (0, 1, 2, 2, 1, 0)[tick % 6]
        elif idle and mood in ("sad", "sleepy"):
            hover = 0                   # resting on the hill
        elif "music" in scene and state != "error":
            hover = (tick // 4) % 2     # bobbing to the beat
        else:
            hover = 1 if math.sin(tick / 7.0) > 0 else 0
        top = self.ground - OH - hover
        ox = self.cx
        if fidget == "nudge" and tick % 90 < 80:
            ox += (0, 1, 0, -1)[tick % 4]
        self._shadow(cv, ox, hover)
        if kind == "helpers":
            self._helpers(cv, tick)
        if "clock" in scene:
            self._alarm(cv, tick, high=kind == "helpers")
        self._orb(cv, state, tick, ox, top, mood, scene, fidget)
        # the reaction sign: on the orb's right shoulder, beside the top of
        # the outline (where the z's and the "?" float), riding the bob
        self.head = (ox + 12, max(0, top))
        self._mood_marks(cv, state, tick, ox, top, mood, scene, fidget)
        if "party" in scene:
            self._hat(cv, tick, ox, top)
        px, py = self.cx + OW + 2, self.ground - 8
        if state == "thinking":
            self._ring(cv, tick, px + 4, py + 2)
        elif state == "writing":
            self._doc(cv, tick, px, py, stream=True, pencil=True)
        elif state == "done":
            self._check(cv, tick, px, py)
        elif state == "error":
            self._warning(cv, tick, px, py)
        elif kind and kind != "helpers":
            getattr(self, "_prop_" + kind)(cv, tick, px, py)
        elif kind == "helpers":
            pass
        elif "game" in scene:
            self._controller(cv, tick, px, py)
        else:
            self._bubbles(cv, tick, px + 2, py + 6, n=2)
        return cv

    def _fidget(self, tick, mood):
        """The idle fidget now: one per 90-tick round, in its last 18 ticks,
        picked by the round's noise from what the mood favours; None the
        rest of the time (and for "rest")."""
        if tick % 90 < 72:
            return None
        table = FIDGETS.get(mood, FIDGETS["calm"])
        pick = lcg(109, tick // 90)() * sum(w for _, w in table)
        for name, weight in table:
            pick -= weight
            if pick < 0:
                return None if name == "rest" else name
        return None

    # -- the sky and the land ----------------------------------------------------------

    def _sky(self, cv, state, tick, scene=frozenset()):
        """Day lightens the top rows and brings the sun, night the stars and
        the moon; anything overcast hides both and greys the clouds."""
        overcast = bool(scene & OVERCAST)
        clear = not overcast and state != "error"
        if "day" in scene and not overcast:
            for y, bg in enumerate(DAY_SKY):
                for x in range(self.cols):
                    cv.recolour(x, y, bg=bg)
        self._aurora(cv, state, tick, scene)
        y0 = 2 if "festive" in scene else 0
        if "night" in scene:
            moon = clear and self.cols >= 50
            for x, y, period, ph in self._stars:
                if overcast and (x + y) % 3:
                    continue        # most of them behind the clouds
                if moon and x >= self.cols - 6 and y < y0 + 3:
                    continue
                if cv.get(x, y) != " ":
                    continue
                t = (tick + ph) % period
                cv.cell(x, y, ".+*+."[t] if t < 5 else ".", STAR if t < 5 else STAR_DIM)
            if moon:
                cv.put(self.cols - 4, y0, ".-", MOON)
                cv.put(self.cols - 5, y0 + 1, "(", MOON)
                cv.put(self.cols - 4, y0 + 2, "`-", MOON)
        elif clear and scene & {"day", "sun"} and self.cols >= 48:
            self._sun(cv, tick, y0)
        self._cloud_layer(cv, tick, scene)
        if "storm" in scene:
            self._lightning(cv, tick)

    def _aurora(self, cv, state, tick, scene=frozenset()):
        """Two ribbons along a slow wave: a glow of dim cell backgrounds
        whose hue slides along them (the shimmer), and a few brighter
        strands of ~ on top. By day only pale wisps of it, by night more of
        it, under clouds a dim grey."""
        bands = ((1, 0.16, 0.0), (3, 0.10, 2.0)) if self.rows >= 17 else ((0, 0.16, 0.0), (2, 0.10, 2.0))
        overcast = bool(scene & OVERCAST)
        dim = state == "error" or overcast
        day = "day" in scene and not dim
        dense = 0.55
        if day:
            dense = 0.18
        elif overcast and state != "error":
            dense = 0.3
        elif "night" in scene and not dim:
            dense = 0.7
        for n, (row, freq, ph) in enumerate(bands):
            for x in range(self.cols):
                y = row + int(round(math.sin(x * freq + ph + tick * 0.04) * 1.2))
                k = (x // 4 + tick // 5 + n * 2) % len(AURORA_GLOW)
                glow = AURORA_DIM if dim else (DAY_GLOW[k % len(DAY_GLOW)] if day else AURORA_GLOW[k])
                if 0 <= y < self.rows:
                    cv.recolour(x, y, bg=glow)
                if lcg(101, x, row)() < dense and 0 <= y < self.rows:
                    colour = TEXT_DIM if dim else (MIST if day else AURORA[(x // 3 + tick // 4 + row) % len(AURORA)])
                    cv.cell(x, y, "~" if (x + tick // 6) % 5 else "-", colour)

    def _cloud_layer(self, cv, tick, scene=frozenset()):
        overcast = bool(scene & OVERCAST)
        grey = CLOUD_STORM if "storm" in scene else CLOUD_GREY
        if overcast:
            # the heavier ones, behind the usual cotton
            for x0, y, speed in self._grey:
                x = int(x0 + tick * speed) % (self.cols + 16) - 12
                y += 2
                cv.sprite(x + 2, y, ".--.  .-.", grey)
                cv.sprite(x, y + 1, "(`    )'  `-.", grey)
                cv.sprite(x, y + 2, "(___________)", grey)
        colour = MIST if not overcast or "day" in scene else CLOUD_GREY
        for x0, y, speed in self._clouds:
            x = int(x0 + tick * speed) % (self.cols + 12) - 8
            y += 2
            cv.sprite(x + 1, y, ".--.", colour)
            cv.sprite(x, y + 1, "(    )_", colour)
            cv.sprite(x + 1, y + 2, "`----'", colour)

    def _hills(self, cv, tick, scene=frozenset()):
        bottom = self.rows - 1
        snow = "snow" in scene
        for heights, fill, edge in ((self._hf, FAR_HILL, FAR_EDGE), (self._hn, GREEN_DARK, GREEN)):
            for x in range(self.cols):
                h = heights[x]
                top = bottom - h
                for y in range(max(0, top + 1), self.rows):
                    cv.cell(x, y, " ", None, fill)
                left = heights[x - 1] if x else h
                right = heights[x + 1] if x + 1 < self.cols else h
                glyph = "/" if left < h <= right else ("\\" if right < h <= left else
                                                       ("." if left < h > right else "_"))
                cv.cell(x, top, glyph, SNOW if snow else edge)
        # grass tufts on the near hills, swaying (snowballs under snow)
        wind = (tick // 6) % 2
        for x, v in enumerate(self._tufts):
            if v < 0.2:
                y = bottom - self._hn[x] + 1
                if y < self.rows:
                    if snow:
                        cv.cell(x, y, "." if v < 0.1 else "o", SNOW, GREEN_DARK)
                    else:
                        cv.cell(x, y, ",'"[(x + wind) % 2] if v < 0.1 else "\"", BAR_SHINE, GREEN_DARK)

    def _shadow(self, cv, ox, hover):
        w = 9 - hover * 2
        for c in range(w):
            x = ox + (OW - w) // 2 + c
            if 0 <= x < self.cols:
                cv.cell(x, self.rows - 1 - self._hn[x], "_", "#173d20")

    # -- the scene (mascot_mood.SCENES) ------------------------------------------------

    def _sun(self, cv, tick, y=0):
        """The sun at the top left and its lens flare down the sky, the
        glossiest thing in any Aero wallpaper."""
        rays = ("\\ | /", "  |  ", "\\   /")[(tick // 8) % 3]
        cv.put(1, y, rays, SUN)
        cv.put(1, y + 1, "-(O)-", SUN)
        cv.put(1, y + 2, "/ | \\" if rays[0] == "\\" else "  |  ", SUN)
        for k, (dx, dy, ch, colour) in enumerate(((8, 3, "o", MIST), (11, 4, ".", SHINE),
                                                  (14, 5, "O", "#7fd0ff"))):
            if (tick // 6 + k) % 5 and cv.get(dx, y + dy) == " ":
                cv.cell(dx, y + dy, ch, colour)

    def _lightning(self, cv, tick):
        cyc, t = divmod(tick, 47)
        if t > 3:
            return
        x = int(lcg(113, cyc)() * (self.cols - 4)) + 1
        for k, (dx, ch) in enumerate(((1, "/"), (0, "/"), (0, "\\"), (1, "/"))):
            cv.cell(x + dx + (k > 1), 1 + k, ch, SUN if t % 2 == 0 else SHINE)

    def _banner(self, cv, tick):
        """Papel picado: a cord along the top row, cut-paper flags in the
        Mexican colours hanging under it, fluttering."""
        for x in range(self.cols):
            cv.cell(x, 0, "-", TEXT_DIM)
            k = x % 4
            if k < 3:
                flutter = (tick // 4 + x // 4) % 2
                cv.cell(x, 1, ("o.o", ".o.")[flutter][k], PANEL, PICADO[(x // 4) % len(PICADO)])

    def _fog(self, cv, tick):
        for k, y in enumerate((self.rows // 3, self.rows // 2 + 1, self.rows - 3)):
            off = (tick // (6 + k * 2) + k * 7) % 12
            for x in range(self.cols):
                if (x + off) % 12 < 5 and (x + off) % 12 != 2:
                    cv.cell(x, y, "~", FOG)

    def _snow(self, cv, tick):
        span = self.rows + 2
        for i in range(max(6, self.cols * self.rows // 60)):
            r = lcg(127, i)
            speed = 0.05 + r() * 0.06
            pos = r() * span + tick * speed
            fall = int(pos // span)
            y = int(pos - fall * span) - 1
            x = int(lcg(131, i, fall)() * self.cols + (0, 1, 1, 0, 0, -1, -1, 0)[(tick // 5 + i) % 8])
            if cv.get(x, y) == " ":
                cv.cell(x, y, "*.+"[i % 3], SNOW)

    def _weather_rain(self, cv, tick, heavy=False):
        """Rain over the stage, on the cells still blank (the orb and the
        windows are drawn over it)."""
        span = self.rows + 2
        for i in range(self.cols * self.rows // (14 if heavy else 24)):
            r = lcg(137, i)
            speed = (0.7 if heavy else 0.5) + r() * 0.3
            y = int((r() * span + tick * speed) % span) - 1
            x = int(r() * self.cols)
            if cv.get(x, y) == " ":
                cv.cell(x, y, "'" if i % 3 else ",", RAIN)

    def _shimmer(self, cv, tick):
        """Heat rising off the hills."""
        for x in range(self.cols):
            if lcg(139, x, tick // 3)() < 0.08:
                y = self.ground - 1 - (x % 2)
                if cv.get(x, y) == " ":
                    cv.cell(x, y, "~", AMBER)

    def _confetti(self, cv, tick):
        span = self.rows + 2
        for i in range(max(4, self.cols * self.rows // 90)):
            r = lcg(149, i)
            pos = r() * span + tick * (0.12 + r() * 0.1)
            fall = int(pos // span)
            y = int(pos - fall * span) - 1
            x = int(lcg(151, i, fall)() * self.cols) + (tick // 4 + i) % 2
            if cv.get(x, y) == " ":
                cv.cell(x, y, ",'.*"[(tick // 3 + i) % 4], CONFETTI[i % len(CONFETTI)])

    def _alarm(self, cv, tick, high=False):
        """The clock gadget on the hill to its left, ringing: an event soon.
        Above the helper orb when there is one."""
        x = max(0, self.cx - 8)
        y = self.ground - (9 if high else 3)
        ring = (tick // 2) % 10 < 5
        shake = tick % 2 if ring else 0
        cv.sprite(x + shake, y, "o.-.o", SKY)
        cv.cell(x + shake, y, "o", AMBER)
        cv.cell(x + shake + 4, y, "o", AMBER)
        cv.sprite(x + shake, y + 1, "(   )", SKY)
        for c in (1, 2, 3):
            cv.recolour(x + shake + c, y + 1, bg=GLASS_LO)
        cv.cell(x + shake + 2, y + 1, "|/-\\"[(tick // 3) % 4], SHINE, GLASS_LO)
        cv.sprite(x + shake, y + 2, "'-^-'", SKY)
        if ring:
            cv.cell(x + 6, y - 1, "!", AMBER)
            cv.cell(x - 1, y, "(", AMBER)
            cv.cell(x + 6, y, ")", AMBER)

    def _hat(self, cv, tick, ox, top):
        cv.cell(ox + 7, top - 3, "*+"[(tick // 4) % 2], AMBER)
        cv.sprite(ox + 6, top - 2, "/:\\", CONFETTI[0])
        cv.sprite(ox + 5, top - 1, "/_:_\\", CONFETTI[3])
        cv.cell(ox + 7, top - 2, ":", AMBER)
        cv.cell(ox + 7, top - 1, ":", AMBER)

    def _controller(self, cv, tick, x, y):
        """Game time: a glossy pad where the bubbles would be, its buttons
        lighting up in turn."""
        cv.sprite(x + 1, y + 2, "  .-----.  ", MIST)
        cv.sprite(x + 1, y + 3, " / +  @ o\\ ", MIST)
        cv.sprite(x + 1, y + 4, "(   .-.   )", MIST)
        cv.sprite(x + 1, y + 5, " `-'   `-' ", MIST)
        cv.cell(x + 4, y + 3, "+", TEXT)
        cv.cell(x + 7, y + 3, "@", GREEN)
        cv.cell(x + 9, y + 3, "o", (AMBER, BAD, GREEN, SKY)[(tick // 3) % 4])
        cv.put(x + 2, y + 6, "Game on!", GREEN if (tick // 6) % 2 else BAR_SHINE, solid=True)

    # -- the orb ----------------------------------------------------------------------

    def _orb(self, cv, state, tick, x0, top, mood="calm", scene=frozenset(), fidget=None):
        idle = state == "idle"
        if state == "error":
            hi, lo = GLASS_RED_HI, GLASS_RED_LO
        elif idle and mood in ("sad", "sleepy"):
            hi, lo = GLASS_DIM_HI, GLASS_DIM_LO
        else:
            hi, lo = GLASS_HI, GLASS_LO
        for i, r in enumerate(ORB):
            cv.sprite(x0, top + i, r, BAD if state == "error" else SKY)
            if i in (0, 7):
                continue
            # the glass: the cells inside the outline, lighter in the top half
            a = len(r) - len(r.lstrip(" "))
            b = len(r.rstrip(" "))
            for c in range(a + 1, b - 1):
                cv.recolour(x0 + c, top + i, bg=hi if i <= 3 else lo)
        if fidget == "glint":
            # a glint sweeping across the glass, top left to bottom right
            t = tick % 90 - 72
            for i in range(1, 7):
                r = ORB[i]
                a = len(r) - len(r.lstrip(" "))
                b = len(r.rstrip(" "))
                for c in (t - 3 + i, t - 2 + i):
                    if a + 1 <= c < b - 1:
                        cv.recolour(x0 + c, top + i, bg="#6aa6e0")
        # the gloss: a shine at the top left, a softer rim light at the bottom right
        cv.cell(x0 + 3, top + 2, "(", SHINE, hi)
        cv.cell(x0 + 4, top + 1, "_", SHINE, hi)
        cv.cell(x0 + 11, top + 5, ")", MIST, lo)
        if scene & {"rain", "storm"}:
            # a raindrop running down the glass
            t = (tick // 3) % 6
            if t < 4:
                cv.cell(x0 + 12, top + 2 + t, ".", SHINE, hi if t < 2 else lo)
        if "cold" in scene:
            # frosted glass at the bottom corners
            for c, i, ch in ((2, 5, "*"), (3, 6, "."), (12, 5, "*"), (11, 6, ".")):
                cv.cell(x0 + c, top + i, ch, SNOW, lo)
        # face
        eye = "o"
        if state == "done":
            eye = "^"
        elif state == "error":
            eye = "o"
        elif state == "thinking":
            eye = "o"
        gaze = 1 if state in ("tool", "writing") else 0
        if state == "thinking":
            gaze = (0, 1, 0, -1)[(tick // 12) % 4]
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
                left = right = "*"          # a sparkle in the eye
        t = tick % 90 - 72
        if fidget == "look":
            gaze = -1 if t < 9 else 1
        elif fidget == "yawn":
            left = right = "-"
            mouth = "O" if 3 <= t < 14 else "o"
        elif fidget == "bubble":
            mouth = "o"
        shut = blink(tick, 49) and state not in ("done", "error")
        lit = AMBER if mood == "excited" and state != "error" else SHINE
        for ex, ch in zip(EYES, (left, right)):
            cv.cell(x0 + ex + gaze, top + 3, "-" if shut else ch, lit, hi)
        cv.cell(x0 + MOUTH[1] + gaze, top + MOUTH[0], mouth, SHINE, lo)
        if mood in BROWS and state != "done":
            for ex, ch in zip(EYES, BROWS[mood]):
                cv.cell(x0 + ex + gaze, top + 2, ch, MIST, hi)
        # blush / sweat / a tear
        if state == "error":
            if (tick // 4) % 3:
                cv.cell(x0 + 12, top + 2, "'", SKY, hi)
        elif (mood == "worried" or "hot" in scene) and state != "done":
            s = (tick // 5) % 4
            if s < 3:
                cv.cell(x0 + 12, top + 2 + (s > 1), "',"[s > 1], SKY, hi)
        if cheek:
            colour = BLUSH if cheek == "/" else "#9fc4f5"
            cv.cell(x0 + 2, top + 4, cheek, colour, lo)
            cv.cell(x0 + 12, top + 4, cheek, colour, lo)
        if mood == "sad" and state in ("idle", "error"):
            s = (tick // 6) % 3
            if s < 2:
                cv.cell(x0 + EYES[0] + gaze, top + 4 + s, ",'"[s], RAIN, lo)

    def _mood_marks(self, cv, state, tick, ox, top, mood, scene, fidget):
        """What floats around it for its mood and scene: z's, a "?", "!"s,
        a blown bubble, nudge marks, music notes, breath in the cold."""
        idle = state == "idle"
        t = tick % 90 - 72
        if idle and mood == "sleepy":
            s = tick % 36
            for j in range(3):
                if s // 9 > j:
                    cv.cell(ox + 13 + j, top + 1 - j, "zzZ"[j], MIST if j < 2 else SHINE)
        elif idle and mood == "curious" and (tick // 5) % 4:
            cv.cell(ox + 13, top, "?", AMBER)
        elif idle and mood == "excited" and (tick // 3) % 4 < 2:
            cv.cell(ox + 1, top, "!", AMBER)
            cv.cell(ox + 13, top, "!", AMBER)
        elif mood == "excited" and state in ("thinking", "tool", "writing", "done"):
            if (tick // 3) % 4 == 0:
                cv.cell(ox + 13, top, "+", AMBER)
        if fidget == "bubble":
            cv.cell(ox - 1 - t // 6, top + 4 - t // 3, "o" if t < 9 else "O", MIST)
        elif fidget == "nudge" and t < 8:
            cv.cell(ox - 2, top + 3, "(", MIST)
            cv.cell(ox + OW + 1, top + 3, ")", MIST)
        if "music" in scene and state != "error":
            for j in range(2):
                s = (tick + j * 12) % 24
                if s < 20:
                    cv.cell(ox - 2 - s // 6 - j * 2, top + 5 - s // 5, "db"[j], NOTE[j])
        if "cold" in scene and idle:
            s = tick % 40
            if s < 12:
                cv.cell(ox + 14 + s // 4, top + 4 - s // 6, ".oO"[min(2, s // 4)], SNOW)

    # -- things beside it ------------------------------------------------------------

    def _window(self, cv, x, y, w, h, title, body=WIN_BODY):
        cv.fill(x, y, w, h, body)
        cv.fill(x, y, w, 1, WIN_BAR)
        cv.put(x + 1, y, title[:w - 5], TEXT, bg=WIN_BAR)
        cv.put(x + w - 2, y, "x", TEXT, bg="#c8404c")

    def _ring(self, cv, tick, x, y):
        """The Windows 7 busy ring: eight dots round a circle, a bright head
        and a fading tail chasing round."""
        pts = ((3, 0), (5, 0), (6, 1), (5, 2), (3, 2), (1, 2), (0, 1), (1, 0))
        head = tick % 8
        for k, (dx, dy) in enumerate(pts):
            age = (head - k) % 8
            colour = SHINE if age == 0 else (SKY if age < 3 else ("#4a7fb8" if age < 5 else None))
            if colour:
                cv.cell(x + dx, y + dy, "o" if age == 0 else ".", colour)
        cv.put(x - 2, y + 4, ("Working" + "." * ((tick // 4) % 4)).ljust(10), TEXT_DIM, solid=True)

    def _doc(self, cv, tick, x, y, stream=False, pencil=False):
        self._window(cv, x, y, 16, 7, "Document")
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
            cv.put(x + 2, y + 1 + k, text, TEXT if k == 4 else TEXT_DIM, bg=WIN_BODY)
        if pencil:
            px = x + 2 + min(col, 11)
            cv.put(px, y + 4, "/", AMBER, bg=WIN_BODY)
            cv.put(px + 1, y + 3, "/", MIST, bg=WIN_BODY)
            if (tick // 3) % 2:
                cv.cell(px, y + 5, "_", SHINE, WIN_BODY)

    def _check(self, cv, tick, x, y):
        cv.put(x + 3, y + 1, ".---.", GREEN)
        cv.put(x + 2, y + 2, "/     \\", GREEN)
        cv.put(x + 2, y + 3, "|   / |", GREEN)
        cv.put(x + 2, y + 4, "| \\/  |", GREEN)
        cv.put(x + 2, y + 5, "\\     /", GREEN)
        cv.put(x + 3, y + 6, "'---'", GREEN)
        r = lcg(103, tick // 3)
        for _ in range(4):
            sx, sy = x + int(r() * 14), y + int(r() * 7)
            if cv.get(sx, sy) == " ":
                cv.cell(sx, sy, "+*."[int(r() * 3)], SHINE)

    def _warning(self, cv, tick, x, y):
        on = (tick // 4) % 2
        colour = AMBER if on else "#b08040"
        cv.put(x + 4, y + 1, "/\\", colour)
        cv.put(x + 3, y + 2, "/  \\", colour)
        cv.put(x + 2, y + 3, "/ !! \\", colour)
        cv.put(x + 1, y + 4, "/______\\", colour)
        cv.put(x, y + 6, "Try again?", TEXT_DIM, solid=True)

    def _bubbles(self, cv, tick, x, y, n=4):
        for j in range(n):
            r = lcg(107, j)
            period = 30 + int(r() * 20)
            t = (tick + int(r() * period)) % period
            bx = x + int(r() * 12) + (1 if (t // 5) % 2 else 0)
            by = y - t // 4
            if by < 0:
                continue
            cv.cell(bx, by, "o" if t < period // 2 else "O", MIST if j % 2 else SKY)

    def _prop_bash(self, cv, tick, x, y):
        self._window(cv, x, y, 16, 7, "cmd", body=CMD_BODY)
        cyc = tick // 30
        cmd = CMDS[cyc % len(CMDS)]
        n = min(len(cmd), (tick % 30) // 2)
        for k in range(3):
            prev = CMDS[(cyc - 3 + k) % len(CMDS)]
            cv.put(x + 1, y + 1 + k, ("C:\\>" + prev)[:14], TEXT_DIM, bg=CMD_BODY)
        cv.put(x + 1, y + 5, ("C:\\>" + cmd[:n])[:14], TEXT, bg=CMD_BODY)
        if (tick // 3) % 2:
            cv.cell(x + 5 + n, y + 5, "_", TEXT, CMD_BODY)

    def _prop_book(self, cv, tick, x, y):
        self._doc(cv, tick, x, y)
        hot = (tick // 3) % 5
        for c in range(14):
            cv.recolour(x + 1 + c, y + 1 + hot, SHINE, SEL)

    def _prop_pad(self, cv, tick, x, y):
        self._doc(cv, tick, x, y, stream=True, pencil=True)

    def _prop_lens(self, cv, tick, x, y):
        self._window(cv, x, y, 16, 7, "Search")
        cv.fill(x + 1, y + 1, 14, 1, "#1c4070")
        q = "files"
        n = min(len(q), (tick % 40) // 3)
        cv.put(x + 2, y + 1, q[:n], TEXT, bg="#1c4070")
        cv.put(x + 13, y + 1, "O", SKY, bg="#1c4070")
        hit = (tick // 5) % 4
        for k, f in enumerate(("theme.py", "aero.css", "notes.txt", "photo.png")):
            cv.put(x + 2, y + 2 + k, f.ljust(12), SHINE if k == hit else TEXT_DIM,
                   bg=SEL if k == hit else WIN_BODY)

    def _prop_globe(self, cv, tick, x, y):
        land = ("~/\\_  ~~ /\\  ", "_/  \\__  ~ _/", "  ~~  \\_/  ~ ")
        off = (tick // 3) % len(land[0])
        cv.put(x + 3, y, ".-\"\"-.", SKY)
        cv.put(x + 2, y + 1, "/      \\", SKY)
        cv.put(x + 2, y + 2, "|      |", SKY)
        cv.put(x + 2, y + 3, "\\      /", SKY)
        cv.put(x + 3, y + 4, "`-..-'", SKY)
        for k in range(3):
            seg = (land[k] * 2)[off:off + 6]
            cv.put(x + 3, y + 1 + k, seg, GREEN)
        # the orbit
        a = tick * 0.4
        ex, ey = x + 6 + int(round(math.cos(a) * 6)), y + 2 + int(round(math.sin(a) * 1.2))
        cv.cell(ex, ey, "*", AMBER)
        # the Windows 7 progress bar: green, with a light sweeping along it
        bx, by, bw = x, y + 6, 15
        pct = (tick * 2) % 101
        n = max(1, int(pct / 100 * bw))
        cv.fill(bx, by, bw, 1, "#1a3048")
        cv.fill(bx, by, n, 1, BAR_GREEN)
        sweep = bx + (tick % (bw + 4)) - 2
        for c in (sweep, sweep + 1):
            if bx <= c < bx + n:
                cv.recolour(c, by, bg=BAR_SHINE)

    def _helpers(self, cv, tick):
        """Two small orbs bobbing either side."""
        for n, x in enumerate((max(0, self.cx - 8), min(self.cols - 7, self.cx + COMP_W + 1))):
            y = self.ground - 5 - (1 if math.sin(tick / 5.0 + n * 2) > 0 else 0)
            hi = ("#3f9a5a", "#7a5ab8")[n]
            cv.sprite(x, y, " .-. ", SKY)
            cv.sprite(x, y + 1, "(o o)", SHINE, bg=hi)
            cv.sprite(x, y + 2, " `-' ", SKY)
        px, py = self.cx + OW + 2, self.ground - 8
        self._window(cv, px, py, 16, 5, "Helpers")
        k = (tick // 8) % 3
        cv.put(px + 1, py + 2, ("asking" + "." * k).ljust(10), TEXT, bg=WIN_BODY)
        cv.put(px + 1, py + 3, "2 friends", TEXT_DIM, bg=WIN_BODY)

    def _prop_todo(self, cv, tick, x, y):
        self._window(cv, x, y, 16, 6, "Tasks")
        done = (tick // 12) % (len(TODO) + 1)
        for k, item in enumerate(TODO):
            mark = "[v]" if k < done else "[ ]"
            cv.put(x + 1, y + 1 + k, mark, GREEN if k < done else TEXT_DIM, bg=WIN_BODY)
            cv.put(x + 5, y + 1 + k, item, TEXT_DIM if k < done else TEXT, bg=WIN_BODY)

    def _prop_wand(self, cv, tick, x, y):
        cv.put(x + 1, y + 6, "*", AMBER)
        cv.put(x + 2, y + 5, "/", MIST)
        self._bubbles(cv, tick, x + 2, y + 5, n=5)
