#!/usr/bin/env python3
r"""The matrix theme's mascot: a hooded hacker at a terminal, in falling
green digital rain. Same API as moe_mascot.Mascot (mascots.py picks it).

    hacker    21 x 11 cells, front view: a hood with only the eyes glowing
              in its shadow, hands on a laptop whose lid faces us
    monitor   17 x 9 cells to the hacker's right, on the same desk: what
              the tool is doing shows on its screen -- a shell for Bash, a
              hex dump for Read, a diff for Edit/Write, a highlighted match
              moving down the lines for the searches, a download bar for
              WebFetch, a checklist for TodoWrite, the white rabbit for
              anything else; agents in shades step in on both sides for
              Task/Agent. Thinking decrypts a word letter by letter,
              writing streams code, done says ACCESS GRANTED.
    ambient   digital rain over the whole stage, behind the two sprites:
              columns of ASCII glyphs (half-width katakana would be the
              film's, but they are wide in a CJK mono font -- never in the
              grid), a pale head, a trail fading through the greens. On
              error the picture glitches: rows tear sideways, cells flip to
              red noise, the screen says ACCESS DENIED.
    mood      one of mascot_mood.MOODS, all in the eyes, brows and mouth in
              the hood's shadow (MOOD_FACE, BROWS) plus what floats by it:
              happy ^ ^, excited * * with "!"s and faster rain, shy > < and
              a blush, curious o O and a "?", focused \ / brows and nonstop
              typing, worried / \ brows, a glance and a sweat drop, sad . .
              with a tear and slow rain, sleepy - - with z's and a yawn.
              Idle, the monitor types the mood's line instead of "wake
              up..." and the fidget (FIDGETS) is the mood's pick: a glance,
              a burst of typing, a mug of coffee, a stretch, the red and the
              blue pill in his hands, or the black cat walking across the
              monitor twice (deja vu). Working, the mood tints the face.
    scene     mascot_mood.SCENES around him: the sun (and, idle, shades on)
              or a crescent moon top left, clouds drifting behind, real
              rain as blue "/" slanting across the green with an umbrella
              over the hood (a storm: harder, with lightning), white snow
              settling on the hood and the monitor, bands of fog that dim
              the rain, heat shimmer and sweat, a scarf and breath, music
              in headphones, snake on the screen for game, a party hat and
              confetti, papel picado along the top for festive, an alarm
              clock ringing on the monitor for an event soon.

Colours: greens on #010803 (the stage card in themes/matrix/
llm-chat.css), heads #a8ffbc, the rain two shades darker behind the
figure; the hacker in the theme's grey (#a8bcae) with green eyes, so he
stands out of the rain; red #ff3030 only for errors, the white rabbit
#eef5ef; the scene's accents (amber sun, blue rain, the party's colours)
are the only other hues.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import STATES, BaseMascot, Canvas, blink, lcg, prop_kind, stream_lines  # noqa: E402
from mascot_mood import MOODS, word  # noqa: E402

THEME = "matrix"
PANEL = "#010803"

HEAD = "#a8ffbc"
RAIN = ("#00ff41", "#00d936", "#00a82a", "#007a1f", "#005214", "#00330c")
HOOD = "#a8bcae"          # the figure in the theme's grey, so it stands out of the rain
HOOD_DIM = "#5f7566"
EYE = "#3dff6e"
EDGE = "#3ddc68"
TEXT = "#00ff41"
TEXT_DIM = "#00a82a"
TEXT_FAINT = "#00661a"
RED = "#ff3030"
RED_DIM = "#a01818"
AMBER = "#ffb000"
WHITE = "#eef5ef"
HILITE_BG = "#00b32c"
INK = "#010803"
# the scene's accents
SUN = "#ffb000"
MOON = "#d8f5dc"
CLOUD = "#5f7566"
CLOUD_DIM = "#33443a"
WET = "#7fb2ff"           # real rain: blue and slanted, never the code's green
BROLLY = "#8fa6c8"
SNOW = "#eef5ef"
FOG = "#7d9585"
HEAT = "#a07a1a"
BLUSH = "#ff7fa0"
SWEAT = "#7fd0ff"
SCARF = ("#d04040", "#eef5ef")
MUSIC = "#5fd7ff"
PILL = ("#ff3030", "#3d7dff")
# The reaction sign over the head (mascot_mood.EMOTE_TONES), all >= 4:1 on
# PANEL (the rain behind it has no background).
EMOTE_COLOURS = {"accent": HEAD, "warn": AMBER, "bad": RED, "good": TEXT,
                 "love": BLUSH, "dim": HOOD_DIM}
CONFETTI = ("#ff5fd7", "#ffb000", "#5fd7ff", "#00ff41", "#ff3030", "#eef5ef")

GLYPHS = "0123456789ABCDEFZ:.=*+-<>|\"^~;!?#$%&"

W, H = 21, 11
HACKER = [
    "      .-~~~~~-.      ",
    "    .'         '.    ",
    "   /   .-----.   \\   ",
    "  |   /       \\   |  ",
    "  |   |       |   |  ",
    "  |   \\       /   |  ",
    "   \\   '-._.-'   /   ",
    "  __'.         .'__  ",
    " /    '-------'    \\ ",
    "|   _.=========._   |",
    "|__|_____(@)_____|__|",
]
# eyes in the hood's shadow: row 4, columns 8 and 12; mouth row 5, col 10
EYE_Y, EYE_L, EYE_R, MOUTH = 4, 8, 12, (5, 10)

MW = 17
MONITOR = [
    ".---------------.",
    "|               |",
    "|               |",
    "|               |",
    "|               |",
    "|               |",
    "|               |",
    "'-------.-------'",
    "      __|__      ",
]
SCREEN_W, SCREEN_H = 13, 6

AGENT = [" ___ ", "(=_=)", "/|Y|\\", " | | "]

COMP_W = W + MW        # the hacker and the monitor side by side

CODE_WORDS = ("if", "for", "0x1f", "int", "ret", "neo", "{", "}", "=>", "jmp", "mov",
              "ax", "nil", "and", "or", "fn", "let", "zion", "101", "xor", "[]")
CMDS = ("ls -la", "make", "git log", "ps aux", "./run", "ssh zion")
DECRYPT = ("THINKING", "DECODING", "TRACE", "KNOCK KNOCK")
DIFF = (("-", "old = 1"), ("+", "new = 2"), ("-", "if bug:"), ("+", "if ok:"),
        ("+", "  return 0"), ("-", "panic()"))
TODO = ("jack in", "find neo", "dodge", "exit")

# The face per mood, idle: (left eye, right eye, mouth). calm: the old one.
MOOD_FACE = {
    "calm": ("o", "o", "_"),
    "happy": ("^", "^", "v"),
    "excited": ("*", "*", "D"),
    "shy": (">", "<", "~"),
    "curious": ("o", "O", "o"),
    "focused": ("o", "o", "-"),
    "worried": ("o", "o", "~"),
    "sad": (".", ".", "n"),
    "sleepy": ("-", "-", "."),
}
# Brows (row 3): left, right, and how far in from over the eyes -- slanted
# ones meet in the middle, or they would read as the hood's own edges.
BROWS = {"focused": ("\\", "/", 1), "sleepy": ("_", "_", 0), "worried": ("/", "\\", 1),
         "sad": ("/", "\\", 1)}
# The idle fidget a mood favours: (name, weight); "rest" is none at all.
FIDGETS = {
    "calm": (("look", 2), ("type", 2), ("mug", 1), ("cat", 1), ("rest", 2)),
    "happy": (("type", 2), ("cat", 2), ("mug", 1), ("look", 1)),
    "excited": (("type", 3), ("cat", 2), ("stretch", 1), ("pill", 1)),
    "shy": (("look", 2), ("mug", 1), ("rest", 2)),
    "curious": (("look", 2), ("pill", 2), ("cat", 2)),
    "focused": (("type", 4), ("mug", 1)),
    "worried": (("look", 3), ("type", 1), ("rest", 1)),
    "sad": (("mug", 1), ("rest", 2)),
    "sleepy": (("stretch", 2), ("mug", 2), ("rest", 2)),
}
# What the monitor types, idle, per mood (13 cells at most).
MOOD_SCREEN = {
    "calm": "wake up...",
    "happy": "hello, neo.",
    "excited": "i know kungfu",
    "shy": "...hi.",
    "curious": "the matrix?",
    "focused": "tail -f zion",
    "worried": "agents near",
    "sad": "no spoon...",
    "sleepy": "zzz...",
}
# How fast the code falls, per mood.
RAIN_PACE = {"excited": 1.3, "sad": 0.7, "sleepy": 0.5}

MOOD_BUBBLES = {
    "happy": "> hello, neo. good to see you.",
    "excited": "> i know kung fu. let's go!",
    "shy": "> …you weren't supposed to see me.",
    "curious": "> what is the matrix? follow the white rabbit…",
    "focused": "> tail -f /dev/zion. ready.",
    "worried": "> agents nearby… stay sharp.",
    "sad": "> there is no spoon. or joy.",
    "sleepy": "> zzz… wake me when the rabbit shows.",
}
# mascot_mood topics in his words (str.format with the topic's arguments).
TOPIC_LINES = {
    "thanks": "> ack. you're welcome, operator.",
    "worried": "> uh-oh… something's in the code.",
    "frustrated": "> again?! déjà vu. one more run…",
    "relieved": "> phew. exit 0.",
    "determined": "> long run… hold the line.",
    "proud": "> done. access granted.",
    "sad": "> sorry… my bad.",
    "happy": "> yes!",
    "curious": "> hmm… how deep does the rabbit hole go?",
    "rain": "> rain in the real world. take an umbrella.",
    "storm": "> storm in the real world. stay inside.",
    "snow": "> snow. the real world is cold.",
    "fog": "> fog out there. visibility: 0.",
    "sun": "> sunny out. shades on.",
    "hot": "> it's hot… {0}. fans to max.",
    "cold": "> brr, {0} outside.",
    "gpu_hot": "> gpu at {0}°C. throttling…",
    "cpu_hot": "> cpu at {0}°C. throttling…",
    "music": "> nice track. the code has a beat.",
    "game": "> loading the training program…",
    "event": "> {0} in {1} min. the phone's ringing.",
    "event_now": "> {0} now. answer the phone.",
    "birthday": "> it's {0}'s birthday. happy rezday!",
    "holiday": "> today is {0}. ¡viva!",
    "go_home": "> {0}. log out, operator. go home.",
    "bedtime": "> {0}… unplug. go to bed.",
    "morning": "> wake up, neo… good morning.",
    "lunch": "> lunch? even the oracle bakes cookies.",
    "weekend": "> weekend. unplug from the matrix.",
    "friday": "> friday. the weekend is a construct too.",
    "hello": ("> hello, operator. what's the task?", "> knock knock. i'm listening.",
              "> connection open. ready."),
    "welcome_back": "> you're back. the matrix kept your seat.",
    "wake": "> huh? i'm awake. i'm in.",
    "long_prompt": "> long transmission. decoding…",
    "code": ("> code. i don't even see it anymore.", "> source incoming. reading…"),
    "image": "> an image. blonde, brunette, redhead…",
    "aborted": "> ctrl-c. jacking out.",
    "tests_pass": ("> tests green. there is no bug.", "> all pass. exit 0.",
                   "> green across the board."),
    "tests_fail": ("> tests red. a glitch in the code.", "> fail. déjà vu… let's look."),
    "commit": ("> committed to the mainframe.", "> pushed. it's in the system now.",
               "> shipped. zion will see it."),
    "fast": ("> done. that was fast.", "> bullet time.", "> faster than an agent."),
    "busy": "> many programs running. hold on…",
    "model": "> new program loaded: {0}",
    "poke": ("> hey. i'm mid-hack here.", "> what? the phone's not ringing.",
             "> yes, i'm real. probably.", "> ping received. hi.",
             "> that tickles the mainframe.", "> careful. that's the red pill."),
    "poke_spam": ("> stop. you're tripping the alarms.", "> enough! the agents will notice."),
    "pet": ("> …thanks. the matrix feels warmer.", "> ok. that was nice.",
            "> head pats. not in the training program."),
}

CAT = (" /\\_/\\ ", "(=o.o=)")


class Mascot(BaseMascot):
    BUBBLES = {
        "idle": "Wake up… the terminal has you.",
        "thinking": "Decoding the signal…",
        "writing": "Typing straight into the Matrix…",
        "done": "Access granted. There is no bug.",
        "error": "A glitch in the Matrix. Déjà vu…",
    }
    TOOL_BUBBLES = {
        "Bash": "Jacking into the shell…",
        "Read": "Reading the source code…",
        "Edit": "Rewriting the code…",
        "MultiEdit": "Rewriting the code…",
        "Write": "Writing a new program into the system…",
        "NotebookEdit": "Patching the construct…",
        "Grep": "Tracing the pattern…",
        "Glob": "Scanning the filesystem…",
        "WebSearch": "Searching the net…",
        "WebFetch": "Downloading a construct…",
        "Task": "Spawning agents…",
        "Agent": "Spawning agents…",
        "TodoWrite": "Updating the mission log…",
    }
    OTHER = "Follow the white rabbit: %s"

    def __init__(self, cols=64, rows=18):
        self.cols = max(int(cols), COMP_W + 2)
        self.rows = max(int(rows), H + 2)
        self.cx = (self.cols - COMP_W) // 2
        self.top = self.rows - 1 - H
        self._stream = stream_lines(CODE_WORDS, SCREEN_W, seed=53)
        self._drops = []
        for x in range(self.cols):
            r = lcg(41, x, self.cols)
            if r() < 0.55:
                continue
            speed = 0.18 + r() * 0.42
            length = 3 + int(r() * max(4, self.rows * 0.7))
            self._drops.append((x, speed, length, r() * (self.rows + length)))

    # -- public ----------------------------------------------------------------------

    moods = True        # draws mascot_mood's moods and scenes (the frontend asks)

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
        # no mood at all: the picture as it always was, without fidgets
        given = mood in MOODS
        if not given:
            mood = "calm"
        if mood == "sleepy" and state in ("thinking", "tool", "writing"):
            mood = "focused"            # he does not doze off on the job
        scene = frozenset(scene or ())
        tick = int(tick)
        cv = Canvas(self.cols, self.rows)
        kind = prop_kind(tool) if state == "tool" else None
        fidget = self._fidget(tick, mood, scene) if state == "idle" and given else None
        # the emote anchor: just right of the hood's crown, where his "?"
        # floats -- off the face, below the umbrella's rim, left of the monitor
        self.head = (self.cx + 17, self.top + 1)
        self._rain(cv, state, tick, mood, scene)
        self._sky(cv, state, tick, scene)
        if "festive" in scene:
            self._banner(cv, tick)
        self._desk(cv)
        if kind == "helpers":
            self._agents(cv, tick)
        if fidget == "mug":
            self._mug(cv, tick)
        self._hacker(cv, state, tick, kind, mood, scene, fidget)
        self._monitor(cv, state, tick, kind, mood, scene)
        if "clock" in scene:
            self._alarm(cv, tick)
        if fidget == "cat":
            self._cat(cv, tick)
        if "fog" in scene:
            self._fog(cv, tick)
        if "snow" in scene:
            self._snow(cv, tick)
        if "hot" in scene:
            self._shimmer(cv, tick)
        if "party" in scene:
            self._confetti(cv, tick)
        if scene & {"rain", "storm"}:
            dry = self._umbrella(cv, "party" in scene)
            self._weather_rain(cv, tick, dry, heavy="storm" in scene)
        if "party" in scene:
            self._hat(cv, tick)
        self._mood_marks(cv, state, tick, mood, scene)
        if state == "error":
            self._glitch(cv, tick)
        return cv

    def _rain(self, cv, state, tick, mood="calm", scene=frozenset()):
        span = self.rows
        fast = 1.6 if state == "done" else (0.5 if state == "thinking" else 1.0)
        fast *= RAIN_PACE.get(mood, 1.0)
        fogged = 2 if "fog" in scene else 0
        flash = "storm" in scene and tick % 47 in (0, 2)
        for x, speed, length, ph in self._drops:
            pos = ph + tick * speed * fast
            cyc = int(pos // (span + length))
            head = int(pos % (span + length))
            red = state == "error" and lcg(47, x, cyc)() < 0.35
            # behind the hacker and his monitor the rain is further away:
            # two shades darker, so the figure reads
            behind = self.cx - 1 <= x <= self.cx + COMP_W
            for k in range(length):
                y = head - k
                if not 0 <= y < self.rows:
                    continue
                g = GLYPHS[int(lcg(43, x, y, (tick + x * 7) // (2 if k == 0 else 7))() * len(GLYPHS))]
                if k == 0:
                    colour = RED if red else (WHITE if flash else (RAIN[1 + fogged] if behind else
                                                                   (RAIN[fogged] if fogged else HEAD)))
                else:
                    # in fog everything is two shades further away
                    shade = min(len(RAIN) - 1, (k * len(RAIN)) // max(1, length) + (1 if k > 1 else 0)
                                + (2 if behind else 0) + fogged)
                    colour = (RED_DIM if k < length // 2 else "#5a0c0c") if red else RAIN[shade]
                cv.cell(x, y, g, colour)

    def _desk(self, cv):
        y = self.rows - 1
        cv.sprite(self.cx - 1, y, "=" * (COMP_W + 2), HOOD_DIM)

    # -- the hacker -----------------------------------------------------------------

    def _fidget(self, tick, mood, scene):
        """The idle fidget now: one per 120-tick round, in its last 30
        ticks, picked by the round's noise from what the mood favours; None
        the rest of the time (and for "rest")."""
        if tick % 120 < 90:
            return None
        table = FIDGETS.get(mood, FIDGETS["calm"])
        pick = lcg(79, tick // 120)() * sum(w for _, w in table)
        for name, weight in table:
            pick -= weight
            if pick < 0:
                if name == "cat" and "clock" in scene:
                    return "look"       # the clock has the monitor's top
                return None if name == "rest" else name
        return None

    def _hacker(self, cv, state, tick, kind, mood="calm", scene=frozenset(), fidget=None):
        x0, top = self.cx, self.top
        idle = state == "idle"
        game = idle and "game" in scene
        rows = list(HACKER)
        typing = state in ("writing", "tool") or (idle and (
            game or fidget == "type" or mood == "focused"
            or (mood not in ("sad", "sleepy") and (tick // 40) % 3 == 0)))
        for i, r in enumerate(rows):
            cv.sprite(x0, top + i, r, HOOD if i < 9 else HOOD_DIM)
        # the hood's rim darker (snowed on, or the headphones' band), the folds
        rim = SNOW if "snow" in scene else (MUSIC if "music" in scene else HOOD_DIM)
        cv.put(x0 + 8, top + 0, "~~~~~", rim)
        for c in (5, 15):
            cv.cell(x0 + c, top + 1, cv.get(x0 + c, top + 1), HOOD_DIM)
        if "music" in scene:
            for i in (3, 4, 5):
                cv.cell(x0 + 1, top + i, "[#["[i - 3], MUSIC)
                cv.cell(x0 + 19, top + i, "]#]"[i - 3], MUSIC)
        if "cold" in scene:
            # a striped scarf round the neck, one end hanging
            for c in range(6, 15):
                cv.cell(x0 + c, top + 7, "=", SCARF[c % 2])
            cv.cell(x0 + 13, top + 8, "#", SCARF[0])
        # hands at the laptop's sides; they tap while typing (fast, excited)
        hand = "o"
        if typing:
            hand = "o" if (tick // (1 if mood == "excited" else 2)) % 2 else "."
        if state == "done" or fidget == "stretch":
            # arms up: "yes!" (or a slow stretch)
            up = (tick // 4) % 2 if state == "done" else 1
            col = EYE if state == "done" else HOOD
            cv.put(x0, top + 7 - up, "\\o", col)
            cv.put(x0 + 19, top + 7 - up, "o/", col)
        elif fidget == "pill":
            # the red pill or the blue pill
            cv.cell(x0 + 2, top + 9, "o", PILL[0])
            cv.cell(x0 + 18, top + 9, "o", PILL[1])
        else:
            other = ("o" if hand == "." else ".") if typing else "o"
            cv.cell(x0 + 2, top + 9, hand, EYE)
            cv.cell(x0 + 18, top + 9, other, EYE)
        # the laptop's logo pulses
        cv.put(x0 + 9, top + 10, "(@)", TEXT if (tick // 8) % 2 else TEXT_DIM)
        self._face(cv, state, tick, mood, scene, fidget, game)

    def _face(self, cv, state, tick, mood, scene, fidget, game):
        """Only the eyes, brows and a hint of mouth, in the hood's shadow."""
        x0, top = self.cx, self.top
        idle = state == "idle"
        gaze = 1 if state in ("tool", "writing") else 0
        if state == "thinking":
            gaze = (0, 1, 0, -1)[(tick // 12) % 4]
        el = er = "o"
        colour = EYE
        mouth = {"done": "v", "error": "o", "thinking": "~"}.get(state, "_")
        mouth_col = HOOD_DIM if state not in ("done", "error") else colour
        if state == "done":
            el = er = "^"
        elif state == "error":
            el = er = "x"
            colour = mouth_col = RED
        elif idle:
            el, er, mouth = MOOD_FACE[mood]
            if mood != "calm":
                mouth_col = HOOD
            if mood == "happy":
                mouth = "vw"[(tick // 40) % 2]
            elif mood == "focused":
                gaze = 1                # on the monitor
            elif mood == "shy":
                gaze = (0, -1)[(tick // 30) % 2]     # anywhere but at you
            elif mood == "worried":
                gaze = (0, -1, 0, 1)[(tick // 9) % 4]
            elif mood == "sleepy":
                if tick % 70 < 10:
                    mouth = "O"         # a yawn
                elif (tick // 25) % 5 == 0:
                    el = er = "o"       # awake, for a moment
        else:
            # working: the mood tints the face
            if mood == "excited" and (tick // 8) % 3 == 0:
                el = er = "*"
            elif mood == "curious":
                er = "O"
            mouth = {"happy": "v", "excited": "D", "shy": "~", "worried": "~", "sad": "n",
                     "focused": "-"}.get(mood, mouth)
        if game:
            el, er, gaze = "o", "o", 1
        if fidget in ("look", "pill"):
            gaze = (-1, 1)[(tick // (6 if fidget == "look" else 10)) % 2]
        elif fidget == "stretch":
            el, er, mouth = "-", "-", "O"
        elif fidget == "cat" and tick % 120 >= 105:
            el, er, gaze = "O", "O", 1      # ... a black cat. again. deja vu
        if el == "*":
            colour = HEAD
        shades = (idle and "sun" in scene and "night" not in scene and not game
                  and mood in ("calm", "happy", "excited", "focused") and fidget != "stretch")
        shut = blink(tick) and state not in ("done", "error") and el not in ("-", "^", ">", ".")
        if shades:
            cv.put(x0 + 7, top + EYE_Y, "[=]-[=]", WHITE)
            cv.put(x0 + 8, top + EYE_Y, "=", TEXT_FAINT)
            cv.put(x0 + 12, top + EYE_Y, "=", TEXT_FAINT)
        else:
            if shut:
                el = er = "-"
            cv.cell(x0 + EYE_L + gaze, top + EYE_Y, el, HOOD if shut else colour)
            cv.cell(x0 + EYE_R + gaze, top + EYE_Y, er, HOOD if shut else colour)
        cv.cell(x0 + MOUTH[1], top + MOUTH[0], mouth, mouth_col)
        if mood in BROWS and state not in ("done", "error"):
            left, right, inset = BROWS[mood]
            cv.cell(x0 + EYE_L + inset, top + EYE_Y - 1, left, HOOD)
            cv.cell(x0 + EYE_R - inset, top + EYE_Y - 1, right, HOOD)
        if mood == "shy" and state != "error":
            for c in (8, 12):
                cv.cell(x0 + c, top + MOUTH[0], "=", BLUSH)
        if mood == "sad" and state != "done" and tick % 40 < 12:
            cv.cell(x0 + EYE_L + gaze, top + MOUTH[0], ",'"[(tick // 4) % 2], SWEAT)

    # -- the monitor ------------------------------------------------------------------

    def _monitor(self, cv, state, tick, kind, mood="calm", scene=frozenset()):
        sx, sy = self.cx + W, self.top + 2
        edge = RED if state == "error" and (tick // 3) % 2 else EDGE
        for i, r in enumerate(MONITOR):
            cv.sprite(sx, sy + i, r, edge if i < 8 else HOOD_DIM)
        if "snow" in scene:
            cv.put(sx + 1, sy, "~" * (MW - 2), SNOW)     # snow settled on top
        tx, ty = sx + 2, sy + 1

        def line(k, text, colour=TEXT):
            cv.put(tx, ty + k, text[:SCREEN_W], colour)

        if state == "thinking":
            self._decrypt(line, tick)
        elif state == "writing":
            self._code(line, cv, tx, ty, tick)
        elif state == "done":
            line(0, "> exit 0", TEXT_DIM)
            on = (tick // 4) % 4 != 0
            line(2, "   ACCESS", TEXT if on else TEXT_DIM)
            line(3, "   GRANTED", TEXT if on else TEXT_DIM)
            line(5, "[" + "#" * 11 + "]", TEXT_DIM)
        elif state == "error":
            line(0, "> segfault", RED_DIM)
            if (tick // 3) % 2:
                line(2, "   ACCESS", RED)
                line(3, "   DENIED", RED)
            line(5, "core dumped", RED_DIM)
        elif state == "tool":
            getattr(self, "_screen_" + kind)(line, cv, tx, ty, tick)
        elif "game" in scene:
            self._snake(cv, tx, ty, tick)
        else:
            slow = 2 if mood == "sleepy" else 1
            line(0, "> _" if (tick // (5 * slow)) % 2 else ">", TEXT_DIM if slow > 1 else TEXT)
            msg = MOOD_SCREEN.get(mood, MOOD_SCREEN["calm"])
            n = min(len(msg), (tick % 90) // (4 * slow))
            line(2, msg[:n], TEXT_FAINT if slow > 1 else TEXT_DIM)
            if (tick % 90) > 60 and mood == "calm":
                line(4, "knock, knock", TEXT_FAINT)

    def _snake(self, cv, tx, ty, tick):
        """Game time: snake winding over the screen, after the food."""
        def at(p):
            row, col = divmod(p % (SCREEN_W * SCREEN_H), SCREEN_W)
            return tx + (col if row % 2 == 0 else SCREEN_W - 1 - col), ty + row
        head = tick
        food = at(head + 9 - head % 9 + 4)
        cv.cell(food[0], food[1], "*", AMBER)
        for k in range(5, 0, -1):
            x, y = at(head - k)
            cv.cell(x, y, "o", TEXT_DIM)
        x, y = at(head)
        cv.cell(x, y, "@", HEAD)

    def _decrypt(self, line, tick):
        word = DECRYPT[(tick // 60) % len(DECRYPT)]
        t = tick % 60
        out = []
        for i, c in enumerate(word.ljust(SCREEN_W)):
            locked = t > 8 + i * 3
            if c == " " or locked:
                out.append(c)
            else:
                out.append(GLYPHS[int(lcg(59, i, tick // 2)() * len(GLYPHS))])
        line(0, "> decrypt", TEXT_DIM)
        line(2, "".join(out), TEXT)
        spin = "-\\|/"[tick % 4]
        line(4, spin + " " + "." * ((tick // 4) % 4), TEXT_DIM)

    def _code(self, line, cv, tx, ty, tick):
        lines = self._stream
        total = tick % (len(lines) * SCREEN_W)
        li, col = divmod(total, SCREEN_W)
        for k in range(SCREEN_H):
            j = li - (SCREEN_H - 1) + k
            if j < 0:
                continue
            text = lines[j] if j < li else lines[j][:col]
            line(k, text, TEXT if k == SCREEN_H - 1 else TEXT_DIM)
        if (tick // 3) % 2:
            cv.cell(tx + min(col, SCREEN_W - 1), ty + SCREEN_H - 1, "_", HEAD)

    def _screen_bash(self, line, cv, tx, ty, tick):
        cyc = tick // 30
        cmd = CMDS[cyc % len(CMDS)]
        n = min(len(cmd), (tick % 30) // 2)
        for k in range(3):
            prev = CMDS[(cyc - 3 + k) % len(CMDS)]
            line(k, "$ " + prev, TEXT_FAINT)
        line(3, "ok", TEXT_FAINT)
        line(5, "$ " + cmd[:n], TEXT)
        if (tick // 3) % 2:
            cv.cell(tx + 2 + n, ty + 5, "_", HEAD)

    def _screen_book(self, line, cv, tx, ty, tick):
        off = tick // 3
        for k in range(SCREEN_H):
            r = lcg(61, off + k)
            hexs = " ".join("%02x" % int(r() * 256) for _ in range(4))
            hot = k == (tick // 2) % SCREEN_H
            line(k, hexs, TEXT if hot else TEXT_DIM)

    def _screen_pad(self, line, cv, tx, ty, tick):
        t = tick % (len(DIFF) * 10)
        n, part = divmod(t, 10)
        for k in range(min(SCREEN_H, n + 1)):
            sign, text = DIFF[k]
            shown = text if k < n else text[:part]
            line(k, sign + " " + shown, TEXT if sign == "+" else RED_DIM)
        if (tick // 3) % 2 and n < SCREEN_H:
            cv.cell(tx + 2 + min(part, len(DIFF[n][1])), ty + n, "_", HEAD)

    def _screen_lens(self, line, cv, tx, ty, tick):
        line(0, "/neo/", AMBER)
        hit = 1 + (tick // 6) % (SCREEN_H - 1)
        for k in range(1, SCREEN_H):
            r = lcg(67, k, tick // 60)
            words = "".join(GLYPHS[int(r() * 26)] for _ in range(SCREEN_W))
            if k == hit:
                cv.put(tx, ty + k, words[:3], TEXT_DIM)
                cv.put(tx + 3, ty + k, " neo ", INK, bg=HILITE_BG)
                cv.put(tx + 8, ty + k, words[8:SCREEN_W], TEXT_DIM)
            else:
                line(k, words, TEXT_FAINT)

    def _screen_globe(self, line, cv, tx, ty, tick):
        pct = (tick * 3) % 101
        bar = int(pct / 100 * 9)
        line(0, "GET /construct", TEXT_DIM)
        line(2, "[" + "#" * bar + "." * (9 - bar) + "]", TEXT)
        line(3, "%3d%%  56k" % pct, TEXT_DIM)
        r = lcg(71, tick // 4)
        line(5, "".join("01"[int(r() * 2)] for _ in range(SCREEN_W)), TEXT_FAINT)
        # packets from the monitor to the laptop, along the desk
        for j in range(3):
            px = self.cx + W - 1 - ((tick + j * 4) % 12)
            cv.cell(px, self.top + 8, "<" if j == 0 else "-", TEXT)

    def _screen_helpers(self, line, cv, tx, ty, tick):
        n = (tick // 10) % 4
        for k in range(min(3, n + 1)):
            line(k, "spawn smith%d" % (k + 1), TEXT_DIM if k < n else TEXT)
        line(4, "[%d agents]" % min(3, n + 1), TEXT)

    def _screen_todo(self, line, cv, tx, ty, tick):
        done = (tick // 12) % (len(TODO) + 1)
        for k, item in enumerate(TODO):
            box = "[x]" if k < done else ("[>]" if k == done and (tick // 3) % 2 else "[ ]")
            line(k, box + " " + item, TEXT_DIM if k < done else TEXT)

    def _screen_wand(self, line, cv, tx, ty, tick):
        line(0, "follow the", TEXT_DIM)
        line(1, "white rabbit", TEXT)
        hop = (tick // 2) % 8
        x = tx + (tick // 2) % (SCREEN_W - 5)
        up = 1 if hop in (1, 2, 3) else 0
        cv.put(x, ty + 3 - up, "(\\_/)", WHITE)
        cv.put(x, ty + 4 - up, "(o.o)", WHITE)
        if not up:
            cv.put(x, ty + 5, "(\")\")", WHITE)

    def _agents(self, cv, tick):
        y = self.rows - 1 - len(AGENT)
        for n, x in enumerate((max(0, self.cx - 6), min(self.cols - 5, self.cx + COMP_W + 1))):
            if (tick // 10) % 4 < n + 1:
                continue
            step = ((tick // 4) + n) % 2
            for i, r in enumerate(AGENT):
                cv.sprite(x, y + i, r, TEXT_DIM if i else HOOD)
            cv.put(x + 1, y + 1, "=_=", EYE)
            if step:
                cv.put(x + 1, y + 3, "/ \\", TEXT_DIM)

    # -- the scene (mascot_mood.SCENES) --------------------------------------------------

    def _sky(self, cv, state, tick, scene):
        """Behind everything but the code: clouds, lightning, the sun or the
        moon top left."""
        overcast = bool(scene & {"cloud", "rain", "storm", "snow", "fog"})
        if overcast:
            colour = CLOUD if "day" in scene else CLOUD_DIM
            span = self.cols + 16
            for i in range(max(2, self.cols // 28)):
                r = lcg(83, i)
                y = (int(r() * 3) if self.rows >= 16 else 0) + (2 if "festive" in scene else 0)
                x = int(r() * span + tick / (9 + i * 3)) % span - 14
                cv.sprite(x, y, "  .--.     ", colour)
                cv.sprite(x, y + 1, " (    ).-. ", colour)
                cv.sprite(x, y + 2, "(_________)", colour)
        if "storm" in scene:
            cyc, t = divmod(tick, 47)
            if t <= 3:
                x = int(lcg(89, cyc)() * (self.cols - 4)) + 1
                for k, (dx, ch) in enumerate(((1, "/"), (0, "/"), (0, "\\"), (1, "/"))):
                    cv.sprite(x + dx + (k > 1), 1 + k, ch, WHITE if t % 2 == 0 else SUN)
        if state == "error" or overcast:
            return
        y = 2 if "festive" in scene else 0
        if "sun" in scene or "day" in scene:
            rays = ("\\ | /", "  |  ", "\\   /")[(tick // 8) % 3]
            cv.put(1, y, rays, SUN)
            cv.sprite(1, y + 1, "-(O)-", SUN)
            cv.put(1, y + 2, "/ | \\" if rays[0] == "\\" else "  |  ", SUN)
        elif "night" in scene:
            cv.sprite(2, y, ".-", MOON)
            cv.sprite(1, y + 1, "(", MOON)
            cv.sprite(2, y + 2, "`-", MOON)

    def _banner(self, cv, tick):
        """Papel picado: a cord along the top row, flags hanging under it."""
        cv.sprite(0, 0, "-" * self.cols, HOOD_DIM)
        for x in range(self.cols):
            if x % 3 == 1:
                flag = "Vv"[(tick // 4 + x // 3) % 2]
                cv.sprite(x, 1, flag, CONFETTI[(x // 3) % len(CONFETTI)])

    def _alarm(self, cv, tick):
        """An alarm clock ringing on top of the monitor: an event soon."""
        x, y = self.cx + W + MW - 6, self.top
        ring = (tick // 2) % 10 < 5
        shake = tick % 2 if ring else 0
        cv.sprite(x + shake, y, "o.-.o", AMBER)
        cv.sprite(x + shake, y + 1, "(   )", WHITE)
        cv.cell(x + shake + 2, y + 1, "|/-\\"[(tick // 3) % 4], AMBER)
        if ring:
            cv.cell(x - 1, y, "(", AMBER)
            cv.cell(x + 6, y, ")", AMBER)
            cv.cell(x + 6, y - 1, "!", AMBER)

    def _cat(self, cv, tick):
        """The black cat walks along the monitor's top -- and then again,
        the very same walk: deja vu, something changed in the Matrix."""
        t = tick % 120 - 90
        x = self.cx + W + min(t % 15, MW - 7)
        y = self.top
        cv.sprite(x, y, CAT[0], HOOD_DIM)
        cv.sprite(x, y + 1, CAT[1], HOOD_DIM)
        cv.put(x + 2, y + 1, "o", EYE)
        cv.put(x + 4, y + 1, "o", EYE)
        if t >= 15 and t % 4 < 2:
            cv.cell(x + 7, y, "!", HEAD)

    def _mug(self, cv, tick):
        """A mug of coffee on the desk to his left, steaming."""
        x, y = self.cx - 4, self.rows - 2
        cv.sprite(x, y, "c[_]", HOOD)
        cv.cell(x + 2, y - 1 - (tick // 4) % 2, "s~"[(tick // 3) % 2], HOOD_DIM)

    def _fog(self, cv, tick):
        for k, y in enumerate((self.rows // 3, self.rows // 2 + 1, self.rows - 3)):
            off = (tick // (6 + k * 2) + k * 7) % 12
            for x in range(self.cols):
                if (x + off) % 12 < 6 and (x + off) % 12 != 2 and not cv.occ[y][x]:
                    cv.cell(x, y, "~", FOG)

    def _snow(self, cv, tick):
        span = self.rows + 2
        for i in range(max(6, self.cols * self.rows // 50)):
            r = lcg(97, i)
            speed = 0.05 + r() * 0.06
            pos = r() * span + tick * speed
            fall = int(pos // span)
            y = int(pos - fall * span) - 1
            x = int(lcg(101, i, fall)() * self.cols + (0, 1, 1, 0, 0, -1, -1, 0)[(tick // 5 + i) % 8])
            if 0 <= x < self.cols and 0 <= y < self.rows and not cv.occ[y][x]:
                cv.cell(x, y, "*.*"[i % 3], SNOW)

    def _shimmer(self, cv, tick):
        """Heat rising off the desk."""
        y = self.rows - 2
        for x in range(self.cols):
            if lcg(103, x, tick // 3)() < 0.2:
                yy = y - (x + tick // 3) % 3
                if not cv.occ[yy][x]:
                    cv.cell(x, yy, "~", HEAT)

    def _confetti(self, cv, tick):
        span = self.rows
        for i in range(max(5, self.cols * self.rows // 90)):
            r = lcg(107, i)
            y = int((r() * span + tick * (0.15 + r() * 0.1)) % span)
            x = int(r() * self.cols) + (0, 1, 0, -1)[(tick // 4 + i) % 4]
            if 0 <= x < self.cols and not cv.occ[y][x]:
                cv.cell(x, y, ".,'"[i % 3], CONFETTI[i % len(CONFETTI)])

    def _hat(self, cv, tick):
        x, top = self.cx, self.top
        cv.cell(x + 10, top - 2, "*+"[(tick // 4) % 2], AMBER)
        cv.sprite(x + 9, top - 1, "/:\\", CONFETTI[0])
        cv.sprite(x + 8, top, "/_:_\\", CONFETTI[0])
        cv.cell(x + 10, top - 1, ":", AMBER)
        cv.cell(x + 10, top, ":", AMBER)

    def _umbrella(self, cv, party):
        """An umbrella over the hood (over the party hat, when there is room
        for both); returns the columns it keeps dry and the row below it."""
        x = self.cx
        y = self.top - (4 if party and self.top >= 4 else 2)
        cv.sprite(x, y, "   .-~~~~~~~~~~~-.   ", BROLLY)
        cv.sprite(x, y + 1, "  /_/_/_/_|_\\_\\_\\_\\  ", BROLLY)
        for yy in range(y + 2, self.top):
            cv.sprite(x + 10, yy, "|", BROLLY)        # the handle, down to the hood
        return x + 2, x + 18, y + 2

    def _weather_rain(self, cv, tick, dry, heavy=False):
        """Real rain: blue, slanting down to the left across the falling
        code, on every cell nothing covers, none under the umbrella."""
        x_a, x_b, y_dry = dry
        span = self.rows + 2
        for i in range(self.cols * self.rows // (12 if heavy else 22)):
            r = lcg(109, i)
            speed = (0.9 if heavy else 0.6) + r() * 0.3
            y = int((r() * span + tick * speed) % span) - 1
            x = (int(r() * self.cols) - y // 2) % self.cols
            if y >= y_dry and x_a <= x <= x_b:
                continue
            if 0 <= y < self.rows and not cv.occ[y][x]:
                cv.cell(x, y, "/" if i % 4 else ",", WET)

    def _mood_marks(self, cv, state, tick, mood, scene):
        """What floats by him for his mood and scene: z's, a "?", "!"s, a
        drop of sweat, music notes, breath in the cold."""
        x0, top = self.cx, self.top
        idle = state == "idle"
        if idle and mood == "sleepy":
            t = tick % 36
            for j in range(3):
                if t // 9 > j:
                    cv.cell(x0 + 19 + j, top + 3 - j, "zzZ"[j], HOOD_DIM if j < 2 else HOOD)
        elif idle and mood == "curious" and (tick // 5) % 4:
            cv.cell(x0 + 19, top + 1, "?", HEAD)
        elif idle and mood == "excited" and (tick // 3) % 4 < 2:
            cv.cell(x0 + 1, top + 1, "!", HEAD)
            cv.cell(x0 + 19, top + 1, "!", HEAD)
        if (mood == "worried" and state != "done") or "hot" in scene:
            t = tick % 16
            if t < 10:
                cv.cell(x0 + 19, top + 2 + (t >= 5), "'" if t < 5 else ",", SWEAT)
        if "music" in scene and state != "error":
            for j in range(2):
                t = (tick + j * 12) % 24
                if t < 20:
                    cv.cell(x0 - 1 - t // 6 - j * 2, top + 5 - t // 5, "db"[j], MUSIC)
        if "cold" in scene and idle:
            t = tick % 40
            if t < 12:
                cv.cell(x0 + 1 - t // 6, top + 6 - t // 4, ".oO"[min(2, t // 4)], SNOW)

    # -- error ------------------------------------------------------------------------

    def _glitch(self, cv, tick):
        """Rows torn sideways and a scatter of red noise, on most frames;
        every eighth frame is clean, so the picture can still be read."""
        if tick % 8 == 0:
            return
        r = lcg(73, tick)
        for _ in range(2 + int(r() * 3)):
            y = int(r() * self.rows)
            cv.shift_row(y, int(r() * 7) - 3)
        for _ in range(self.cols // 4):
            x, y = int(r() * self.cols), int(r() * self.rows)
            if cv.get(x, y) != " ":
                cv.cell(x, y, GLYPHS[int(r() * len(GLYPHS))], RED)
