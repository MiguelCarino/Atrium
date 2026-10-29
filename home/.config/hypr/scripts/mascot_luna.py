#!/usr/bin/env python3
"""The luna theme's mascot: Folio, a cheerful manila folder sitting on one
round green hill under a blue sky, with a little XP-style taskbar along the
bottom of the stage. Same API as moe_mascot.Mascot (mascots.py picks it).
Our own drawing: an homage to the era, no Microsoft picture copied.

    sky       painted as cell backgrounds, deep blue at the top fading into
              the stage card (#0d2350 in themes/luna/llm-chat.css) near the
              hill; at night it is just the card, with stars and a moon.
              Small clouds of ~ and ( drift across it
    the hill  ONE broad smooth dome (aero has two ranges of hills; this one
              keeps the two apart): a dark green fill under an edge drawn in
              _ . - ' by how high the slope reaches into each cell, so the
              curve reads smoothly, grass tufts below the edge
    taskbar   the bottom row: a blue strip, a green "start" segment at the
              left, Folio's own task button when there is room, the real
              HH:MM in a lighter tray well at the right
    Folio     13 x 7 cells: a tab bump at the top left, the back of the
              folder, the front flap in a deeper manila, a dark outline, a
              small shine, a friendly face; it bobs one row, and its shadow
              lies on the hill under it
    props     to its right, small windows with a blue title row and - x:
              C:\\>_ on black for Bash, a page with lines for Read, the page
              and a pencil for Edit/Write, a search box and an O- magnifier
              for the searches, a (@) globe and XP's green progress blocks for
              WebFetch, two mini folders for Task/Agent, a to-do list for
              TodoWrite, sparkles otherwise. Thinking is the XP hourglass (its
              sand running down, then turned over), writing the flap opening
              and pages fluttering over to a page that fills with words, done
              a balloon tip with a green v/ (Folio hops), an error a red (x)
              window, the folder drooping, a sweat drop

  mood      one of mascot_mood.MOODS. Idle, it is the whole face: happy
              ^ ^ w, excited starry eyes and hops, shy > < with pink cheeks,
              looking away, curious o O and a "?", focused and worried brows
              (worried sweats), sad dots and a drooping flap, sleepy shut eyes
              and z's. At work only the accents show (brows, sweat, cheeks, a
              twinkle) over the work face; sleepy works focused. calm (or
              None) is its usual face. The idle fidget at the end of each
              9-second round (shuffling its papers, peeking out of the flap, a
              balloon popping up, a wave, a yawn) is picked by the noise and
              weighted by the mood.
  scene     a set of mascot_mood.SCENES: day (the blue sky), night (the card,
              stars, a crescent moon), sun (a sun at the top right), cloud
              (more clouds, a dimmer sky; any overcast tag hides the sun),
              rain and storm (rain over the stage; a flash and a bolt now and
              then in a storm), snow (flakes, a snowcap on the hill), fog
              (drifting bands), hot (heat shimmer, a sweat drop), cold (frost
              on the folder's corners, breath puffs), music (notes, a bob to
              the beat, a note in the tray), game (a little controller in the
              idle slot), party (a party hat, confetti), festive (papel picado
              along the top), clock (the taskbar clock flashes and a (!)
              balloon pops up over it).

Mid and deep blues, a dark green hill; the light cells are small (eyes, the
shine, a balloon of a few cells). Every glyph is single-column.
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import STATES, BaseMascot, Canvas, blink, lcg, prop_kind, stream_lines  # noqa: E402
from mascot_mood import MOODS, word  # noqa: E402

THEME = "luna"
PANEL = "#0d2350"

# the folder
TAB = "#d9b44a"
BODY = "#c9a23c"
FLAP = "#a8842a"
INSIDE = "#7a5c18"          # the inside of the folder, seen with the flap open
OUTLINE = "#6b5214"
SHINE = "#f2dc8a"
INK = "#1c1a14"
CHEEK = "#ff9a8a"
BODY_DIM = "#a89050"        # sad / error: a tired, greyer manila
FLAP_DIM = "#8a7438"
TAB_DIM = "#b09a58"
# the land and the sky
SKY_TOP = "#163d94"
SKY_TOP_DIM = "#112f72"     # overcast: a dimmer sky
HILL = "#1f5a24"
HILL_EDGE = "#5fae4a"
TUFT = "#4f9a3e"
SHADOW = "#123a16"
CLOUD = "#9fb8e0"
CLOUD_GREY = "#6f86ac"
CLOUD_STORM = "#566e94"
STAR = "#a8c8f0"
STAR_DIM = "#5a78a8"
MOON = "#f3e3a8"
SUN = "#ffd75e"
RAIN = "#9fc4f0"
SNOW = "#f2f8ff"
FOG = "#5a7898"
FLASH = "#25499a"           # the sky in a lightning flash: lighter, still dark
# the taskbar and the windows
TASKBAR = "#1d4cb0"
START = "#2b7f2b"
TASK_BTN = "#143680"        # Folio's task button, pressed (it is the window in front)
TRAY = "#0e66b0"
WHITE = "#ffffff"
TEXT = "#e4eefa"
TEXT_DIM = "#9fb0d0"
TITLE = "#2459c8"
CLOSE = "#c8402c"
WIN_BODY = "#10285a"
CMD_BODY = "#000000"
PAGE = "#b8b39c"            # a dimmed cream page, small enough for the HDR screen
PAGE_DIM = "#4e4a36"
SEL = "#316ac5"
BALLOON = "#cbc7a3"
GOOD = "#14540f"
BAD = "#ff6b5a"
BAR = "#3fa83a"
TROUGH = "#b8b39c"
GLASS = "#9fb8e0"           # the hourglass frame
SAND = "#e3c04a"
GLOW = "#f0a030"            # XP's hot-track orange
SWEAT = "#9fd0ff"
NOTE = ("#ffd75e", "#a8e890")
CONFETTI = ("#ff8a7a", "#ffd75e", "#a8e890", "#9cc2ff", "#c8b8ff")
PICADO = ("#ff6fae", "#ffa94d", "#7fd46f", "#6fb6ff", "#c58bff", "#ffd84d")
OVERCAST = frozenset(("cloud", "rain", "storm", "snow", "fog"))

OW, OH = 13, 7
FOLDER = [
    " .----.      ",
    "/      '----.",
    "|           |",
    "|           |",
    "|           |",
    "|           |",
    "'-----------'",
]
EYES = (3, 9)               # row 3
MOUTH = (4, 6)              # row 4, on the flap
# the flap, open (writing / the peek fidget): its edge folds down in a V
OPEN = ("|\\         /|", "| `-------' |")
# the flap, drooping (sad / error)
DROOP = "|`-._   _.-'|"

COMP_W = OW + 2 + 17
WORDS = ("the", "file", "is", "ready", "and", "all", "set", "your", "notes", "ok", "to",
         "folder", "now", "done", "a", "it", "saved", "so", "here")
CMDS = ("dir", "ver", "cls", "tree", "ping", "type")
TODO = ("Back up", "Update", "Tidy up")

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
# Brows on the folder above each eye (row 2): left, right.
BROWS = {"focused": ("\\", "/"), "worried": ("/", "\\"), "sad": ("/", "\\")}
# The idle fidget a mood favours: (name, weight); "rest" is none at all.
FIDGETS = {
    "calm": (("shuffle", 2), ("peek", 2), ("balloon", 2), ("wave", 1), ("rest", 2)),
    "happy": (("wave", 3), ("balloon", 2), ("shuffle", 1)),
    "excited": (("wave", 3), ("balloon", 2), ("peek", 2)),
    "shy": (("peek", 3), ("rest", 3)),
    "curious": (("peek", 3), ("balloon", 2)),
    "focused": (("shuffle", 3), ("rest", 2)),
    "worried": (("shuffle", 2), ("rest", 2)),
    "sad": (("rest", 1),),
    "sleepy": (("yawn", 3), ("rest", 2)),
}

MOOD_BUBBLES = {
    "happy": "Neat as a new folder. Ready for the next job!",
    "excited": "Ooh, a new project! I've got a fresh folder ready!",
    "shy": "Oh! I didn't see you there… hello ☺",
    "curious": "What's in there? Let's take a look!",
    "focused": "Sorting things out. I'm listening.",
    "worried": "Hmm, something looks out of order…",
    "sad": "My papers are all crumpled today…",
    "sleepy": "Folio is idle… zz",
}
# mascot_mood topics in its words, a balloon tip's voice (str.format with
# the topic's arguments).
TOPIC_LINES = {
    "thanks": "Any time! I'll file that one under \"nice\".",
    "worried": "Hmm, that doesn't look right. Shall we check?",
    "frustrated": "Stuck again? Let's sort it out afresh.",
    "relieved": "Phew! It works now.",
    "determined": "This is a big one. I'll keep the papers in order.",
    "proud": "All done, and neatly filed!",
    "sad": "Oh dear. I'll sit quietly in the drawer for a bit…",
    "happy": "Hooray!",
    "curious": "Interesting! Tell me more?",
    "rain": "It's raining outside. Good day to stay in and tidy up.",
    "storm": "A storm is coming. Save your work!",
    "snow": "Snow on the hill! I'll keep your files cosy ❄",
    "fog": "Can't see the hill for the fog. Careful as you go.",
    "sun": "Lovely sunny day on the hill ☀",
    "hot": "It's {0} outside. Stay cool!",
    "cold": "{0}! Chilly enough to curl my corners.",
    "gpu_hot": "Graphics card at {0}°C. Don't toast my edges!",
    "cpu_hot": "Processor at {0}°C! Time for a breather.",
    "music": "Nice tune! ♪",
    "game": "Play first, paperwork later!",
    "event": "Psst: {0} comes up in {1} min.",
    "event_now": "Now's the moment: {0}.",
    "birthday": "It's your big day, {0}! Party hats on 🎈",
    "holiday": "It's {0}. The in-tray can wait!",
    "go_home": "{0} already. Close the drawers, go home!",
    "bedtime": "{0}. Even the files need their sleep. Shut down?",
    "morning": "Morning! I've sorted today's papers.",
    "lunch": "Time for a lunch break?",
    "weekend": "No in-tray on a weekend. Go play outside!",
    # conversation and stage events (a tuple: variants, said in turn)
    "friday": "Friday afternoon! Nearly time to log off ☺",
    "hello": ("Hi there! What shall we file today?",
              "Hello! Fresh folder, ready to go.",
              "Welcome! Pick a task, any task."),
    "welcome_back": "Welcome back! I kept your desktop tidy.",
    "wake": ("Oh! Sorry, my screensaver kicked in.",
             "Huh? I'm up! Just defragmenting…"),
    "long_prompt": ("That's a thick stack of papers!",
                    "Whoa, this needs a bigger folder!"),
    "code": ("Code! Let me get the right folder.",
             "Ooh, source files. I'll sort them."),
    "image": ("A picture! Straight into My Pictures.",
              "Ooh, a picture! Nice thumbnail."),
    "aborted": ("Cancelled. Nothing was lost!",
                "Stopped. Undo is my middle name."),
    "tests_pass": ("All tests passed! ✓",
                   "Green checkmarks all round!",
                   "Tests OK. Filed under \"works\"."),
    "tests_fail": ("Some tests failed. Let's take a look.",
                   "Tests failed… I'll pull the report."),
    "commit": ("Committed! Safely filed away.",
               "Saved to history ✓",
               "Shipped! Stamped and filed."),
    "fast": ("That was quick!",
             "Done in a click!",
             "Speedy! Like a fresh install."),
    "busy": ("So many windows open! Busy busy…",
             "Lots of tasks running. Hang on!"),
    "model": ("Say hello to {0}!",
              "New helper on the job: {0}."),
    "poke": ("Hi! Need a hand?",
             "Hee, that tickles my tab!",
             "You clicked me! Shall we work?",
             "Double-click to open… just kidding!",
             "Yes? I'm all ears. Well, all tabs.",
             "Psst! I'm a folder, not a button ☺"),
    "poke_spam": ("Hey! My papers are going everywhere!",
                  "Easy! You'll scatter my files!",
                  "Okay, okay! I'm wide awake!"),
    "pet": ("Aww, you're making my corners curl ☺",
            "That's nice… I feel so organised.",
            "Hehe, a gold star for me?",
            "D'aww. Best desktop ever."),
    # railguard.py's notifications (mascot_notify.py says them, voice on)
    "rg_memory": "{0} was hogging the memory -- I've put it away.",
    "rg_vram": "{0} filled the graphics memory -- filed it away.",
    "rg_game_vram": "{0} is using nearly all the graphics memory. Lower the textures?",
    "rg_panic": "Done! {0} is closed.",
    "rg_stuck": "Memory's nearly full and I can't find which file to close...",
    "rg_agents": "All the agents' jobs are closed. Your sessions are safe.",
}
# The reaction sign over its head (mascot_mood.EMOTE_TONES) in Folio's
# palette: >= 5:1 on the stage card, >= 3:1 on the bright sky top and a
# lightning flash behind the anchor.
EMOTE_COLOURS = {"accent": "#9cc2ff", "warn": SUN, "bad": BAD,
                 "good": "#a8e890", "love": "#ffa0c8", "dim": TEXT_DIM}


def _mix(a, b, f):
    """The colour f of the way from hex a to hex b."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * f)) for x, y in zip(pa, pb))


class Mascot(BaseMascot):
    BUBBLES = {
        "idle": "Hi, I'm Folio! What shall we work on?",
        "thinking": "Please wait…",
        "writing": "Writing it up…",
        "done": "Done! Everything's filed ✓",
        "error": "Hmm, that didn't work. Want to try again?",
    }
    TOOL_BUBBLES = {
        "Bash": "Running a command…",
        "Read": "Opening the file…",
        "Edit": "Saving changes…",
        "MultiEdit": "Saving changes…",
        "Write": "Saving changes…",
        "NotebookEdit": "Saving changes…",
        "Grep": "Searching your files…",
        "Glob": "Searching your files…",
        "WebSearch": "Searching the web…",
        "WebFetch": "Downloading…",
        "Task": "Asking a few helpers…",
        "Agent": "Asking a few helpers…",
        "TodoWrite": "Updating your to-do list…",
    }
    OTHER = "Working with %s…"
    moods = True

    def __init__(self, cols=64, rows=18):
        self.cols = max(int(cols), COMP_W + 2)
        self.rows = max(int(rows), OH + 7)
        self.cx = (self.cols - COMP_W) // 2
        self.bottom = self.rows - 2           # the hill's lowest row (the taskbar is under it)
        # The dome: highest under Folio, falling smoothly to both sides, a
        # little wobble so it is not a perfect arc. Heights are floats (cells
        # above the bottom row); the fraction picks the edge glyph.
        peak = 4.5 if self.rows >= 18 else 3.6
        hc = self.cx + OW / 2.0
        half = max(self.cols * 0.62, 30.0)
        self._h = []
        for x in range(self.cols):
            u = min(1.0, abs(x + 0.5 - hc) / half)
            self._h.append(0.9 + (peak - 0.9) * (1 - u * u) + 0.25 * math.sin(x * 0.17 + 1.3))
        # the first row of hill under Folio's middle: it sits just above it
        self.ground = self.bottom - int(self._h[int(hc)])
        self._tufts = [lcg(89, x)() for x in range(self.cols)]
        self._stream = stream_lines(WORDS, 12, seed=67)
        self._clouds = []
        for i in range(max(2, self.cols // 28)):
            r = lcg(79, i, self.cols)
            self._clouds.append((r() * self.cols, int(r() * max(2, self.ground // 3)), 0.02 + r() * 0.03))
        # overcast: as many again, from their own noise
        self._grey = []
        for i in range(max(2, self.cols // 24)):
            r = lcg(83, i, self.cols)
            self._grey.append((r() * self.cols, int(r() * max(2, self.ground // 3)), 0.03 + r() * 0.03))
        self._stars = []
        for i in range(self.cols * self.rows // 40):
            r = lcg(97, i)
            self._stars.append((int(r() * self.cols), int(r() * max(2, self.ground - 3)),
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

    def _edge(self, x):
        """The row of the hill's edge glyph at column x."""
        return self.bottom - int(self._h[x])

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
        self._hill(cv, tick, scene)
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
        self._taskbar(cv, tick, scene)
        if state == "done":
            hover = (0, 1, 2, 2, 1, 0, 0, 0)[tick % 8]      # hopping for joy
        elif idle and mood == "excited" and (tick // 30) % 2:
            hover = (0, 1, 2, 2, 1, 0)[tick % 6]
        elif state == "error" or (idle and mood in ("sad", "sleepy")):
            hover = 0                   # slumped on the grass
        elif "music" in scene:
            hover = (tick // 4) % 2     # bobbing to the beat
        else:
            hover = 1 if math.sin(tick / 7.0) > 0 else 0
        top = self.ground - OH - hover
        ox = self.cx
        self._shadow(cv, ox, hover)
        if kind == "helpers":
            self._helpers(cv, tick)
        # the reaction sign's anchor: just above the right of its top edge
        # (the tab is at the left), clear of the face and the "?" spot
        self.head = (min(ox + OW - 3, self.cols - 3), max(0, top))
        self._folder(cv, state, tick, ox, top, mood, scene, fidget)
        self._mood_marks(cv, state, tick, ox, top, mood, scene, fidget)
        if "party" in scene:
            self._hat(cv, tick, ox, top)
        px, py = self.cx + OW + 2, self.ground - 8
        if state == "thinking":
            self._hourglass(cv, tick, px + 4, py)
        elif state == "writing":
            self._pages(cv, tick, ox, top, px, py)
            self._doc(cv, tick, px, py, stream=True, pencil=True)
        elif state == "done":
            self._check(cv, tick, px, py)
        elif state == "error":
            self._error(cv, tick, px, py)
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
        pick = lcg(109, tick // 90)() * sum(w for _, w in table)
        for name, weight in table:
            pick -= weight
            if pick < 0:
                return None if name == "rest" else name
        return None

    # -- the sky and the land ----------------------------------------------------------

    def _sky(self, cv, state, tick, scene=frozenset()):
        """By day (and by default) the sky is cell backgrounds from deep
        blue at the top into the card colour at the hill; by night only the
        card, with stars and the moon. Anything overcast dims the sky, hides
        the sun and greys the clouds."""
        overcast = bool(scene & OVERCAST)
        clear = not overcast and state != "error"
        night = "night" in scene
        flash = "storm" in scene and tick % 47 < 2
        if not night or flash:
            top = FLASH if flash else (SKY_TOP_DIM if overcast else SKY_TOP)
            span = max(1, self.ground)
            for y in range(self.bottom + 1):
                bg = _mix(top, PANEL, min(1.0, y / float(span)))
                for x in range(self.cols):
                    cv.recolour(x, y, bg=bg)
        y0 = 2 if "festive" in scene else 0
        if night:
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

    def _cloud_layer(self, cv, tick, scene=frozenset()):
        overcast = bool(scene & OVERCAST)
        grey = CLOUD_STORM if "storm" in scene else CLOUD_GREY
        y0 = 3 if "festive" in scene else 1        # under the papel picado
        if overcast:
            # the heavier ones, behind the small puffs
            for x0, y, speed in self._grey:
                x = int(x0 + tick * speed) % (self.cols + 14) - 10
                y += y0
                cv.put(x + 2, y, "(~~~)  (~~)", grey)
                cv.put(x, y + 1, "(~~~~~~~~~~~~)", grey)
        colour = CLOUD if not overcast else CLOUD_GREY
        for x0, y, speed in self._clouds:
            x = int(x0 + tick * speed) % (self.cols + 10) - 7
            y += y0
            cv.put(x + 1, y, "(~~)", colour)
            cv.put(x, y + 1, "(~~~~~)", colour)

    def _hill(self, cv, tick, scene=frozenset()):
        """The one dome: the fill below the edge, then the edge glyph picked
        by how far the slope reaches into its cell (_ low, . - ' higher), so
        a gentle curve shows in a coarse grid."""
        snow = "snow" in scene
        for x in range(self.cols):
            h = self._h[x]
            top = self.bottom - int(h)
            for y in range(top + 1, self.bottom + 1):
                cv.cell(x, y, " ", None, HILL)
            frac = h - int(h)
            glyph = "_.-'"[min(3, int(frac * 4))]
            cv.cell(x, top, glyph, SNOW if snow else HILL_EDGE)
        # grass tufts just under the edge, swaying (snowballs under snow)
        wind = (tick // 6) % 2
        for x, v in enumerate(self._tufts):
            if v < 0.22:
                y = self._edge(x) + 1
                if y <= self.bottom:
                    if snow:
                        cv.cell(x, y, "." if v < 0.1 else "o", SNOW, HILL)
                    else:
                        cv.cell(x, y, ",'"[(x + wind) % 2] if v < 0.11 else "\"", TUFT, HILL)

    def _shadow(self, cv, ox, hover):
        """Its shadow on the hill: narrower the higher it hops."""
        w = 11 - hover * 2
        for c in range(w):
            x = ox + (OW - w) // 2 + c
            if 0 <= x < self.cols:
                cv.cell(x, self._edge(x), "_", SHADOW, HILL)

    def _taskbar(self, cv, tick, scene=frozenset()):
        """The bottom row: the blue strip, a green start segment, Folio's
        task button, the tray well with the real time in it. The clock
        scene flashes the clock; music puts a note in the tray."""
        y = self.rows - 1
        cv.fill(0, y, self.cols, 1, TASKBAR, occupy=False)
        cv.put(0, y, " start ", WHITE, bg=START)
        cv.cell(7, y, ")", "#1d5a1d", TASKBAR)
        if self.cols >= 60:
            cv.put(9, y, " Folio ", TEXT, bg=TASK_BTN)
        clock = time.strftime(" %H:%M ")   # the real time: it reacts to it anyway
        ring = "clock" in scene and (tick // 5) % 2
        cx = self.cols - len(clock)
        cv.put(cx, y, clock, INK if ring else WHITE, bg=GLOW if ring else TRAY)
        icons = [("d", NOTE[0])] if "music" in scene else []
        if "clock" in scene:
            icons.append(("!", GLOW if ring else WHITE))
        tx = cx - 2 * len(icons)
        cv.fill(tx, y, 2 * len(icons), 1, TRAY, occupy=False)
        for i, (c, colour) in enumerate(icons):
            cv.cell(tx + 1 + 2 * i, y, c, colour, TRAY)
        if "clock" in scene and (tick // 10) % 3:
            # the balloon tip popping up over the tray, its tail pointing down
            text = " (!) Reminder "
            bx = max(0, self.cols - len(text) - 1)
            cv.put(bx, y - 2, text, INK, bg=BALLOON)
            cv.cell(bx + 2, y - 2, "!", "#8e1c16", BALLOON)
            cv.cell(self.cols - 4, y - 1, "V", BALLOON)

    # -- the scene (mascot_mood.SCENES) ------------------------------------------------

    def _sun(self, cv, tick, y=0):
        """The sun at the top right."""
        x = self.cols - 7
        rays = ("\\ | /", "  |  ", "\\   /")[(tick // 8) % 3]
        cv.put(x, y, rays, SUN)
        cv.put(x, y + 1, "-(O)-", SUN)
        cv.put(x, y + 2, "/ | \\" if rays[0] == "\\" else "  |  ", SUN)

    def _lightning(self, cv, tick):
        cyc, t = divmod(tick, 47)
        if t > 3:
            return
        x = int(lcg(113, cyc)() * (self.cols - 4)) + 1
        for k, (dx, ch) in enumerate(((1, "/"), (0, "/"), (0, "\\"), (1, "/"))):
            cv.cell(x + dx + (k > 1), 1 + k, ch, SUN if t % 2 == 0 else SNOW)

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
            if y < self.rows - 1 and cv.get(x, y) == " ":
                cv.cell(x, y, "*.+"[i % 3], SNOW)

    def _weather_rain(self, cv, tick, heavy=False):
        """Slanted rain over the stage, on the cells still blank (Folio and
        the windows are drawn over it)."""
        span = self.rows + 2
        for i in range(self.cols * self.rows // (14 if heavy else 24)):
            r = lcg(137, i)
            speed = (0.7 if heavy else 0.5) + r() * 0.3
            y = int((r() * span + tick * speed) % span) - 1
            x = int(r() * self.cols - y * 0.5) % self.cols
            if y < self.rows - 1 and cv.get(x, y) == " ":
                cv.cell(x, y, "/", RAIN)

    def _shimmer(self, cv, tick):
        """Heat rising off the hill."""
        for x in range(self.cols):
            if lcg(139, x, tick // 3)() < 0.08:
                y = self._edge(x) - 1 - (x % 2)
                if cv.get(x, y) == " ":
                    cv.cell(x, y, "~", GLOW)

    def _confetti(self, cv, tick):
        span = self.rows + 2
        for i in range(max(4, self.cols * self.rows // 90)):
            r = lcg(149, i)
            pos = r() * span + tick * (0.12 + r() * 0.1)
            fall = int(pos // span)
            y = int(pos - fall * span) - 1
            x = int(lcg(151, i, fall)() * self.cols) + (tick // 4 + i) % 2
            if y < self.rows - 1 and cv.get(x, y) == " ":
                cv.cell(x, y, ",'.*"[(tick // 3 + i) % 4], CONFETTI[i % len(CONFETTI)])

    def _hat(self, cv, tick, ox, top):
        """A party hat on the tab."""
        cv.cell(ox + 3, top - 3, "*+"[(tick // 4) % 2], SUN)
        cv.put(ox + 2, top - 2, "/:\\", CONFETTI[0])
        cv.put(ox + 1, top - 1, "/_:_\\", CONFETTI[3])
        cv.cell(ox + 3, top - 2, ":", SUN)
        cv.cell(ox + 3, top - 1, ":", SUN)

    def _controller(self, cv, tick, x, y):
        """Game time: a little pad where the props go, its buttons lighting
        up in turn."""
        cv.put(x + 1, y + 2, "  .-----.  ", CLOUD)
        cv.put(x + 1, y + 3, " / +  o o\\ ", CLOUD)
        cv.put(x + 1, y + 4, "(   .-.   )", CLOUD)
        cv.put(x + 1, y + 5, " `-'   `-' ", CLOUD)
        cv.cell(x + 4, y + 3, "+", TEXT)
        cv.cell(x + 7, y + 3, "o", NOTE[1])
        cv.cell(x + 9, y + 3, "o", (SUN, BAD, NOTE[1], RAIN)[(tick // 3) % 4])
        cv.put(x + 2, y + 6, " Game on! ", WHITE, bg=START if (tick // 6) % 2 else TASK_BTN)

    # -- Folio -----------------------------------------------------------------------

    def _folder(self, cv, state, tick, x0, top, mood="calm", scene=frozenset(), fidget=None):
        idle = state == "idle"
        tired = state == "error" or (idle and mood in ("sad", "sleepy"))
        tab, body, flap = (TAB_DIM, BODY_DIM, FLAP_DIM) if tired else (TAB, BODY, FLAP)
        t = tick % 90 - 72
        opened = state == "writing" or (fidget == "peek" and 4 <= t < 15)
        for i, r in enumerate(FOLDER):
            cv.sprite(x0, top + i, r, OUTLINE)      # opaque inside: no cloud or rain shows through
        # the paper colours inside the outline: the tab's bump, the back,
        # the front flap
        for c in range(1, 7):
            cv.recolour(x0 + c, top + 1, bg=tab)
        for i in (2, 3):
            for c in range(1, OW - 1):
                cv.recolour(x0 + c, top + i, bg=body)
        for i in (4, 5):
            for c in range(1, OW - 1):
                cv.recolour(x0 + c, top + i, bg=INSIDE if opened else flap)
        if opened:
            # the flap folded down: its edge a V, the dark inside showing
            for i, r in enumerate(OPEN):
                for c, ch in enumerate(r[1:-1], 1):
                    if ch != " ":
                        cv.cell(x0 + c, top + 4 + i, ch, OUTLINE, INSIDE)
        elif tired or (idle and mood == "worried"):
            for c, ch in enumerate(DROOP[1:-1], 1):
                if ch != " ":
                    cv.cell(x0 + c, top + 5, ch, OUTLINE, flap)
        # papers peeking out of the top (the shuffle fidget, and at work)
        if fidget == "shuffle" or state in ("tool", "writing"):
            off = (tick // 3) % 2 if fidget == "shuffle" else 0
            cv.put(x0 + 8 + off, top, "[==]"[:4 - off], PAGE_DIM, bg=PAGE)
        # the shine at the top right of the back
        cv.cell(x0 + 10, top + 2, "'", SHINE, body)
        if "cold" in scene:
            # frost on the folder's bottom corners
            for c, i in ((1, 5), (11, 5)):
                cv.cell(x0 + c, top + i, "*", SNOW, flap)
        # face
        eye = "^" if state == "done" else "o"
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
        if state == "error":
            left, right = "x", "x"
        if fidget == "peek":
            gaze = -1 if t < 9 else 1      # peeking out, left then right
        elif fidget == "yawn":
            left = right = "-"
            mouth = "O" if 3 <= t < 14 else "o"
        elif fidget == "balloon":
            mouth = "o"
        shut = blink(tick, 47) and state not in ("done", "error")
        for ex, ch in zip(EYES, (left, right)):
            cv.cell(x0 + ex + gaze, top + 3, "-" if shut else ch, INK, body)
        mbg = INSIDE if opened else flap
        cv.cell(x0 + MOUTH[1] + gaze, top + MOUTH[0], mouth, SHINE if opened else INK, mbg)
        if mood in BROWS and state != "done":
            for ex, ch in zip(EYES, BROWS[mood]):
                cv.cell(x0 + ex + gaze, top + 2, ch, OUTLINE, body)
        # sweat / a tear / cheeks
        if state == "error" or ((mood == "worried" or "hot" in scene) and state != "done"):
            s = (tick // 5) % 4
            if s < 3:
                cv.cell(x0 + OW, top + 1 + s, "',."[s], SWEAT)
        if cheek and not opened:
            cv.cell(x0 + 2, top + 4, cheek, CHEEK, mbg)
            cv.cell(x0 + 10, top + 4, cheek, CHEEK, mbg)
        if mood == "sad" and idle:
            s = (tick // 6) % 3
            if s < 2:
                cv.cell(x0 + EYES[0] + gaze, top + 4 + s, ",'"[s], SWEAT, mbg)

    def _mood_marks(self, cv, state, tick, ox, top, mood, scene, fidget):
        """What floats around it for its mood and scene: z's, a "?", "!"s,
        a little balloon, a waving hand, music notes, breath in the cold."""
        idle = state == "idle"
        t = tick % 90 - 72
        if idle and mood == "sleepy":
            s = tick % 36
            for j in range(3):
                if s // 9 > j:
                    cv.cell(ox + OW + 1 + j, top + 1 - j, "zzZ"[j], TEXT_DIM if j < 2 else TEXT)
        elif idle and mood == "curious" and (tick // 5) % 4:
            cv.cell(ox + OW + 1, top, "?", SUN)
        elif idle and mood == "excited" and (tick // 3) % 4 < 2:
            cv.cell(ox - 1, top, "!", SUN)
            cv.cell(ox + OW + 1, top, "!", SUN)
        elif mood == "excited" and state in ("thinking", "tool", "writing", "done"):
            if (tick // 3) % 4 == 0:
                cv.cell(ox + OW + 1, top, "+", SUN)
        if fidget == "balloon" and t >= 2:
            # a balloon tip pops up over its tab
            cv.put(ox - 1, top - 2, " Hi! ", INK, bg=BALLOON)
            cv.cell(ox + 1, top - 1, "V", BALLOON)
        elif fidget == "wave":
            arm = "\\/"[(tick // 3) % 2]
            cv.cell(ox + OW, top + 3, "o", BODY)
            cv.cell(ox + OW + 1, top + 2, arm, BODY)
        if "music" in scene:
            for j in range(2):
                s = (tick + j * 12) % 24
                if s < 20:
                    cv.cell(ox - 2 - s // 6 - j * 2, top + 5 - s // 5, "db"[j], NOTE[j])
        if "cold" in scene and idle:
            s = tick % 40
            if s < 12:
                cv.cell(ox + OW + 1 + s // 4, top + 4 - s // 6, ".oO"[min(2, s // 4)], SNOW)

    # -- things beside it ------------------------------------------------------------

    def _window(self, cv, x, y, w, h, title, body=WIN_BODY):
        """A little XP window: a blue title row with - x, the body under it."""
        cv.fill(x, y, w, h, body)
        cv.fill(x, y, w, 1, TITLE)
        cv.put(x + 1, y, title[:w - 6], WHITE, bg=TITLE)
        cv.cell(x + w - 4, y, "-", WHITE, TITLE)
        cv.cell(x + w - 2, y, "x", WHITE, CLOSE)

    def _hourglass(self, cv, tick, x, y):
        """The XP hourglass in ASCII: the sand runs from the top bulb to the
        bottom one a grain at a time, a grain falling through the neck, then
        it is turned over and runs again."""
        frame = ("._____.", "\\     /", " \\   / ", "  ) (  ", " /   \\ ", "/     \\", "'-----'")
        for i, r in enumerate(frame):
            cv.put(x, y + i, r, GLASS)
        top_cells = [(1, 1), (1, 5), (1, 2), (1, 4), (1, 3), (2, 2), (2, 4), (2, 3)]
        bottom_cells = [(5, 3), (5, 2), (5, 4), (5, 1), (5, 5), (4, 3), (4, 2), (4, 4)]
        t = tick % 40
        n = min(8, t // 4)      # the last few ticks it rests full, then turns over
        for k, (r, c) in enumerate(top_cells):
            if k >= n:
                cv.cell(x + c, y + r, ":", SAND)
        for k, (r, c) in enumerate(bottom_cells):
            if k < n:
                cv.cell(x + c, y + r, ".", SAND)
        if n < 8 and tick % 2:
            cv.cell(x + 3, y + 3, ":", SAND)
        cv.put(x - 3, y + 7, ("Please wait" + "." * ((tick // 4) % 4)).ljust(14), TEXT_DIM, solid=True)

    def _doc(self, cv, tick, x, y, stream=False, pencil=False, title="Notes"):
        """A window holding a dimmed cream page with lines of text."""
        self._window(cv, x, y, 16, 7, title, body=PAGE)
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
            cv.put(x + 2, y + 1 + k, text, INK if k == 4 else PAGE_DIM, bg=PAGE)
        if pencil:
            px = x + 2 + min(col, 11)
            cv.put(px, y + 4, "/", "#a04400", bg=PAGE)
            cv.put(px + 1, y + 3, "/", SAND, bg=PAGE)

    def _pages(self, cv, tick, ox, top, px, py):
        """Pages fluttering out of the open flap over to the page: each one
        an arc from Folio's middle to the window's edge."""
        x0, y0 = ox + OW - 1, top + 4
        x1, y1 = px, py + 3
        for k in range(2):
            s = ((tick + k * 9) % 18) / 18.0
            x = int(round(x0 + (x1 - x0) * s))
            y = int(round(y0 + (y1 - y0) * s - 2.5 * math.sin(s * math.pi)))
            cv.cell(x, y, "=", PAGE_DIM, PAGE)

    def _check(self, cv, tick, x, y):
        """A balloon tip with a green check: done, filed away."""
        cv.fill(x, y + 2, 15, 3, BALLOON)
        cv.put(x + 1, y + 2, "(i) Folio", "#0f3c96", bg=BALLOON)
        cv.put(x + 1, y + 3, "v/", GOOD, bg=BALLOON)
        cv.put(x + 4, y + 3, "All filed!", INK, bg=BALLOON)
        cv.put(x + 13, y + 2, "x", PAGE_DIM, bg=BALLOON)
        cv.cell(x + 1, y + 5, "/", BALLOON)
        r = lcg(103, tick // 3)
        for _ in range(4):
            sx, sy = x + int(r() * 15), y + int(r() * 7)
            if cv.get(sx, sy) == " ":
                cv.cell(sx, sy, "+*."[int(r() * 3)], SHINE)

    def _error(self, cv, tick, x, y):
        """An error window: a red (x), a short line, an OK button."""
        self._window(cv, x, y + 1, 16, 5, "Error")
        on = (tick // 4) % 2
        cv.put(x + 1, y + 2, "(x)", BAD if on else "#b04a40", bg=WIN_BODY)
        cv.put(x + 5, y + 2, "Oops!", TEXT, bg=WIN_BODY)
        cv.put(x + 5, y + 3, "Try again?", TEXT_DIM, bg=WIN_BODY)
        cv.put(x + 6, y + 5, "[ OK ]", INK, bg=PAGE)

    def _sparkles(self, cv, tick, x, y, n=5):
        for j in range(n):
            r = lcg(107, j)
            period = 24 + int(r() * 16)
            t = (tick + int(r() * period)) % period
            sx = x + int(r() * 12)
            sy = y - int(r() * 5)
            if t < period * 2 // 3:
                cv.cell(sx, sy, "*+."[(t // 4 + j) % 3], (SUN, SHINE, CLOUD)[j % 3])

    def _prop_bash(self, cv, tick, x, y):
        self._window(cv, x, y, 16, 7, "Command", body=CMD_BODY)
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
        self._doc(cv, tick, x, y, title="Reading")
        hot = (tick // 3) % 5
        for c in range(14):
            cv.recolour(x + 1 + c, y + 1 + hot, WHITE, SEL)

    def _prop_pad(self, cv, tick, x, y):
        self._doc(cv, tick, x, y, stream=True, pencil=True, title="Editing")

    def _prop_lens(self, cv, tick, x, y):
        self._window(cv, x, y, 16, 7, "Search")
        cv.fill(x + 1, y + 1, 14, 1, PAGE)
        q = "files"
        n = min(len(q), (tick % 40) // 3)
        cv.put(x + 2, y + 1, q[:n], INK, bg=PAGE)
        # the magnifier sweeping over the results
        hit = (tick // 5) % 4
        for k, f in enumerate(("notes.txt", "luna.css", "photo.png", "todo.txt")):
            cv.put(x + 4, y + 2 + k, f.ljust(11), WHITE if k == hit else TEXT_DIM,
                   bg=SEL if k == hit else WIN_BODY)
        cv.put(x + 1, y + 2 + hit, "O-", SUN, bg=WIN_BODY)

    def _prop_globe(self, cv, tick, x, y):
        self._window(cv, x, y, 16, 7, "Download")
        cv.put(x + 1, y + 2, ("(@)", "(o)", "(@)", "(O)")[(tick // 4) % 4], RAIN, bg=WIN_BODY)
        cv.put(x + 5, y + 2, "page.html", TEXT, bg=WIN_BODY)
        pct = (tick * 2) % 101
        cv.put(x + 5, y + 3, ("%d%%" % pct).ljust(5), TEXT_DIM, bg=WIN_BODY)
        # XP's progress bar: green blocks with gaps in a trough
        bx, by, bw = x + 1, y + 5, 14
        cv.fill(bx, by, bw, 1, TROUGH)
        n = int(pct / 100.0 * bw)
        for c in range(n):
            if c % 3 != 2:
                cv.recolour(bx + c, by, bg=BAR)

    def _helpers(self, cv, tick):
        """Two mini folders bobbing either side."""
        for n, x in enumerate((max(0, self.cx - 7), min(self.cols - 6, self.cx + COMP_W + 1))):
            y = self.ground - 4 - (1 if math.sin(tick / 5.0 + n * 2) > 0 else 0)
            body = (BODY, "#b8963a")[n]
            cv.put(x, y, " ._  ", OUTLINE)
            cv.put(x, y + 1, "|o o|", INK, bg=body)
            cv.cell(x, y + 1, "|", OUTLINE, body)
            cv.cell(x + 4, y + 1, "|", OUTLINE, body)
            cv.put(x, y + 2, "'---'", OUTLINE)
        px, py = self.cx + OW + 2, self.ground - 8
        self._window(cv, px, py, 16, 5, "Helpers")
        k = (tick // 8) % 3
        cv.put(px + 1, py + 2, ("asking" + "." * k).ljust(10), TEXT, bg=WIN_BODY)
        cv.put(px + 1, py + 3, "2 folders", TEXT_DIM, bg=WIN_BODY)

    def _prop_todo(self, cv, tick, x, y):
        self._window(cv, x, y, 16, 5, "To Do")
        done = 1 + (tick // 12) % len(TODO)
        for k, item in enumerate(TODO):
            mark = "[x]" if k < done else "[ ]"
            cv.put(x + 1, y + 1 + k, mark, "#a8e890" if k < done else TEXT_DIM, bg=WIN_BODY)
            cv.put(x + 5, y + 1 + k, item, TEXT_DIM if k < done else TEXT, bg=WIN_BODY)

    def _prop_wand(self, cv, tick, x, y):
        cv.put(x + 1, y + 6, "*", SUN)
        cv.put(x + 2, y + 5, "/", CLOUD)
        self._sparkles(cv, tick, x + 2, y + 4, n=6)
