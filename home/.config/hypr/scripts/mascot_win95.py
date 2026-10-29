#!/usr/bin/env python3
"""The win95 theme's mascot: a paperclip assistant with eyebrows, in a grey
"Office Assistant" window on the teal desktop. Same API as
moe_mascot.Mascot (mascots.py picks it).

    desktop   the teal of Windows 95 (#008080) on every cell -- a small
              Windows 95 screen in the stage's sunken dark bezel
              (themes/win95/llm-chat.css) -- My Computer and the Recycle
              Bin down the left when there is room, the taskbar along the
              bottom row: Start, the assistant's task button, the clock
    window    36 x 13 cells of the dimmed face grey #acacac with a navy
              title bar ("Office Assistant", _ and x), a shadow-grey edge
              on its right and bottom -- the bevel, as far as a cell grid
              can draw one
    the clip  13 x 11 cells on the window's left: two eyes (whites are
              #e4e4e4 cells, black pupils that look about) under the
              eyebrows that made him famous -- they wiggle, rise when he
              has an idea, frown on an error -- on a two-loop wire
    props     on the window's right, each a little window or icon of the
              time: an MS-DOS Prompt for Bash, a Notepad page for Read, the
              page and a pencil for Edit/Write, Find: Files or Folders for
              the searches, the flying-paper copy dialog for WebFetch, two
              small clips for Task/Agent, a checklist for TodoWrite, the
              hourglass for anything else; thinking lights a bulb, done is
              a hop and an OK box, an error the illegal-operation box

Moods and scenery (mascot_mood.py; lines / markup take mood= and scene=):

  mood    idle, it is his eyes, brows and pose: happy (^^) eyes under
          raised brows, excited starry eyes, "!"s and hops, shy >  < eyes
          and a blush, curious o.O with one brow up and a "?", focused
          frowning at the tip, worried brows and darting eyes with a sweat
          drop, sad slumped (one wire row shorter) with a tear, sleepy
          slumped with heavy lids, z's, and the Starfield screen saver for
          the tip. At work the brows, the sweat, the blush and the "!"
          carry it over the work face; done and error keep theirs. calm (or
          None) is the face he always had. The idle fidget at the end of
          each 9-second round (a brow wiggle, a look about, a wink, a paper
          plane, a yawn) is weighted by the mood.
  scene   outside is the desktop: weather only ever lands on teal cells,
          never on the window. day a sun disc, sun its rays, night a moon,
          stars and a PM clock, cloud / rain / storm / snow / fog clouds
          drifting behind the window (storm: lightning), rain and snow
          falling, a snowdrift on the window, fog bands, hot a shimmer and a
          sweat drop, cold a scarf, a shiver and icicles, music notes and a
          tray icon, game Solitaire for the tip, party a hat and confetti,
          festive papel picado along the top, clock a ringing alarm icon
          and a flashing taskbar clock. A Weather Channel ticker scrolls
          the lot along the window's bottom row, so a crowd of tags still
          reads at the smallest size.

The 16-colour palette only (teal, navy, greys, black, maroon, yellow,
green), every grey dimmed as the theme's are for an HDR primary: no white.
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import STATES, BaseMascot, Canvas, blink, lcg, prop_kind, stream_lines  # noqa: E402
from mascot_mood import ACTIVE, MOODS, word  # noqa: E402

THEME = "win95"
PANEL = "#4a4a4a"       # the stage: a dark bezel; the grid paints its own teal desktop

TEAL = "#008080"
NAVY = "#000080"
GREY = "#acacac"
HI = "#e4e4e4"
SHADOW = "#727272"
BLACK = "#000000"
FIELD = "#cccccc"
DIM = "#3a3a3a"
YELLOW = "#d4c000"
MAROON = "#800000"
RED = "#e00000"
GREEN = "#007a00"
BLUE = "#1084d0"
# papel picado and confetti: on the teal desktop, and on the window's grey
PICADO = (RED, YELLOW, HI, BLUE, GREEN)
PICADO_IN = (RED, NAVY, GREEN, BLUE, MAROON)

DW, DH = 36, 13

# The clip: rows 0-1 eyebrows (raised / resting), 2 the eyes, 3-10 the wire.
CW = 13
WIRE = [
    "   .-' '-.   ",
    "   |  _  |   ",
    "   | | | |   ",
    "   | | | |   ",
    "   | | | |   ",
    "   | '-' |   ",
    "   |     |   ",
    "   '-----'   ",
]
SLUMP = 6                  # the wire row a sad or sleepy clip sags out of
EYES_X = (2, 7)            # each eye: "(" whites whites ")"
BROWS = {
    "rest": ("~~", "~~"),
    "up": ("__", "__"),
    "think": ("_/", "~~"),
    "sad": ("\\_", "_/"),
    "glad": ("^^", "^^"),
    "worry": ("_/", "\\_"),
    "quirk": ("__", "~~"),
}
# Idle, per mood: (brows, raised left, raised right). calm: as he always was.
MOOD_BROWS = {
    "calm": ("rest", False, False),
    "happy": ("rest", True, True),
    "excited": ("up", True, True),
    "shy": ("rest", False, False),
    "curious": ("quirk", True, False),
    "focused": ("sad", False, False),
    "worried": ("worry", True, True),
    "sad": ("worry", False, False),
    "sleepy": ("up", False, False),
}
# ... and at work (thinking, tool, writing): only these change his brows.
WORK_BROWS = {"focused": "sad", "worried": "worry", "sad": "worry", "excited": "up"}
# The idle fidget a mood favours: (name, weight); "rest" is none at all.
FIDGETS = {
    "calm": (("wiggle", 2), ("look", 2), ("plane", 1), ("wink", 1), ("rest", 2)),
    "happy": (("wiggle", 2), ("wink", 2), ("plane", 2)),
    "excited": (("wiggle", 3), ("plane", 2), ("wink", 1)),
    "shy": (("look", 2), ("wink", 1), ("rest", 2)),
    "curious": (("look", 3), ("wiggle", 2), ("plane", 1)),
    "focused": (("rest", 3), ("look", 1)),
    "worried": (("look", 3), ("rest", 1)),
    "sad": (("rest", 2), ("look", 1)),
    "sleepy": (("yawn", 3), ("rest", 2)),
}
# The Weather Channel ticker: what each tag adds, in this order.
TICKER = (("sun", "Sunny"), ("cloud", "Cloudy"), ("rain", "Rain"),
          ("storm", "Severe storm warning"), ("snow", "Snow"), ("fog", "Dense fog"),
          ("hot", "Heat advisory"), ("cold", "Freeze warning"),
          ("music", "Now playing: CD Player"), ("game", "Solitaire running"),
          ("party", "party.exe"), ("festive", "Feliz dia!"),
          ("clock", "Scheduled Task due soon"))

MOOD_BUBBLES = {
    "happy": "It looks like you're having a great day! Want to keep it that way?",
    "excited": "It looks like you're about to do something AMAZING! Can I help?!",
    "shy": "Oh! I didn't see you there. Um... would you like help?",
    "curious": "It looks like you're up to something. What are we making?",
    "focused": "Focus mode on. I'll stay out of your way. Mostly.",
    "worried": "It looks like something might go wrong. Did you remember to save?",
    "sad": "It looks like nobody needs an assistant today...",
    "sleepy": "It looks like you're tired. Starting screen saver... zzz",
}
# mascot_mood topics in his words (str.format with the topic's arguments).
TOPIC_LINES = {
    "thanks": "It looks like you're saying thanks. You're welcome! Click OK.",
    "worried": "It looks like something went wrong. Would you like help?",
    "frustrated": "Abort, Retry, Ignore? ...Retry. One more time!",
    "relieved": "Phew! The problem has been resolved. Click OK to continue.",
    "determined": "This may take several minutes. Please do not turn off your computer.",
    "proud": "Task completed successfully. Nice work!",
    "sad": "The AI has performed an illegal operation and is very sorry.",
    "happy": "It looks like you're happy! Shall I run party.exe?",
    "curious": "It looks like you're asking a question. Searching Help Topics...",
    "rain": "Weather Channel: rain today. Take an umbrella.",
    "storm": "Severe storm warning! Save your work and stay inside.",
    "snow": "It looks like it's snowing! Would you like to build a snowman?",
    "fog": "Weather Channel: dense fog. Visibility: 640 x 480.",
    "sun": "Weather Channel: sunny today. Go outside -- Solitaire will wait.",
    "hot": "Heat advisory: {0} outside. Even the fan is sweating.",
    "cold": "Brr, {0} outside. Sit closer to the CRT.",
    "gpu_hot": "Warning: the GPU has reached {0}°C. Not a fatal exception... yet.",
    "cpu_hot": "Warning: the CPU is at {0}°C. Is the fan plugged in?",
    "music": "It looks like you're listening to music. Starting CD Player...",
    "game": "It looks like you're playing a game. I won't tell your boss.",
    "event": "Scheduled Task: {0} in {1} min.",
    "event_now": "Reminder: {0} is starting now! Snooze is not an option.",
    "birthday": "It looks like it's {0}'s birthday! Running party.exe...",
    "holiday": "Today is {0}! Feliz dia! Loading papel_picado.bmp...",
    "go_home": "It's {0}. It looks like you're done for the day. Shut Down?",
    "bedtime": "It's {0}. It is now safe to turn off your computer.",
    "morning": "Good morning! Windows is starting up...",
    "lunch": "It looks like it's lunch time. Minimize all windows?",
    "weekend": "It looks like it's the weekend! Solitaire, anyone?",
    "friday": "It looks like it's Friday afternoon. Log off?",
    # conversation and stage events (tuples: a new variant each time round)
    "hello": ("Hi! It looks like you're starting something.",
              "Welcome to Windows 95! Need help?",
              "Hello! I'm your Office Assistant."),
    "welcome_back": ("Welcome back! Your desktop has been restored.",
                     "It looks like you're back! Resume?"),
    "wake": ("Huh? Resuming from Standby... I'm up!",
             "Screen saver off! I wasn't sleeping."),
    "long_prompt": ("It looks like you're writing a novel!",
                    "Whoa. That's longer than AUTOEXEC.BAT."),
    "code": ("It looks like you're writing code. Help?",
             "Code! Opening it in EDIT.COM..."),
    "image": ("It looks like a picture. Opening Paint...",
              "Ooh, a bitmap! In 256 colors?"),
    "aborted": ("Operation cancelled. Click OK.",
                "Ctrl+Alt+Del! Task ended."),
    "tests_pass": ("All tests passed. Click OK to continue.",
                   "ScanDisk found no errors!",
                   "Tests passed! Shall I run party.exe?"),
    "tests_fail": ("It looks like a test failed. Retry?",
                   "Tests failed. Abort, Retry, Fix?"),
    "commit": ("Your files have been saved to C:\\.",
               "It looks like you shipped it! Click OK.",
               "Backup complete. Copied to floppy!"),
    "fast": ("Done before the hourglass even turned!",
             "That was fast! Faster than a 486.",
             "Finished in record time. Click OK."),
    "busy": ("It looks like you're very busy. Need help?",
             "Multitasking! Don't press Ctrl+Alt+Del."),
    "model": ("It looks like you installed {0}!",
              "New driver loaded: {0}."),
    "poke": ("It looks like you clicked me! Need help?",
             "Hey! I'm a paperclip, not a button.",
             "*wiggles eyebrows* Yes?",
             "Hi! Would you like a tip?",
             "Did you mean to double-click?",
             "Boing! Still here. Still helpful."),
    "poke_spam": ("It looks like you're clicking a lot. Stop?",
                  "Stop! You'll bend my wire!",
                  "Too many clicks! Not responding..."),
    "pet": ("Aww. Nobody ever pets the paperclip!",
            "Nicer than 'Hide Assistant'. Thanks!",
            "Office Assistant is now happy.",
            "*blushes in 16 colors*"),
    # railguard.py's notifications (mascot_notify.py says them, voice on)
    "rg_memory": "It looks like {0} was using all the memory. I've closed it for you!",
    "rg_vram": "It looks like {0} filled the graphics memory. It has been terminated.",
    "rg_game_vram": "It looks like {0} is using nearly all the graphics memory. Lower the details?",
    "rg_panic": "{0} has performed an illegal operation and will be shut down.",
    "rg_stuck": "Out of memory. Close some programs and try again. (I can't find which!)",
    "rg_agents": "All agent tasks have been ended. Your sessions are safe. Click OK.",
}
# The reaction sign over the head (mascot_mood.EMOTE_TONES), in the 16-colour
# palette: it sits on the window's face grey (#acacac), never on the title
# bar, so each is dark enough for >= 3:1 there. (PANEL is never behind it:
# the grid paints its own desktop over every cell.)
EMOTE_COLOURS = {
    "accent": NAVY,         # 7.1 on GREY
    "warn": "#6a5000",      # dark olive-gold: 3.4 (YELLOW on grey is 1.7)
    "bad": MAROON,          # 4.8
    "good": "#006000",      # 3.5 (GREEN #007a00 is 2.4)
    "love": "#800080",      # the palette's purple: 4.2
    "dim": DIM,             # 5.0
}

WORDS = ("Dear", "Sir", "the", "and", "model", "file", "is", "ok", "to", "please",
         "find", "all", "yours", "report", "a", "of", "done", "help")
DOS = ("dir", "cd \\", "mem", "edit", "ver", "scandisk")
TODO = ("Backup", "Defrag", "Reply", "Save")


class Mascot(BaseMascot):
    BUBBLES = {
        "idle": "It looks like you're writing a prompt. Would you like help?",
        "thinking": "Please wait while the AI thinks…",
        "writing": "It looks like you're writing a letter. The AI is typing…",
        "done": "Task completed successfully. Click OK to continue.",
        "error": "This program has performed an illegal operation.",
    }
    TOOL_BUBBLES = {
        "Bash": "Starting MS-DOS Prompt…",
        "Read": "Opening document…",
        "Edit": "It looks like you're editing a file. Need help?",
        "MultiEdit": "It looks like you're editing a file. Need help?",
        "Write": "Saving to C:\\…",
        "NotebookEdit": "Editing the notebook…",
        "Grep": "Find: Files or Folders…",
        "Glob": "Searching My Computer…",
        "WebSearch": "Connecting to the Information Superhighway…",
        "WebFetch": "Downloading… 28.8 kbps",
        "Task": "Starting the Wizard: calling helpers…",
        "Agent": "Starting the Wizard: calling helpers…",
        "TodoWrite": "Updating your To Do list…",
    }
    OTHER = "Running %s.exe…"
    moods = True        # draws mascot_mood's moods and scenes (the frontend asks)

    def __init__(self, cols=64, rows=18):
        self.cols = max(int(cols), DW + 2)
        self.rows = max(int(rows), DH + 1)
        self.wx = (self.cols - DW) // 2
        self.wy = max(0, (self.rows - 1 - DH) // 2)
        self.icons = self.wx >= 9
        self._stream = stream_lines(WORDS, 12, seed=57)
        # the sky's corner: the top of the desktop right of the window
        self.sx = max(self.wx + DW, self.cols - 9)
        self.sy = 0
        # night: where the stars are, fixed per size
        self._stars = []
        for i in range(max(4, self.cols * self.rows // 70)):
            r = lcg(13, i, self.cols, self.rows)
            period = 20 + int(r() * 30)
            self._stars.append((int(r() * self.cols), int(r() * max(3, self.rows * 2 // 3)),
                                period, int(r() * period)))

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
        return super().bubble(state, tool, mood)

    # -- composition ---------------------------------------------------------------

    def _render(self, state, tick, tool, mood=None, scene=()):
        if state not in STATES:
            state = "idle"
        if mood not in MOODS:
            mood = "calm"
        if mood == "sleepy" and state in ACTIVE:
            mood = "focused"        # he does not doze off on the job
        scene = frozenset(scene or ())
        tick = int(tick)
        cv = Canvas(self.cols, self.rows)
        kind = prop_kind(tool) if state == "tool" else None
        # The whole grid is the desktop: a little Windows 95 screen, taskbar
        # and all, in the stage's grey well (the grid is narrower than the
        # stage, so the stage cannot be the desktop: its taskbar would stop
        # short of both edges).
        cv.fill(0, 0, self.cols, self.rows, TEAL, occupy=False)
        if self.icons:
            self._icons(cv, tick)
        self._taskbar(cv, tick, scene)
        self._window(cv, state, tick)
        # outside: the weather lands on the desktop only, behind the window
        if scene:
            self._outside(cv, state, tick, scene)
        dy = 0
        if state == "done":
            dy = (0, 1, 1, 0, 0, 0, 0, 0)[tick % 8]
        elif state == "idle" and mood == "excited" and (tick // 30) % 2:
            dy = (0, 1, 1, 0, 0, 0)[tick % 6]
        x0, top = self._clip(cv, state, tick, kind, dy, mood, scene)
        self._mood_marks(cv, state, tick, x0, top, mood, scene)
        # the reaction sign: right of his right brow, a row under the top of
        # the window's face so its float stays on grey, off the title bar
        self.head = (x0 + 10, max(self.wy + 2, top + 1))
        px, py = self.wx + 16, self.wy + 2
        if state == "thinking":
            self._bulb(cv, tick, px, py)
        elif state == "writing":
            self._page(cv, tick, px, py, pencil=True, stream=True)
        elif state == "done":
            self._msgbox(cv, tick, px, py, ok=True)
        elif state == "error":
            self._msgbox(cv, tick, px, py, ok=False)
        elif kind:
            getattr(self, "_prop_" + kind)(cv, tick, px, py)
        elif "game" in scene:
            self._solitaire(cv, tick, px, py)
        elif mood == "sleepy":
            self._screensaver(cv, tick, px, py)
        else:
            self._idle_tip(cv, tick, px, py)
        if state == "idle" and self._fidget(tick, mood) == "plane":
            self._plane(cv, tick, x0)
        self._ticker(cv, tick, scene)
        return cv

    # -- the desktop ---------------------------------------------------------------

    def _icons(self, cv, tick):
        x = max(1, (self.wx - 6) // 2)
        y = 1
        cv.put(x, y, ".--.", HI)
        cv.put(x, y + 1, "|__|", HI)
        cv.put(x, y + 2, "/__\\", GREY)
        cv.put(x, y + 3, "MyPC", HI)
        if self.rows >= 18:
            cv.put(x, y + 5, " __ ", GREY)
            cv.put(x, y + 6, "|::|", GREY)
            cv.put(x, y + 7, "|__|", GREY)
            cv.put(x, y + 8, "Bin", HI)

    def _taskbar(self, cv, tick, scene=frozenset()):
        y = self.rows - 1
        cv.fill(0, y, self.cols, 1, GREY, occupy=False)
        cv.put(0, y, "[Start]", BLACK, bg=GREY)
        cv.cell(1, y, "S", NAVY, GREY)
        if self.cols >= 60:
            cv.put(8, y, "[Office Assistant]", BLACK, bg=FIELD)
        now = time.localtime()     # the real time: she reacts to it anyway
        h = now.tm_hour
        clock = " %d:%02d %s " % ((h - 1) % 12 + 1, now.tm_min, "AM" if h < 12 else "PM")
        ring = "clock" in scene and (tick // 5) % 2
        cx = self.cols - len(clock)
        cv.put(cx, y, clock, BLACK, bg=YELLOW if ring else FIELD)
        # the tray, left of the clock: CD Player, the reminder's bell
        icons = [("d", NAVY)] if "music" in scene else []
        if "clock" in scene:
            icons.append(("!", RED if ring else MAROON))
        tx = cx - 2 * len(icons)
        cv.fill(tx, y, 2 * len(icons), 1, FIELD, occupy=False)
        for i, (c, colour) in enumerate(icons):
            cv.cell(tx + 1 + 2 * i, y, c, colour, FIELD)

    def _window(self, cv, state, tick):
        x, y = self.wx, self.wy
        cv.fill(x, y, DW, DH, GREY)
        # the bevel: a dark right / bottom edge
        cv.fill(x + DW - 1, y + 1, 1, DH - 1, SHADOW)
        cv.fill(x + 1, y + DH - 1, DW - 1, 1, SHADOW)
        active = state != "idle" or (tick // 100) % 2 == 0
        cv.fill(x, y, DW - 1, 1, NAVY if active else SHADOW)
        cv.put(x + 1, y, "Office Assistant", HI, bg=NAVY if active else SHADOW)
        cv.put(x + DW - 6, y, "_", BLACK, bg=GREY)
        cv.put(x + DW - 4, y, "x", BLACK, bg=GREY)

    # -- outside: the scene on the desktop -------------------------------------------

    def _desk(self, cv, x, y, s, colour, solid=False):
        """Write s on bare desktop only: never over the window, an icon, the
        taskbar or what is already out there. solid claims the gaps between
        s's ends too, so nothing falls through it."""
        if not 0 <= y < self.rows - 1:
            return
        a, b = len(s) - len(s.lstrip(" ")), len(s.rstrip(" "))
        for i in range(a, b):
            xx = x + i
            if 0 <= xx < self.cols and not cv.occ[y][xx] and cv.ch[y][xx] == " ":
                if s[i] != " ":
                    cv.cell(xx, y, s[i], colour)
                if solid:
                    cv.occ[y][xx] = True

    def _outside(self, cv, state, tick, scene):
        # the sky starts under the papel picado when it hangs there
        self.sy = 2 if "festive" in scene else 0
        overcast = bool(scene & {"cloud", "rain", "storm", "snow", "fog"})
        if "festive" in scene:
            self._picado(cv, tick)
        if "clock" in scene:
            self._alarm(cv, tick)
        if overcast:
            self._clouds(cv, tick, scene)
        elif "sun" in scene or "day" in scene:
            self._sun(cv, tick, rays="sun" in scene)
        elif "night" in scene:
            for k, row in enumerate((" .-", "(  ", " `-")):
                self._desk(cv, self.sx + 2, self.sy + k, row, YELLOW, solid=True)
        if "storm" in scene:
            self._lightning(cv, tick)
        if "fog" in scene:
            self._fog(cv, tick)
        if "snow" in scene:
            self._snowdrift(cv)
        if "cold" in scene:
            self._icicles(cv, tick, scene)
        if "hot" in scene:
            self._shimmer(cv, tick)
        if "night" in scene:
            for x, y, period, ph in self._stars:
                if overcast and (x + y) % 3:
                    continue        # most of them behind the clouds
                t = (tick + ph) % period
                self._desk(cv, x, y, ".+*+."[t] if t < 5 else ".", YELLOW if t < 5 else GREY)
        if scene & {"rain", "storm"}:
            heavy = "storm" in scene
            self._fall(cv, tick, 71, self.cols * self.rows // (20 if heavy else 32),
                       0.7 if heavy else 0.5, "',/" if heavy else "','", FIELD)
        if "snow" in scene:
            self._fall(cv, tick, 59, self.cols * self.rows // 50, 0.06, "*.+", HI, drift=True)
        if "party" in scene:
            self._fall(cv, tick, 79, self.cols * self.rows // 45, 0.15, "*'.o", PICADO,
                       drift=True)

    def _fall(self, cv, tick, seed, n, speed, glyphs, colour, drift=False):
        """Things falling down the desktop -- rain, snow, confetti -- on the
        cells nothing else holds. colour is one colour or a tuple."""
        span = self.rows + 1
        for i in range(n):
            r = lcg(seed, i)
            v = speed * (0.7 + r() * 0.6)
            pos = r() * span + tick * v
            fall = int(pos // span)
            y = int(pos - fall * span) - 1
            x = int(lcg(seed + 1, i, fall)() * self.cols)
            if drift:
                x += (0, 1, 1, 0, 0, -1, -1, 0)[(tick // 5 + i) % 8]
            c = colour if isinstance(colour, str) else colour[i % len(colour)]
            self._desk(cv, x, y, glyphs[i % len(glyphs)], c)

    def _sun(self, cv, tick, rays=False):
        x, y = self.sx + 1, self.sy
        if rays:
            top = ("\\ | /", "  |  ", "\\   /")[(tick // 8) % 3]
            self._desk(cv, x, y, top, YELLOW)
            self._desk(cv, x, y + 1, "-(O)-", YELLOW, solid=True)
            self._desk(cv, x, y + 2, "/ | \\" if top[0] == "\\" else "  |  ", YELLOW)
        else:
            self._desk(cv, x, y, " .-. ", YELLOW, solid=True)
            self._desk(cv, x, y + 1, "(   )", YELLOW, solid=True)
            self._desk(cv, x, y + 2, " '-' ", YELLOW, solid=True)

    def _clouds(self, cv, tick, scene):
        """One cloud in the sky's corner and more drifting behind the window."""
        dark = scene & {"storm", "night"}
        flash = "storm" in scene and tick % 47 < 4 and tick % 2 == 0
        colour = HI if flash else (SHADOW if "storm" in scene else GREY if dark else HI)
        self._desk(cv, self.sx, self.sy, "  .--. ", colour, solid=True)
        self._desk(cv, self.sx, self.sy + 1, "(____)", colour, solid=True)
        span = self.cols + 12
        for i in range(max(1, self.cols // 30)):
            r = lcg(47, i)
            y = (int(r() * 3) if self.rows >= 18 else 0) + self.sy
            x = int(r() * span + tick / (9 + i * 3)) % span - 10
            self._desk(cv, x, y, "  .--.   ", colour, solid=True)
            self._desk(cv, x, y + 1, "(___)__) ", colour, solid=True)

    def _lightning(self, cv, tick):
        cyc, t = divmod(tick, 47)
        if t > 3:
            return
        colour = YELLOW if t % 2 == 0 else HI
        bolt = ((1, "/"), (0, "/"), (1, "\\"), (2, "/"))
        for x in (self.sx + 3, int(lcg(53, cyc)() * (self.cols - 4)) + 1):
            for k, (dx, ch) in enumerate(bolt):
                self._desk(cv, x + dx, self.sy + 2 + k, ch, colour)

    def _fog(self, cv, tick):
        for k, y in enumerate((self.rows // 3, self.rows // 2 + 1, self.rows - 3)):
            off = (tick // (6 + k * 2) + k * 7) % 12
            for x in range(self.cols):
                if (x + off) % 12 < 6 and (x + off) % 12 != 2:
                    self._desk(cv, x, y, "~", GREY)

    def _snowdrift(self, cv):
        """Snow settled on the window's top edge and along the bottom of the
        desktop."""
        drift = ".-~~-._.-~-.__.-~~-._.-~-.__.-~~-.__"
        if self.wy >= 1:
            self._desk(cv, self.wx, self.wy - 1, drift[:DW], HI)
        for x in range(self.cols):
            self._desk(cv, x, self.rows - 2, "_.-"[(x * 7) % 5 // 2], HI)

    def _icicles(self, cv, tick, scene):
        """Icicles under the window's bottom edge; with no room for them
        there, under the title bar instead (unless the papel picado is)."""
        y = self.wy + DH
        if y < self.rows - 1:
            for x in range(self.wx + 2, self.wx + DW, 3):
                self._desk(cv, x, y, "V" if x % 2 else "v", HI)
                if (tick // 7 + x) % 9 == 0:
                    self._desk(cv, x, y + 1, "'", HI)
        elif "festive" not in scene:
            for x in range(self.wx + 17, self.wx + DW - 2, 3):
                cv.cell(x, self.wy + 1, "V" if x % 2 else "v", BLUE, GREY)

    def _shimmer(self, cv, tick):
        for y in (self.rows - 2, self.rows - 3):
            for x in range(self.cols):
                if lcg(67, x, y, tick // 3)() < 0.12:
                    self._desk(cv, x, y, "~", YELLOW)

    def _picado(self, cv, tick):
        """Papel picado: a cord along the top, flags hanging under it -- on
        the desktop above the window, or, with no room, under its title bar."""
        for x in range(self.cols):
            self._desk(cv, x, 0, "-", GREY)
            if x % 3 == 1:
                self._desk(cv, x, 1, "Vv"[(tick // 4 + x // 3) % 2], PICADO[(x // 3) % len(PICADO)])
        if self.wy < 2:
            for x in range(self.wx + 17, self.wx + DW - 2, 2):
                cv.cell(x, self.wy + 1, "Vv"[(tick // 4 + x // 2) % 2], PICADO_IN[(x // 2) % len(PICADO_IN)],
                        GREY)

    def _alarm(self, cv, tick):
        """An alarm clock in the desktop's bottom-right corner, ringing: an
        event soon (Scheduled Tasks)."""
        x = max(self.wx + DW, self.cols - 8) + 1
        y = self.rows - 5
        ring = (tick // 2) % 10 < 5
        shake = tick % 2 if ring else 0
        self._desk(cv, x + shake, y, "o.-.o", HI, solid=True)
        self._desk(cv, x + shake, y + 1, "( | )", HI, solid=True)
        cv.cell(x + shake + 2, y + 1, "|/-\\"[(tick // 3) % 4], RED)
        self._desk(cv, x + shake, y + 2, "'-^-'", HI, solid=True)
        if self.cols - x >= 6:
            self._desk(cv, x, y + 3, "Alarm", HI, solid=True)
        if ring:
            self._desk(cv, x + 2, y - 1, "!", YELLOW)
            self._desk(cv, x - 1, y, "(", YELLOW)
            self._desk(cv, x + 6, y, ")", YELLOW)

    def _ticker(self, cv, tick, scene):
        """The Weather Channel ticker along the window's bottom row: every
        tag in a word, scrolling when they do not fit."""
        items = [text for tag, text in TICKER if tag in scene]
        if not items:
            return
        when = "Tonight: " if "night" in scene else "Today: " if "day" in scene else ""
        text = when + " * ".join(items)
        x, y, w = self.wx + 16, self.wy + DH - 2, 18
        if len(text) <= w:
            shown = text.center(w)
        else:
            loop = text + "  *  "
            off = (tick // 2) % len(loop)
            shown = (loop[off:] + loop)[:w]
        cv.put(x, y, shown, YELLOW, bg=NAVY)

    # -- the clip -----------------------------------------------------------------

    def _fidget(self, tick, mood):
        """The idle fidget now: one per 90-tick round, in its last 18 ticks,
        picked by the round's noise from what the mood favours; None the
        rest of the time (and for "rest")."""
        if tick % 90 < 72:
            return None
        table = FIDGETS.get(mood, FIDGETS["calm"])
        pick = lcg(43, tick // 90)() * sum(w for _, w in table)
        for name, weight in table:
            pick -= weight
            if pick < 0:
                return None if name == "rest" else name
        return None

    def _clip(self, cv, state, tick, kind, dy, mood="calm", scene=frozenset()):
        """Draw him; returns (x0, top), where the marks around him go."""
        idle = state == "idle"
        fidget = self._fidget(tick, mood) if idle else None
        slump = idle and mood in ("sad", "sleepy")
        # the cold: a shiver, now and then
        dx = tick % 2 if "cold" in scene and state != "error" and tick % 30 < 6 else 0
        x0, top = self.wx + 2 + dx, self.wy + 1 - dy + slump
        wire = WIRE[:SLUMP] + WIRE[SLUMP + 1:] if slump else WIRE
        for i, r in enumerate(wire):
            cv.put(x0, top + 3 + i, r, BLACK)
        # a highlight down the outer wire: steel
        for i in range(1, len(wire) - 1):
            cv.recolour(x0 + 9, top + 3 + i, DIM)
        # eyebrows
        if state == "thinking":
            key = WORK_BROWS.get(mood, "think")
            brow, raised = BROWS[key], (key in ("think", "up"), key == "up")
        elif state == "error":
            brow, raised = BROWS["sad"], (False, False)
        elif state == "done":
            brow, raised = BROWS["glad"], (False, False)
        elif idle:
            key, ra, rb = MOOD_BROWS[mood]
            brow, raised = BROWS[key], (ra, rb)
            if fidget == "wiggle" and (tick // 3) % 2 or fidget == "yawn":
                brow, raised = BROWS["up"], (True, True)
            elif "music" in scene and mood not in ("sad", "sleepy") and (tick // 5) % 2:
                raised = (True, True)       # bobbing to the beat
        else:
            key = WORK_BROWS.get(mood, "rest")
            up = key == "up" or (key == "rest" and (tick // 25) % 4 == 0)
            brow, raised = BROWS[key], (up, key == "up")
        if "party" in scene:
            raised = (False, False)         # the hat has the row above them
        for k, ex in enumerate(EYES_X):
            row = max(self.wy + 1, top + (0 if raised[k] else 1))
            cv.put(x0 + ex + 1, row, brow[k], BLACK)
        # eyes: whites as light cells, a pupil that looks about
        if state in ("tool", "writing"):
            look = 1
        elif state == "thinking":
            look = (tick // 15) % 2
        elif idle and fidget == "look":
            look = (tick // 4) % 2
        elif idle and mood == "worried":
            look = (tick // 3) % 2          # darting
        elif idle and mood in ("curious", "focused"):
            look = 1                        # at the tip
        elif idle and mood in ("sad", "sleepy"):
            look = 0
        elif idle:
            look = (0, 0, 1, 1, 0, 0, 0, 1)[(tick // 12) % 8]
        else:
            look = 0
        shut = blink(tick, 47) and state not in ("done", "error")
        if idle and (fidget == "yawn" or mood == "sleepy" and tick % 40 < 30):
            shut = True
        for e, ex in enumerate(EYES_X):
            cv.cell(x0 + ex, top + 2, "(", BLACK)
            cv.cell(x0 + ex + 3, top + 2, ")", BLACK)
            pair = self._eye(state, mood, look, e, tick)
            closed = shut or (fidget == "wink" and e == 1)
            for k in range(2):
                c = "-" if closed else pair[k]
                cv.cell(x0 + ex + 1 + k, top + 2, c, BLACK, GREY if closed else HI)
        if fidget == "yawn":
            cv.cell(x0 + 6, top + 3, "O", BLACK)        # in the wire's gap
        return x0, top

    def _eye(self, state, mood, look, e, tick):
        """One eye's two white cells (e: 0 left, 1 right)."""
        if state == "error":
            return "x "
        if state == "done":
            return "^ "
        pupil = "o"
        if state == "idle":
            if mood == "happy":
                return "^^"
            if mood == "shy":
                return " >" if e == 0 else "< "
            if mood == "sleepy":
                return "__"                 # heavy lids, open a crack
            pupil = {"excited": "*", "sad": ".", "curious": "oO"[e]}.get(mood, "o")
        elif mood == "excited":
            pupil = "*"
        elif mood == "sad":
            pupil = "."
        return pupil + " " if look == 0 else " " + pupil

    def _mood_marks(self, cv, state, tick, x0, top, mood, scene):
        """What is on and around him for his mood and the scene: sweat, a
        tear, a blush, "?" and "!", z's, notes, a scarf, a party hat."""
        idle = state == "idle"
        work = state in ACTIVE
        y1 = self.wy + 1                    # the first row under the title bar
        if mood == "worried" and state != "done" or "hot" in scene:
            t = tick % 12
            cv.cell(x0 + 11, max(y1, top + 1) + t // 4, "'',"[t // 4], BLUE)
        if mood == "sad" and state in ("idle", "error"):
            t = tick % 15
            cv.cell(x0 + 10, top + 3 + t // 5, ",'."[t // 5], BLUE)
        if mood == "shy" and state != "error":
            cv.put(x0 + 1, top + 3, "//", RED)
            cv.put(x0 + 10, top + 3, "//", RED)
        if mood == "curious" and (idle or work and (tick // 20) % 3 == 0) and (tick // 5) % 4:
            cv.cell(x0 + 12, max(y1, top), "?", NAVY)
        if mood == "excited" and (idle or state == "done" or (tick // 20) % 3 == 0) \
                and (tick // 3) % 4 < 2:
            cv.cell(x0, max(y1, top + 1), "!", RED)
            cv.cell(x0 + 12, max(y1, top + 1), "!", RED)
        if idle and mood == "sleepy":
            t = tick % 36
            for j in range(3):
                if t // 9 > j:
                    cv.cell(x0 + 11 + j, max(y1, top + 1 - j), "zzZ"[j], NAVY)
        if "music" in scene and state != "error":
            for j in range(2):
                t = (tick + j * 12) % 24
                if t < 20:
                    cv.cell(x0 - 1 + j, top + 9 - t // 4, "db"[j], NAVY)
        if "cold" in scene:
            cv.put(x0 + 2, top + 4, "=========", MAROON)
            cv.cell(x0 + 10, top + 5, "#", MAROON)
            cv.cell(x0 + 10, top + 6, "#" if (tick // 6) % 2 else "%", MAROON)
        if "party" in scene:
            # a hop takes it up into the title bar: light on navy there
            cv.put(x0 + 5, top, "/ \\", MAROON if top > self.wy else HI)
            cv.cell(x0 + 6, top, "*", RED if top > self.wy else YELLOW)

    # -- things beside him -----------------------------------------------------------

    def _frame(self, cv, x, y, w, h, title, body=FIELD, bar=NAVY):
        """A small window: title bar, a body, a shadow edge."""
        cv.fill(x, y, w, h, body)
        cv.fill(x, y, w, 1, bar)
        cv.put(x + 1, y, title[:w - 2], HI, bg=bar)
        cv.fill(x + w, y + 1, 1, h, SHADOW)
        cv.fill(x + 1, y + h, w, 1, SHADOW)

    def _idle_tip(self, cv, tick, x, y):
        cv.put(x, y, "Tip of the Day", NAVY, bg=GREY)
        tips = (("Press Enter", "to send."), ("Shift+Enter", "adds a line."),
                ("Ctrl+T opens", "a terminal."), ("Esc closes", "this window."))
        a, b = tips[(tick // 80) % len(tips)]
        cv.put(x, y + 2, a, BLACK, bg=GREY)
        cv.put(x, y + 3, b, BLACK, bg=GREY)
        self._button(cv, x + 3, y + 6, "Next >", (tick % 80) > 70)

    def _screensaver(self, cv, tick, x, y):
        """Sleepy: the Starfield screen saver, previewed in a little window."""
        self._frame(cv, x, y, 17, 7, "Screen Saver", body=BLACK)
        cx, cy = x + 8, y + 3.5
        for i in range(12):
            r = lcg(89, i)
            a = r() * 2 * math.pi
            d = (r() + tick * (0.02 + r() * 0.03)) % 1.0
            sx = int(round(cx + math.cos(a) * d * 9))
            sy = int(round(cy + math.sin(a) * d * 3.4))
            if x <= sx < x + 17 and y + 1 <= sy < y + 7:
                cv.cell(sx, sy, ".+*"[min(2, int(d * 3))], HI if d > 0.5 else SHADOW, BLACK)
        cv.put(x, y + 8, "Starfield  zZ", NAVY, bg=GREY)

    def _solitaire(self, cv, tick, x, y):
        """Game time: Solitaire, cards going up, then the bouncing cascade."""
        self._frame(cv, x, y, 18, 8, "Solitaire", body=GREEN)
        t = tick % 120
        up = min(4, t // 15)
        cv.put(x + 1, y + 1, "[#]", HI, bg=NAVY)
        for k in range(4):
            fx = x + 6 + k * 3
            if k < up:
                cv.put(fx, y + 1, "A23"[k % 3] if k < 3 else "K", RED if k % 2 else BLACK, bg=HI)
            else:
                cv.cell(fx, y + 1, ":", HI, GREEN)
        for k in range(4 if t < 75 else 0):
            for j in range(max(0, 4 - k - (up > k))):
                cv.put(x + 1 + k * 4, y + 3 + j, " %s " % "KQJ9"[j], RED if (j + k) % 2 else BLACK,
                       bg=HI)
                cv.cell(x + 1 + k * 4, y + 3 + j, "|", SHADOW, HI)
        if t >= 75:
            # the win: a card bouncing off down the felt, its trail behind it
            bounce = (0, 1, 2, 3, 4, 5, 4, 3, 2, 3, 4, 5, 4, 5)
            for s in range(min(len(bounce), (t - 75) // 3 + 1)):
                cv.cell(x + 15 - s, y + 1 + bounce[s], "K", BLACK, HI)

    def _plane(self, cv, tick, x0):
        """The paper-plane fidget: one flies off along the top of the window."""
        t = tick % 90 - 72
        x = x0 + 12 + t
        if x < self.wx + DW - 3:
            cv.put(x, self.wy + 1, "=>", NAVY, bg=GREY)

    def _button(self, cv, x, y, label, pressed=False):
        w = len(label) + 2
        cv.fill(x, y, w, 1, FIELD if not pressed else SHADOW)
        cv.put(x + 1, y, label, BLACK, bg=FIELD if not pressed else SHADOW)
        cv.fill(x + w, y, 1, 1, SHADOW if not pressed else GREY)

    def _bulb(self, cv, tick, x, y):
        lit = (tick // 6) % 4 != 0
        glow = YELLOW if lit else SHADOW
        cv.put(x + 4, y, ".-.", glow, bg=GREY)
        cv.put(x + 3, y + 1, "( ' )", glow, bg=GREY)
        cv.put(x + 4, y + 2, ")=(", DIM, bg=GREY)
        cv.put(x + 4, y + 3, "'-'", DIM, bg=GREY)
        if lit:
            for dx, dy, c in ((-1, 0, "\\"), (7, 0, "/"), (-2, 1, "-"), (8, 1, "-")):
                cv.cell(x + 4 + dx, y + dy, c, YELLOW, GREY)
        dots = "." * ((tick // 4) % 4)
        cv.put(x, y + 5, "Please wait" + dots, BLACK, bg=GREY)
        self._hourglass(cv, tick, x + 14, y + 1)

    def _hourglass(self, cv, tick, x, y):
        if (tick // 8) % 2:
            rows = ("___", "\\:/", "/.\\", "---")
        else:
            rows = ("___", "\\./", "/:\\", "---")
        for i, r in enumerate(rows):
            cv.put(x, y + i, r, BLACK, bg=GREY)

    def _page(self, cv, tick, x, y, pencil=False, stream=False):
        self._frame(cv, x, y, 16, 8, "Notepad")
        lines = self._stream
        if stream:
            total = tick % (len(lines) * 12)
            li, col = divmod(total, 12)
        else:
            li, col = tick // 6, 12
        for k in range(6):
            j = li - 5 + k
            if j < 0:
                continue
            text = lines[j % len(lines)] if j < li else lines[j % len(lines)][:col]
            cv.put(x + 1, y + 1 + k, text, BLACK, bg=FIELD)
        if pencil:
            px = x + 1 + min(col, 11)
            cv.put(px, y + 5, "/", YELLOW, bg=FIELD)
            cv.put(px + 1, y + 4, "/", MAROON, bg=FIELD)
            if (tick // 3) % 2:
                cv.cell(px, y + 6, "_", BLACK, FIELD)

    def _msgbox(self, cv, tick, x, y, ok):
        self._frame(cv, x, y, 18, 8, "LLM chat" if ok else "Error", body=GREY,
                    bar=NAVY)
        if ok:
            cv.put(x + 1, y + 2, "(i)", HI, bg=NAVY)
            cv.put(x + 5, y + 2, "Completed", BLACK, bg=GREY)
            cv.put(x + 5, y + 3, "successfully", BLACK, bg=GREY)
            self._button(cv, x + 5, y + 6, " OK ", (tick % 30) > 26)
        else:
            flash = (tick // 4) % 2
            cv.put(x + 1, y + 2, "(X)", HI, bg=RED if flash else MAROON)
            cv.put(x + 5, y + 2, "Illegal", BLACK, bg=GREY)
            cv.put(x + 5, y + 3, "operation", BLACK, bg=GREY)
            self._button(cv, x + 2, y + 6, "Close", False)
            self._button(cv, x + 9, y + 6, "Debug", False)

    def _prop_bash(self, cv, tick, x, y):
        self._frame(cv, x, y, 16, 7, "MS-DOS Prompt", body=BLACK)
        cyc = tick // 30
        cmd = DOS[cyc % len(DOS)]
        n = min(len(cmd), (tick % 30) // 2)
        for k in range(3):
            prev = DOS[(cyc - 3 + k) % len(DOS)]
            cv.put(x + 1, y + 1 + k, ("C:\\>" + prev)[:14], SHADOW, bg=BLACK)
        cv.put(x + 1, y + 5, ("C:\\>" + cmd[:n])[:14], GREY, bg=BLACK)
        if (tick // 3) % 2:
            cv.cell(x + 5 + n, y + 5, "_", GREY, BLACK)

    def _prop_book(self, cv, tick, x, y):
        self._page(cv, tick, x, y)
        hot = (tick // 3) % 6
        for c in range(14):
            cv.recolour(x + 1 + c, y + 1 + hot, HI, NAVY)

    def _prop_pad(self, cv, tick, x, y):
        self._page(cv, tick, x, y, pencil=True, stream=True)

    def _prop_lens(self, cv, tick, x, y):
        self._frame(cv, x, y, 16, 8, "Find: All Files", body=GREY)
        cv.put(x + 1, y + 1, "Named:", BLACK, bg=GREY)
        cv.put(x + 8, y + 1, "*.py   ", BLACK, bg=FIELD)
        hit = (tick // 4) % 4
        files = ("theme.py", "panel.py", "front.py", "clip.py")
        for k, f in enumerate(files):
            sel = k == hit
            cv.put(x + 1, y + 3 + k, f.ljust(14), HI if sel else BLACK, bg=NAVY if sel else FIELD)
        # the magnifier sweeping the list
        mx = x + 10 + (tick // 2) % 4
        cv.put(mx, y + 3 + hit, "O-", MAROON, bg=NAVY)

    def _prop_globe(self, cv, tick, x, y):
        self._frame(cv, x, y, 17, 8, "Copying...", body=GREY)
        cv.put(x + 1, y + 2, "[__]", BLACK, bg=YELLOW)
        cv.put(x + 12, y + 2, "[__]", BLACK, bg=YELLOW)
        t = tick % 10
        arc = (0, 1, 1, 2, 2, 2, 2, 1, 1, 0)
        cv.put(x + 4 + t * 7 // 10, y + 3 - arc[t] + 1, "#", HI, bg=GREY)
        pct = (tick * 2) % 101
        n = int(pct / 100 * 15)
        cv.fill(x + 1, y + 5, 15, 1, FIELD)
        cv.fill(x + 1, y + 5, n, 1, NAVY)
        cv.put(x + 1, y + 6, ("%d%% of 28.8k" % pct)[:15], BLACK, bg=GREY)

    def _prop_helpers(self, cv, tick, x, y):
        for n in range(2):
            bx = x + n * 8
            hop = ((tick // 4) + n) % 2
            cv.put(bx + 1, y + 1 - hop, "~~", BLACK, bg=GREY)
            cv.put(bx, y + 2 - hop, "(oo)", BLACK, bg=GREY)
            cv.cell(bx + 1 + (tick // 10 + n) % 2, y + 2 - hop, "o", BLACK, HI)
            cv.put(bx, y + 3 - hop, "|.-|", BLACK, bg=GREY)
            cv.put(bx, y + 4 - hop, "||||", BLACK, bg=GREY)
            cv.put(bx, y + 5 - hop, "|'-'", BLACK, bg=GREY)
            cv.put(bx, y + 6 - hop, "'--'", BLACK, bg=GREY)
        cv.put(x, y + 8, "Wizard 1 of 2", NAVY, bg=GREY) if y + 8 < self.wy + DH - 1 else None

    def _prop_todo(self, cv, tick, x, y):
        self._frame(cv, x, y, 16, 7, "To Do", body=FIELD)
        done = (tick // 12) % (len(TODO) + 1)
        for k, item in enumerate(TODO):
            box = "[x]" if k < done else "[ ]"
            colour = GREEN if k < done else BLACK
            cv.put(x + 1, y + 1 + k, box, colour, bg=FIELD)
            cv.put(x + 5, y + 1 + k, item, BLACK if k >= done else DIM, bg=FIELD)
            if k == done and (tick // 3) % 2:
                cv.put(x + 1, y + 1 + k, "[>]", NAVY, bg=FIELD)

    def _prop_wand(self, cv, tick, x, y):
        self._hourglass(cv, tick, x + 6, y + 1)
        cv.put(x + 1, y + 6, "Working" + "." * ((tick // 4) % 4), BLACK, bg=GREY)
        r = lcg(83, tick // 5)
        for j in range(3):
            sx, sy = x + int(r() * 15), y + int(r() * 5)
            if cv.get(sx, sy) == " ":
                cv.cell(sx, sy, "*", NAVY, GREY)
