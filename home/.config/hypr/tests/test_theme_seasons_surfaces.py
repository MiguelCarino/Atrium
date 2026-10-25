"""The seasons theme's other surfaces (~/.config/themes/seasons: launcher,
wofi, llm-chat, mako, gtk4, mpv, kitty, prompt), checked as files: the
contracts that keep one stylesheet right in all four seasons. theme.py's own
season mechanism has its tests in test_theme_seasons.py; `theme.py check
seasons` parses the GTK3 stylesheets with GTK.

Why these and not pixels: the base files are shared by the four seasons, so
a season's hex written into one of them would be wrong three quarters of the
year; the season files carry only colours, so a size can never move between
seasons; and gtk4.css and palette.css hold the same values in two syntaxes
(GTK4 custom properties, GTK3 @define-color), which must not drift apart.
Read-only: nothing here writes outside the scratch folder."""
import os
import re
import subprocess
import unittest

import helpers  # noqa: F401  (scratch XDG dirs before anything else)

THEME = os.path.join(os.path.expanduser("~"), ".config", "themes", "seasons")
SEASONS = ("spring", "summer", "autumn", "winter")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
# The one fixed colour of the shared stylesheets: the chat stage, a neutral
# night equal to mascot_seasons.PANEL in every season (llm-chat.css says why).
FIXED = {"#101418"}


def read(*parts):
    with open(os.path.join(THEME, *parts)) as handle:
        return handle.read()


def strip_comments(text, style):
    if style == "css":
        return re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", "--")))


def palette(season):
    """{name: #hex} from the season's palette.css (the GTK3 names, s- dropped)."""
    return {m[1]: m[2].lower() for m in
            re.finditer(r"@define-color\s+s-([\w-]+)\s+(#[0-9a-fA-F]{6})", read("season", season, "palette.css"))}


def accent(season):
    return re.search(r"^accent=(#[0-9a-fA-F]{6})", read("season", season, "theme.conf"), re.M)[1].lower()


@unittest.skipUnless(os.path.isdir(os.path.join(THEME, "season")), "the seasons theme is not installed")
class SharedFiles(unittest.TestCase):
    def test_no_season_hex_in_the_shared_files(self):
        """Every colour in the shared files is a name (@s-*, @cyan, var(--s-*)):
        a hex there would be one season's, wrong in the other three."""
        for name, style in (("launcher.css", "css"), ("wofi.css", "css"), ("llm-chat.css", "css"),
                            ("gtk4.css", "css"), ("mako", "conf"), ("kitty.conf", "conf"),
                            ("mpv.conf", "conf"), ("prompt.sh", "conf")):
            with self.subTest(name):
                code = strip_comments(read(name), style)
                found = {h.lower() for h in HEX.findall(code)} - FIXED
                if name == "mpv.conf":
                    found -= {"#000000"}            # the letterbox, black in every theme
                self.assertEqual(found, set(), f"{name} writes a colour literal")

    def test_gtk4_names_are_defined_in_every_season(self):
        used = set(re.findall(r"var\(--(s-[\w-]+)\)", read("gtk4.css")))
        self.assertIn("s-accent", used)
        for season in SEASONS:
            with self.subTest(season):
                defined = set(re.findall(r"--(s-[\w-]+)\s*:", read("season", season, "gtk4.css")))
                self.assertEqual(used - defined, set())

    def test_gtk4_values_match_palette_css(self):
        """The same 22 values in both syntaxes, plus the season's accent."""
        for season in SEASONS:
            with self.subTest(season):
                gtk4 = {m[1]: m[2].lower() for m in
                        re.finditer(r"--s-([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})", read("season", season, "gtk4.css"))}
                want = dict(palette(season), accent=accent(season))
                self.assertEqual(gtk4, want)


@unittest.skipUnless(os.path.isdir(os.path.join(THEME, "season")), "the seasons theme is not installed")
class SeasonFiles(unittest.TestCase):
    MAKO_KEYS = {"background-color", "text-color", "border-color", "progress-color"}

    def test_mako_season_files_hold_colours_only(self):
        """No size, face or format in a season's mako: the notification is the
        same size all year."""
        for season in SEASONS:
            with self.subTest(season):
                section = ""
                for line in strip_comments(read("season", season, "mako"), "conf").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("["):
                        section = line
                        self.assertIn(section, ("[urgency=critical]", "[urgency=low]"))
                        continue
                    key, value = line.split("=", 1)
                    self.assertIn(key, self.MAKO_KEYS, line)
                    self.assertRegex(value, r"^(over )?#[0-9A-F]{6}([0-9A-F]{2})?$", line)

    def test_mako_colours_are_the_palette(self):
        for season in SEASONS:
            with self.subTest(season):
                pal = palette(season)
                text = read("season", season, "mako")
                self.assertIn(f"background-color={pal['card'].upper()}F2", text)
                self.assertIn("\n[urgency=critical]", text)
                critical = text.split("\n[urgency=critical]", 1)[1].split("\n[", 1)[0]
                self.assertIn(f"border-color={pal['bad'].upper()}", critical)

    def test_kitty_and_mpv_carry_the_season_accent(self):
        for season in SEASONS:
            with self.subTest(season):
                pal, acc = palette(season), accent(season)
                kitty = read("season", season, "kitty.conf")
                self.assertIn(f"active_tab_background {acc}", kitty)
                self.assertIn(f"active_tab_foreground {pal['ink']}", kitty)
                mpv = read("season", season, "mpv.conf")
                colours = dict(kv.split("=") for kv in
                               re.search(r"uosc-color=(\S+)", mpv)[1].split(","))
                self.assertEqual(colours["foreground"], acc[1:])
                self.assertEqual(colours["foreground_text"], pal["ink"][1:])
                self.assertEqual(colours["background"], pal["surface"][1:])
                self.assertEqual(colours["error"], pal["bad"][1:])
                # mpv's own colour options are quoted: # starts a comment there.
                for key in ("osd-color", "osd-border-color", "sub-color", "sub-border-color"):
                    self.assertRegex(mpv, rf'(?m)^{key}="#[0-9A-F]{{6}}"$')


@unittest.skipUnless(os.path.isdir(os.path.join(THEME, "season")), "the seasons theme is not installed")
class Prompt(unittest.TestCase):
    """prompt.sh then a season's prompt.sh, as theme.py writes them, run in a
    bare bash (no rc files, no Fedora prompt script): the hook's variables."""

    def run_prompt(self, season, last_status=0):
        script = (f"source {os.path.join(THEME, 'prompt.sh')}\n"
                  f"source {os.path.join(THEME, 'season', season, 'prompt.sh')}\n"
                  f"cd {helpers.SCRATCH}\n"
                  f"(exit {last_status}); __seasons_prompt\n"
                  'printf "%s\\0" "$__seasons_mark" "$__seasons_end" "$__seasons_mood" '
                  '"$PROMPT_DIR_COLOR" "$__seasons_glyph" "$__seasons_hue" "$PROMPT_COMMAND"\n')
        out = subprocess.run(["bash", "--norc", "--noprofile", "-c", script], capture_output=True,
                             text=True, timeout=10, env=dict(os.environ, LC_ALL="C.UTF-8", GIT_DIR="/nonexistent"))
        self.assertEqual(out.returncode, 0, out.stderr)
        keys = ("mark", "end", "mood", "dir", "glyph", "hue", "command")
        return dict(zip(keys, out.stdout.split("\0")))

    def test_each_season_has_its_own_single_width_mark(self):
        glyphs = set()
        for season in SEASONS:
            with self.subTest(season):
                got = self.run_prompt(season)
                self.assertEqual(len(got["glyph"]), 1)
                self.assertNotIn("️", got["mark"])       # never an emoji presentation
                self.assertIn(got["glyph"], got["mark"])
                self.assertRegex(got["hue"], r"^3[0-7]$")      # an ANSI index: the palette carries the season
                self.assertEqual(got["dir"], f"1;{got['hue']}")
                self.assertIn("›", got["end"])
                self.assertEqual(got["mood"], "")
                self.assertTrue(got["command"].startswith("__seasons_prompt"))
                glyphs.add(got["glyph"])
        self.assertEqual(len(glyphs), 4)

    def test_mark_carries_the_date(self):
        got = self.run_prompt("autumn")
        self.assertRegex(got["mark"], r" \d{1,2} [A-Z][a-z]{2}")

    def test_failure_shows_its_status(self):
        got = self.run_prompt("winter", last_status=3)
        self.assertIn("exit 3", got["mood"])
        self.assertIn("\x1b[0;31m", got["mood"])

    def test_hook_is_added_once(self):
        script = (f"source {os.path.join(THEME, 'prompt.sh')}; source {os.path.join(THEME, 'prompt.sh')}; "
                  'printf "%s" "$PROMPT_COMMAND"')
        out = subprocess.run(["bash", "--norc", "--noprofile", "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(out.stdout.count("__seasons_prompt"), 1)


if __name__ == "__main__":
    unittest.main()
