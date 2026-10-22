#!/usr/bin/env python3
"""One ASCII mascot per desktop theme, for llm-chat.py's stage.

    mascots.py [--theme T] [STATE [TOOL]]   play one state in this terminal
                                            (truecolour; Ctrl+C stops)
    mascots.py [--theme T] --cycle          every state and prop in turn
    mascots.py [--theme T] --frame STATE TOOL|- TICK [COLS ROWS]
                                            one frame as plain text
    mascots.py ... [--mood M] [--scene TAG,TAG] [--weather KIND]
                                            the same, in a mood and scene
                                            (mascot_mood.MOODS / SCENES;
                                            --weather rain is --scene rain,
                                            plus day or night by the clock);
                                            every theme's mascot draws them
    mascots.py --check [--theme T]... [--full]
                                            every theme (or those given):
                                            every state x prop at every size
                                            48..100 x 14..24 and every fourth
                                            width on to 160, exact widths,
                                            markup that parses and says the
                                            same text. Default: 30 ticks per
                                            size spread over 0..1199 plus 400
                                            straight ticks at twelve corner
                                            sizes (about half a minute a
                                            theme across all cores); --full:
                                            ticks 0..199 at every size, as
                                            moe's own check always did.
                                            A mascot that draws moods is
                                            also checked in every mood and
                                            scene (mascot_common.MOOD_COMBOS)
T is a theme name (default: the desktop's current theme, theme.py).

    Mascot(cols, rows, theme="moe")   the theme's mascot (moe for any theme
                                      without one of its own)
    mascot_for(theme)                 its class
    panel(theme)                      the background colour it is drawn on
                                      (the theme's llm-chat.css paints
                                      the same colour on #stage)

Every mascot has the API moe_mascot.Mascot has always had -- lines(state,
tick, tool), markup(state, tick, tool), bubble(state, tool) -- and draws on
mascot_common.Canvas, single-column characters only.

    moe        moe_mascot.py        the chibi cat-eared girl, sakura night
    matrix     mascot_matrix.py     a hooded hacker at a terminal, digital rain
    win95      mascot_win95.py      a paperclip assistant in a dialog box
    aero       mascot_aero.py       a glossy orb buddy over hills and aurora
    cyberpunk  mascot_cyberpunk.py  a neon android with a visor, scanlines
"""

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mascot_common import COMBOS, STATES, TOOLS, ansi, check_size  # noqa: E402

MODULES = {
    "moe": "moe_mascot",
    "matrix": "mascot_matrix",
    "win95": "mascot_win95",
    "aero": "mascot_aero",
    "cyberpunk": "mascot_cyberpunk",
}
THEMES = tuple(MODULES)
DEFAULT = "moe"


def module_for(theme):
    return importlib.import_module(MODULES.get(theme or DEFAULT, MODULES[DEFAULT]))


def mascot_for(theme):
    mod = module_for(theme)
    return mod.Mascot


def panel(theme):
    return getattr(module_for(theme), "PANEL", "#000000")


def Mascot(cols=64, rows=18, theme=DEFAULT):
    return mascot_for(theme)(cols, rows)


# --- CLI -----------------------------------------------------------------------

# Every width 48..100 (where most stages are), then every fourth up to 160
# (llm-chat's ART_MAX), every height 14..24.
COLS = list(range(48, 101)) + list(range(104, 157, 4)) + [160]
SIZES = [(c, r) for c in COLS for r in range(14, 25)]
CORNERS = [(c, r) for c in (48, 74, 100, 160) for r in (14, 19, 24)]


def _sample_ticks(cols, rows, n=30, span=1200):
    """n distinct ticks in 0..span-1, different for every size, the same on
    every run: together the sizes cover the whole span many times over."""
    from mascot_common import lcg
    r = lcg(97, cols, rows)
    out = set()
    while len(out) < n:
        out.add(int(r() * span))
    return sorted(out)


def check(themes, full=False):
    import multiprocessing
    import time
    jobs = []
    for theme in themes:
        if full:
            jobs += [(theme, c, r, range(200)) for c, r in SIZES]
        else:
            jobs += [(theme, c, r, _sample_ticks(c, r)) for c, r in SIZES]
            jobs += [(theme, c, r, range(400)) for c, r in CORNERS]
    t0 = time.monotonic()
    fails, n = [], 0
    with multiprocessing.Pool() as pool:
        for k, f in pool.imap_unordered(check_size, jobs, chunksize=4):
            n += k
            fails += f
    for theme in themes:
        m = Mascot(64, 18, theme=theme)
        for s in STATES:
            for t in TOOLS:
                if not m.bubble(s, t):
                    fails.append("%s: empty bubble %s/%s" % (theme, s, t))
    took = time.monotonic() - t0
    if fails:
        print("FAIL (%d frames checked)" % n)
        for f in fails[:30]:
            print("  " + f)
        return 1
    print("OK: %d frames, themes %s: %s, cols 48..100 + every 4th to 160 x rows 14..24, "
          "%d state/tool combos (%.0f s)"
          % (n, " ".join(themes),
             "ticks 0..199 at every size" if full else
             "30 sampled ticks per size + 400 ticks at %d corner sizes" % len(CORNERS),
             len(COMBOS), took))
    return 0


def _play(theme, seq, cols, rows, mood=None, scene=()):
    import time
    m = Mascot(cols, rows, theme=theme)
    bg = panel(theme)
    sys.stdout.write("\x1b[?25l\x1b[2J")
    try:
        tick = 0
        while True:
            state, tool = seq[(tick // 60) % len(seq)]
            frame = ansi(m.markup(state, tick, tool, mood, scene), bg)
            label = "%s: %s %s %s  %s" % (theme, state, tool or "", mood or "",
                                          m.bubble(state, tool, mood))
            sys.stdout.write("\x1b[H" + frame + "\n\x1b[K" + label + "\n")
            sys.stdout.flush()
            tick += 1
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\n")


def current_theme():
    try:
        import theme as desktop
        return desktop.current()
    except Exception:
        return DEFAULT


def main(argv, default_theme=None):
    argv = list(argv)
    themes, full = [], False
    while "--theme" in argv:
        i = argv.index("--theme")
        if i + 1 >= len(argv):
            print("--theme wants a name: " + " ".join(THEMES), file=sys.stderr)
            return 2
        themes.append(argv[i + 1])
        del argv[i:i + 2]
    if "--full" in argv:
        full = True
        argv.remove("--full")
    mood, scene = None, set()
    for flag in ("--mood", "--scene", "--weather"):
        while flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                print(f"{flag} wants a value", file=sys.stderr)
                return 2
            value = argv[i + 1]
            del argv[i:i + 2]
            if flag == "--mood":
                mood = value
            else:
                scene.update(t for t in value.split(",") if t)
                if flag == "--weather" and not scene & {"day", "night"}:
                    import time
                    scene.add("day" if 7 <= time.localtime().tm_hour < 19 else "night")
    from mascot_mood import MOODS, SCENES
    if mood is not None and mood not in MOODS:
        print("no mood %r (have: %s)" % (mood, " ".join(MOODS)), file=sys.stderr)
        return 2
    if scene - set(SCENES):
        print("no scene %s (have: %s)" % (", ".join(sorted(scene - set(SCENES))), " ".join(SCENES)),
              file=sys.stderr)
        return 2
    for t in themes:
        if t != "all" and t not in MODULES:
            print("no mascot for theme %r (have: %s)" % (t, " ".join(THEMES)), file=sys.stderr)
            return 2
    if argv and argv[0] == "--check":
        if not themes or "all" in themes:
            themes = list(THEMES)
        return check(themes, full)
    theme = themes[0] if themes and themes[0] != "all" else (default_theme or current_theme())
    if theme not in MODULES:
        theme = DEFAULT
    if argv and argv[0] == "--frame":
        state = argv[1] if len(argv) > 1 else "idle"
        tool = argv[2] if len(argv) > 2 and argv[2] != "-" else None
        tick = int(argv[3]) if len(argv) > 3 else 0
        cols = int(argv[4]) if len(argv) > 4 else 64
        rows = int(argv[5]) if len(argv) > 5 else 18
        m = Mascot(cols, rows, theme=theme)
        for l in m.lines(state, tick, tool, mood, scene):
            print("|" + l + "|")
        print(m.bubble(state, tool, mood))
        return 0
    import shutil
    ts = shutil.get_terminal_size((80, 24))
    cols = max(48, min(100, ts.columns))
    rows = max(14, min(24, ts.lines - 2))
    if argv and argv[0] == "--cycle":
        seq = [(s, None) for s in STATES if s != "tool"]
        seq[2:2] = [("tool", t) for t in TOOLS[:-1] if t != "Agent"]
    else:
        state = argv[0] if argv else "idle"
        tool = argv[1] if len(argv) > 1 else None
        seq = [(state, tool)]
    _play(theme, seq, cols, rows, mood, frozenset(scene))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
