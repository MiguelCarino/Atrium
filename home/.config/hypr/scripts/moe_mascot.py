#!/usr/bin/env python3
"""The moe theme's mascot: a chibi cat-eared girl drawn in ASCII, animated,
for llm-chat.py to show on its dark plum panel while the model works.

    moe_mascot.py [ARGS]              the same CLI as mascots.py (demo,
                                      --cycle, --frame, --check), with the
                                      theme defaulting to moe; see there

Pure Python and no GTK: llm-chat.py imports it and asks, ten times a
second, for one picture of the current state:

    m = Mascot(cols=64, rows=18)      (mascots.Mascot(cols, rows, theme=...)
                                       picks this one for theme "moe")
    m.lines(state, tick, tool)    rows strings, each exactly cols columns
    m.markup(state, tick, tool)   the same picture as Pango markup
    m.bubble(state, tool)         a short speech line for the frontend's label

STATES are idle, thinking, tool, writing, done and error; tool is the name of
the tool running (Bash, Read, Edit, Write, Grep, Glob, WebSearch,
WebFetch, Task/Agent, TodoWrite; anything else gets the sparkly wand).

Every call also takes mood= and scene= (mascot_mood.py decides them; the
frontend passes its View along):

    m.lines(state, tick, tool, mood="sleepy", scene={"night", "rain"})
    m.bubble(state, tool, mood)   idle: the mood's own line
    m.say(topic)                  a mascot_mood topic in her words

  mood    one of mascot_mood.MOODS. Idle, it is her whole face and pose:
          happy ^w^, excited sparkly eyes and little hops, shy >///< with
          hearts, curious o.O and a "?", focused and worried brows (worried
          sweats), sad droopy ears and a tear, sleepy half-shut eyes, yawns
          and z's. At work (thinking, tool, writing) only the accents show --
          brows, sweat, blush, a sparkle in the eye -- over the work face;
          done and error keep theirs. calm (or None) is the face she always
          had. The idle fidget at the end of each 9-second round (a wave, a
          look around, a stretch, catching a petal) is picked by the noise
          and weighted by the mood.
  scene   a set of mascot_mood.SCENES: day (a sun or clouds for the stars and
          moon), cloud, rain and storm (rain across the stage, a parasol over
          her, lightning), snow (snowflakes for petals), fog (drifting bands),
          hot (sweat, shimmer over the grass), cold (a scarf, breath puffs),
          music (headphones, notes, a bob), game (a handheld in her hands,
          idle), party (a party hat, confetti), festive (papel picado along
          the top), clock (an alarm clock ringing on the grass).

The picture is three layers on a cell grid, painted back to front:

  ambient   stars twinkling in the upper half, a crescent moon when there is
            room, sakura petals drifting down and to the right, sparkles
            blooming and fading, grass along the bottom row; per state, a
            heart burst (done), a raincloud (error), a heart rising (idle).
  mascot    21 x 11 cells, centred horizontally, feet on the row above the
            grass. Opaque between the first and last drawn cell of each of
            her rows, so petals pass BEHIND her, never through her face.
            The face (eyes, mouth, blush) and the pose (arms, ears, tail,
            head tilt, jump) are per state; she blinks every few seconds.
  props     to her right at hand height: a tiny terminal for Bash, a book
            for Read, a notepad and pencil for Edit/Write, a magnifier for
            the searches, a globe for WebFetch, two helper cats for
            Task/Agent, a checklist for TodoWrite, a wand otherwise; a
            thought bubble when thinking, a streaming scroll when writing.

Every cell the grid ever holds is one display column wide: put() refuses a
character whose east_asian_width is W, F or A (A -- ambiguous -- is wide in a
CJK monospace font such as M PLUS 1 Code, which the frontend uses), so a row
of cols cells is cols columns in any font. The art is plain ASCII. Japanese
goes in bubble() only, which the frontend draws in its own label.

Deterministic: the picture is a function of (state, tick, tool, size) and
nothing else -- petals, stars and sparkles come from a small LCG seeded per
element (and per fall, so a petal lands somewhere new each time round), not
from the random module or the clock. Motion is in whole cells; the mascot's
column only changes on purpose (the idle head tilt, nothing else), so the
frame never jitters sideways.

Colours are the moe terminal night palette, pastels on #2b1d2e: outline
#f6dce8, blush and hearts #ff7a9c, eyes #d8a6f0 / #9fc4f5, petals #f78fb3 /
#ff9db5, sparkles #ffd98a, props #8fe3e0 / #9be6b4, rain #9fc4f5. markup()
coalesces each row into runs of one colour (a space joins any run: it has no
colour to show), escapes &, < and >, and leaves uncoloured cells bare.
"""

import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import (COMBOS, STATES, TOOLS, Canvas, display_width, dw,  # noqa: E402,F401
                           lcg, prop_kind)
from mascot_mood import MOODS, word  # noqa: E402

THEME = "moe"
PANEL = "#2b1d2e"       # the night plum card she is drawn on (llm-chat.css)

# --- palette (moe night) -----------------------------------------------------

OUTLINE = "#f6dce8"
HAIR = "#e7b8d8"
BLUSH = "#ff7a9c"
EYE = "#d8a6f0"
EYE_COOL = "#9fc4f5"
PIN = "#f78fb3"
PETAL = ("#f78fb3", "#ff9db5", "#f4a3c4")
SPARKLE = "#ffd98a"
STAR_DIM = "#8a6a8f"
HEART = "#ff7a9c"
PROP = "#8fe3e0"
PROP2 = "#9be6b4"
RAIN = "#9fc4f5"
CLOUD = "#b9a7c9"
GRASS = "#9be6b4"
GRASS_DIM = "#5f8f78"
MOON = "#f3d27a"
INK = "#d8a6f0"
SUN = "#ffd98a"
SNOW = "#f3ecf7"
FOG = "#7d6a85"
BAD = "#ff6470"          # a coral red, for the "x"/"#" signs (her pinks read as love)
CONFETTI = ("#ff7a9c", "#8fe3e0", "#ffd98a", "#9be6b4", "#9fc4f5", "#d8a6f0")

# The reaction sign over her head (mascot_mood.EMOTE_TONES), all >= 5:1 on PANEL.
EMOTE_COLOURS = {"accent": EYE, "warn": SPARKLE, "bad": BAD, "good": GRASS,
                 "love": HEART, "dim": CLOUD}

# --- the mascot --------------------------------------------------------------
# 21 columns, mirror-symmetric about column 10. Rows 0-6 are the head (ears,
# hair, face, hair tails and the collar bow), rows 7-10 the body. Face cells:
# eyes at (3, 7) and (3, 13), mouth (4, 10), blush (4, 6) and (4, 14).

W, H = 21, 11

HEAD = [
    "   /\\           /\\   ",
    "  /  \\.-------./  \\  ",
    " |   .'~~~~~~~`.   | ",
    " |  /           \\  | ",
    " |  |           |  | ",
    "  \\  \\_________/  /  ",
    "   `-._ |>o<| _.-'   ",
]
# The two ears flattened sideways, for error.
EARS_DROOP = [
    "                     ",
    " ,__ \\.-------./ __, ",
]

BODY = {
    #            row 7                    row 8                    row 9                    row 10
    "neutral": ["      /|  :  |\\      ", "     o |_____| o     ", "      /_______\\      ", "        |   |        "],
    "wave":    ["      /|  :  |\\_o    ", "     o |_____|       ", "      /_______\\      ", "        |   |        "],
    "chin":    ["      /|  :  |)      ", "     o |_____|       ", "      /_______\\      ", "        |   |        "],
    "hold":    ["      /|  :  |\\      ", "     o |_____|--o    ", "      /_______\\      ", "        |   |        "],
    "type":    ["      /|  :  |\\      ", "      o|_____|o      ", "      /_______\\      ", "        |   |        "],
    "cheer":   ["    o_/|  ", "       |_____|       ", "      /_______\\      ", "        |   |        "],
    "cheer2":  ["    \\o/|  ", "       |_____|       ", "      /_______\\      ", "        |   |        "],
    "slump":   ["       |  :  |       ", "      o|_____|o      ", "      /_______\\      ", "        |   |        "],
    "air":     ["    o_/|  ", "       |_____|       ", "      /_______\\      ", "       /     \\       "],
}
# "cheer", "cheer2" and "air" give only the left half of row 7 (columns 0-9):
# _fix_body() mirrors it about the centre column, so the raised arms match.

TAIL = [  # (row 8 at columns 2-4, row 9 at columns 2-5): a slow swish
    ("  (", "  `-"),
    (" ( ", "  `-"),
    ("(  ", " `--"),
    (" ( ", "  `-"),
]

# Kaomoji pieces per state: (eye, mouth, blush)
FACE = {
    "idle": ("O", "w", '"'),
    "thinking": ("o", "~", '"'),
    "tool": ("O", "o", '"'),
    "writing": ("O", "o", '"'),
    "done": ("^", "w", '"'),
    "error": ("T", "n", ""),
}
# ... and per mood, idle: (left eye, right eye, mouth, blush). calm: FACE's.
MOOD_FACE = {
    "happy": ("^", "^", "w", '"'),
    "excited": ("*", "*", "D", '"'),
    "shy": (">", "<", "~", "/"),
    "curious": ("o", "O", "o", ""),
    "focused": ("o", "o", "-", ""),
    "worried": ("o", "o", "~", ""),
    "sad": (".", ".", "n", ""),
    "sleepy": ("-", "-", ".", '"'),
}
# Brows over the fringe (row 2, above each eye): left, right.
BROWS = {"focused": ("\\", "/"), "worried": ("/", "\\"), "sad": ("/", "\\")}
# The idle fidget a mood favours: (name, weight); "rest" is none at all.
FIDGETS = {
    "calm": (("wave", 2), ("look", 2), ("stretch", 1), ("petal", 1), ("rest", 2)),
    "happy": (("wave", 3), ("petal", 2), ("look", 1)),
    "excited": (("wave", 2), ("petal", 2), ("stretch", 1)),
    "shy": (("look", 2), ("rest", 2)),
    "curious": (("look", 4), ("petal", 1)),
    "focused": (("rest", 3), ("look", 1)),
    "worried": (("look", 2), ("rest", 2)),
    "sad": (("rest", 1),),
    "sleepy": (("stretch", 3), ("rest", 2)),
}


def _fix_body():
    """Complete the half-rows above as mirror images; check every row's width."""
    def mirror(s):
        swap = {"/": "\\", "\\": "/", "(": ")", ")": "(", "`": "'", "'": "`"}
        return "".join(swap.get(c, c) for c in reversed(s))

    for key in ("cheer", "cheer2", "air"):
        left = BODY[key][0]
        BODY[key][0] = left + ":" + mirror(left)
    for rows in BODY.values():
        for r in rows:
            assert len(r) == W, (rows, r, len(r))


_fix_body()
for _r in HEAD + EARS_DROOP:
    assert len(_r) == W, (_r, len(_r))


# --- shared with the other themes' mascots (mascot_common.py) ---------------
# Kept under their old names here: moe_mascot.Canvas, _lcg, _dw ... are what
# callers of this module used before the other mascots existed.

_lcg = lcg
_dw = dw
_prop_kind = prop_kind


# --- the mascot class ---------------------------------------------------------

BUBBLES = {
    "idle": "なにする？ ready when you are (=^･ω･^=)",
    "thinking": "うーん… let me think (｡•ˇ‸ˇ•｡)",
    "writing": "かきかき… writing it down ✎",
    "done": "できた！ all done ♡ (ﾉ◕ヮ◕)ﾉ*:･ﾟ✧",
    "error": "ごめんね… something went wrong (╥﹏╥)",
}
TOOL_BUBBLES = {
    "Bash": "コマンド実行中！ running a command",
    "Read": "よみよみ… reading (・ω・)",
    "Edit": "なおしてる！ editing ✎",
    "MultiEdit": "なおしてる！ editing ✎",
    "Write": "かいてる！ writing a file ✎",
    "NotebookEdit": "ノートを編集中 editing a notebook",
    "Grep": "さがしてる… searching (・・ )?",
    "Glob": "ファイルさがし… looking for files",
    "WebSearch": "ネットでさがす！ searching the web",
    "WebFetch": "ダウンロード中… fetching a page",
    "Task": "おてつだい呼ぶね！ calling helpers",
    "Agent": "おてつだい呼ぶね！ calling helpers",
    "TodoWrite": "やることリスト！ updating the list ☑",
}

MOOD_BUBBLES = {
    "happy": "ごきげん♪ ready when you are (=^･ω･^=)",
    "excited": "わくわく！ what are we doing? ✧",
    "shy": "…な、なに？ (〃ω〃)",
    "curious": "なになに？ what's next? (・・ )?",
    "focused": "しゅうちゅう… ready ( •̀ω•́ )",
    "worried": "だいじょうぶかな… (・_・;)",
    "sad": "しょんぼり… (´・ω・`)",
    "sleepy": "ねむい… sleepy (´-ω-)zz",
}
# mascot_mood topics in her words (str.format with the topic's arguments).
TOPIC_LINES = {
    "thanks": "えへへ…どういたしまして ♡ (〃▽〃)",
    "worried": "だいじょうぶ…？ uh-oh (・_・;)",
    "frustrated": "うぅ…もう一回！ one more try (｀ε´)",
    "relieved": "ほっ…なおった！ phew, fixed (´▽`)",
    "determined": "ながいね…がんばる！ hang in there ٩(ˊᗜˋ)و",
    "proud": "やったー！ big job done ✧",
    "sad": "ごめんね… sorry (´;ω;`)",
    "happy": "うれしい！ yay ♪",
    "curious": "ふむふむ… hmm (・・ )?",
    "rain": "雨だね… take an umbrella ☂",
    "storm": "かみなり！ stay inside ⚡",
    "snow": "ゆきだ！ it's snowing ❄",
    "fog": "きりがすごい… foggy out",
    "sun": "いい天気！ sunny today ☀",
    "hot": "あつい… {0} outside",
    "cold": "さむい… {0} brr",
    "gpu_hot": "GPUあちち… {0}°C ♨",
    "cpu_hot": "CPUあちち… {0}°C ♨",
    "music": "いい曲〜 ♪",
    "game": "ゲームタイム！ game on",
    "event": "あと{1}分！ {0} in {1} min",
    "event_now": "もうすぐ！ {0} is starting",
    "birthday": "{0}のおたんじょうび！ happy birthday 🎂",
    "holiday": "きょうは{0}！ 🎉",
    "go_home": "{0}… おつかれさま！ work's over, go home",
    "bedtime": "{0}… もう寝よう？ go to bed (´-ω-)zz",
    "morning": "おはよう！ good morning ☀",
    "lunch": "おひるごはん？ lunch time",
    "weekend": "しゅうまつだ〜 weekend ♪",
    "friday": "金曜日だ〜！ almost the weekend ♪",
    # conversation and stage events (tuples rotate: a new one each time)
    "hello": ("こんにちは！ what shall we do? ✧", "やっほー！ hi hi ♡",
              "おはなししよ？ let's make something ♪"),
    "welcome_back": "おかえりなさい！ welcome back ♡",
    "wake": "はっ！ねてないよ！ I'm up! (⊙_⊙)",
    "long_prompt": ("わぁ、ながい！ a long one… (°o°)", "よむね…！ reading it all ( •̀ω•́ )"),
    "code": "コードだ！ let me see ( •̀ω•́ )",
    "image": "え、写真？ ooh, a picture ✧",
    "aborted": "ストップ！ stopping (・_・)ゞ",
    "tests_pass": ("テスト合格！ all green ✧", "ぜんぶパス！ tests pass ♪",
                   "みどり〜！ green green (ﾉ◕ヮ◕)ﾉ"),
    "tests_fail": ("テスト失敗… tests failed (´;ω;`)", "あかい… red tests (・_・;)"),
    "commit": ("コミット！ shipped ✧", "おくったよ！ pushed ♡", "できあがり！ it's out (ﾉ◕ヮ◕)ﾉ"),
    "fast": ("はやっ！ quick one ✧", "いっしゅん！ done in a blink", "らくしょう♪ easy peasy"),
    "busy": ("いそがしい〜 busy busy (>_<)", "まだまだ！ so many tools ٩(ˊᗜˋ)و"),
    "model": "あたらしい子？ hello, {0} ✧",
    "poke": ("ひゃっ！ hey! (〃ω〃)", "なぁに？ yes? (・・ )?", "つんつんしないで〜 (>ω<)",
             "にゃっ！ nya! ♪", "えへへ、くすぐったい (〃▽〃)", "あそぶ？ wanna play? ✧"),
    "poke_spam": ("もう！やめて〜！ stop poking! (｀ε´)", "つつきすぎ！ too many pokes! (>_<)",
                  "むぅ…おこるよ！ I'll get mad! (｀へ´)"),
    "pet": ("ふにゃ〜 ♡ (´ω`)", "なでなで…うれしい ♡", "もっと〜 more pats please ♡",
            "ごろごろ… purr ♡ (=^･ω･^=)"),
}

STREAM_WORDS = ("moe", "nya", "ok", "so", "code", "fix", "yay", "the", "sakura",
                "it", "now", "neko", "kawaii", "and", "done", "a", "test", "uwu")


class Mascot:
    def __new__(cls, cols=64, rows=18, theme=THEME):
        # Mascot(cols, rows, theme="matrix") hands out that theme's mascot
        # (mascots.py), so this module stays the one entry point it was.
        if cls is Mascot and theme not in (None, THEME):
            import mascots
            return mascots.Mascot(cols, rows, theme=theme)
        return super().__new__(cls)

    def __init__(self, cols=64, rows=18, theme=THEME):
        self.cols = max(int(cols), W + 2)
        self.rows = max(int(rows), H + 2)
        self.x0 = (self.cols - W) // 2
        # feet on the row above the grass
        self.top = self.rows - 1 - H
        area = self.cols * self.rows
        self.n_petals = max(4, area // 85)
        self.n_stars = max(3, area // 110)
        self.n_sparkles = max(2, area // 260)
        self._stream = self._make_stream()
        # fixed per size: where the stars are, what grows along the bottom
        self._stars = []
        for i in range(self.n_stars):
            r = _lcg(7, i, self.cols, self.rows)
            x = int(r() * self.cols)
            y = int(r() * max(2, self.rows // 2))
            period = 24 + int(r() * 30)
            self._stars.append((x, y, period, int(r() * period)))
        self._grass_v = [_lcg(23, x)() for x in range(self.cols)]

    # -- public ----------------------------------------------------------------

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
        if state == "tool":
            if tool and tool.startswith("mcp__"):
                return "まほう発動！ %s ✧" % tool.split("__")[-1]
            return TOOL_BUBBLES.get(tool or "", "まほう発動！ %s ✧" % (tool or "magic"))
        return BUBBLES.get(state, BUBBLES["idle"])

    # -- composition -------------------------------------------------------------

    def _render(self, state, tick, tool, mood=None, scene=()):
        if state not in STATES:
            state = "idle"
        if mood not in MOODS:
            mood = "calm"
        scene = frozenset(scene or ())
        tick = int(tick)
        cv = Canvas(self.cols, self.rows)
        kind = _prop_kind(tool) if state == "tool" else None

        # vertical position: done jumps, excited bounces now and then
        dy = 0
        if state == "done":
            hop = (0, 0, 1, 2, 2, 2, 1, 0, 0, 0, 0, 0)
            dy = hop[tick % len(hop)]
        elif state == "idle" and mood == "excited" and (tick // 30) % 2:
            dy = (0, 1, 1, 0, 0, 0)[tick % 6]
        dy = min(dy, self.top)
        top = self.top - dy

        self._sky(cv, state, tick, scene)
        if "fog" in scene:
            self._fog(cv, tick)
        if "snow" in scene:
            self._snow(cv, tick)
        self._petals(cv, state, tick, scene)
        if "festive" in scene:
            self._banner(cv, tick)
        self._sparkles(cv, state, tick)
        self._grass(cv, tick)
        if "hot" in scene:
            self._shimmer(cv, tick)
        if state == "idle" and mood in ("calm", "happy", "shy", "excited"):
            self._rising_heart(cv, tick, 35 if mood == "shy" else 70)
        if kind == "helpers":
            self._helpers(cv, tick)
        elif "clock" in scene:
            self._alarm(cv, tick)

        hx = self._mascot(cv, state, tick, top, kind, dy, mood, scene)
        # the reaction sign's anchor: just above and right of her right ear
        # (ear tip at column 17 of the head), following the hop and the tilt;
        # a column further out under the parasol, whose canopy reaches 18.
        rainy = bool(scene & {"rain", "storm"})
        self.head = (self.x0 + hx + (19 if rainy else 18), max(0, top - 1))
        self._mood_marks(cv, state, tick, top, hx, mood, scene)
        if "party" in scene:
            self._hat(cv, tick, top, hx)
        if scene & {"rain", "storm"}:
            dry = self._parasol(cv, top - (2 if "party" in scene else 0), hx)
            if state != "error":
                self._weather_rain(cv, tick, dry, heavy="storm" in scene)

        if state == "thinking":
            self._thought(cv, tick, top)
        elif state == "writing":
            self._scroll(cv, tick, top)
        elif kind and kind != "helpers":
            self._prop(cv, kind, tick, top)
        if state == "done":
            self._burst(cv, tick, top)
        if state == "error":
            self._rain(cv, tick)
            self._cloud(cv, tick)
        return cv

    # -- ambient ---------------------------------------------------------------

    def _sky(self, cv, state, tick, scene=frozenset()):
        overcast = bool(scene & {"cloud", "rain", "storm", "snow", "fog"})
        if overcast:
            self._clouds(cv, tick, dim="day" not in scene)
        if "storm" in scene:
            self._lightning(cv, tick)
        if "day" in scene:
            if not overcast and state != "error" and self.cols >= 50:
                self._sun(cv, tick, 2 if "festive" in scene else 0)
            return
        moon = self.cols >= 60 and self.rows >= 16 and state != "error" and not overcast
        if moon:
            cv.put(2, 0, ".-", MOON)
            cv.put(1, 1, "(", MOON)
            cv.put(2, 2, "`-", MOON)
        for x, y, period, ph in self._stars:
            if moon and x < 5 and y < 3:
                continue
            if overcast and (x + y) % 3:
                continue        # most of them behind the clouds
            t = (tick + ph) % period
            seq = ".+*+."
            if t < len(seq):
                cv.cell(x, y, seq[t], SPARKLE)
            else:
                cv.cell(x, y, ".", STAR_DIM)

    def _petals(self, cv, state, tick, scene=frozenset()):
        span = self.rows + 4
        n = self.n_petals if state != "error" else self.n_petals // 2
        if "snow" in scene:
            n = 0               # snowflakes instead (_snow)
        elif scene & {"rain", "storm"}:
            n //= 3
        party = "party" in scene
        glyphs = ("*", "~", ",", "'", "`", "~")
        for i in range(n):
            r = _lcg(11, i)
            speed = 0.10 + r() * 0.12            # rows per tick: 1-2.2 rows/s
            drift = 0.6 + r() * 0.8               # columns per row fallen
            ph = r() * span
            colour = CONFETTI[i % len(CONFETTI)] if party and i % 2 else PETAL[i % len(PETAL)]
            pos = ph + tick * speed
            fall = int(pos // span)
            yy = pos - fall * span - 2
            rr = _lcg(13, i, fall)
            x0 = rr() * (self.cols + self.rows)
            sway = (0, 1, 1, 0, 0, -1, -1, 0)[int(pos * 2) % 8] * 0.5
            x = int(x0 + (yy + 2) * drift + sway) % (self.cols + self.rows) - self.rows // 2
            y = int(yy)
            g = glyphs[(int(pos * 3) + i) % len(glyphs)]
            cv.cell(x, y, g, colour)

    def _sparkles(self, cv, state, tick):
        n = self.n_sparkles + (2 if state == "done" else 0)
        if state == "error":
            n = max(1, n // 2)
        seq = ".+*+."
        for j in range(n):
            r = _lcg(17, j)
            period = 18 + int(r() * 22)
            ph = int(r() * period)
            t = tick + ph
            cyc = t // period
            k = t % period
            if k >= len(seq):
                continue
            rr = _lcg(19, j, cyc)
            x = int(rr() * self.cols)
            y = int(rr() * (self.rows - 1))
            if cv.get(x, y) == " ":
                cv.cell(x, y, seq[k], SPARKLE)

    def _grass(self, cv, tick):
        y = self.rows - 1
        wind = (tick // 6) % 4
        for x, v in enumerate(self._grass_v):
            if v < 0.22:
                c = ",'"[(x + wind) % 2] if v < 0.11 else "."
                cv.cell(x, y, c, GRASS_DIM)
            elif v < 0.30:
                cv.cell(x, y, "\"" if (x + wind) % 3 else "'", GRASS)
            elif v < 0.335:
                cv.cell(x, y, "*", PETAL[x % 3])
        # under her feet: a soft shadow
        cv.put(self.x0 + 7, y, "._____.", GRASS_DIM, solid=True)

    def _rising_heart(self, cv, tick, period=70):
        t = tick % period
        if t >= period * 4 // 7:
            return
        cyc = tick // period
        side = -1 if cyc % 2 else 1
        x = self.x0 + 10 + side * (13 + (t // 8) % 2)
        y = self.top + 4 - t // 5
        cv.put(x, y, "<3", HEART)

    # -- the scene (mascot_mood.SCENES) ------------------------------------------

    def _sun(self, cv, tick, y=0):
        rays = ("\\ | /", "  |  ", "\\   /")[(tick // 8) % 3]
        cv.put(1, y, rays, SUN)
        cv.put(1, y + 1, "-(", SUN)
        cv.put(3, y + 1, "O", SUN)
        cv.put(4, y + 1, ")-", SUN)
        cv.put(1, y + 2, "/ | \\" if rays[0] == "\\" else "  |  ", SUN)

    def _clouds(self, cv, tick, dim=False):
        colour = STAR_DIM if dim else CLOUD
        span = self.cols + 16
        for i in range(max(2, self.cols // 28)):
            r = _lcg(47, i)
            y = int(r() * 3) if self.rows >= 16 else 0
            x = int(r() * span + tick / (9 + i * 3)) % span - 14
            cv.put(x, y, "  .--.     ", colour)
            cv.put(x, y + 1, " (    ).-. ", colour)
            cv.put(x, y + 2, "(_________)", colour)

    def _lightning(self, cv, tick):
        cyc, t = divmod(tick, 47)
        if t > 3:
            return
        x = int(_lcg(53, cyc)() * (self.cols - 4)) + 1
        for k, (dx, ch) in enumerate(((1, "/"), (0, "/"), (0, "\\"), (1, "/"))):
            cv.cell(x + dx + (k > 1), 1 + k, ch, SUN if t % 2 == 0 else OUTLINE)

    def _fog(self, cv, tick):
        for k, y in enumerate((self.rows // 3, self.rows // 2 + 1, self.rows - 3)):
            off = (tick // (6 + k * 2) + k * 7) % 12
            for x in range(self.cols):
                if (x + off) % 12 < 5 and (x + off) % 12 != 2:
                    cv.cell(x, y, "~", FOG)

    def _snow(self, cv, tick):
        span = self.rows + 2
        for i in range(max(6, self.cols * self.rows // 60)):
            r = _lcg(59, i)
            speed = 0.05 + r() * 0.06
            pos = r() * span + tick * speed
            fall = int(pos // span)
            y = int(pos - fall * span) - 1
            x = int(_lcg(61, i, fall)() * self.cols + (0, 1, 1, 0, 0, -1, -1, 0)[(tick // 5 + i) % 8])
            cv.cell(x, y, "*.+"[i % 3], SNOW)

    def _banner(self, cv, tick):
        """Papel picado: a cord along the top row, flags hanging under it."""
        for x in range(self.cols):
            cv.cell(x, 0, "-", STAR_DIM)
            if x % 3 == 1:
                flag = "Vv"[(tick // 4 + x // 3) % 2]
                cv.cell(x, 1, flag, CONFETTI[(x // 3) % len(CONFETTI)])

    def _shimmer(self, cv, tick):
        y = self.rows - 2
        for x in range(self.cols):
            if _lcg(67, x, tick // 3)() < 0.08 and cv.get(x, y) == " ":
                cv.cell(x, y - (x % 2), "~", SPARKLE)

    def _alarm(self, cv, tick):
        """An alarm clock ringing on the grass to her left: an event soon."""
        x, y = self.x0 - 9, self.rows - 4
        ring = (tick // 2) % 10 < 5
        shake = (0, 1)[tick % 2] if ring else 0
        cv.sprite(x + shake, y, "o.-.o", PROP)
        cv.sprite(x + shake, y + 1, "(   )", PROP)
        cv.cell(x + shake + 2, y + 1, "|/-\\"[(tick // 3) % 4], SPARKLE)
        cv.sprite(x + shake, y + 2, "'-^-'", PROP)
        if ring:
            cv.cell(x + 6, y - 1, "!", SPARKLE)
            cv.cell(x - 2, y, "(", SPARKLE)
            cv.cell(x + 7, y, ")", SPARKLE)

    def _hat(self, cv, tick, top, hx):
        fx = self.x0 + hx
        cv.cell(fx + 10, top - 2, "*+"[(tick // 4) % 2], SPARKLE)
        cv.sprite(fx + 9, top - 1, "/:\\", PIN)
        cv.sprite(fx + 8, top, "/_:_\\", PROP)
        cv.cell(fx + 10, top - 1, ":", SPARKLE)

    def _parasol(self, cv, top, hx):
        """A parasol over her head; returns the columns it keeps dry and the
        row below it, for _weather_rain."""
        fx = self.x0 + hx
        y = top - 2
        cv.sprite(fx, y, "   .-~~~~~~~~~~~-.   ", PIN)
        cv.sprite(fx, y + 1, "  /_/_/_/_|_\\_\\_\\_\\  ", PIN)
        cv.cell(fx + 10, y + 1, "|", PROP)
        return fx + 2, fx + 18, y + 2

    def _weather_rain(self, cv, tick, dry, heavy=False):
        """Rain over the whole stage, on the cells nothing covers, none under
        the parasol."""
        x_a, x_b, y_dry = dry
        span = self.rows + 2
        for i in range(self.cols * self.rows // (14 if heavy else 24)):
            r = _lcg(71, i)
            speed = (0.7 if heavy else 0.5) + r() * 0.3
            y = int((r() * span + tick * speed) % span) - 1
            x = int(r() * self.cols)
            if y >= y_dry and x_a <= x <= x_b:
                continue
            if 0 <= x < cv.cols and 0 <= y < cv.rows and not cv.occ[y][x] and cv.get(x, y) == " ":
                cv.cell(x, y, "'" if i % 3 else ",", RAIN)

    def _rain(self, cv, tick):
        """Drops from the cloud to the grass, drawn after her but only on
        cells she does not cover: on her hair between the ears, past her
        shoulders, never across her face."""
        cx = self.x0 + 4 + self._cloud_dx(tick)
        top = max(0, self.top - 3) + 2
        length = max(3, self.rows - 1 - top)
        for i in range(30):
            r = _lcg(29, i)
            speed = 0.6 + r() * 0.3
            ph = r() * length
            y = top + int((ph + tick * speed) % length)
            x = cx + i % 15
            if 0 <= x < cv.cols and 0 <= y < cv.rows and not cv.occ[y][x]:
                cv.cell(x, y, "'" if i % 3 else ",", RAIN)

    def _cloud_dx(self, tick):
        return (0, 1, 1, 0, 0, -1, -1, 0)[(tick // 6) % 8]

    def _cloud(self, cv, tick):
        x = self.x0 + 3 + self._cloud_dx(tick)
        y = max(0, self.top - 3)
        cv.sprite(x, y, "   .--.  .-.     ", CLOUD)
        cv.sprite(x, y + 1, " (`    )'   `-.  ", CLOUD)
        cv.sprite(x, y + 2, "(_______________)", CLOUD)
        if (tick // 3) % 9 == 0:
            cv.put(x + 7, y + 2, "/", SPARKLE)

    def _burst(self, cv, tick, top):
        period = 22
        t = tick % period
        cx = self.x0 + 10
        cy = top + 4
        dirs = ((-1, 0), (1, 0), (-1, -1), (1, -1), (0, -1), (-1, 1), (1, 1))
        if t < 16:
            rad = 2 + t
            for k, (ux, uy) in enumerate(dirs):
                x = cx + ux * (6 + rad * 2) - (1 if ux == 0 else 0)
                y = cy + uy * (1 + rad // 2) - (2 if uy < 0 and ux == 0 else 0)
                glyph = "<3" if (t + k) % 4 else "**"
                colour = HEART if glyph == "<3" else SPARKLE
                cv.put(x, y, glyph, colour)

    def _helpers(self, cv, tick):
        """Two mini cats marching in place either side of her."""
        y = self.rows - 4
        for n, x in enumerate((self.x0 - 9, self.x0 + W + 1)):
            step = ((tick // 3) + n * 2) % 4
            hop = 1 if step in (1, 2) else 0
            ear = "/\\_/\\"
            face = ("(=^.^=)", "(=o.o=)", "(=^.^=)", "(=-.-=)")[(tick // 6 + n) % 4] \
                if (tick + n * 17) % 41 > 2 else "(=-.-=)"
            feet = (' (")(") ', ' (") (")', ' (")(") ', '(") (") ')[step]
            cv.sprite(x + 1, y - hop, ear, OUTLINE)
            cv.sprite(x, y + 1 - hop, face, OUTLINE)
            fx = face.index("^") if "^" in face else -1
            if fx >= 0:
                cv.put(x + fx, y + 1 - hop, "^", EYE)
                cv.put(x + fx + 2, y + 1 - hop, "^", EYE)
            cv.put(x + 1, y + 1 - hop, "=", BLUSH)
            cv.put(x + 5, y + 1 - hop, "=", BLUSH)
            cv.put(x, y + 2 - hop, feet, PROP2)
            if (tick // 4 + n) % 6 == 0:
                cv.put(x + 7, y - 1 - hop, "!", SPARKLE)

    # -- her -------------------------------------------------------------------

    def _blink(self, tick):
        t = tick % 53
        if t in (0, 1):
            return True
        # a double blink now and then
        return tick % 159 in (5, 6)

    def _fidget(self, tick, mood):
        """The idle fidget now: one per 90-tick round, in its last 18 ticks,
        picked by the round's noise from what the mood favours; None the
        rest of the time (and for "rest")."""
        if tick % 90 < 72:
            return None
        table = FIDGETS.get(mood, FIDGETS["calm"])
        pick = _lcg(43, tick // 90)() * sum(w for _, w in table)
        for name, weight in table:
            pick -= weight
            if pick < 0:
                return None if name == "rest" else name
        return None

    def _mascot(self, cv, state, tick, top, kind, dy, mood="calm", scene=frozenset()):
        """Draw her; returns the head's column offset (the tilt), for what
        is drawn on her head afterwards."""
        x0 = self.x0
        idle = state == "idle"
        fidget = self._fidget(tick, mood) if idle else None
        game = idle and "game" in scene

        # pose
        if idle:
            pose = "neutral"
            if game or mood in ("shy", "worried"):
                pose = "type"
            elif mood in ("sad", "sleepy"):
                pose = "slump"
            elif mood == "curious":
                pose = "chin"
            elif mood == "excited" and dy:
                pose = "cheer2"
            if fidget == "wave" and not game:
                pose = "wave" if (tick // 3) % 2 else pose
            elif fidget == "petal" and not game:
                pose = "wave"
            elif fidget == "stretch" and not game:
                pose = "cheer2" if (tick // 6) % 2 else "cheer"
        elif state == "thinking":
            pose = "chin"
        elif state == "tool":
            pose = "neutral" if kind == "helpers" else "hold"
        elif state == "writing":
            pose = "hold"
        elif state == "done":
            pose = "air" if dy >= 2 else ("cheer2" if (tick // 4) % 2 else "cheer")
        else:
            pose = "slump"

        # head tilt: idle sways a column either way, slowly; music bobs it
        hx = 0
        if idle:
            if "music" in scene and mood not in ("sad", "sleepy"):
                hx = (0, 1)[(tick // 4) % 2]
            elif mood == "curious":
                hx = 1
            elif mood not in ("sad", "sleepy", "focused"):
                hx = (0, 0, 1, 1, 1, 0, 0, -1, -1, -1)[(tick // 5) % 10]
        elif state == "thinking":
            hx = 1

        droop = state == "error" or mood == "sad" and state not in ("done",)
        head = list(HEAD)
        if droop:
            head[0], head[1] = EARS_DROOP
        elif state in ("tool", "writing") and (tick // 12) % 2:
            # one ear flicks
            head[0] = "   /\\           |\\   "

        # body first (the head's row 6 bow sits over the neck)
        rows = BODY[pose]
        for i, r in enumerate(rows):
            cv.sprite(x0, top + 7 + i, r, OUTLINE)
        # walking feet / tap
        if state in ("tool", "writing") and (tick // 5) % 2:
            cv.put(x0 + 8, top + 10, "|   /", OUTLINE)
        # tail, behind her on the left
        tail = TAIL[(tick // 4) % len(TAIL)]
        if droop:
            tail = ("   ", " __-")
        cv.put(x0 + 1, top + 8, tail[0], HAIR)
        cv.put(x0 + 1, top + 9, tail[1], HAIR)
        if game:
            # a handheld between her hands, its screen blinking
            cv.put(x0 + 7, top + 8, "[", PROP)
            cv.put(x0 + 8, top + 8, "+", SPARKLE)
            cv.put(x0 + 9, top + 8, "#=#" if (tick // 4) % 2 else "=#=", PROP2)
            cv.put(x0 + 12, top + 8, "o", BLUSH)
            cv.put(x0 + 13, top + 8, "]", PROP)
        if fidget == "petal" and not game:
            cv.cell(x0 + 17, top + 6, "*", PETAL[1])

        for i, r in enumerate(head):
            cv.sprite(x0 + hx, top + i, r, OUTLINE)
        # hair colour: fringe, ears' insides, tails
        fringe_row = top + 2
        for c in range(7, 14):
            cv.cell(x0 + hx + c, fringe_row, "~", HAIR)
        for row, cols in ((0, (3, 4, 16, 17)), (6, (3, 4, 5, 6, 14, 15, 16, 17))):
            if droop and row == 0:
                continue
            for c in cols:
                ch = head[row][c]
                if ch != " ":
                    cv.cell(x0 + hx + c, top + row, ch, HAIR)
        if "cold" in scene:
            # a scarf for the bow
            cv.put(x0 + hx + 8, top + 6, "=~=~=", PIN)
        else:
            cv.put(x0 + hx + 9, top + 6, ">o<", PIN)
        # sakura hairpin over the right ear
        if not droop:
            pin = "*" if (tick // 7) % 6 else "+"
            cv.cell(x0 + hx + 15, top + 2, pin, PIN)
        if "music" in scene:
            # headphones
            for k in (3, 4):
                cv.cell(x0 + hx, top + k, "[", PROP)
                cv.cell(x0 + hx + 20, top + k, "]", PROP)

        # the face
        eye, mouth, blush = FACE[state]
        el = er = eye
        gaze = 0
        if state == "thinking":
            gaze = 1 if (tick // 15) % 3 else 0
        elif state in ("tool", "writing"):
            gaze = 1
        if state == "writing":
            mouth = "o-Ow-o~-"[(tick // 2) % 8]
        elif idle:
            mouth = "w" if (tick // 40) % 3 else "v"
        elif state == "done":
            mouth = "wvD"[(tick // 5) % 3]
        elif state == "tool" and kind in ("bash", "pad", "todo"):
            mouth = "-" if (tick // 10) % 2 else "o"
        if idle and mood in MOOD_FACE:
            el, er, mouth, blush = MOOD_FACE[mood]
            if mood == "happy":
                mouth = "wv"[(tick // 40) % 2]
            elif mood == "sleepy":
                if tick % 70 < 10:
                    mouth = "O"         # a yawn
                elif (tick // 25) % 5 == 0:
                    el = er = "o"       # awake, for a moment
        elif state in ("thinking", "tool", "writing"):
            if mood == "excited" and (tick // 8) % 3 == 0:
                el = er = "*"
            elif mood == "shy":
                blush = "/"
            elif mood == "sad":
                blush = ""
        if fidget == "look":
            gaze = (-1, 1)[(tick // 6) % 2]
        elif fidget == "petal":
            el = er = "^"
        elif fidget == "stretch":
            el, er, mouth = "-", "-", "O"
        if game:
            el, er = "o", "o"
        blink = self._blink(tick) and state not in ("done", "error") and el not in ("-", "^", ">")
        eye_col = EYE_COOL if state in ("tool", "writing") else EYE
        if el == "*":
            eye_col = SPARKLE
        if blink:
            el = er = "-"
        fx = x0 + hx
        shades = (idle and "sun" in scene and "day" in scene and not game
                  and mood in ("calm", "happy", "excited") and fidget != "stretch")
        if shades:
            cv.put(fx + 6, top + 3, "[=]---[=]", INK)
        else:
            cv.cell(fx + 7 + gaze, top + 3, el, OUTLINE if blink else eye_col)
            cv.cell(fx + 13 + gaze, top + 3, er, OUTLINE if blink else eye_col)
            # a glint in the eyes now and then
            if not blink and idle and el not in ("-", ".") and (tick // 3) % 11 == 0 \
                    or not blink and state == "done" and (tick // 3) % 11 == 0:
                cv.cell(fx + 8 + gaze, top + 3, "+", SPARKLE)
                cv.cell(fx + 14 + gaze, top + 3, "+", SPARKLE)
        cv.cell(fx + 10, top + 4, mouth, BLUSH)
        if blush == "/":
            for c in (6, 7, 8, 12, 13, 14):
                cv.cell(fx + c, top + 4, "/", BLUSH)
        elif blush:
            cv.cell(fx + 6, top + 4, blush, BLUSH)
            cv.cell(fx + 14, top + 4, blush, BLUSH)
        if mood in BROWS and state not in ("done", "error"):
            left, right = BROWS[mood]
            cv.cell(fx + 7, top + 2, left, OUTLINE)
            cv.cell(fx + 13, top + 2, right, OUTLINE)
        if state == "error":
            # tears, dripping
            t = tick % 12
            if t < 8:
                cv.cell(fx + 7, top + 4, ",'"[t // 4 % 2], RAIN)
                cv.cell(fx + 13, top + 4, "',"[t // 4 % 2], RAIN)
            cv.cell(fx + 6, top + 4, ";", RAIN)
        elif idle and mood == "sad" and tick % 40 < 12:
            cv.cell(fx + 7, top + 4, ",'"[(tick // 4) % 2], RAIN)
        if (mood == "worried" and state != "done") or "hot" in scene:
            # a drop of sweat by her cheek
            t = tick % 16
            if t < 10:
                cv.cell(fx + 18, top + 2 + (t >= 5), "'" if t < 5 else ",", RAIN)
        if state == "thinking":
            cv.cell(fx + 14, top + 6, "o", OUTLINE)   # the hand at her chin
        return hx

    def _mood_marks(self, cv, state, tick, top, hx, mood, scene):
        """What floats around her for her mood and scene: z's, a "?", "!"s,
        music notes, breath in the cold."""
        fx = self.x0 + hx
        idle = state == "idle"
        if idle and mood == "sleepy":
            t = tick % 36
            for j in range(3):
                if t // 9 > j:
                    cv.cell(fx + 20 + j, top + 2 - j, "zzZ"[j], INK if j < 2 else OUTLINE)
        elif idle and mood == "curious" and (tick // 5) % 4:
            cv.cell(fx + 18, max(0, top - 1), "?", SPARKLE)
        elif idle and mood == "excited" and (tick // 3) % 4 < 2:
            cv.cell(fx + 1, top, "!", SPARKLE)
            cv.cell(fx + 19, top, "!", SPARKLE)
        if "music" in scene and state != "error":
            for j in range(2):
                t = (tick + j * 12) % 24
                x = fx - 2 - t // 6 - j * 2
                y = top + 5 - t // 5
                if t < 20:
                    cv.cell(x, y, "db"[j], (SPARKLE, PIN)[j])
        if "cold" in scene and idle:
            t = tick % 40
            if t < 12:
                cv.cell(fx + 21 + t // 4, top + 4 - t // 6, ".oO"[min(2, t // 4)], SNOW)

    # -- things around her ---------------------------------------------------------

    def _thought(self, cv, tick, top):
        x = self.x0 + W + 1
        y = max(0, top - 1)
        cv.cell(x - 1, top + 3, ".", INK)
        cv.cell(x, top + 2, "o", INK)
        cv.sprite(x + 1, y, " .-~~~~~-. ", OUTLINE)
        cv.sprite(x + 1, y + 1, "(         )", OUTLINE)
        cv.sprite(x + 1, y + 2, " `-~~~~~-' ", OUTLINE)
        phase = (tick // 3) % 12
        if phase < 8:
            n = min(3, phase // 2)
            dots = " ".join(".oO"[:n]) if n else ""
            cv.put(x + 3, y + 1, dots.ljust(5), INK)
            spin = "-\\|/"[tick % 4]
            cv.cell(x + 9, y + 1, spin, SPARKLE)
        else:
            cv.put(x + 4, y + 1, "? !"[0:(phase - 8) + 1] if phase < 11 else "?!", SPARKLE)
            cv.cell(x + 9, y + 1, "*", SPARKLE)

    def _make_stream(self):
        r = _lcg(31)
        words = []
        for _ in range(400):
            words.append(STREAM_WORDS[int(r() * len(STREAM_WORDS))])
        width = 9
        text_lines, cur = [], ""
        for w in words:
            if len(cur) + len(w) + (1 if cur else 0) > width:
                text_lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w) if cur else w
        text_lines.append(cur)
        return [l.ljust(width) for l in text_lines]

    def _scroll(self, cv, tick, top):
        """A little scroll to her right, text streaming onto it a cell a tick,
        lines scrolling up as they fill; a quill bobbing at the cursor."""
        x = self.x0 + 18
        y = top + 5
        lines = self._stream
        width = 9
        total = tick % (len(lines) * width)
        line_i, col = divmod(total, width)
        cv.sprite(x, y, ".-----------.", OUTLINE)
        for k in range(3):
            li = line_i - 2 + k
            if li < 0:
                text = " " * width
            elif li < line_i:
                text = lines[li]
            else:
                text = lines[li][:col].ljust(width)
            cv.sprite(x, y + 1 + k, "|" + " " * 11 + "|", OUTLINE)
            cv.put(x + 2, y + 1 + k, text, PROP if k < 2 else PROP2)
        cv.sprite(x, y + 4, "'-----------'", OUTLINE)
        # the cursor, a quill nib half the time
        if (tick // 3) % 2:
            cv.cell(x + 2 + col, y + 3, "_", SPARKLE)
        else:
            cv.cell(x + 2 + col, y + 3, "/", PIN)

    def _prop(self, cv, kind, tick, top):
        x = self.x0 + 18
        y = top + 6
        getattr(self, "_prop_" + kind)(cv, tick, x, y)

    def _prop_bash(self, cv, tick, x, y):
        cmds = ("make", "ls", "git", "npm t", "pytest", "cargo")
        cyc = tick // 30
        cmd = cmds[cyc % len(cmds)]
        n = min(len(cmd), (tick % 30) // 2)
        cv.sprite(x + 1, y - 1, ".--------.", PROP)
        cv.sprite(x + 1, y, "|        |", PROP)
        cv.sprite(x + 1, y + 1, "|        |", PROP)
        cv.sprite(x + 1, y + 2, "'--------'", PROP)
        cv.put(x + 4, y + 3, "/__\\", PROP)
        prev = cmds[(cyc - 1) % len(cmds)]
        cv.put(x + 2, y, "$", STAR_DIM)
        cv.put(x + 4, y, prev[:6], STAR_DIM)
        cv.put(x + 2, y + 1, "$", SPARKLE)
        cv.put(x + 4, y + 1, cmd[:n][:5], PROP2)
        if (tick // 3) % 2:
            cv.cell(x + 4 + min(n, 5), y + 1, "_", SPARKLE)

    def _prop_book(self, cv, tick, x, y):
        flip = (tick // 4) % 10
        cv.sprite(x + 1, y - 1, " ____ ____ ", PROP)
        spine = "|" if flip < 8 else ("/" if flip == 8 else "\\")
        cv.sprite(x + 1, y, "|    " + spine + "    |", PROP)
        cv.sprite(x + 1, y + 1, "|    |    |", PROP)
        cv.sprite(x + 1, y + 2, "|____|____|", PROP)
        line = (tick // 6) % 4
        texts = (("~~~ ", "~~ ~"), ("~ ~~", "~~~ "), ("~~~ ", "~ ~~"), ("~~ ~", "~~~ "))
        for k in range(2):
            a, b = texts[(k + tick // 40) % 4]
            cv.put(x + 2, y + k, a, PROP2)
            cv.put(x + 7, y + k, b, PROP2)
        # reading marker
        rx = x + 2 + (line % 2) * 5
        cv.put(rx, y + (line // 2), "~~", SPARKLE)

    def _prop_pad(self, cv, tick, x, y):
        cv.sprite(x + 1, y - 1, ".--------.", PROP)
        for k in range(3):
            cv.sprite(x + 1, y + k, "|        |", PROP)
        cv.sprite(x + 1, y + 3, "'--------'", PROP)
        total = tick % 54
        row, col = divmod(total // 1, 18)
        col //= 3
        scr = ("~-~~-~", "~~-~-~", "-~~~-~")
        for k in range(3):
            if k < row:
                cv.put(x + 2, y + k, scr[k], PROP2)
            elif k == row:
                cv.put(x + 2, y + k, scr[k][:col], PROP2)
        px = x + 2 + col
        py = y + row
        bob = (tick // 2) % 2
        cv.put(px, py - 1 - bob, "/", SPARKLE)
        cv.put(px + 1, py - 2 - bob, "/", PIN)

    def _prop_lens(self, cv, tick, x, y):
        data = "a1 f~ :) b3 c7 *k"
        span = 7
        k = tick // 2 % (span * 2)
        off = k if k < span else span * 2 - k
        cv.put(x + 1, y + 3, data[:12], PROP2)
        lx = x + off
        cv.sprite(lx + 1, y, " .-. ", PROP)
        cv.sprite(lx + 1, y + 1, "(   )", PROP)
        cv.sprite(lx + 1, y + 2, " `-'\\", PROP)
        cv.put(lx + 6, y + 3, "\\", PROP)
        if off in (3, 4) and (tick // 2) % 2:
            cv.cell(lx + 3, y + 1, "!", SPARKLE)
        else:
            cv.cell(lx + 3, y + 1, "o", EYE_COOL)

    def _prop_globe(self, cv, tick, x, y):
        land = ("  __/~\\_   ~~  ", " /   _ \\__  /\\_", "  \\_/ \\__)  __ ", "    ~~  \\_/    ")
        off = (tick // 3) % len(land[0])
        cv.sprite(x + 2, y - 1, " .-\"\"-. ", PROP)
        cv.sprite(x + 2, y, "/      \\", PROP)
        cv.sprite(x + 2, y + 1, "|      |", PROP)
        cv.sprite(x + 2, y + 2, "\\      /", PROP)
        cv.sprite(x + 2, y + 3, " `-..-' ", PROP)
        for k in range(3):
            row = land[k] * 2
            seg = row[off:off + 6]
            cv.put(x + 3, y + k, seg, PROP2)
        # packets flying from the globe to her
        for j in range(3):
            px = x + 1 - ((tick + j * 3) % 9) // 3
            if (tick + j) % 3 == 0:
                continue
            cv.cell(px, y + 4, "<" if j == 0 else ".", SPARKLE)

    def _prop_todo(self, cv, tick, x, y):
        cv.sprite(x + 1, y - 1, ".--------.", PROP)
        for k in range(3):
            cv.sprite(x + 1, y + k, "|        |", PROP)
        cv.sprite(x + 1, y + 3, "'--------'", PROP)
        done = (tick // 12) % 5
        items = ("~~~~", "~~ ~", "~~~ ")
        for k in range(3):
            tick_ = k < done
            box = "[x]" if tick_ else "[ ]"
            if k == done and (tick // 3) % 2:
                box = "[>]"
            cv.put(x + 2, y + k, box, SPARKLE if tick_ else PROP)
            cv.put(x + 6, y + k, items[k], PROP2 if not tick_ else STAR_DIM)

    def _prop_wand(self, cv, tick, x, y):
        cv.cell(x - 1, y + 2, "_", PROP)
        cv.cell(x, y + 1, "/", PROP)
        star = ("*", "+", "*", "x")[(tick // 2) % 4]
        cv.cell(x + 1, y, star, SPARKLE)
        trail = ".+*+."
        for j in range(5):
            t = (tick + j * 4) % 20
            if t >= 5:
                continue
            r = _lcg(37, j, (tick + j * 4) // 20)
            sx = x + 2 + int(r() * 7)
            sy = y - 2 + int(r() * 5)
            cv.cell(sx, sy, trail[t], SPARKLE if j % 2 else PETAL[1])


# --- terminal demo / check -------------------------------------------------------
# The demo and the checker are mascots.py's, for every theme; run from here
# they default to this one (--check still covers every theme unless given
# --theme moe).

def main(argv):
    import mascots
    return mascots.main(argv, default_theme=THEME)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
