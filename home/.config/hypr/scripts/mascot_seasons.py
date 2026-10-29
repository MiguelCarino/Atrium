#!/usr/bin/env python3
"""The seasons theme's mascot: Sorrel, a little fox kit sitting at the foot of
a small tree on a strip of ground, with an almanac strip along the bottom of
the stage. The tree, the ground and the sky turn with the real season (the
one theme.py shows: the date and your hemisphere, or a pin). Same API as
moe_mascot.Mascot (mascots.py picks it). Our own drawing: no fox from any
film, game or brand.

    the sky   painted as cell backgrounds, the season's floor (s-floor:
              spring #0c110e, summer #06110c, autumn #110b07, winter
              #070b11) at the top fading into the stage card (#101418 =
              PANEL, the stage in themes/seasons/llm-chat.css) at the
              ground; stars and the real moon's phase by night, a small
              sun by day in the sun scene, cloud bands when overcast
    the tree  13 cells wide, at the left of the stage (the left third when
              the stage is wide). Spring: a crown of blossom (* o .) in
              pinks, petals drifting down. Summer: a full deep-green crown,
              fireflies blinking by night. Autumn: an amber and rust crown,
              leaves falling (, ' ~) and piling at the root. Winter: bare
              branches (/ \\ Y) with snow on them and snow on the ground
    ground    one row of grass, leaves or snow under Sorrel and the tree
    strip     the bottom row, the almanac: the season in capitals with the
              day and month (AUTUMN - 24 OCT), the real moon's phase as one
              cell (. new, ) waxing, O full, ( waning), the state word
              (resting, musing, foraging, writing, found it, oops) and the
              real HH:MM at the right when there is room
    Sorrel    15 x 5 cells: pointed ears, a round face with two eyes and a
              cream muzzle, paws, a big tail curled at the side (it wags
              while writing). Thinking, a thought bubble of tiny leaves
              rises; writing, it scratches in a notebook with a twig;
              done, a hop and a sprout (v/); an error, a little rain cloud
              over its head and its ears flat; sleepy, curled into a ball
              with its tail over its nose, z's rising. In winter (and in
              the cold scene) it wears a scarf and its breath puffs
    props     to its right, small field-notes cards (a header row with the
              label in the season's hue2, the body under it): a notebook of
              "> cmd" lines for Bash, a pressed-leaf book with a highlight
              bar for Read, a page filling with words for Edit/Write, a
              magnifier over a leaf pile for Grep/Glob, a paper kite
              bringing a page for WebSearch/WebFetch, two sparrows carrying
              notes for Task/Agent, a seed-packet checklist for TodoWrite,
              fireflies and sparkles for anything else

  mood      one of mascot_mood.MOODS. Idle, it is the whole face: happy
              ^ ^ w, excited starry eyes and hops, shy > < with cheeks and
              eyes turned away, curious o O and a "?", focused and worried
              brows (worried sweats), sad dots, drooped ears and a tear,
              sleepy curled up asleep. At work only the accents show
              (brows, sweat, cheeks, a twinkle); sleepy works focused.
              calm (or None) is its usual face. Each 9-second idle round
              ends with a fidget picked by the noise and weighted by the
              mood: an ear flick, a tail swish, a sniff at a leaf, a
              pounce at a petal (a snowflake in winter), a yawn.
  scene     a set of mascot_mood.SCENES. The weather is real, so a scene
              beats the season: snow in July still snows. Rain is a shower
              in spring, a thunderstorm in summer (with flashes), a drizzle
              in autumn and sleet in winter; storm flashes in any season.
              fog draws mist bands, hot a heat shimmer and a sweat drop,
              cold frost and the scarf. music: notes drifting and a bob.
              game: a controller card. party: a party hat and confetti.
              festive: papel picado along the top. clock: the strip's time
              flashes the warn colour, with a (!) card.

The season: theme.season("seasons") (imported lazily; theme.py has no GTK),
which honours $HYPR_SEASON, the display.conf pin, the date and the
hemisphere; any failure means autumn. It is looked up again at most every
SEASON_RECHECK_S of time.monotonic(), so an open chat turns with the season.
Mascot.season_pin, when set, wins (the tests and the Integrate phase use it).

EMOTE_COLOURS (the reaction sign over its head) is UPDATED IN PLACE when the
season changes: mascots.emote_markup reads the module attribute at call
time. Measured on PANEL #101418 (WCAG 2.x), lowest of the four seasons:
accent 8.3 (autumn copper), warn 9.1 (summer's sun orange), bad (bad-fg)
7.1 (autumn), good 10.2 (autumn), love #ff9cc8 9.5, dim #a9b4bf 8.8 -- all
>= 4.5 in every season (tests/test_mascot_seasons.py measures them again).

Dark cells with a few small light ones (the eyes, blossoms, fireflies, the
moon, a card's few words). Every glyph is single-column.
"""

import datetime
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mascot_common import STATES, BaseMascot, Canvas, blink, lcg, prop_kind, stream_lines  # noqa: E402
from mascot_mood import MOODS, word  # noqa: E402

THEME = "seasons"
PANEL = "#101418"               # themes/seasons/llm-chat.css #stage
SEASONS = ("spring", "summer", "autumn", "winter")
DEFAULT_SEASON = "autumn"       # when theme.py cannot say
SEASON_RECHECK_S = 300          # look the season up again at most this often

# Each season's palette: the s-* names of themes/seasons/season/<s>/palette.css
# (spec section 2.1), plus the stage's own colours for the tree, the ground
# and the particles. All dark except the small accents.
PALETTES = {
    "spring": dict(
        floor="#0c110e", surface="#131b16", card="#141c17", raised="#1c2820", rule="#2c3d32",
        rule_hi="#46604f", text="#eee2e8", dim="#a9b8ad", readout="#f6edf1", ink="#1a0c12",
        accent="#f4a8d0", good="#7fd66a", warn="#f2c14e", bad="#ff6a45", bad_fg="#ff8a6e",
        hue1="#a8c8f0", hue2="#c5b3f2", hue3="#f2c4a0", epoch="#f1e8c8",
        crown_bg=("#3a1f30", "#4a2a3e"), crown_fg=("#f4a8d0", "#d887b0", "#f6c8de"),
        crown_glyphs="*o.*o", trunk="#5a4636", ground_bg="#14261a", ground_fg=("#3c6e40", "#5a8a4a"),
        flower="#f4a8d0", drift=("#f4a8d0", "#e8b8d0"), drift_glyphs=".*'"),
    "summer": dict(
        floor="#06110c", surface="#0b1a13", card="#0c1b14", raised="#12261c", rule="#21402f",
        rule_hi="#335c45", text="#e8efda", dim="#a2b8a2", readout="#f3f6ea", ink="#05140f",
        accent="#5ccfd6", good="#a3d65c", warn="#ff9f45", bad="#ff5c80", bad_fg="#ff86a0",
        hue1="#9fc2ff", hue2="#ecd27a", hue3="#d8d0f0", epoch="#f2dc90",
        crown_bg=("#0f2a18", "#143420"), crown_fg=("#3e8a4a", "#5aa05a", "#2e6e3a"),
        crown_glyphs="\"',%\"", trunk="#5a4630", ground_bg="#0e2416", ground_fg=("#3a7a3e", "#4e8e44"),
        flower="#ecd27a", drift=("#e6f08a", "#c8d860"), drift_glyphs=".*"),
    "autumn": dict(
        floor="#110b07", surface="#1b120c", card="#1c130d", raised="#281a11", rule="#45301f",
        rule_hi="#64462c", text="#f1e3d0", dim="#bba78f", readout="#f8efe3", ink="#1c0d04",
        accent="#ee9a62", good="#86d0a0", warn="#f0d85c", bad="#e9506e", bad_fg="#f47a90",
        hue1="#a9bfd8", hue2="#c9a2d8", hue3="#c8b8a0", epoch="#f0dfb8",
        crown_bg=("#3a1a0c", "#4a2410"), crown_fg=("#ee9a62", "#d0703a", "#e8b048", "#b8502a"),
        crown_glyphs="*,'*~", trunk="#4a3426", ground_bg="#22140c", ground_fg=("#a85a2a", "#c8782e", "#8a3e1e"),
        flower="#e8b048", drift=("#ee9a62", "#d0703a", "#e8b048"), drift_glyphs=",'~"),
    "winter": dict(
        floor="#070b11", surface="#0e141e", card="#0f1520", raised="#172030", rule="#2a384e",
        rule_hi="#415678", text="#e4ebf4", dim="#9caabd", readout="#f1f5fa", ink="#06111c",
        accent="#8ccaf2", good="#6fd8a2", warn="#f1c45c", bad="#f26a7c", bad_fg="#ff8a98",
        hue1="#c4ccd8", hue2="#b9a8f0", hue3="#e6cdb8", epoch="#eee6c8",
        crown_bg=None, crown_fg=None, crown_glyphs="", trunk="#5a5a66", ground_bg="#141c2a",
        ground_fg=("#b8c8dc", "#8a9ab4"), flower="#c4ccd8", drift=("#dce4f0", "#b8c8dc"), drift_glyphs="*."),
}
# Sorrel, the same in every season
FUR = "#b8582a"                 # the coat: a deep fox orange
FUR_DIM = "#8a4426"             # sad / error / asleep
OUTLINE = "#e09a62"             # the outline glyphs over the dark stage
MUZZLE = "#e8d8c0"              # the cream muzzle and the tail's tip (small)
INK = "#1a0c06"                 # eyes and nose on the fur
CHEEK = "#f08a8a"
SCARF = "#5a3a8a"               # winter's scarf: the lilac hue, darkened
SCARF_FG = "#b9a8f0"
SWEAT = "#9fd0ff"
STAR = "#c9d3e0"
STAR_DIM = "#5a6b86"
MOON = "#e8e4d0"
SUN = "#ffe08a"
FLASH = "#e8edf5"
RAIN = "#8ab4e0"
SNOW = "#e4ecf6"
FOG = "#4a5666"
CLOUD = "#5a6878"
NOTEBOOK = "#d8ccb4"
CONFETTI = ("#f08a8a", "#ffe08a", "#7fd66a", "#8ab4e0", "#c5b3f2")
PICADO = ("#ff6fae", "#ffa94d", "#7fd46f", "#6fb6ff", "#c58bff", "#ffd84d")
OVERCAST = frozenset(("cloud", "rain", "storm", "snow", "fog"))

# -- Sorrel's drawing (15 x 5) ------------------------------------------------------
SW, SH = 15, 5
SORREL = [
    " /\\     /\\     ",       # ears
    "/   ---   \\    ",       # the top of the head (brows go at cols 3 and 7)
    "|         |    ",       # eyes (drawn on their own: they move with the gaze)
    " \\  .v.  /     ",       # muzzle
    "  (_)---(_)    ",       # paws
]
EARS_FLAT = " _\\     /_     "
EARS_FLICK = " /\\     |\\     "     # the right ear turned
TAIL = (                        # (row, col, text) per frame: curled up, swished
    ((2, 12, " _ "), (3, 11, "( )"), (4, 11, "-'")),
    ((2, 11, "_  "), (3, 10, " (\\ "), (4, 11, "-' ")),
)
CURLED = [                      # asleep: a ball, the tail over the nose
    "               ",
    "               ",
    "  .-'''''-.    ",
    " (  -  - ~~)   ",
    "  '-.___.-'    ",
]
EYES = (3, 7)                   # row 2
SNOUT = (3, 5)                  # (row, col)
HEAD_FILL = ((1, 1, 10), (2, 1, 10), (3, 2, 9))      # (row, from col, to col): fur cells
for _r in SORREL + CURLED + [EARS_FLAT, EARS_FLICK]:
    assert len(_r) == SW, _r

# -- the tree (13 wide) --------------------------------------------------------------
TW = 13
CROWN = [                       # # = a crown cell
    "    #####    ",
    "  #########  ",
    " ########### ",
    "#############",
    " ########### ",
    "   #######   ",
]
BRANCHES = [                    # winter: bare limbs
    "  \\  \\ / /Y  ",
    " Y \\  \\|/ /  ",
    "  \\ \\ Y|/ /  ",
    "   \\ \\ |/    ",
    "    \\ \\|/    ",
    "      ||     ",
]
TRUNK = ("     |:|     ", "     |:|     ", "     |:|     ", "   _/   \\_   ")
for _r in CROWN + BRANCHES + list(TRUNK):
    assert len(_r) == TW, _r
TREE_H = len(CROWN) + len(TRUNK)

CARD_W = 16
COMP_W = TW + 1 + SW + 2 + CARD_W          # 47: tree, Sorrel, a card
WORDS = ("the", "path", "bends", "here", "a", "leaf", "on", "wind", "and", "we",
         "follow", "tracks", "by", "the", "brook", "soft", "moss", "noted", "seed", "sun")
CMDS = ("ls", "dig", "sniff", "grep", "make", "tree")
TODO = ("Sow", "Water", "Wait")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

# Per mood, idle: (left eye, right eye, snout, cheeks). calm: the usual face.
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
BROWS = {"focused": ("\\", "/"), "worried": ("/", "\\"), "sad": ("/", "\\")}
# The idle fidget a mood favours: (name, weight); "rest" is none at all.
FIDGETS = {
    "calm": (("ear", 2), ("swish", 2), ("sniff", 2), ("pounce", 1), ("rest", 2)),
    "happy": (("pounce", 3), ("swish", 2), ("ear", 1)),
    "excited": (("pounce", 3), ("swish", 2), ("ear", 2)),
    "shy": (("ear", 2), ("rest", 3)),
    "curious": (("sniff", 3), ("ear", 2)),
    "focused": (("ear", 2), ("rest", 3)),
    "worried": (("ear", 2), ("swish", 1), ("rest", 2)),
    "sad": (("rest", 1),),
    "sleepy": (("yawn", 3), ("rest", 2)),
}

MOOD_BUBBLES = {
    "happy": "Bright day in the woods! Where to next?",
    "excited": "Ooh, a new trail? Let's go, let's go!",
    "shy": "Oh! I didn't hear you on the path… hi ☺",
    "curious": "Fresh tracks! Let's see where they lead.",
    "focused": "Nose down. I'm following the trail.",
    "worried": "Hmm, the wind just changed…",
    "sad": "A grey sort of day. I'll sit by the roots a while.",
    "sleepy": "Curled up in the leaves… zz",
}
# mascot_mood topics in its words: a gentle young naturalist with a pocket
# almanac (str.format with the topic's arguments; a tuple holds variants,
# said in turn).
TOPIC_LINES = {
    "thanks": "Aw, thank you. That's going in my field notes.",
    "worried": "Hmm, the tracks look odd here. Want to double-check?",
    "frustrated": "Still tangled? Let's back up a few steps and try the other path.",
    "relieved": "Phew, there it is! Sunlight through the branches.",
    "determined": "Long trail ahead. I'll keep pace with you.",
    "proud": "We made it to the top! Look at that view.",
    "sad": "It's okay. Even the trees rest in winter.",
    "happy": "Hooray! My tail won't stop wagging.",
    "curious": "Ooh, a question. Let me check my almanac.",
    "rain": "Rain on the leaves. Good weather for staying in the den.",
    "storm": "Thunder! Let's tuck in and save our work.",
    "snow": "Snow! Everything's gone quiet and soft ❄",
    "fog": "Fog in the hollow. Let's go slowly and stay on the path.",
    "sun": "Sun on my fur. Perfect for a stretch ☀",
    "hot": "{0} out there. Find some shade, okay?",
    "cold": "{0}! Tuck your paws in.",
    "gpu_hot": "GPU at {0}°C. It's getting warm under the fur!",
    "cpu_hot": "CPU at {0}°C! Let it catch its breath?",
    "music": "Is that a song? My ears are dancing ♪",
    "game": "Play time! The almanac can wait.",
    "event": "Heads up: {0} in {1} min.",
    "event_now": "{0} is starting now. Off you go!",
    "birthday": "Happy birthday, {0}! I found you a pinecone.",
    "holiday": "{0} today. A good day for a long walk!",
    "go_home": "{0} already. The sun's going down, time to head home.",
    "bedtime": "{0}. Even the owls are yawning. Bed?",
    "morning": "Morning! Dew on everything. What's first?",
    "lunch": "Lunch? I'd share my berries.",
    "weekend": "Weekend! The trails are all yours.",
    "friday": "Friday afternoon. Almost time to wander.",
    "hello": ("Sorrel here! What are we exploring today?",
              "Hi! I kept the path clear for you.",
              "Oh, you're back. Pull up a log and tell me."),
    "welcome_back": "Welcome back! I saved your spot by the roots.",
    "wake": ("Huh? Oh! I was just resting my eyes.",
             "Mm… up, up. Leaves out of my ears!"),
    "long_prompt": ("That's a long trail of words! Reading…",
                    "Big bundle! Let me unpack it."),
    "code": ("Code! Let me sniff it over.",
             "Tracks in the source. Following them."),
    "image": ("A picture! Let me have a look.",
              "Ooh, an image. Pinning it in my notes."),
    "aborted": ("Stopping! Back to the den.",
                "Okay, okay, I'll put it down."),
    "tests_pass": ("All green, like new leaves ✓",
                   "Tests pass! Bright and clear."),
    "tests_fail": ("A few weeds in the garden. Let's pull them.",
                   "Tests failed. We'll find the burr."),
    "commit": ("Planted! It'll grow from here.",
               "Committed. Another ring in the tree ✓"),
    "fast": ("Quick as a hare!",
             "In and out, like a squirrel."),
    "busy": ("So many trails at once…",
             "Busy, busy, like a beaver."),
    "model": ("A new guide on the trail: {0}.",
              "{0} is leading now. Hello!"),
    "poke": ("Hey! That tickles.",
             "Boop! Right on the nose.",
             "Yes? I'm listening, ears up.",
             "Careful, I was napping on that leaf!",
             "Sorrel here. What's up?",
             "Eep! You found me."),
    "poke_spam": ("Okay, okay! I'm awake!",
                  "My tail's in a knot!",
                  "Too many boops! Hiding in the leaves!"),
    "pet": ("Mmm… warm as a summer stone.",
            "That's the good spot behind the ears ☺",
            "Purr… wait, foxes don't purr. Still nice.",
            "Best friend in the whole forest."),
    # railguard.py's notifications (mascot_notify.py says them, voice on)
    "rg_memory": "{0} was hoarding all the memory, like acorns. I chased it off.",
    "rg_vram": "{0} filled the GPU's den. Shooed it out.",
    "rg_game_vram": "{0} is using almost all the GPU memory. Lower the textures?",
    "rg_panic": "Got it! {0} has scampered off.",
    "rg_stuck": "Memory's running thin and I can't find the tracks...",
    "rg_agents": "Every agent job is stopped. The sessions are safe in the burrow.",
}
# A few topics in each season's own words; the rest come from TOPIC_LINES.
SEASON_LINES = {
    "spring": {
        "hello": "Hi! The cherry trees are out. What shall we grow today?",
        "morning": "Morning! The birds started before us.",
        "weekend": "Weekend! The meadow's full of flowers.",
        "rain": "A spring shower. Everything smells green.",
        "snow": "Snow in spring? The blossoms are shivering ❄",
        "sun": "Warm sun on new leaves ☀",
        "hot": "{0} already? Spring's in a hurry.",
        "cold": "{0}. A late frost, mind the buds.",
        "pet": "Mmm… soft as new moss ☺",
    },
    "summer": {
        "hello": "Hey! Long bright days. What's the plan?",
        "morning": "Morning! Let's get going before the heat.",
        "weekend": "Weekend! Go find a lake and some shade.",
        "rain": "Thunder rumbling. Let's sit this one out.",
        "snow": "Snow in summer?! Quick, look ❄",
        "sun": "Big summer sun. Water and shade ☀",
        "hot": "{0}! Paws in the stream, okay?",
        "cold": "{0}? A cool summer night, nice.",
        "pet": "Mmm… like lying in warm grass ☺",
    },
    "autumn": {
        "hello": "Hi! Crunchy leaves everywhere. Let's get cosy and work.",
        "morning": "Morning! Mist in the hollow and apples in the grass.",
        "weekend": "Weekend! Perfect for a walk through the leaves.",
        "rain": "A soft drizzle. The leaves are glowing.",
        "snow": "First snow on the leaves ❄",
        "sun": "Golden sun through the branches ☀",
        "hot": "{0} in autumn? The trees are confused.",
        "cold": "{0}. Sweater weather!",
        "pet": "Mmm… like a nest of dry leaves ☺",
    },
    "winter": {
        "hello": "Brr, hi! I saved you a warm spot by the fire.",
        "morning": "Morning! Frost on every branch.",
        "weekend": "Weekend! Cocoa and a blanket?",
        "rain": "Sleet. Not quite rain, not quite snow.",
        "snow": "Fresh snow! Want to make tracks? ❄",
        "sun": "Low winter sun. It sparkles on the snow ☀",
        "hot": "{0} in winter? Strange days.",
        "cold": "{0}! Scarf on, paws tucked.",
        "pet": "Mmm… warmer already ☺",
    },
}


def _contrast_colours(p):
    """A season's reaction-sign colours (mascot_mood.EMOTE_TONES)."""
    return {"accent": p["accent"], "warn": p["warn"], "bad": p["bad_fg"],
            "good": p["good"], "love": "#ff9cc8", "dim": "#a9b4bf"}


# The reaction sign over its head, UPDATED IN PLACE when the season changes
# (mascots.emote_markup reads this attribute at call time).
EMOTE_COLOURS = _contrast_colours(PALETTES[DEFAULT_SEASON])
_EMOTE_SEASON = [DEFAULT_SEASON]


def set_emote_season(season):
    """Point EMOTE_COLOURS at a season's colours (in place, same dict)."""
    if season in PALETTES and _EMOTE_SEASON[0] != season:
        EMOTE_COLOURS.update(_contrast_colours(PALETTES[season]))
        _EMOTE_SEASON[0] = season


def current_season():
    """The season theme.py says seasons shows now ($HYPR_SEASON, the pin,
    the date and hemisphere); DEFAULT_SEASON on any failure."""
    try:
        import theme
        s = theme.season(THEME)
    except Exception:
        return DEFAULT_SEASON
    return s if s in SEASONS else DEFAULT_SEASON


MOON_EPOCH = datetime.datetime(2000, 1, 6, 18, 14)     # a new moon (UTC)
SYNODIC = 29.530588853                                  # days, new moon to new moon


def moon_glyph(when=None):
    """The moon's phase as one cell: "." new, ")" waxing, "O" full, "("
    waning (as seen from the north; the strip is a hint, not an ephemeris).
    Age in days since a known new moon, modulo the synodic month."""
    when = when or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    age = ((when - MOON_EPOCH).total_seconds() / 86400.0) % SYNODIC
    if age < 1.85 or age >= SYNODIC - 1.85:
        return "."
    if age < SYNODIC / 2 - 1.85:
        return ")"
    if age < SYNODIC / 2 + 1.85:
        return "O"
    return "("


def almanac_date(season, today=None):
    """The strip's date: AUTUMN - 24 OCT (single-column only: no middle dot,
    which is East Asian ambiguous and would become "?")."""
    today = today or datetime.date.today()
    return "%s - %d %s" % (season.upper(), today.day, MONTHS[today.month - 1])


def _mix(a, b, f):
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * f)) for x, y in zip(pa, pb))


STATUS = {"idle": "resting", "thinking": "musing", "tool": "foraging",
          "writing": "writing", "done": "found it", "error": "oops"}


class Mascot(BaseMascot):
    BUBBLES = {
        "idle": "Sorrel here, under the old tree. What shall we look into?",
        "thinking": "Hmm, let me think it through…",
        "writing": "Writing it down in my field notes…",
        "done": "Found it! All written down ✓",
        "error": "Oops, a tangle in the brambles. Try again?",
    }
    TOOL_BUBBLES = {
        "Bash": "Scribbling commands in my notebook…",
        "Read": "Leafing through the pages…",
        "Edit": "Writing the changes in…",
        "MultiEdit": "Writing the changes in…",
        "Write": "Writing the changes in…",
        "NotebookEdit": "Writing the changes in…",
        "Grep": "Sniffing through the leaf pile…",
        "Glob": "Sniffing through the leaf pile…",
        "WebSearch": "Flying my kite out for news…",
        "WebFetch": "The kite's bringing a page back…",
        "Task": "Sending the sparrows with notes…",
        "Agent": "Sending the sparrows with notes…",
        "TodoWrite": "Sorting my seed packets…",
    }
    OTHER = "Trying out %s…"
    moods = True

    def __init__(self, cols=64, rows=18):
        self.cols = max(int(cols), COMP_W + 1)
        self.rows = max(int(rows), TREE_H + 4)
        self.season_pin = None
        self.season = None
        self._season_at = None
        self.ground = self.rows - 2            # the ground row (the strip is under it)
        cx = (self.cols - COMP_W) // 2
        # The tree at the left of the group; on a wide stage it moves out to
        # the left third, so it reads as the scene's tree, not a prop.
        self.tx = cx if self.cols < 90 else max(1, self.cols // 3 - TW - 4)
        self.sx = max(self.tx + TW + 1, cx + TW + 1)   # Sorrel
        self.px = self.sx + SW + 2                     # the cards
        self._stream = stream_lines(WORDS, 12, seed=59)
        self._stars = []
        for i in range(self.cols * self.rows // 30):
            r = lcg(227, i)
            self._stars.append((int(r() * self.cols), int(r() * max(2, self.ground - 3)),
                                20 + int(r() * 30), int(r() * 50)))
        # which crown cells get a glyph, and which one (fixed per stage)
        self._crown = {}
        for y, row in enumerate(CROWN):
            for x, c in enumerate(row):
                if c == "#":
                    self._crown[(x, y)] = lcg(229, x, y)()
        self._ground = [lcg(233, x)() for x in range(self.cols)]

    # -- public --------------------------------------------------------------------
    def lines(self, state, tick, tool=None, mood=None, scene=()):
        return self._render(state, tick, tool, mood, scene).lines()

    def markup(self, state, tick, tool=None, mood=None, scene=()):
        return self._render(state, tick, tool, mood, scene).markup()

    def say(self, topic):
        s = self._season()
        table = SEASON_LINES.get(s, {})
        if topic and topic[0] in table:
            return word(table, topic)
        return word(TOPIC_LINES, topic)

    def bubble(self, state, tool=None, mood=None):
        if state == "idle" and mood in MOOD_BUBBLES:
            return MOOD_BUBBLES[mood]
        return BaseMascot.bubble(self, state, tool)

    def _season(self):
        """The season to draw: the pin, else theme.py's (looked up at most
        every SEASON_RECHECK_S). Keeps EMOTE_COLOURS in step."""
        if self.season_pin in SEASONS:
            s = self.season_pin
        else:
            now = time.monotonic()
            if self.season is None or self._season_at is None or now - self._season_at >= SEASON_RECHECK_S:
                self._season_at = now
                self.season = current_season()
            s = self.season
        set_emote_season(s)
        return s

    # -- composition ---------------------------------------------------------------
    def _render(self, state, tick, tool, mood=None, scene=()):
        if state not in STATES:
            state = "idle"
        if mood not in MOODS:
            mood = "calm"
        if mood == "sleepy" and state in ("thinking", "tool", "writing"):
            mood = "focused"            # no napping on the job
        scene = frozenset(scene or ())
        tick = int(tick)
        season = self._season()
        p = PALETTES[season]
        cv = Canvas(self.cols, self.rows)
        kind = prop_kind(tool) if state == "tool" else None
        if state == "tool" and tool in ("WebSearch", "WebFetch"):
            kind = "kite"
        idle = state == "idle"
        fidget = self._fidget(tick, mood) if idle else None
        asleep = idle and mood == "sleepy"
        cold = season == "winter" or "cold" in scene
        self._sky(cv, p, state, tick, scene)
        if "festive" in scene:
            self._banner(cv, tick)
        self._tree(cv, p, season, tick, scene)
        self._ground_row(cv, p, season, tick, scene)
        self._weather(cv, p, season, tick, scene)
        if "party" in scene:
            self._confetti(cv, tick)
        self._strip(cv, p, season, state, tick, scene)
        if state == "done":
            hop = (0, 1, 2, 2, 1, 0, 0, 0)[tick % 8]
        elif idle and mood == "excited" and (tick // 30) % 2:
            hop = (0, 1, 2, 1, 0, 0)[tick % 6]
        elif fidget == "pounce":
            hop = (0, 1, 2, 1, 0, 0)[min(5, (tick % 90 - 72) // 2)]
        elif "music" in scene and not asleep:
            hop = (tick // 4) % 2
        else:
            hop = 0
        top = self.ground - SH - hop
        ox = self.sx
        # the reaction sign's anchor: just over the right ear
        self.head = (min(ox + 10, self.cols - 3), max(0, top - 1))
        if kind == "helpers":
            self._sparrows(cv, p, tick)
        self._sorrel(cv, p, state, tick, ox, top, mood, scene, fidget, asleep, cold)
        self._marks(cv, p, state, tick, ox, top, mood, scene, fidget, asleep, cold)
        if "party" in scene and not asleep:
            self._hat(cv, tick, ox, top)
        px, py = self.px, self.ground - 8
        if state == "thinking":
            self._musing(cv, p, tick, px, py)
        elif state == "writing":
            self._notebook(cv, p, tick, ox, top)
            self._doc(cv, p, tick, px, py, stream=True, title="FIELD NOTES")
        elif state == "done":
            self._found(cv, p, tick, px, py, ox)
        elif state == "error":
            self._oops(cv, p, tick, px, py)
        elif kind and kind != "helpers":
            getattr(self, "_prop_" + kind)(cv, p, tick, px, py)
        elif "game" in scene:
            self._controller(cv, p, tick, px, py)
        return cv

    def _fidget(self, tick, mood):
        """The idle fidget now: one per 90-tick round, in its last 18 ticks,
        picked by the round's noise from what the mood favours."""
        if tick % 90 < 72:
            return None
        table = FIDGETS.get(mood, FIDGETS["calm"])
        pick = lcg(239, tick // 90)() * sum(w for _, w in table)
        for name, weight in table:
            pick -= weight
            if pick < 0:
                return None if name == "rest" else name
        return None

    # -- the stage -----------------------------------------------------------------
    def _sky(self, cv, p, state, tick, scene):
        """The season's floor at the top fading to the card at the ground;
        stars and the moon by night, a sun by day, cloud bands overcast."""
        overcast = bool(scene & OVERCAST)
        night = "night" in scene
        span = max(1, self.ground)
        for y in range(self.rows):
            bg = _mix(p["floor"], PANEL, min(1.0, y / float(span)))
            for x in range(self.cols):
                cv.recolour(x, y, bg=bg)
        y0 = 2 if "festive" in scene else 0
        sun = not night and not overcast and state != "error" and "sun" in scene
        if night or not overcast:
            for x, y, period, ph in self._stars:
                if overcast and (x + y) % 3:
                    continue
                if not night and (x * 7 + y) % 3:
                    continue        # dusk: a few only
                if y < y0 or (sun and x >= self.cols - 8 and y < y0 + 4):
                    continue
                t = (tick + ph) % period
                cv.cell(x, y, ".+*+."[t] if t < 5 else ".", STAR if t < 5 else STAR_DIM)
        if night and not overcast:
            mx = self.cols - 4
            cv.cell(mx, y0 + 1, moon_glyph(), MOON)
        if sun:
            x = self.cols - 7
            rays = ("\\ | /", "  |  ", "\\   /")[(tick // 8) % 3]
            cv.put(x, y0, rays, SUN)
            cv.put(x, y0 + 1, "-(O)-", SUN)
            cv.put(x, y0 + 2, "/ | \\" if rays[0] == "\\" else "  |  ", SUN)
        if overcast:
            heavy = bool(scene & {"rain", "storm"})
            for i in range(max(2, self.cols // 16)):
                r = lcg(241, i, self.cols)
                w = 5 + int(r() * 7)
                y = y0 + int(r() * 3)
                x = int(r() * self.cols + tick * (0.05 + r() * 0.04)) % (self.cols + w) - w
                for c in range(w):
                    if cv.get(x + c, y) == " ":
                        cv.cell(x + c, y, "~" if (c + i) % 3 else "-", FOG if heavy else CLOUD)

    def _tree(self, cv, p, season, tick, scene):
        x0 = self.tx
        base = self.ground - 1                  # the trunk's root row
        ty = base - TREE_H + 1                  # the crown's top row
        for i, row in enumerate(TRUNK):
            y = ty + len(CROWN) + i
            for c, ch in enumerate(row):
                if ch != " ":
                    cv.cell(x0 + c, y, ch, p["trunk"], "#1e140e" if ch == ":" else None)
        if season == "winter":
            for i, row in enumerate(BRANCHES):
                for c, ch in enumerate(row):
                    if ch != " ":
                        cv.cell(x0 + c, ty + i, ch, p["trunk"])
                        # snow resting on the limb: the cell above, if free
                        if i > 0 and BRANCHES[i - 1][c] == " " and (c + i) % 2 == 0:
                            cv.cell(x0 + c, ty + i - 1, ".", SNOW)
            return
        sway = 1 if (tick // 24) % 2 and "storm" in scene else 0
        for (c, r), noise in self._crown.items():
            x, y = x0 + c + (sway if r < 2 else 0), ty + r
            bg = p["crown_bg"][int(noise * 7) % 2]
            glyphs = p["crown_glyphs"]
            if noise < 0.55:
                g = glyphs[int(noise * 97) % len(glyphs)]
                fg = p["crown_fg"][int(noise * 31) % len(p["crown_fg"])]
                # a few twinkle in spring and autumn, as the light moves
                if season in ("spring", "autumn") and (tick // 6 + c * 3 + r) % 23 == 0:
                    g = "*"
                cv.cell(x, y, g, fg, bg)
            else:
                cv.cell(x, y, " ", None, bg)

    def _ground_row(self, cv, p, season, tick, scene):
        y = self.ground
        snow = season == "winter" or "snow" in scene
        for x in range(self.cols):
            n = self._ground[x]
            bg = "#1a2230" if snow else p["ground_bg"]
            if snow:
                ch, fg = ("_" if n < 0.5 else "~" if n < 0.8 else "."), p["ground_fg"][0] if season == "winter" else SNOW
            else:
                ch = (",", "'", "\"", ".")[int(n * 4)]
                fg = p["ground_fg"][int(n * 13) % len(p["ground_fg"])]
                if season == "spring" and n > 0.86:
                    ch, fg = "*", p["flower"]
                elif season == "summer" and n > 0.92:
                    ch, fg = "*", p["flower"]
            cv.cell(x, y, ch, fg, bg)
        if season == "autumn" and "snow" not in scene:
            # the leaf pile at the root, a cell wider either side of the trunk
            for c in range(TW):
                x = self.tx + c
                if 2 <= c <= 10:
                    n = self._ground[x % self.cols]
                    cv.cell(x, y - 1 if c in (4, 8) else y, ",'~"[int(n * 3)],
                            p["ground_fg"][(c + int(n * 5)) % len(p["ground_fg"])],
                            None if c in (4, 8) else p["ground_bg"])

    def _weather(self, cv, p, season, tick, scene):
        """The season's drift (petals, fireflies by night, falling leaves,
        snow) unless the real weather overrides it; then the weather."""
        night = "night" in scene
        top = 2 if "festive" in scene else 0
        span = max(2, self.ground - top)
        precip = None
        if "snow" in scene:
            precip = "snow"
        elif "storm" in scene:
            precip = "storm"
        elif "rain" in scene:
            precip = {"spring": "shower", "summer": "storm", "autumn": "drizzle", "winter": "sleet"}[season]
        if precip is None:
            if season == "summer" and not night:
                pass                    # fireflies only after dark
            else:
                n = {"spring": 6, "summer": 7, "autumn": 7, "winter": 10}[season]
                for i in range(max(3, self.cols * n // 64)):
                    r = lcg(251, i)
                    if season == "summer":
                        # fireflies: drifting low, each blinking on its own beat
                        x = int(r() * self.cols + math.sin(tick / 9.0 + i) * 2) % self.cols
                        y = self.ground - 1 - int(r() * min(6, span - 1))
                        period = 14 + int(r() * 12)
                        if (tick + int(r() * period)) % period < period // 2 and cv.get(x, y) == " ":
                            cv.cell(x, y, "*" if (tick + i) % 5 == 0 else ".", p["drift"][i % 2])
                        continue
                    pos = r() * span + tick * (0.08 + r() * 0.06)
                    fall = int(pos // span)
                    y = top + int(pos - fall * span)
                    x = int(lcg(253, i, fall)() * self.cols + math.sin(tick / 7.0 + i) * 1.5) % self.cols
                    if y < self.ground and cv.get(x, y) == " ":
                        g = p["drift_glyphs"][(i + fall) % len(p["drift_glyphs"])]
                        cv.cell(x, y, g, p["drift"][(i + fall) % len(p["drift"])])
        else:
            dense = {"snow": 10, "storm": 16, "shower": 7, "drizzle": 6, "sleet": 10}[precip]
            for i in range(max(4, self.cols * dense // 64)):
                r = lcg(257, i)
                speed = 0.12 if precip == "snow" else (0.5 if precip == "storm" else 0.35)
                pos = r() * span + tick * (speed + r() * 0.1)
                fall = int(pos // span)
                y = top + int(pos - fall * span)
                drift = (tick // 3) if precip == "storm" else 0
                x = int(lcg(259, i, fall)() * self.cols + drift * 0.3) % self.cols
                if y >= self.ground or cv.get(x, y) != " ":
                    continue
                if precip == "snow":
                    cv.cell(x, y, "*." [i % 2], SNOW)
                elif precip == "storm":
                    cv.cell(x, y, "/", RAIN)
                elif precip == "shower":
                    cv.cell(x, y, "'", p["hue1"])
                elif precip == "drizzle":
                    cv.cell(x, y, ".", p["hue1"])
                else:                    # sleet: rain and wet flakes
                    cv.cell(x, y, ",*"[i % 2], RAIN if i % 2 == 0 else SNOW)
            if precip == "storm" or "storm" in scene:
                cyc, t = divmod(tick, 37)
                if t < 3:
                    x = int(lcg(263, cyc)() * (self.cols - 4)) + 2
                    for k, ch in enumerate("\\/\\"):
                        cv.cell(x + (k % 2), top + 1 + k, ch, FLASH)
        if "fog" in scene:
            for k in range(2):
                off = (tick // (7 + k * 3) + k * 5) % 10
                y = self.ground - 2 - k * 3
                for x in range(self.cols):
                    if (x + off) % 10 < 5 and cv.get(x, y) == " ":
                        cv.cell(x, y, "~", FOG)
        if "cold" in scene:
            # frost along the ground's edge
            for x in range(0, self.cols, 5):
                cv.cell(x + (tick // 20) % 2, self.ground, "*", SNOW, None)

    def _strip(self, cv, p, season, state, tick, scene):
        """The almanac: SEASON - D MON, the moon, the state word, HH:MM."""
        y = self.rows - 1
        cv.fill(0, y, self.cols, 1, p["raised"], occupy=False)
        cv.recolour(0, y, bg=p["accent"])
        date = " " + almanac_date(season) + " "
        cv.put(1, y, date, p["hue2"], bg=p["rule"])
        x = 1 + len(date) + 1
        cv.cell(x, y, moon_glyph(), MOON, p["raised"])
        x += 2
        colour = {"done": p["good"], "error": p["bad_fg"]}.get(state, p["dim"] if state == "idle" else p["accent"])
        cv.put(x, y, STATUS.get(state, "resting"), colour, bg=p["raised"])
        clock = time.strftime(" %H:%M ")
        ring = "clock" in scene and (tick // 5) % 2
        cx = self.cols - len(clock)
        if cx > x + 10:
            cv.put(cx, y, clock, p["ink"] if ring else p["text"], bg=p["warn"] if ring else p["rule"])
            if "music" in scene:
                cv.cell(cx - 2, y, "d", p["accent"], p["raised"])
        if "clock" in scene and (tick // 10) % 3:
            text = " (!) REMINDER "
            bx = max(0, self.cols - len(text) - 1)
            cv.put(bx, y - 2, text, p["ink"], bg=p["warn"])
            cv.cell(self.cols - 4, y - 1, "V", p["warn"])

    def _banner(self, cv, tick):
        """Papel picado: a cord along the top row, cut-paper flags under it."""
        for x in range(self.cols):
            cv.cell(x, 0, "-", "#a9b4bf")
            k = x % 4
            if k < 3:
                flutter = (tick // 4 + x // 4) % 2
                cv.cell(x, 1, ("o.o", ".o.")[flutter][k], PANEL, PICADO[(x // 4) % len(PICADO)])

    def _confetti(self, cv, tick):
        span = self.rows + 2
        for i in range(max(4, self.cols * self.rows // 90)):
            r = lcg(269, i)
            pos = r() * span + tick * (0.10 + r() * 0.08)
            fall = int(pos // span)
            y = int(pos - fall * span) - 1
            x = int(lcg(271, i, fall)() * self.cols) + (tick // 4 + i) % 2
            if y < self.rows - 1 and cv.get(x, y) == " ":
                cv.cell(x, y, ",'.*"[(tick // 3 + i) % 4], CONFETTI[i % len(CONFETTI)])

    # -- Sorrel --------------------------------------------------------------------
    def _sorrel(self, cv, p, state, tick, x0, top, mood, scene, fidget, asleep, cold):
        idle = state == "idle"
        tired = state == "error" or (idle and mood == "sad")
        fur = FUR_DIM if (tired or asleep) else FUR
        t = tick % 90 - 72
        if asleep:
            for i, row in enumerate(CURLED):
                cv.sprite(x0, top + i, row, OUTLINE)
            for x in range(x0 + 3, x0 + 10):
                cv.recolour(x, top + 3, bg=fur)
            for x in (x0 + 8, x0 + 9):
                cv.recolour(x, top + 3, MUZZLE, fur)     # the tail's pale tip over the nose
            for x in (x0 + 5, x0 + 8):
                if cv.get(x, top + 3) == "-":
                    cv.recolour(x, top + 3, INK, fur)
            if cold:
                cv.put(x0 + 3, top + 4, "~~~", SCARF_FG, bg=SCARF)
            return
        rows = list(SORREL)
        if state == "error" or (idle and mood == "sad"):
            rows[0] = EARS_FLAT
        elif fidget == "ear" and (t // 3) % 2:
            rows[0] = EARS_FLICK
        for i, row in enumerate(rows):
            cv.sprite(x0, top + i, row, OUTLINE)
        for r, a, b in HEAD_FILL:
            for x in range(x0 + a, x0 + b):
                cv.recolour(x, top + r, bg=fur)
        for x in range(x0 + 4, x0 + 7):
            cv.recolour(x, top + 3, INK, MUZZLE)         # the muzzle
        # the tail: curled up; it wags while writing, swishes in the fidget
        frame = 0
        if state == "writing" or (state == "done" and tick % 4 < 2):
            frame = (tick // 2) % 2
        elif fidget == "swish":
            frame = (t // 3) % 2
        for r, c, text in TAIL[frame]:
            cv.sprite(x0 + c, top + r, text, OUTLINE)
        for r, c, text in TAIL[frame]:
            for k, ch in enumerate(text):
                if ch == "(":
                    cv.recolour(x0 + c + k + 1, top + r, bg=fur)
                    cv.cell(x0 + c + k + 1, top + r, " ", None, MUZZLE if r == 3 else fur)
        # the face
        eye = "^" if state == "done" else "o"
        gaze = 1 if state in ("tool", "writing") else 0
        if state == "thinking":
            gaze = (0, 1, 0, -1)[(tick // 10) % 4]
        snout = {"done": "D", "error": "~", "thinking": "o"}.get(state, "v")
        if state == "writing":
            snout = "vov-"[(tick // 2) % 4]
        left = right = eye
        cheek = "~" if state in ("done", "idle") else ""
        if idle and mood in MOOD_FACE:
            left, right, snout, cheek = MOOD_FACE[mood]
            if mood == "shy":
                gaze = -1
            elif mood == "curious":
                gaze = 1
            elif mood == "worried":
                gaze = (0, -1, 0, 1)[(tick // 8) % 4]
        elif mood == "shy" and state != "error":
            cheek = "/"
        elif mood in ("happy", "excited") and state != "error":
            cheek = "~"
            if mood == "excited" and state != "done" and tick % 20 < 3:
                left = right = "*"
        if state == "error":
            left = right = "x"
        if fidget == "yawn":
            left = right = "-"
            snout = "O" if 3 <= t < 14 else "o"
        elif fidget == "sniff":
            snout = "o" if (t // 2) % 2 else "v"
        shut = blink(tick, 47) and state not in ("done", "error")
        for ex, ch in zip(EYES, (left, right)):
            cv.cell(x0 + ex + gaze, top + 2, "-" if shut else ch, INK, fur)
        cv.cell(x0 + SNOUT[1], top + SNOUT[0], snout, INK, MUZZLE)
        if mood in BROWS and state != "done":
            for ex, ch in zip(EYES, BROWS[mood]):
                cv.cell(x0 + ex + gaze, top + 1, ch, OUTLINE, fur)
        if cheek:
            cv.cell(x0 + 2, top + 3, cheek, CHEEK, fur)
            cv.cell(x0 + 8, top + 3, cheek, CHEEK, fur)
        if cold:
            # the scarf: across the paws' row, its end hanging by the left paw
            cv.put(x0 + 5, top + 4, "~~~", SCARF_FG, bg=SCARF)
            cv.cell(x0 + 1, top + 4, "{", SCARF_FG, None)

    def _marks(self, cv, p, state, tick, ox, top, mood, scene, fidget, asleep, cold):
        """What floats around Sorrel: z's, a "?", "!"s, the thought leaves,
        the rain cloud, breath puffs, sweat, notes, heat shimmer, the sniffed
        leaf and the pounced petal."""
        idle = state == "idle"
        t = tick % 90 - 72
        if asleep:
            s = tick % 36
            for j in range(3):
                if s // 9 > j:
                    cv.cell(ox + 11 + j, top + 1 - j, "zzZ"[j], p["dim"] if j < 2 else p["text"])
        elif idle and mood == "curious" and (tick // 5) % 4:
            cv.cell(ox + 11, top, "?", p["accent"])
        elif idle and mood == "excited" and (tick // 3) % 4 < 2:
            cv.cell(ox, top, "!", p["warn"])
            cv.cell(ox + 11, top, "!", p["warn"])
        elif mood == "excited" and state in ("thinking", "tool", "writing", "done"):
            if (tick // 3) % 4 == 0:
                cv.cell(ox + 11, top, "+", SUN)
        if state == "thinking":
            # a thought bubble of tiny leaves rising off the head
            leaf = PALETTES["summer"]["crown_fg"][1] if self.season_is("winter") else p["drift"][0]
            for j in range(3):
                s = (tick // 3 + j * 3) % 9
                if s < 7:
                    cv.cell(ox + 10 + j + s // 3, top - 1 - s // 2, ".o,'"[(j + s) % 4],
                            leaf if j else p["hue2"])
        if state == "error":
            cv.put(ox + 2, top - 3, ".--.", CLOUD)
            cv.put(ox + 1, top - 2, "(____)", CLOUD)
            for k in range(3):
                if (tick // 2 + k) % 3 == 0:
                    cv.cell(ox + 2 + k * 2, top - 1, "'", RAIN)
        if cold and not asleep and state != "error":
            # breath puffs drifting up and left from the muzzle
            s = tick % 24
            if s < 12:
                cv.cell(ox + 3 - s // 4, top + 2 - s // 4, ".o"[s // 6 % 2], p["dim"])
        if state == "error" or ((mood == "worried" or "hot" in scene) and state != "done" and not asleep):
            s = (tick // 5) % 4
            if s < 3:
                cv.cell(ox + 11, top + 1 + s, "',."[s], SWEAT)
        if idle and mood == "sad":
            s = (tick // 6) % 3
            if s < 2:
                cv.cell(ox + EYES[0], top + 3 + s, ",'"[s], SWEAT, FUR_DIM if s == 0 else None)
        if fidget == "sniff":
            cv.cell(ox - 1, top + 4, ",", p["drift"][0])
        if fidget == "pounce" and t < 12:
            g = "*" if self.season_is("winter") else "."
            cv.cell(ox + 6, top - 2 + t // 6, g, p["drift"][0])
        if "music" in scene:
            for j in range(2):
                s = (tick + j * 12) % 24
                if s < 20:
                    cv.cell(ox - 1 - s // 6 - j * 2, top + 4 - s // 5, "db"[j], (p["accent"], p["hue2"])[j])
        if "hot" in scene:
            for k in range(3):
                if lcg(277, k, tick // 3)() < 0.6:
                    x = ox + 2 + k * 4 + (tick // 3) % 2
                    if cv.get(x, self.ground - 1) == " ":
                        cv.cell(x, self.ground - 1, "~", p["warn"])

    def season_is(self, s):
        return (self.season_pin or self.season) == s

    def _hat(self, cv, tick, ox, top):
        x = ox + 5
        cv.cell(x, top - 3, "*+"[(tick // 4) % 2], SUN)
        cv.put(x - 1, top - 2, "/:\\", CONFETTI[0])
        cv.put(x - 2, top - 1, "/_:_\\", CONFETTI[3])
        cv.cell(x, top - 2, ":", SUN)
        cv.cell(x, top - 1, ":", SUN)

    # -- things beside it ------------------------------------------------------------
    def _card(self, cv, p, x, y, w, h, title, status=None, status_colour=None, body=None):
        """A field-notes card: a header row (the label in the season's hue2,
        a tab in the accent at the left, a status at the right), the body."""
        body = body or p["raised"]
        cv.fill(x, y, w, h, body)
        cv.fill(x, y, w, 1, p["rule"])
        cv.recolour(x, y, bg=p["accent"])
        cv.put(x + 2, y, title[:w - 3], p["hue2"], bg=p["rule"])
        if status and len(title) + len(status) + 4 <= w:
            cv.put(x + w - len(status) - 1, y, status, status_colour or p["good"], bg=p["rule"])

    def _musing(self, cv, p, tick, x, y):
        """Thinking: the almanac open, a weathervane turning, dots."""
        self._card(cv, p, x, y + 1, CARD_W, 5, "ALMANAC")
        cv.put(x + 2, y + 3, "-\\|/"[(tick // 3) % 4], p["accent"], bg=p["raised"])
        cv.put(x + 4, y + 3, "wind & leaf", p["dim"], bg=p["raised"])
        cv.put(x + 2, y + 4, ("hmm" + "." * ((tick // 4) % 4)).ljust(12), p["text"], bg=p["raised"])

    def _doc(self, cv, p, tick, x, y, stream=False, title="READ", status=None):
        self._card(cv, p, x, y, CARD_W, 7, title, status, p["accent"])
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
            cv.put(x + 2, y + 1 + k, text, p["text"] if k == 4 else p["dim"], bg=p["raised"])
        if stream and (tick // 3) % 2:
            cv.cell(x + 2 + min(col, 11), y + 5, "_", p["accent"], p["raised"])

    def _notebook(self, cv, p, tick, ox, top):
        """Writing: a little notebook at the left paw, a twig scratching."""
        x, y = ox - 4, top + 3
        cv.put(x, y + 1, "[==]", INK, bg=NOTEBOOK)
        cv.cell(x + 1 + (tick // 2) % 2, y, "/", p["trunk"])

    def _found(self, cv, p, tick, x, y, ox):
        self._card(cv, p, x, y + 1, CARD_W, 5, "FOUND IT")
        cv.put(x + 1, y + 3, "v/", p["good"], bg=p["raised"])
        cv.put(x + 4, y + 3, "all written", p["text"], bg=p["raised"])
        cv.put(x + 4, y + 4, "down", p["dim"], bg=p["raised"])
        # the sprout at Sorrel's feet
        cv.put(ox - 3, self.ground - 1, "v/", p["good"])
        r = lcg(281, tick // 3)
        for _ in range(4):
            sx, sy = x + int(r() * CARD_W), y + int(r() * 7)
            if cv.get(sx, sy) == " ":
                cv.cell(sx, sy, "+*."[int(r() * 3)], STAR)

    def _oops(self, cv, p, tick, x, y):
        on = (tick // 4) % 2
        cv.fill(x, y + 1, CARD_W, 5, p["raised"])
        cv.fill(x, y + 1, CARD_W, 1, p["warn"] if on else p["rule"])
        cv.put(x + 1, y + 1, "OOPS", p["ink"] if on else p["warn"], bg=p["warn"] if on else p["rule"])
        cv.put(x + 1, y + 3, "(x)", p["bad_fg"], bg=p["raised"])
        cv.put(x + 5, y + 3, "brambles", p["bad_fg"], bg=p["raised"])
        cv.put(x + 5, y + 4, "try again?", p["dim"], bg=p["raised"])

    def _controller(self, cv, p, tick, x, y):
        self._card(cv, p, x, y + 1, CARD_W, 6, "PLAY")
        cv.put(x + 3, y + 3, ".-----.", p["dim"], bg=p["raised"])
        cv.put(x + 2, y + 4, "( +  oo )", p["dim"], bg=p["raised"])
        cv.put(x + 3, y + 5, "'-' '-'", p["dim"], bg=p["raised"])
        cv.cell(x + 4, y + 4, "+", p["text"], p["raised"])
        cv.cell(x + 7, y + 4, "o", p["good"], p["raised"])
        cv.cell(x + 8, y + 4, "o", (p["accent"], p["bad_fg"], p["good"], p["warn"])[(tick // 3) % 4], p["raised"])

    def _sparkles(self, cv, p, tick, x, y, n=5):
        for j in range(n):
            r = lcg(283, j)
            period = 24 + int(r() * 16)
            t = (tick + int(r() * period)) % period
            sx = x + int(r() * 12)
            sy = y - int(r() * 5)
            if t < period * 2 // 3 and cv.get(sx, sy) == " ":
                cv.cell(sx, sy, "*+."[(t // 4 + j) % 3], (p["drift"][0], STAR, p["accent"])[j % 3])

    def _prop_bash(self, cv, p, tick, x, y):
        self._card(cv, p, x, y, CARD_W, 7, "NOTEBOOK", "RUN", p["accent"], body=p["floor"])
        cyc = tick // 30
        cmd = CMDS[cyc % len(CMDS)]
        n = min(len(cmd), (tick % 30) // 2)
        for k in range(3):
            prev = CMDS[(cyc - 3 + k) % len(CMDS)]
            cv.put(x + 1, y + 1 + k, ("> " + prev)[:14], p["dim"], bg=p["floor"])
        cv.put(x + 1, y + 5, ("> " + cmd[:n])[:14], p["text"], bg=p["floor"])
        if (tick // 3) % 2:
            cv.cell(x + 3 + n, y + 5, "_", p["accent"], p["floor"])

    def _prop_book(self, cv, p, tick, x, y):
        """Read: a pressed-leaf book, a highlight bar moving down it."""
        self._doc(cv, p, tick, x, y, title="LEAF BOOK")
        hot = (tick // 3) % 5
        for c in range(14):
            cv.recolour(x + 1 + c, y + 1 + hot, p["text"], p["rule_hi"])
        cv.cell(x + CARD_W - 2, y + 1, "&", p["crown_fg"][0] if p["crown_fg"] else p["hue2"], p["raised"])

    def _prop_pad(self, cv, p, tick, x, y):
        self._doc(cv, p, tick, x, y, stream=True, title="FIELD NOTES")

    def _prop_lens(self, cv, p, tick, x, y):
        """Grep/Glob: a magnifier sweeping over a leaf pile, one leaf found."""
        self._card(cv, p, x, y, CARD_W, 7, "LEAF PILE", "SNIFF", p["accent"])
        for r in range(4):
            for c in range(14):
                n = lcg(287, r, c)()
                if n < 0.55:
                    cv.cell(x + 1 + c, y + 2 + r, ",'~"[int(n * 5) % 3],
                            p["drift"][int(n * 11) % len(p["drift"])], p["raised"])
        lx = x + 1 + (tick // 2) % 12
        ly = y + 2 + (tick // 8) % 3
        cv.put(lx, ly, "(o)", p["text"], bg=p["rule_hi"])
        cv.cell(lx + 3, ly + 1, "\\", p["dim"], p["raised"])

    def _prop_kite(self, cv, p, tick, x, y):
        """WebSearch/WebFetch: a paper kite on a string bringing a page."""
        self._card(cv, p, x, y + 2, CARD_W, 5, "KITE POST", "AIR", p["accent"])
        kx = x + 9 + (1 if math.sin(tick / 5.0) > 0 else 0)
        ky = max(0, y - 2)
        cv.put(kx, ky, "/\\", p["accent"])
        cv.put(kx, ky + 1, "\\/", p["accent"])
        for k in range(2):          # the string, down to just over the card
            cv.cell(kx - 1 - k, ky + 2 + k, "\\" if (tick // 3 + k) % 2 else ".", p["dim"])
        cv.put(x + 2, y + 4, "page.html", p["text"], bg=p["raised"])
        pct = (tick * 2) % 101
        bw = 12
        filled = int(pct / 100.0 * bw)
        for c in range(bw):
            cv.cell(x + 2 + c, y + 5, "=" if c < filled else "-", p["accent"] if c < filled else p["rule_hi"], p["raised"])

    def _sparrows(self, cv, p, tick):
        """Task/Agent: two sparrows either side, each carrying a note, and a
        MESSENGERS card."""
        # one over Sorrel's head, one past the card (clear of the tree)
        for n, x in enumerate((self.sx + 4, min(self.cols - 3, self.px + CARD_W + 1))):
            y = self.ground - 9 - (1 if math.sin(tick / 4.0 + n * 2) > 0 else 0)
            wing = "v" if (tick // 2 + n) % 2 else "^"
            cv.put(x, y, wing + "o" + wing, p["dim"])
            cv.cell(x + 1, y, "o", p["hue3"])
            cv.put(x, y + 1, "[=]", INK, bg=NOTEBOOK)
        px, py = self.px, self.ground - 8
        self._card(cv, p, px, py, CARD_W, 5, "MESSENGERS", None)
        k = (tick // 8) % 3
        cv.put(px + 1, py + 2, ("flying" + "." * k).ljust(11), p["text"], bg=p["raised"])
        cv.put(px + 1, py + 3, "2 sparrows", p["dim"], bg=p["raised"])

    def _prop_todo(self, cv, p, tick, x, y):
        self._card(cv, p, x, y, CARD_W, 5, "SEED PACKETS")
        done = 1 + (tick // 12) % len(TODO)
        for k, item in enumerate(TODO):
            mark = "[x]" if k < done else "[ ]"
            cv.put(x + 1, y + 1 + k, mark, p["good"] if k < done else p["dim"], bg=p["raised"])
            cv.put(x + 5, y + 1 + k, item, p["dim"] if k < done else p["text"], bg=p["raised"])

    def _prop_wand(self, cv, p, tick, x, y):
        """Anything else: fireflies circling, sparkles."""
        for j in range(4):
            a = tick / 6.0 + j * 1.57
            fx, fy = x + 6 + int(round(math.cos(a) * 5)), y + 4 + int(round(math.sin(a) * 2))
            if cv.get(fx, fy) == " ":
                cv.cell(fx, fy, "*" if j == (tick // 4) % 4 else ".", "#e6f08a")
        self._sparkles(cv, p, tick, x + 2, y + 6, n=5)
