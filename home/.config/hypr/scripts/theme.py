#!/usr/bin/env python3
"""Desktop themes: one switch for the bar, its toolbox, the popup panels, the
launcher (and quick note, clipboard), wofi, mako, the Hyprland look, the
wallpaper set, the wallpaper accent, and libadwaita apps (Nautilus).

    theme.py list              the themes, the current one starred
    theme.py current           the current theme's name
    theme.py set <name>        switch: remember it, apply it, change the
                               wallpaper set, set the theme's animation preset;
                               if gtk.css changed, restart Files (Nautilus)
                               when it has no window, else watch for its last
                               window to close (toast: "Restart Files now")
    theme.py apply             re-apply the current theme (after editing one of
                               its files -- the generated copies are not live)
    theme.py ensure            only create generated files that are missing;
                               no other side effect (waybar.service ExecStartPre)
    theme.py check [<name>]    lint a theme: keys, colours, every stylesheet
                               parsed by GTK against the base it overrides,
                               the wallpaper set, hypr.lua (loads, rule
                               names unique across themes)
    theme.py get <key> [<name>]   one resolved theme.conf value (with your
                               own overrides, below, over it)
    theme.py fonts             only the text: rewrite the generated files and
                               the terminals for the current theme with your
                               font overrides, reload mako, signal kitty; no
                               accent, wallpaper or Hyprland look (what
                               font-settings.py runs after a font change;
                               `apply` does all of this too)
    theme.py cursor            only the pointer: the resolved cursor theme
                               and size to gsettings and hyprctl setcursor
    theme.py fade [on|off]     the cross-fade over a switch (theme-fade.py)
    theme.py apps              Qt, Firefox and Chrome in the theme's colours
                               (see "other apps" below; the accent script
                               runs this part on every accent it writes)
    theme.py glass [<0-100>|default|fix]
                               the current theme's window glass (below):
                               no argument prints it as JSON with the theme's
                               default and the worst-case contrast; a number
                               keeps that for this theme (glass_<theme> in
                               display.conf) and re-applies the terminals;
                               fix = the most glass that keeps the text
                               readable (see readable_glass)
    theme.py season [--json]   the season the current theme shows, your
                               hemisphere and where it came from, and the
                               next season's first day ("cyberpunk: not
                               seasonal" for the others); never a place
    theme.py season pin <spring|summer|autumn|winter|auto>
                               hold one season (auto: follow the date
                               again), then re-apply if the theme is seasonal
    theme.py season hemisphere <north|south|auto>
                               your hemisphere (auto: from your places), then
                               the same
    theme.py season-check      re-apply the current theme if its season has
                               changed (theme-season.timer, hourly; a
                               no-op for every other theme)

Also importable (display.py, wallpaper-slideshow.py, theme-from-wallpaper.py
and launcher.py do): themes(), current(), load(name), get(key); and
season(name) (the mascot asks it which season to draw).

Where a theme lives
-------------------
    ~/.config/themes/<name>/
        theme.conf    key=value, every key optional (see KEYS below)
        waybar.css    the bar AND the toolbox  -> waybar/generated/theme.css
        panel.css     the popup panels         -> waybar/generated/theme-panel.css
        launcher.css  launcher, quick note, clipboard
                                               -> waybar/generated/theme-launcher.css
        dock.css      the dock / taskbar (dock.py; it watches the copy
                      and restyles itself)
                                               -> waybar/generated/theme-dock.css
        llm-chat.css  the LLM chat window (llm-chat.py; it watches
                      the copy and restyles itself, and switches to the
                      theme's mascot, mascots.py)
                                               -> waybar/generated/theme-llm-chat.css
        wofi.css      wofi (SUPER+W switcher)  -> waybar/generated/theme-wofi.css
        mako          mako config fragment     -> mako/generated/theme
        gtk4.css      libadwaita / GTK4 apps   -> ~/.config/gtk-4.0/gtk.css
        kitty.conf    kitty options (tabs, cursor, links, borders...), appended
                      to ~/.config/kitty/theme.conf after the term.* colours
        prompt.sh     the bash prompt: the PROMPT_* variables of Fedora's
                      bash-color-prompt, and a PROMPT_COMMAND hook if it needs
                      one   -> ~/.bashrc.d/theme-prompt.sh (new shells; none =
                      Fedora's default prompt)
        mpv.conf      mpv: its on-screen controls (which skin from
                      ~/.config/mpv/skins/, uosc's script-opts), mpv's own
                      messages, subtitles, letterbox -- plain mpv options
                                               -> ~/.config/mpv/theme.conf
                      (mpv.conf includes it, before its first [profile];
                      read at mpv's start, so from the next video). None =
                      mpv's stock controls. ~/.config/themes/mpv-base.conf
                      (how the controls behave: when they show, the
                      controls row, message and subtitle sizes) is written
                      above it for every theme; the theme's lines win.
        hypr.lua      optional: Hyprland window/layer rules for this theme
                      only (read by lua/display.lua, see there)
        season/<s>/   optional: a SEASONAL theme ("Seasonal themes" below):
                      for each of spring summer autumn winter, a theme.conf
                      (colours only), palette.css, and additions to any file
                      above (not hypr.lua, not sounds/)
A missing file means "no override": the generated copy is still written
(header only), because every one of them is @import-ed or include=-d by the
base files, and waybar draws NOTHING styled if an import target is missing.

Each generated stylesheet is imported LAST by its base file (style.css,
style-toolbox.css, panel.css, launcher.css, llm-chat.css,
wofi/style.css, scripts/dock.css), after
generated/accent.css. GTK3 resolves a named colour by its last definition
anywhere in the provider, so a theme recolours by redefining the PALETTE
names at the top of each base file; every other property it changes with a
rule of the same selector, which wins by coming later. The base files hold no
colour literals in their rules for exactly this reason.

Copies, not symlinks, on purpose: waybar re-reads its style when an imported
file changes, and a copy changes exactly once, atomically, when theme.py says
so -- never half-way through an edit in an editor. The price is that editing a
theme's file shows up only after `theme.py apply`.

Inheritance
-----------
Every theme inherits cyberpunk (the base, today's neon look) for any key it
does not set; `inherit=<other>` puts another theme in between. Stylesheets do
NOT inherit -- each theme's css is an override of the cyberpunk base files, and
cyberpunk's own are empty.

Seasonal themes
---------------
A theme with a season/ folder changes with the real date (seasons/ is the
one that does). season/<spring|summer|autumn|winter>/ each hold:

    theme.conf    laid over the theme's resolved conf by load(), but ONLY
                  the keys in SEASON_KEYS and color.*: the accent,
                  gtk_accent_color, icon_theme, wallpaper_prefix,
                  wallpaper_video, glass, the term.* and cosmic.* colours.
                  Everything else -- shape, fonts, hypr.*, lang, anim, the
                  cursor -- is the theme's all year: lua/display.lua,
                  lua/env.lua and display_panel.py read theme.conf
                  themselves and would never see a season's value, and a
                  face that changed with the season would change every
                  panel's size. (The window border still follows: a theme
                  with hypr.accent_stops lets the season's accent= in.)
                  `check` reports any other key, with why.
    palette.css   @define-color lines inserted into every GTK3 stylesheet
                  (waybar, panel, launcher, llm-chat, wofi) after the font
                  rules and BEFORE the theme's own css, so the theme's rules
                  use names defined above them. Not gtk4.css: GTK4 has no
                  @define-color; a season's gtk4.css addition carries CSS
                  custom properties instead.
    <file>        an addition to any theme file (waybar.css ... mpv.conf,
                  kitty.conf, prompt.sh), appended after the theme's own
                  under a comment naming it (theme_text) -- a later rule,
                  option, assignment or script-opts-append wins. mako is the
                  exception: merged section-wise (mako_merge: both
                  fragments' global lines first, then both sets of
                  [sections]), since a global line after a [section] header
                  would belong to that section. Not hypr.lua or sounds/:
                  lua/display.lua, theme-sound.sh and timers.py read those
                  from the theme folder itself.

The season (season()) is meteorological -- whole months, as weather
services count them: MAM spring, JJA summer, SON autumn, DJF winter in the
north, six months on in the south. (The astronomical dates differ by three
weeks at most, and whole months are easy to test.) The hemisphere is
display.conf season_hemisphere=north|south, else (auto) the sign of the
weather place's latitude (region.conf weather= as "lat,lon", or wttr.py's
cached answer for that place), else the time zone's principal city's
(zone1970.tab), else north -- nothing is fetched, and only north/south is
ever printed. display.conf season_pin=<season> holds one season;
HYPR_SEASON=<season> beats both for one process (previews, tests, checks).

write_generated records the season the generated files are for in
waybar/generated/season (the stylesheet headers name it too, so waybar
re-reads them when it changes). `theme.py season-check` compares that with
the season due now and re-applies only when they differ, so most of
theme-season.timer's hourly ticks cost a few file reads. A Steam game on
screen holds the change until the next tick (a pin or hemisphere you just
chose does not wait). Its own timer, not theme-schedule.timer:
`theme-schedule.py off` disables that one, and the season must still turn.
Hourly, so a held check or a machine asleep at midnight catches up within
the hour (Persistent=true after a power-off). `check` runs every season:
the folder first (check_seasons), then the full lint once per season, a
problem all four share printed once, the rest with a [season] prefix.

theme.conf KEYS (cyberpunk's file lists every one with its value)
-----------------
    name=Cyberpunk             label in the display panel and the launcher
    order=10                   sort position in those lists
    inherit=                   theme to inherit from (default cyberpunk)
    accent=                    #rrggbb: the theme's own accent (@cyan in the
                               stylesheets, mako's border). Empty = the base
                               stylesheets' own neon.
    accent_follow=yes          yes: the accent may follow the primary screen's
                               wallpaper
                               (the display panel's switch; theme_auto in
                               display.conf). no: always the theme's accent,
                               the switch greyed out.
    font=IBM Plex Sans         replaces "IBM Plex Sans" in every base
    font_mono=IBM Plex Mono    stylesheet and in mako's font= (rules are
                               generated, see font_rules()); the same face as
                               the base = nothing generated. Either may be a
                               comma-separated list, first choice first
                               ("font=Selawik, IBM Plex Sans"): a face with
                               few glyphs keeps a fallback the theme chose,
                               instead of whatever fontconfig's sans-serif is
    hypr.*                     the Hyprland look, applied by lua/display.lua
                               at every config load (so a reload and gamemode
                               OFF bring the THEME back, not settings.lua):
                               rounding, gaps_in, gaps_out, border_size,
                               active_border, inactive_border (Hyprland
                               gradient syntax: colours then an angle),
                               accent_stops (which active_border stops the
                               accent replaces, 1-based, "" = none),
                               blur=yes|no, blur_size, blur_passes,
                               blur_brightness, blur_contrast, blur_vibrancy,
                               blur_vibrancy_darkness, blur_noise,
                               shadow=yes|no, shadow_range,
                               shadow_render_power, shadow_color,
                               shadow_color_inactive (the unfocused
                               windows' shadow; "" = none, the transparent
                               rgba(00000000) lua/settings.lua sets),
                               shadow_offset ("x y" px, "0 0" = a glow
                               rather than a drop shadow), rounding_power
                               (the corner shape: 2 round, more = squircle;
                               also a your-window-look key, see display.lua)
    anim=fancy                 animation preset set by `set` (snappy, smooth,
                               fancy, calm, spring); you can change it
                               afterwards
    wallpaper_prefix=skyline-  the slideshow's set: file-name prefix, same
                               name in every monitor's folder
    wallpaper_video=           a MOVING wallpaper: a video file name looked
                               for in every monitor's folder, played by the
                               slideshow over the still (paused while covered,
                               stopped in gamemode; the display panel's
                               switch turns it off). Empty = stills only.
    gtk_color_scheme=prefer-dark   gsettings org.gnome.desktop.interface
    gtk_accent_color=blue          (accent: blue teal green yellow orange red
                                    pink purple slate)
    gtk_button_layout=appmenu:close   gsettings org.gnome.desktop.wm.preferences
                               button-layout: where GTK / libadwaita windows
                               (Files) put their title-bar buttons -- words
                               from appmenu close minimize maximize icon
                               spacer, "left:right" around the colon.
                               orchard: close,minimize,maximize: (the three
                               dots on the left, its gtk4.css paints them)
    icon_theme=Adwaita         gsettings icon-theme (GTK apps, live) and
                               mako's icon-path: a folder name in
                               ~/.local/share/icons or /usr/share/icons.
                               Win95, Phosphor, Neon, Moe, Lofi, Luna, Orbit
                               and Seasons-* are BUILT by
                               make-icon-theme.py (rerun it after installing
                               an app); `check` says when one is missing
    cursor_theme=Adwaita       the pointer: a cursor theme's folder name in
                               ~/.local/share/icons or /usr/share/icons, set
                               through gsettings (GTK apps) and hyprctl
                               setcursor (Hyprland, live), at XCURSOR_SIZE
    lang=en                    en or ja: the language the desktop speaks where
                               it shows words -- the bar's day (clock.py:
                               10月18日 (日)), the workspace numbers (一 二 三
                               ..., waybar/generated/theme-modules.json, which
                               the bar's config includes), the launcher's
                               prompt. Written to waybar/generated/lang
    crt_suggest=no             yes: the display panel suggests the CRT filter;
                               never switched on by a theme
    term.*                     the terminals: COSMIC Terminal (SUPER+Q) and
                               kitty (the scratchpad, the launcher's tools).
                               term.background / term.foreground /
                               term.cursor #rrggbb; term.normal and
                               term.bright: 8 colours each, space-separated,
                               ANSI order (black red green yellow blue
                               magenta cyan white); term.font (one mono
                               face); term.font_size (px, the one unit
                               used everywhere for it -- COSMIC Terminal
                               takes px as is, kitty gets the same size in
                               points, px x 0.75). Written to
                               ~/.config/cosmic/com.system76.CosmicTerm/v1/
                               (app_theme, color_schemes_dark,
                               syntax_theme_dark, font_name, font_size,
                               opacity: open
                               windows follow at once -- so the terminal's
                               own settings for those are the theme's now)
                               and ~/.config/kitty/theme.conf (kitty.conf
                               includes it; kitty gets SIGUSR1, a reload)
    cosmic.*                   COSMIC apps' own toolkit (libcosmic: the
                               terminal's title bar and menus, COSMIC Files,
                               Edit...): cosmic.background, cosmic.foreground,
                               cosmic.accent #rrggbb, cosmic.radius (corner
                               scale: 1 = stock, 0 = square). The stock
                               COSMIC dark theme (/usr/share/cosmic/
                               com.system76.CosmicTheme.Dark) with its greys
                               moved onto background..foreground and its
                               teal onto the accent, status colours left
                               alone -> ~/.config/cosmic/
                               com.system76.CosmicTheme.Dark/v2 (live;
                               what was there: v2.before-themes)
    glass=12                   how see-through the terminals are, 0-100 (0 =
                               opaque): COSMIC Terminal, kitty, and COSMIC
                               windows' title bars. COSMIC Terminal is TWO
                               layers -- the window colour, then its own
                               background over it -- so each gets
                               1-sqrt(glass) opacity and the text area ends
                               up exactly glass% clear (the title bar, one
                               layer, clearer still: sqrt(glass)); kitty
                               takes glass% in one. glass_<theme> in
                               display.conf (the display panel's slider)
                               overrides it per theme. Derived, never set:
                               term.opacity and cosmic.alpha
    island.enabled=            the dynamic island (island.py) while this theme
    island.style=              is on: yes|no, one of ISLAND_STYLES, yes|no.
    island.match_bar=          "" (every theme but orchard) = the theme leaves
                               the island alone. Only `set` hands them over
                               (island_handoff): it keeps what you had in
                               ~/.local/state/hypr/island.before-theme.json
                               and puts it back when you switch to a theme
                               that sets none -- unless you changed that
                               setting yourself meanwhile. Not apply, ensure
                               or a season tick: a login never flips the island
    bar.clock=                 menubar: the date and time move to the bar's
                               far right as one "Tue 27 Oct  21:21" (clock.py
                               menubar, honouring region.conf clock=12); the
                               centre's custom/day and custom/clock print
                               nothing (waybar hides them). "" = the centre
                               clock as always
    bar.logo=                  a glyph for custom/logo, the bar's first item
                               (orchard: Font Awesome's leaf). "" = hidden.
                               Its click is the power menu, so with a logo
                               the power pill (custom/power, clock.py power)
                               hides: one power menu on the bar. The
                               taskbar's start button does not count (it
                               opens the launcher, which has no power menu)
    bar.workspaces=            dots: the workspaces as ● (active) and ○ dots
                               (theme-modules.json). "" = their numbers
                               (bar.clock and bar.logo are written to
                               waybar/generated/bar.conf, which clock.py reads)
    dock.start=                a word beside the taskbar's start button glyph
                               (dock.py, the "taskbar" layout; win95 and luna:
                               "Start"). "" = the glyph alone. Written to
                               bar.conf as start=, where dock.py reads it
    dock.magnify=              yes: the dock's icons grow under the pointer,
                               macOS-like (dock.py's magnify setting at
                               "theme", its default; orchard and
                               orchard-dark). "" or no = they do not. Written
                               to bar.conf as magnify=
    color.<name>=#rrggbb       colours DRAWN by code rather than CSS -- Pango
                               markup in bar scripts, cairo graphs in panels:
                               written to waybar/generated/colors.conf, read
                               by waybar/scripts/themecolors.py and the shell
                               scripts. Names: see cyberpunk/theme.conf.

The switch itself lives in ~/.local/state/hypr/display.conf as theme=<name>
(lua/shared.lua documents that file), so lua/display.lua finds it at every
reload; a missing key is cyberpunk.

Your own fonts and cursor, over every theme
-------------------------------------------
The Settings window's "Fonts & text" page (font-settings.py) can pick the
desktop's faces for you, whatever the theme. Those choices are display.conf
keys too, and load() lays them over the resolved theme.conf, so every
generated file, the terminals and mako get them exactly as if the theme had
said so -- and a theme switch keeps them:

    font_user=Inter            over font=: the bar, toolbox, panels,
                               launcher, wofi, mako. The theme's own list
                               stays behind it as the fallback ("Inter,
                               Selawik, IBM Plex Sans"), so a glyph your face
                               lacks still comes from a face the theme chose
    font_mono_user=Fira Code   over font_mono= (the same, the mono rules)
    term_font_user=Fira Code   over term.font= (COSMIC Terminal, kitty)
    term_font_size_user=15     over term.font_size= (px)
    cursor_theme_user=Pop      over cursor_theme=
    cursor_size=32             the pointer size (gsettings cursor-size,
                               hyprctl setcursor; lua/env.lua and
                               ~/.config/uwsm/env read it for XCURSOR_SIZE /
                               HYPRCURSOR_SIZE at login). Not a theme key:
                               no theme sets a size. Missing = 24

A missing key is "the theme's", so "Use the theme's fonts" deletes them.
The theme's own value stays readable as theme:<key> in load()'s answer
(theme:font, theme:term.font...) for the page to show. `check` lints the
theme alone, without them (load(name, user=False)).
"""

import json
import os
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screens  # noqa: E402  (scripts/screens.py: the primary, the screens' order)
import desk_common  # noqa: E402  (run: a command with a timeout)
import bar_signals  # noqa: E402  (the bar's signal numbers; poke() redraws a pill)

HOME = os.path.expanduser("~")
THEMES_DIR = os.path.join(HOME, ".config", "themes")
BASE = "cyberpunk"
BASE_FONT = "IBM Plex Sans"         # the face the base stylesheets are written in
BASE_MONO = "IBM Plex Mono"
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                     "hypr", "display.conf")
HYPR = os.path.join(HOME, ".config", "hypr", "scripts")
NOTIFY = os.path.join(HYPR, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
WAYBAR = os.path.join(HOME, ".config", "waybar")
BAR_RESTART = os.path.join(WAYBAR, "scripts", "bar-restart.sh")   # never SIGUSR2 (crashes waybar 0.15)
GEN = os.path.join(WAYBAR, "generated")
SLIDESHOW = os.path.join(HYPR, "wallpaper-slideshow.py")
SLIDESHOW_STATE = os.path.join(HOME, ".cache", "wallpaper-slideshow.json")
ACCENT_SCRIPT = os.path.join(HYPR, "theme-from-wallpaper.py")
PRESETS = ["snappy", "smooth", "fancy", "calm", "spring"]   # lua/display.lua M.presets, display.py PRESETS
GTK_ACCENTS = ["blue", "teal", "green", "yellow", "orange", "red", "pink", "purple", "slate"]
GTK_SCHEMES = ["default", "prefer-dark", "prefer-light"]
# gtk_button_layout's words (org.gnome.desktop.wm.preferences button-layout).
BUTTON_WORDS = ("appmenu", "close", "minimize", "maximize", "icon", "spacer")
BUTTON_LAYOUT = re.compile(r"^[a-z,:]*$")
# The island hand-off (island_handoff, below). ISLAND_STYLES is island.py's
# STYLES, copied so that `check` needs no import (tests/test_theme_island.py
# keeps the two equal). The keys in the order `set` sends them: enabled LAST,
# so a service that starts reads the final look.
ISLAND = os.path.join(HYPR, "island.py")
ISLAND_STYLES = ("notch", "island", "glass", "theme", "outline")
ISLAND_KEYS = ("style", "match_bar", "enabled")
ISLAND_SNAPSHOT = os.path.join(os.path.dirname(STATE), "island.before-theme.json")
# The bar's layout keys -> waybar/generated/bar.conf (clock.py reads it).
# bar_conf() joins it to GEN when asked, so a test that points GEN at a
# scratch folder never writes the live one.
BAR_CONF_NAME = "bar.conf"
BAR_CLOCKS = ("", "menubar")
BAR_WORKSPACES = ("", "dots")
DOCK_START_MAX = 12                        # dock.start=: one short word
DOCK_MAGNIFY = ("", "yes", "no")           # dock.magnify=

# The values cyberpunk/theme.conf holds, so that a deleted or half-written
# theme folder can never leave a key unanswered (the slideshow, for one, asks
# for wallpaper_prefix every time it picks a picture). Keep in step with
# ~/.config/themes/cyberpunk/theme.conf.
DEFAULTS = {
    "name": "Cyberpunk", "order": "10", "inherit": "",
    "accent": "", "accent_follow": "yes",
    "font": BASE_FONT, "font_mono": BASE_MONO,
    "anim": "fancy", "wallpaper_prefix": "skyline-", "wallpaper_video": "",
    "gtk_color_scheme": "prefer-dark", "gtk_accent_color": "blue",
    "icon_theme": "Adwaita", "gtk_button_layout": "appmenu:close",
    "crt_suggest": "no", "lang": "en", "cursor_theme": "Adwaita",
    "island.enabled": "", "island.style": "", "island.match_bar": "",
    "bar.clock": "", "bar.logo": "", "bar.workspaces": "", "dock.start": "",
    "dock.magnify": "",
    "term.font": BASE_MONO, "term.font_size": "14", "glass": "12", "term.bright_bold": "no",
    "cosmic.background": "#0d1018", "cosmic.foreground": "#c8d3e6", "cosmic.accent": "#00f0ff",
    "cosmic.radius": "1",
    "term.background": "#07090f", "term.foreground": "#e6fcff", "term.cursor": "#00f0ff",
    "term.normal": "#1b1f2a #ff2a6d #39ff14 #f9f002 #5c8dff #c060ff #00f0ff #c8d3e6",
    "term.bright": "#5a6478 #ff6b96 #8aff70 #fff86b #8fb0ff #d890ff #8af8ff #ffffff",
}

# theme file -> (generated copy, comment style, base stylesheets whose
# font-family rules the font swap is generated from). The base list is also
# what `check` parses the override against.
TARGETS = {
    "waybar.css": (os.path.join(GEN, "theme.css"), "css",
                   [os.path.join(WAYBAR, "style.css"), os.path.join(WAYBAR, "style-toolbox.css")]),
    "panel.css": (os.path.join(GEN, "theme-panel.css"), "css", [os.path.join(WAYBAR, "panel.css")]),
    "launcher.css": (os.path.join(GEN, "theme-launcher.css"), "css", [os.path.join(HYPR, "launcher.css")]),
    "llm-chat.css": (os.path.join(GEN, "theme-llm-chat.css"), "css",
                     [os.path.join(HYPR, "llm-chat.css")]),
    "dock.css": (os.path.join(GEN, "theme-dock.css"), "css", [os.path.join(HYPR, "dock.css")]),
    "wofi.css": (os.path.join(GEN, "theme-wofi.css"), "css",
                 [os.path.join(HOME, ".config", "wofi", "style.css")]),
    "mako": (os.path.join(HOME, ".config", "mako", "generated", "theme"), "mako", []),
    "gtk4.css": (os.path.join(HOME, ".config", "gtk-4.0", "gtk.css"), "css", []),
}

# Seasonal themes (see "Seasonal themes" in the docstring).
SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_DIR = "season"                      # <theme>/season/<s>/
# month (1-12) -> season, northern hemisphere; the south is six months on.
# Meteorological seasons (whole months), as weather services count them.
NORTH = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
         6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
HEMISPHERES = ("north", "south")
# The keys a season's theme.conf may set: colours and the sets that carry
# them. Everything else (shape, fonts, hypr.*, language, ...) is the
# theme's, the same all year -- because lua/display.lua, lua/env.lua and
# display_panel.py read theme.conf themselves, and because a face that
# changed with the season would change every panel's size.
SEASON_KEYS = {"accent", "gtk_accent_color", "icon_theme", "wallpaper_prefix", "wallpaper_video",
               "glass", "term.background", "term.foreground", "term.cursor", "term.normal",
               "term.bright", "term.bright_bold", "cosmic.background", "cosmic.foreground",
               "cosmic.accent"}            # plus every color.* key
# Files a season folder may hold (theme.conf, the shared palette, and an
# addition to any of the theme's own files). Not hypr.lua, not sounds/:
# lua/display.lua, theme-sound.sh and timers.py read those from the theme
# folder itself.
SEASON_FILES = {"theme.conf", "palette.css", "kitty.conf", "prompt.sh", "mpv.conf"} | set(TARGETS)
SEASON_FILE = os.path.join(GEN, "season")  # the season the generated files are for ("" = none)
SEASON_CACHE_S = 60                        # hemisphere lookups kept this long per process

COLORS = os.path.join(GEN, "colors.conf")
LANG_FILE = os.path.join(GEN, "lang")
MODULES = os.path.join(GEN, "theme-modules.json")
KANJI = "一二三四五六七八九十"
COSMIC_TERM = os.path.join(HOME, ".config", "cosmic", "com.system76.CosmicTerm", "v1")
KITTY = os.path.join(HOME, ".config", "kitty")
ANSI = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
TERM_SCHEME_ID = 7000       # our entry in cosmic-term's colour scheme map
MPV = os.path.join(HOME, ".config", "mpv")
MPV_SKINS = ("uosc", "glass")
# How mpv's interface behaves in every theme; mpv_text() puts it first.
MPV_BASE = os.path.join(THEMES_DIR, "mpv-base.conf")
# v2: the version this libcosmic reads (v1 is an older format with float
# colours, ignored -- writing there changed nothing, found the hard way).
COSMIC_STOCK = "/usr/share/cosmic/com.system76.CosmicTheme.Dark/v2"
COSMIC_THEME = os.path.join(HOME, ".config", "cosmic", "com.system76.CosmicTheme.Dark", "v2")
# The stock dark theme's anchors: its window grey #1B1B1B, its text grey
# #E7E7E7 (background.on), its teal #63D0DF.
STOCK_BG, STOCK_FG = 0x1B / 255, 0xE7 / 255
STOCK_ACCENT = (0x63 / 255, 0xD0 / 255, 0xDF / 255)
RON_COLOUR = re.compile(r'"#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})"')
MAKO_ACCENT = "~/.config/mako/generated/accent"
MARK = "GENERATED by ~/.config/hypr/scripts/theme.py"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


# -- reading themes ------------------------------------------------------------
def read_kv(path):
    """key=value lines; '#' comments and blank lines skipped. None if missing."""
    try:
        with open(path) as handle:
            lines = handle.readlines()
    except OSError:
        return None
    out = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def theme_dir(name):
    return os.path.join(THEMES_DIR, name)


def exists(name):
    return bool(name) and "/" not in name and os.path.isfile(os.path.join(theme_dir(name), "theme.conf"))


def chain(name):
    """[name, its parent, ..., cyberpunk]: the inherit= chain, cycles cut."""
    out = []
    while name and name not in out and exists(name):
        out.append(name)
        parent = (read_kv(os.path.join(theme_dir(name), "theme.conf")) or {}).get("inherit", "")
        name = parent or (BASE if name != BASE else "")
    if BASE not in out:
        out.append(BASE)
    return out


# display.conf key -> the theme.conf key it overrides (see "Your own fonts
# and cursor" above). The two face lists keep the theme's list behind yours.
USER_KEYS = {"font_user": "font", "font_mono_user": "font_mono", "term_font_user": "term.font",
             "term_font_size_user": "term.font_size", "cursor_theme_user": "cursor_theme"}
USER_FALLBACK = ("font", "font_mono")
CURSOR_SIZE = "24"           # XCURSOR_SIZE when display.conf has no cursor_size


def user_layer(conf, state):
    """Lay the user's own font / cursor choices (display.conf) over a
    resolved theme conf, in place. The theme's value is kept as
    theme:<key>. A value that cannot be right is skipped, not trusted: a
    term font size outside 6-48, an empty face."""
    for skey, key in USER_KEYS.items():
        conf[f"theme:{key}"] = conf.get(key, "")
        mine = state.get(skey, "").strip()
        if not mine:
            continue
        if key == "term.font_size" and not (mine.isdigit() and 6 <= int(mine) <= 48):
            continue
        if key in USER_FALLBACK:
            faces = font_list(mine)
            faces += [f for f in font_list(conf.get(key, "")) if f not in faces]
            mine = ", ".join(faces)
        elif key == "term.font":
            mine = (font_list(mine) or [""])[0]
            if not mine:
                continue
        conf[key] = mine
    return conf


def cursor_size(state=None):
    """The pointer size: display.conf cursor_size, else 24 (lua/env.lua's
    default). Whole px, 8-256."""
    size = (state if state is not None else read_state()).get("cursor_size", "")
    return size if size.isdigit() and 8 <= int(size) <= 256 else CURSOR_SIZE


def season_allowed(key):
    """May a season's theme.conf set `key`? (SEASON_KEYS and color.*)"""
    return key in SEASON_KEYS or key.startswith("color.")


def load(name=None, user=True, season=None):
    """The resolved theme.conf of `name` (default: the current theme), with
    the user's own fonts and cursor over it (user=False: the theme alone).
    A seasonal theme gets its season's theme.conf laid over the chain --
    only the keys season_allowed() lets through; `check` reports the rest.
    season=None: the season it shows now (season()); "spring".."winter":
    that one (check and the tests); "": no overlay. conf["season"] says
    which ("" for every other theme)."""
    name = name or current()
    conf = dict(DEFAULTS)
    for link in reversed(chain(name)):
        conf.update(read_kv(os.path.join(theme_dir(link), "theme.conf")) or {})
    # The parameter hides the module's season(); _season is the same function.
    s = _season(name) if season is None else season
    if s and seasonal(name):
        over = read_kv(os.path.join(season_dir(name, s), "theme.conf")) or {}
        conf.update({k: v for k, v in over.items() if season_allowed(k)})
    else:
        s = ""
    conf["season"] = s
    conf["id"] = name
    conf["glass_default"] = conf.get("glass", "0")
    state = read_state()
    if user:
        user_layer(conf, state)
    mine = state.get(f"glass_{name}", "")
    if mine.isdigit() and int(mine) <= 100:
        conf["glass"] = mine
    try:
        glass = min(100, max(0, int(conf.get("glass", "0")))) / 100
    except ValueError:
        glass = 0
    # Two equal layers whose clear parts multiply to `glass`.
    layer = round((1 - glass ** 0.5) * 100)
    conf["term.opacity"] = conf["cosmic.alpha"] = str(layer)
    return conf


def get(key, name=None):
    return load(name).get(key, "")


def themes():
    """[(name, label)], sorted by order= then label; only folders with a theme.conf."""
    try:
        names = [n for n in os.listdir(THEMES_DIR) if exists(n)]
    except OSError:
        names = []
    rows = []
    for n in names:
        conf = load(n)
        try:
            order = float(conf.get("order", 50))
        except ValueError:
            order = 50
        rows.append((order, conf.get("name") or n, n))
    rows.sort()
    return [(n, label) for _, label, n in rows] or [(BASE, DEFAULTS["name"])]


# -- seasons (see "Seasonal themes" in the docstring) ---------------------------
def seasonal(name):
    """Does theme `name` change with the seasons (it has a season/ folder)?"""
    return bool(name) and "/" not in name and os.path.isdir(os.path.join(theme_dir(name), SEASON_DIR))


def season_dir(name, s):
    return os.path.join(theme_dir(name), SEASON_DIR, s)


def season_for(month, hemisphere):
    """The season of month 1-12: NORTH's, or six months on for "south"
    (January is summer there)."""
    return NORTH[(month + 5) % 12 + 1] if hemisphere == "south" else NORTH[month]


def hemisphere_from(setting, weather_lat, zone_lat):
    """-> (hemisphere, source). The setting north|south wins ("setting");
    anything else is auto: the sign of the weather place's latitude
    ("weather"), else the time zone's ("time zone"), else ("north",
    "default"). Latitude 0 counts as north. Pure."""
    if setting in HEMISPHERES:
        return setting, "setting"
    for lat, source in ((weather_lat, "weather"), (zone_lat, "time zone")):
        if isinstance(lat, (int, float)):
            return ("south" if lat < 0 else "north"), source
    return "north", "default"


LAT_LON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*-?\d+(?:\.\d+)?\s*$")
_places = {"at": None, "value": (None, None)}


def place_latitudes():
    """(weather_lat, zone_lat), each a float or None, from region.py (no
    GTK; imported only here). Weather: region.conf weather= parsed as
    "lat,lon" when it is that, else wttr.py's cached answer
    (region.read_weather_place) when it is for that place -- nothing is
    fetched. Zone: the system time zone's principal city. Any failure is
    None. Kept SEASON_CACHE_S per process: the launcher daemon and the
    slideshow live long, and themes() loads every theme. Only the sign is
    ever used; the numbers are never printed."""
    now = time.monotonic()
    if _places["at"] is not None and now - _places["at"] < SEASON_CACHE_S:
        return _places["value"]
    weather_lat = zone_lat = None
    try:
        import region
        place = (region.prefs().get("weather") or "").strip()
        m = LAT_LON.match(place)
        if m:
            weather_lat = float(m.group(1))
        elif place:
            found = region.read_weather_place(place)
            if found and isinstance(found.get("lat"), (int, float)):
                weather_lat = float(found["lat"])
    except Exception:       # a broken region.conf or cache must never stop a theme
        weather_lat = None
    try:
        import region
        zone = region.zone_place()
        if zone and isinstance(zone.get("lat"), (int, float)):
            zone_lat = float(zone["lat"])
    except Exception:
        zone_lat = None
    _places.update(at=now, value=(weather_lat, zone_lat))
    return _places["value"]


def hemisphere(state=None):
    """(hemisphere, source) now: display.conf season_hemisphere, else auto."""
    state = state if state is not None else read_state()
    return hemisphere_from(state.get("season_hemisphere", "auto"), *place_latitudes())


def season(name=None, today=None, state=None):
    """The season theme `name` (default: the current one) shows: "" when it
    is not seasonal; else $HYPR_SEASON if it is one of SEASONS (previews,
    tests, checks -- per process); else display.conf season_pin if one of
    SEASONS; else the month's in your hemisphere. today defaults to
    datetime.date.today()."""
    name = name or current()
    if not seasonal(name):
        return ""
    env = os.environ.get("HYPR_SEASON", "")
    if env in SEASONS:
        return env
    state = state if state is not None else read_state()
    pin = state.get("season_pin", "")
    if pin in SEASONS:
        return pin
    if today is None:
        import datetime
        today = datetime.date.today()
    return season_for(today.month, hemisphere(state)[0])


_season = season        # load()'s parameter `season` hides the function there


def next_season(today, hemi):
    """(season, date) of the first day of the next season after `today`."""
    import datetime
    now = season_for(today.month, hemi)
    year, month = today.year, today.month
    for _ in range(12):
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        if season_for(month, hemi) != now:
            return season_for(month, hemi), datetime.date(year, month, 1)
    return now, None


SOURCE_WORDS = {"setting": "set by you", "weather": "from the weather place",
                "time zone": "from the time zone", "default": "by default"}


def season_status(name=None, today=None, state=None):
    """`theme.py season --json`: {"theme", "seasonal", "season",
    "hemisphere", "source", "pin", "next": {"season", "date"}}. pin is the
    pinned season ($HYPR_SEASON or season_pin) or "" when it follows the
    date; next is null then, since a pinned season does not end by itself.
    Never a latitude or a place name: only north/south and the source word."""
    import datetime
    name = name or current()
    state = state if state is not None else read_state()
    today = today or datetime.date.today()
    out = {"theme": name, "seasonal": seasonal(name), "season": "", "hemisphere": "",
           "source": "", "pin": "", "next": None}
    if not out["seasonal"]:
        return out
    hemi, source = hemisphere(state)
    env, pin = os.environ.get("HYPR_SEASON", ""), state.get("season_pin", "")
    out.update(season=season(name, today, state), hemisphere=hemi, source=source,
               pin=env if env in SEASONS else pin if pin in SEASONS else "")
    if not out["pin"]:
        nxt, date = next_season(today, hemi)
        out["next"] = {"season": nxt, "date": date.isoformat() if date else ""}
    return out


def season_line(status):
    """season_status() as one line: "seasons: autumn (north, from the
    weather place; next: winter on 2026-12-01)"."""
    if not status["seasonal"]:
        return f"{status['theme']}: not seasonal"
    where = f"{status['hemisphere']}, {SOURCE_WORDS.get(status['source'], status['source'])}"
    tail = (f"pinned to {status['pin']}" if status["pin"]
            else f"next: {status['next']['season']} on {status['next']['date']}")
    return f"{status['theme']}: {status['season']} ({where}; {tail})"


def season_due(recorded, want):
    """Should season-check apply? Only for a seasonal theme (want != "")
    whose generated files are for another season than `want`. Pure."""
    return bool(want) and recorded != want


def _read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def season_text(conf, filename):
    """The season's addition to theme file `filename` (season/<s>/<filename>)
    under a one-line comment naming it, or "" (no season, no such file).
    The comment style follows the file: /* */ for .css, # for the others."""
    name, s = conf["id"], conf.get("season", "")
    extra = _read(os.path.join(season_dir(name, s), filename)) if s else ""
    if not extra:
        return ""
    label = f"season={s}: ~/.config/themes/{name}/{SEASON_DIR}/{s}/{filename}"
    return (f"/* {label} */" if filename.endswith(".css") else f"# {label}") + "\n" + extra


def theme_text(conf, filename):
    """The theme's own file `filename`, then season_text() after a blank
    line; "" when neither exists. Every reader of a theme file goes through
    this (mako through mako_merge instead), so a theme without a season
    reads exactly what it read before."""
    own = _read(os.path.join(theme_dir(conf["id"]), filename))
    extra = season_text(conf, filename)
    if not extra:
        return own
    if own and not own.endswith("\n"):
        own += "\n"
    return own + ("\n" if own else "") + extra


def season_palette(conf):
    """season/<s>/palette.css, the @define-color s-* block, or ""."""
    s = conf.get("season", "")
    if not s:
        return ""
    try:
        with open(os.path.join(season_dir(conf["id"], s), "palette.css")) as handle:
            return handle.read()
    except OSError:
        return ""


def mako_split(text):
    """(global lines, [section]s and after) of a mako fragment, cut at its
    first line starting with "[" -- the cut generated_text's accent include
    uses too."""
    lines = text.splitlines(keepends=True)
    cut = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
    return "".join(lines[:cut]), "".join(lines[cut:])


def mako_merge(base, extra):
    """Two mako fragments as one: base globals, extra globals, base
    sections, extra sections. Required, not cosmetic: a global line after a
    [section] header belongs to that section, so the season's colours simply
    appended to a base that ends in [urgency=critical] would only colour
    critical toasts."""
    if not extra:
        return base
    nl = lambda t: t if not t or t.endswith("\n") else t + "\n"
    (bg, bs), (eg, es) = mako_split(nl(base)), mako_split(nl(extra))
    return bg + eg + bs + es


def game_running():
    """A Steam game on screen (theme-schedule.py's same check): a season
    change waits for the next hourly tick instead of repainting over it."""
    out = run(["hyprctl", "clients", "-j"], timeout=3)
    return out is not None and '"class": "steam_app_' in (out.stdout or "")


def switch_sound():
    """theme-sound.sh switch, detached (a switch's chime)."""
    try:
        subprocess.Popen([THEME_SOUND, "switch"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def read_season_record():
    try:
        with open(SEASON_FILE) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def cmd_season_check(force=False):
    """`theme.py season-check` (theme-season.timer, hourly): re-apply the
    current theme when the season it shows is not the one its generated
    files are for. Quiet and cheap when nothing changed (a few file reads);
    a game on screen holds it until the next tick, unless forced (a pin or
    a hemisphere you just chose). Returns True when it applied."""
    name = current()
    if not seasonal(name):
        return False
    want = season(name)
    if not force and not season_due(read_season_record(), want):
        return False
    if not force and game_running():
        return False
    changed = apply(load())
    title = f"Seasons: {want}"
    if not gtk4_restart(changed, title):
        status = season_status(name)
        if status["pin"]:
            body = "pinned -- `theme.py season pin auto` follows the date again"
        else:
            body = (f"{status['hemisphere'].capitalize()}ern hemisphere -- until "
                    f"{status['next']['date']}")
        notify(title, body)
    switch_sound()
    return True


def cmd_season(args):
    """theme.py season [--json] | pin <s|auto> | hemisphere <north|south|auto>."""
    if args and args[0] in ("pin", "hemisphere") and len(args) == 2:
        key, value = f"season_{args[0]}", args[1]
        allowed = SEASONS if args[0] == "pin" else HEMISPHERES
        if value not in allowed + ("auto",):
            sys.exit(f"season {args[0]}: one of {', '.join(allowed + ('auto',))}")
        state = read_state()
        state[key] = "" if value == "auto" else value     # write_state drops empty keys
        write_state(state)
        _places["at"] = None
        if seasonal(current()):
            cmd_season_check(force=True)
        print(season_line(season_status()))
    elif args in ([], ["--json"]):
        status = season_status()
        print(json.dumps(status) if args else season_line(status))
    else:
        sys.exit("season [--json] | season pin <spring|summer|autumn|winter|auto> | "
                 "season hemisphere <north|south|auto>")


# -- state (the format and the other readers: lua/shared.lua) -----------------
def read_state():
    state = {}
    try:
        with open(STATE) as handle:
            for line in handle:
                key, sep, value = line.partition("=")
                if sep:
                    state[key.strip()] = value.strip()
    except OSError:
        pass
    return state


def write_state(state):
    """Same writer as display.py: whole file, sorted, atomically replaced."""
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        for key in sorted(state):
            if state[key] != "":
                handle.write(f"{key}={state[key]}\n")
    os.replace(tmp, STATE)     # atomic: Lua may read it at any moment


def current():
    name = read_state().get("theme", "")
    return name if exists(name) else BASE


def following(conf=None):
    """Does the accent follow the wallpaper right now? Both have to agree: the
    theme allows it (accent_follow) and the switch is on (theme_auto)."""
    conf = conf or load()
    return (conf.get("accent_follow", "yes") == "yes"
            and read_state().get("theme_auto", "on") != "off")


# -- generating ----------------------------------------------------------------
def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def font_list(value):
    """font= / font_mono= as a list of faces: "Selawik, IBM Plex Sans" ->
    ["Selawik", "IBM Plex Sans"]. Quotes are optional in theme.conf."""
    return [f.strip().strip('"\'').strip() for f in value.split(",") if f.strip().strip('"\'').strip()]


def css_families(value):
    """The same list as CSS: '"Selawik", "IBM Plex Sans"'. One face gives
    exactly the '"Face"' this always wrote, so single-face themes are
    unchanged byte for byte."""
    return ", ".join(f'"{f}"' for f in font_list(value))


def font_rules(base_files, swaps):
    """For every rule in the base stylesheets that names a font-family, the same
    selector again with the face swapped -- so `font=` reaches the clock, the
    weather, the key caps... without a theme having to find and repeat each
    of those selectors itself. Font Awesome and emoji fallbacks are kept.
    Emitted BEFORE the theme's own css, so the theme can still override one."""
    out = []
    for path in base_files:
        try:
            css = strip_comments(open(path).read())
        except OSError:
            continue
        css = re.sub(r"@(define-color|import)[^;]*;", "", css)
        depth_zero = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", depth_zero):
            m = re.search(r"font-family\s*:\s*([^;]+);?", body)
            if not m:
                continue
            value = m.group(1).strip()
            # One pass for all swaps, so font=IBM Plex Mono with a different
            # font_mono cannot have its result swapped a second time.
            table = {f'"{old}"': css_families(face) for old, face in swaps}
            new = re.sub("|".join(re.escape(k) for k in table), lambda x: table[x.group(0)], value)
            if new != value:
                out.append(f"{' '.join(sel.split())} {{ font-family: {' '.join(new.split())}; }}")
    return "\n".join(out)


def generated_text(target, conf):
    """The full text of one generated file for theme `conf`."""
    path, style, bases = TARGETS[target]
    name = conf["id"]
    s = conf.get("season", "")
    if target == "mako":
        # Section-wise, not appended: see mako_merge.
        body = mako_merge(_read(os.path.join(theme_dir(name), target)), season_text(conf, target))
    else:
        body = theme_text(conf, target)
    at = f"from theme '{name}'" + (f" season '{s}'" if s else "")
    swaps = [(BASE_FONT, conf.get("font") or BASE_FONT), (BASE_MONO, conf.get("font_mono") or BASE_MONO)]
    swaps = [(old, new) for old, new in swaps if new != old]
    if style == "css":
        head = (f"/* {MARK} {at} -- do not edit.\n"
                f"   Source: ~/.config/themes/{name}/{target}"
                f"{'' if body else ' (none: no override)'}; change that and run theme.py apply. */\n")
        # A url() a theme cannot write relatively (the generated copy lives
        # elsewhere, and wofi hands GTK text with no base path): it writes
        # file://~/.config/... and gets this home's absolute path here.
        body = body.replace("file://~/", f"file://{HOME}/")
        fonts = font_rules(bases, swaps) if swaps else ""
        if fonts:
            head += f"\n/* font={conf.get('font')} font_mono={conf.get('font_mono')}: the base's font-family rules, face swapped. */\n{fonts}\n"
        accent = conf.get("accent", "")
        if target == "wofi.css" and HEX.match(accent):
            # wofi is the one GTK3 surface that never imports the wallpaper
            # accent (wofi/style.css says why), so the theme's own accent=
            # is handed to it here; the theme's wofi.css below can still
            # redefine @cyan itself.
            head += f"\n/* accent={accent} (wofi has no generated/accent.css) */\n@define-color cyan {accent.lower()};\n"
        palette = season_palette(conf) if bases else ""
        if palette:
            # Every GTK3 target (not gtk4.css, which has no bases and its own
            # season file): the s-* names defined BEFORE the theme's rules
            # use them -- after the font rules, which name no colour.
            head += (f"\n/* season={s}: ~/.config/themes/{name}/{SEASON_DIR}/{s}/palette.css */\n"
                     + palette.rstrip("\n") + "\n")
        return head + ("\n" + body if body else "")
    # mako: fragment included at the very end of mako/config (top level).
    head = (f"# {MARK} {at} -- do not edit.\n"
            f"# Source: ~/.config/themes/{name}/mako{'' if body else ' (none: no override)'}.\n")
    if any(old == BASE_FONT for old, _ in swaps):
        # Pango takes a family LIST too ("A, B SemiBold 11"), so a fallback
        # chain reaches mako the same way it reaches the stylesheets.
        head += f"font={', '.join(font_list(conf.get('font')))} SemiBold 11\n"
    icons = icon_theme_chain(conf.get("icon_theme"))
    if icons:
        # mako looks icons up by itself, in these folders only (its default
        # is hicolor alone), so the theme's icon set and what it inherits.
        head += f"icon-path={':'.join(icons + ['/usr/share/pixmaps'])}\n"
    if body and not body.endswith("\n"):
        body += "\n"
    if following(conf) and body:
        # The accent outranks the theme's own border here, as it does in the
        # stylesheets when the theme lets the wallpaper decide: read it again
        # after the fragment's GLOBAL lines -- and before its first [section].
        # Not after the whole fragment: mako rejects include= inside a section
        # ("Failed to parse option", mako/config explains), and a fragment
        # that repeats [urgency=low] ends inside one, so the include there
        # made `makoctl reload` refuse the whole config (found with aero, the
        # first theme with both a fragment and accent_follow=yes). Before the
        # sections is also the right order: the accent beats the theme's
        # global border, and the theme's [urgency=critical] border still
        # beats the accent.
        globals_, sections = mako_split(body)
        body = (globals_
                + f"# accent_follow: the wallpaper accent, again, after the theme's global lines.\ninclude={MAKO_ACCENT}\n"
                + sections)
    return head + body


def colors_text(conf):
    lines = [f"# {MARK} from theme '{conf['id']}' -- do not edit.",
             "# Colours drawn by code (Pango markup, cairo): theme.conf color.* keys,",
             "# read by waybar/scripts/themecolors.py and the bar's shell scripts."]
    for key in sorted(k for k in conf if k.startswith("color.")):
        lines.append(f"{key[6:]}={conf[key]}")
    return "\n".join(lines) + "\n"


def modules_text(conf):
    """waybar/generated/theme-modules.json: module options that differ by
    theme, merged into the bar's config through its "include" (waybar keeps
    the main file's keys and takes only the ones it lacks, so the main
    config leaves these out). Now: the workspace numbers -- or, with
    bar.workspaces=dots (orchard), a dot each: ● the active one, ○ the rest
    ("active" and "default" are the two state names waybar-ext-workspaces(5)
    documents; it has no "urgent" icon, style.css colours .urgent). The
    kanji win over dots: a ja theme's numbers are the point of it."""
    if conf.get("lang") == "ja":
        icons = {str(i + 1): k for i, k in enumerate(KANJI)}
        icons["default"] = "{name}"
        ws = {"format": "{icon}", "format-icons": icons}
    elif conf.get("bar.workspaces") == "dots":
        ws = {"format": "{icon}", "format-icons": {"active": "●", "default": "○"}}
    else:
        ws = {"format": "{name}"}
    return json.dumps({"ext/workspaces": ws}, ensure_ascii=False, indent=1) + "\n"


def bar_conf():
    return os.path.join(GEN, BAR_CONF_NAME)


def bar_text(conf):
    """waybar/generated/bar.conf: the bar-layout keys clock.py reads
    (bar_style()): clock=menubar moves the date and time to the far right,
    logo= is custom/logo's glyph; start= is the word on dock.py's start
    button (dock.start), magnify= whether its dock magnifies (dock.magnify).
    Empty values = the usual bar."""
    return (f"# {MARK} from theme '{conf['id']}' -- do not edit.\n"
            f"clock={conf.get('bar.clock', '')}\n"
            f"logo={conf.get('bar.logo', '')}\n"
            f"start={conf.get('dock.start', '')}\n"
            f"magnify={conf.get('dock.magnify', '')}\n")


def write_if_changed(path, text):
    """Atomic, and only when the content differs: every rewrite of a waybar
    import makes both bars re-read their whole style."""
    try:
        with open(path) as handle:
            if handle.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if path.endswith("gtk-4.0/gtk.css") and os.path.exists(path):
        # Never overwrite a gtk.css someone wrote by hand: keep it beside.
        with open(path) as handle:
            if MARK not in handle.read(4096):
                os.replace(path, path + ".before-themes")
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, path)
    return True


def term_colours(conf, key):
    return conf.get(key, "").split()


def cosmic_term_files(conf):
    """{file in COSMIC_TERM: RON text}. cosmic-config keeps one file per
    setting and every COSMIC app watches its folder, so open terminals
    repaint as soon as these land. The scheme's name carries the theme's:
    a new name is what makes cosmic-term look the scheme up again."""
    name = f"Desktop: {conf.get('name') or conf['id']}"

    def ansi(key):
        cols = term_colours(conf, key)
        return "(" + ", ".join(f'{n}: "{c.upper()}"' for n, c in zip(ANSI, cols)) + ")"

    # Left out, cosmic-term draws bold (with use_bright_bold) and dim text in
    # black: on win95's black background all bold text vanished. Bold gets
    # the bright white; dim is the foreground two thirds of the way from the
    # background, like alacritty's own default.
    bright_fg = term_colours(conf, "term.bright")[7]
    fg, bg = hex_rgb(conf["term.foreground"]), hex_rgb(conf["term.background"])
    dim_fg = "#" + "".join(f"{round((b + (f - b) * 0.66) * 255):02X}" for f, b in zip(fg, bg))

    scheme = (f"// {MARK} from theme '{conf['id']}' -- do not edit; see term.* in its theme.conf.\n"
              f"{{\n    {TERM_SCHEME_ID}: (\n"
              f'        name: "{name}",\n'
              f'        foreground: "{conf["term.foreground"].upper()}",\n'
              f'        background: "{conf["term.background"].upper()}",\n'
              f'        cursor: "{conf["term.cursor"].upper()}",\n'
              f'        bright_foreground: "{bright_fg.upper()}",\n'
              f'        dim_foreground: "{dim_fg}",\n'
              f"        normal: {ansi('term.normal')},\n"
              f"        bright: {ansi('term.bright')},\n"
              f"    ),\n}}\n")
    return {
        # Dark always: every theme's terminal is a dark one, and "System"
        # would pick the LIGHT scheme list under a light colour scheme.
        "app_theme": "Dark",
        "color_schemes_dark": scheme,
        "syntax_theme_dark": f'"{name}"',
        "font_name": f'"{font_list(conf["term.font"])[0]}"',
        "font_size": str(int(conf["term.font_size"])),
        "opacity": str(int(conf["term.opacity"])),
        "use_bright_bold": "true" if conf.get("term.bright_bold") == "yes" else "false",
    }


def kitty_text(conf):
    lines = [f"# {MARK} from theme '{conf['id']}' -- do not edit; see term.* in its theme.conf.",
             "# Included by ~/.config/kitty/kitty.conf.",
             f"font_family {font_list(conf['term.font'])[0]}",
             # kitty sizes in points: 16px is 12pt at its 96 dpi.
             f"font_size {int(conf['term.font_size']) * 0.75:g}",
             # One layer in kitty: what COSMIC Terminal's text area gets from
             # its two.
             f"background_opacity {1 - int(conf['glass']) / 100:.2f}",
             f"background {conf['term.background']}",
             f"foreground {conf['term.foreground']}",
             f"cursor {conf['term.cursor']}",
             f"selection_background {conf['term.foreground']}",
             f"selection_foreground {conf['term.background']}"]
    for i, col in enumerate(term_colours(conf, "term.normal") + term_colours(conf, "term.bright")):
        lines.append(f"color{i} {col}")
    # The season's kitty.conf comes after the theme's: a later kitty option wins.
    extra = theme_text(conf, "kitty.conf")
    if extra or os.path.isfile(os.path.join(theme_dir(conf["id"]), "kitty.conf")):
        lines += ["", f"# --- ~/.config/themes/{conf['id']}/kitty.conf ---", extra.rstrip("\n")]
    return "\n".join(lines) + "\n"


PROMPT_FILE = os.path.join(HOME, ".bashrc.d", "theme-prompt.sh")


def prompt_text(conf):
    """~/.bashrc.d/theme-prompt.sh: the theme's prompt.sh under a header, or
    a reset to Fedora's default prompt when the theme has none (a shell that
    sourced another theme's file must not keep its hook)."""
    # The season's prompt.sh comes after the theme's: its assignments win.
    body = theme_text(conf, "prompt.sh")
    if not body and not os.path.isfile(os.path.join(theme_dir(conf["id"]), "prompt.sh")):
        body = ("# (none: Fedora's default prompt)\n"
                "PROMPT_COMMAND=${PROMPT_COMMAND//__cp_prompt;/}\n")
    return f"# {MARK} from theme '{conf['id']}' -- do not edit.\n" + body


def hex_rgb(value):
    return [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]


def cosmic_colour(rgb, conf):
    """One stock colour, moved into the theme. Greys keep their place on
    the stock window..text ramp, on the theme's background..foreground
    (a little past either end too: black on the accent becomes "past the
    background", which is light on win95's grey -- right for text on navy);
    the teal keeps its brightness relative to the stock teal, as the
    theme's accent; anything else (the status reds, greens, yellows) stays."""
    hi, lo = max(rgb), min(rgb)
    if hi - lo < 0.03:
        t = max(-0.4, min(1.4, (sum(rgb) / 3 - STOCK_BG) / (STOCK_FG - STOCK_BG)))
        bg, fg = hex_rgb(conf["cosmic.background"]), hex_rgb(conf["cosmic.foreground"])
        return [b + (f - b) * t for b, f in zip(bg, fg)]
    if all(abs(c / hi - a / max(STOCK_ACCENT)) < 0.12 for c, a in zip(rgb, STOCK_ACCENT)):
        scale = hi / max(STOCK_ACCENT)
        accent = hex_rgb(conf["cosmic.accent"])
        if scale <= 1:
            return [c * scale for c in accent]
        return [c + (1 - c) * min(1, scale - 1) for c in accent]
    return rgb


def cosmic_theme_files(conf):
    """{file: RON text} for COSMIC_THEME, from the stock theme's files."""
    try:
        names = sorted(os.listdir(COSMIC_STOCK))
    except OSError:
        return {}
    radius = float(conf.get("cosmic.radius") or 1)
    out = {}
    for name in names:
        with open(os.path.join(COSMIC_STOCK, name)) as handle:
            text = handle.read()

        def swap(m):
            rgb = cosmic_colour([int(m[1][i:i + 2], 16) / 255 for i in (0, 2, 4)], conf)
            return '"#' + "".join(f"{round(min(1.0, max(0.0, c)) * 255):02X}" for c in rgb) + m[2].upper() + '"'
        text = RON_COLOUR.sub(swap, text)
        if name == "background":
            # Only the window colour itself (the file's first base:), not its
            # buttons: they sit on it and would double up.
            alpha = round(int(conf.get("cosmic.alpha") or 100) * 2.55)
            text = re.sub(r'(base: "#[0-9A-F]{6})[0-9A-F]{2}"', lambda m: f'{m[1]}{alpha:02X}"', text, count=1)
        if name == "corner_radii":
            text = re.sub(r"\d+\.\d+", lambda m: f"{float(m[0]) * radius:.1f}", text)
        elif name == "name":
            text = f'"desktop-{conf["id"]}"'
        elif name == "palette":
            text = re.sub(r'name: "[^"]*"', f'name: "desktop-{conf["id"]}"', text, count=1)
        elif name == "is_dark":
            # libcosmic picks contrast colours (text on buttons...) by this;
            # a light window face (win95's grey) is a light theme to it.
            light = sum(hex_rgb(conf["cosmic.background"])) / 3 > 0.5
            text = "false" if light else "true"
        out[name] = text
    return out


def mpv_text(conf):
    """~/.config/mpv/theme.conf: the shared behaviour (themes/mpv-base.conf),
    then the theme's mpv.conf, under a header. The theme's file does not
    inherit from cyberpunk's -- a theme without one gets mpv's stock controls
    -- but it comes after the base, so it can override a base line."""
    def read(path):
        try:
            with open(path) as handle:
                return handle.read()
        except OSError:
            return ""
    base = read(MPV_BASE)
    # The season's mpv.conf after the theme's: a later script-opts-append wins.
    body = theme_text(conf, "mpv.conf")
    head = (f"# {MARK} from theme '{conf['id']}' -- do not edit.\n"
            f"# Source: ~/.config/themes/mpv-base.conf, then "
            f"~/.config/themes/{conf['id']}/mpv.conf{'' if body else ' (none: stock mpv)'}.\n")
    return head + ("\n" + base if base else "") + ("\n" + body if body else "")


def check_mpv(name, season=""):
    """Problems in a theme's mpv.conf (and its season's, when given) and in
    the shared mpv-base.conf: lines that are not option=value, and a skin
    directory or input file named that is not there."""
    problems = []
    srcs = [(MPV_BASE, "mpv-base.conf"), (os.path.join(theme_dir(name), "mpv.conf"), "mpv.conf")]
    if season:
        srcs.append((os.path.join(season_dir(name, season), "mpv.conf"), f"{SEASON_DIR}/{season}/mpv.conf"))
    for src, label in srcs:
        try:
            with open(src) as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") or "=" not in line:
                problems.append(f"{label} line {n}: not option=value ({line[:40]!r}); "
                                "a [profile] here would swallow everything after it")
                continue
            key, value = line.split("=", 1)
            if value.startswith("#"):
                problems.append(f"{label} line {n}: {key}={value}: quote it -- # starts a comment in mpv's config")
            if key in ("scripts-append", "input-conf"):
                path = value.replace("~~", MPV, 1)
                # A script is a folder with a main.lua (the skins) or one .lua file (the HUD).
                want = os.path.join(path, "main.lua") if key == "scripts-append" and not path.endswith(".lua") else path
                if not os.path.exists(want):
                    problems.append(f"{label} line {n}: {value} is not installed (~/.config/mpv/skins/README)")
    return problems


def write_terminals(conf):
    """cosmic-term and kitty. Returns ["cosmic-term"] / ["kitty"] as changed."""
    changed = []
    schemes = os.path.join(COSMIC_TERM, "color_schemes_dark")
    try:
        with open(schemes) as handle:
            old = handle.read()
    except OSError:
        old = ""
    if old.strip() not in ("", "{}") and MARK not in old and not os.path.exists(schemes + ".before-themes"):
        # Schemes made in the terminal's own settings: kept beside, once.
        with open(schemes + ".before-themes", "w") as handle:
            handle.write(old)
    for key, text in cosmic_term_files(conf).items():
        if write_if_changed(os.path.join(COSMIC_TERM, key), text):
            changed.append("cosmic-term")
    before = COSMIC_THEME + ".before-themes"
    if os.path.isdir(COSMIC_THEME) and not os.path.exists(before):
        # What a COSMIC session (or its Settings) left there: kept, once.
        import shutil
        shutil.copytree(COSMIC_THEME, before)
    for key, text in cosmic_theme_files(conf).items():
        if write_if_changed(os.path.join(COSMIC_THEME, key), text):
            changed.append("cosmic-theme")
    kitty_conf = os.path.join(KITTY, "kitty.conf")
    if not os.path.exists(kitty_conf):
        write_if_changed(kitty_conf, "# kitty. Colours, font and opacity come from the desktop theme:\n"
                                     "# ~/.config/hypr/scripts/theme.py writes theme.conf (term.* keys).\n"
                                     "# Your own settings go BELOW the include, to win over the theme's.\n"
                                     "include theme.conf\n")
    if write_if_changed(os.path.join(KITTY, "theme.conf"), kitty_text(conf)):
        changed.append("kitty")
    if write_if_changed(PROMPT_FILE, prompt_text(conf)):
        changed.append("prompt")
    if os.path.isdir(MPV) and write_if_changed(os.path.join(MPV, "theme.conf"), mpv_text(conf)):
        changed.append("mpv")
    return sorted(set(changed))


WOFI_STYLE = os.path.join(HOME, ".config", "wofi", "style.css")
WOFI_IMPORT = re.compile(r'url\("file://[^"]*/\.config/waybar/generated/theme-wofi\.css"\)')


def fix_wofi_import(path=WOFI_STYLE):
    """wofi/style.css imports the generated theme-wofi.css by an ABSOLUTE
    file:// url (that file says why): point it at this home, whatever home
    it was written for (file://~/... or another user's /home/x/...). True
    when it had to change; nothing happens when it is right already."""
    try:
        with open(path) as handle:
            text = handle.read()
    except OSError:
        return False
    want = f'url("file://{GEN}/theme-wofi.css")'
    new = WOFI_IMPORT.sub(lambda _m: want, text)
    return new != text and write_if_changed(path, new)


def write_generated(conf, only_missing=False):
    """Every generated file for `conf`. Returns the targets that changed."""
    changed = []
    if fix_wofi_import():
        changed.append("wofi-import")
    for target, (path, _, _) in TARGETS.items():
        if only_missing and os.path.exists(path):
            continue
        if write_if_changed(path, generated_text(target, conf)):
            changed.append(target)
    if not (only_missing and os.path.exists(COLORS)):
        if write_if_changed(COLORS, colors_text(conf)):
            changed.append("colors")
    if not (only_missing and os.path.exists(LANG_FILE)):
        if write_if_changed(LANG_FILE, (conf.get("lang") or "en") + "\n"):
            changed.append("lang")
    if not (only_missing and os.path.exists(SEASON_FILE)):
        # The season these files are for: season-check compares it with the
        # season due now, so an unchanged season costs no re-apply.
        if write_if_changed(SEASON_FILE, conf.get("season", "") + "\n"):
            changed.append("season")
    if not (only_missing and os.path.exists(MODULES)):
        if write_if_changed(MODULES, modules_text(conf)):
            changed.append("modules")
    if not (only_missing and os.path.exists(bar_conf())):
        # `ensure` writes the theme's real one when it is missing: it is a
        # plain key file, so the "placeholder" is simply the right answer.
        if write_if_changed(bar_conf(), bar_text(conf)):
            changed.append("bar")
    # The lock screen's colours and fonts: ~/.config/hypr/hyprlock.conf
    # sources this after its own (cyberpunk) defaults; hyprlock reads it at
    # every lock, so nothing to restart. scripts/hyprlock_theme.py says
    # where each value comes from.
    import hyprlock_theme  # noqa: E402  (scripts/hyprlock_theme.py)
    lock = os.path.join(GEN, hyprlock_theme.NAME)
    if not (only_missing and os.path.exists(lock)):
        if write_if_changed(lock, hyprlock_theme.text(conf)):
            changed.append("hyprlock")
    if not only_missing:
        changed += write_terminals(conf)
    if only_missing:
        # The wallpaper accent's files are imported / included just as
        # unconditionally (theme-from-wallpaper.py owns them); a fresh restore
        # has none, so give each an empty one -- "no accent" -- until the first
        # re-pick writes the real thing.
        for path, text in ((os.path.join(GEN, "accent.css"),
                            "/* placeholder from theme.py ensure: no accent yet. */\n"),
                           (os.path.expanduser(MAKO_ACCENT),
                            "# placeholder from theme.py ensure: no accent yet.\n"),
                           # island.py's bar-centre look (match_bar), imported
                           # last by style.css; empty until the island writes it.
                           (os.path.join(GEN, "island-bar.css"),
                            "/* placeholder from theme.py ensure: no island look yet. */\n")):
            if not os.path.exists(path):
                write_if_changed(path, text)
                changed.append(os.path.basename(path))
    return changed


# -- applying ------------------------------------------------------------------
def run(cmd, timeout=10, **kw):
    """The CompletedProcess, None when it could not run or timed out."""
    return desk_common.run(cmd, timeout=timeout, **kw)


def icon_theme_dirs(name):
    """Every folder of icon theme `name` that has an index.theme, in lookup
    order (hicolor has several: ~/.local, flatpak's exports, /usr)."""
    if not name or "/" in name:
        return []
    data = [os.path.join(HOME, ".local", "share")]
    data += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    roots = [os.path.join(HOME, ".icons")] + [os.path.join(d, "icons") for d in data]
    return [os.path.join(r, name) for r in roots if os.path.isfile(os.path.join(r, name, "index.theme"))]


def icon_theme_dir(name):
    """The folder of icon theme `name`, or None."""
    return next(iter(icon_theme_dirs(name)), None)


def icon_theme_chain(name):
    """Folders of `name` and everything it Inherits=, depth first, then
    hicolor (the spec's last resort) -- mako's icon-path, which does not
    follow Inherits= by itself."""
    out, todo = [], [name]
    while todo:
        path = icon_theme_dir(todo.pop(0))
        if not path or path in out:
            continue
        out.append(path)
        inherits = (read_kv(os.path.join(path, "index.theme")) or {}).get("Inherits", "")
        todo = [n.strip() for n in inherits.split(",") if n.strip()] + todo
    hicolor = icon_theme_dirs("hicolor")
    return [p for p in out if p not in hicolor] + hicolor


def is_cursor_theme(name):
    path = icon_theme_dir(name)
    return bool(path) and os.path.isdir(os.path.join(path, "cursors"))


def apply_cursor(conf, force=False):
    """The pointer: theme (the user's cursor_theme_user over the theme's
    cursor_theme, already in conf) and size (display.conf cursor_size) to
    gsettings -- GTK apps -- and hyprctl setcursor -- Hyprland itself and
    XWayland, live. Only when gsettings disagrees (or force): setcursor
    reloads the cursor images. Returns True if it set anything."""
    want = conf.get("cursor_theme") or "Adwaita"
    if not is_cursor_theme(want):
        want = "Adwaita"
    size = cursor_size()
    schema = "org.gnome.desktop.interface"
    now = run(["gsettings", "get", schema, "cursor-theme"])
    now_size = run(["gsettings", "get", schema, "cursor-size"])
    if now is None:
        return False
    differs = (now.stdout.strip().strip("'") != want
               or (now_size is not None and now_size.stdout.strip() != size))
    if differs or force:
        run(["gsettings", "set", schema, "cursor-theme", want])
        run(["gsettings", "set", schema, "cursor-size", size])
        run(["hyprctl", "setcursor", want, size])
        return True
    return False


def apply_text(conf):
    """`theme.py fonts`: only what text and the pointer need -- the
    generated files (font rules, mako's font=), the terminals, mako
    reloaded, kitty signalled, the cursor. waybar, the panels and the
    launcher pick the generated stylesheets up by themselves (see "Copies,
    not symlinks" above); COSMIC Terminal watches its config folder."""
    changed = write_generated(conf)
    if "mako" in changed:
        run(["makoctl", "reload"])
    if "kitty" in changed:
        run(["pkill", "-USR1", "-x", "kitty"])
    if apply_cursor(conf):
        changed.append("cursor")
    return changed


def apply_gsettings(conf):
    schema = "org.gnome.desktop.interface"
    want = conf.get("icon_theme")
    if not icon_theme_dir(want):
        # Not installed / not built yet: Adwaita, never the last theme's set
        # (win95 -> aero kept the Windows 95 icons). `check` names the fix.
        want = DEFAULTS["icon_theme"]
    if want:
        now = run(["gsettings", "get", schema, "icon-theme"])
        if now is not None and now.stdout.strip().strip("'") != want:
            run(["gsettings", "set", schema, "icon-theme", want])
    for key, want, allowed in (("color-scheme", conf.get("gtk_color_scheme"), GTK_SCHEMES),
                               ("accent-color", conf.get("gtk_accent_color"), GTK_ACCENTS)):
        if want not in allowed:
            continue
        now = run(["gsettings", "get", schema, key])
        if now is not None and now.stdout.strip().strip("'") != want:
            run(["gsettings", "set", schema, key, want])
    # The title-bar buttons (orchard: the three dots on the left). Every other
    # theme inherits cyberpunk's appmenu:close, so leaving orchard puts the
    # stock layout back. Live: GTK4 windows follow the setting at once.
    layout = conf.get("gtk_button_layout", DEFAULTS["gtk_button_layout"])
    if button_layout_ok(layout):
        wm = "org.gnome.desktop.wm.preferences"
        now = run(["gsettings", "get", wm, "button-layout"])
        if now is not None and now.stdout.strip().strip("'") != layout:
            run(["gsettings", "set", wm, "button-layout", layout])


def button_layout_ok(value):
    """gtk_button_layout: at most one colon, comma-separated BUTTON_WORDS
    on either side (an empty side is fine: "close,minimize,maximize:")."""
    if not BUTTON_LAYOUT.match(value or "") or value.count(":") > 1:
        return False
    words = [w for side in value.split(":") for w in side.split(",") if w]
    return all(w in BUTTON_WORDS for w in words)


def wallpaper_matches(conf):
    prefix = conf.get("wallpaper_prefix", "")
    try:
        with open(SLIDESHOW_STATE) as handle:
            shown = os.path.basename(json.load(handle).get(screens.primary(), ""))
    except (OSError, ValueError):
        return False
    return shown.startswith(prefix)


def apply(conf, quiet=False):
    changed = write_generated(conf)
    apply_gsettings(conf)
    apply_cursor(conf)
    if "mako" in changed:
        run(["makoctl", "reload"])
    # The accent: from the wallpaper if the theme lets it follow (and the
    # switch is on), else the theme's own accent= -- written to
    # generated/accent.css and mako's accent file, and handed to the window
    # border through display.py accent, which re-runs lua/display.lua.
    run([ACCENT_SCRIPT, "refresh"], timeout=30, env=dict(os.environ, DISPLAY_QUIET="1"))
    # The Hyprland look (lua/display.lua reads theme= and this theme.conf).
    # display.py accent above already ran it; again here so a failure there
    # cannot leave the old border, gaps and rules behind.
    run(["hyprctl", "eval", 'require("lua.display").apply()'])
    if not wallpaper_matches(conf):
        # The slideshow re-reads the prefix on every pick; `next` makes it pick
        # now instead of at the next 10-minute turn.
        run([SLIDESHOW, "next"])
    # The toolbox's Display row (bar_signals "display") shows the theme in
    # its tooltip.
    bar_signals.poke("display")
    if "kitty" in changed:
        run(["pkill", "-USR1", "-x", "kitty"])     # kitty: reload kitty.conf
    if "modules" in changed:
        # The include is read with the config, not the style, so the bar has
        # to start again to pick it up. Not SIGUSR2: waybar 0.15 can crash
        # on that in-place reload (bar-restart.sh says why); bar-restart.sh
        # restarts the systemd unit (the toolbox comes back with it). Detached,
        # because it waits a moment to check the bar stayed up.
        try:
            subprocess.Popen([BAR_RESTART], start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            print(f"theme.py: bar restart: {exc}", file=sys.stderr)
    if "lang" in changed or "bar" in changed:
        # custom/day redraws in the new language; custom/logo,
        # custom/menuclock and custom/power (the same "day" signal) re-read
        # bar.conf -- custom/day blanks or comes back with bar.clock, the
        # power pill with an empty bar.logo. custom/clock's
        # watcher reads bar.conf by itself every tick.
        bar_signals.poke("day")
    if "colors" in changed:
        # updates.sh reads color.pending once per run and runs hourly, so the
        # pending box kept the old theme's colour for up to an hour: its
        # signal ("updates") re-runs it now. The weather glyph (wttr.py, every
        # 30 minutes) is the same story ("weather"), and wttr.py redraws it
        # from the answer it already has instead of fetching again.
        # (cpu_usage.sh / gpu_usage.sh re-read the colours every tick by
        # themselves.)
        bar_signals.poke("updates", "weather")
    return changed


def notify(title, body=""):
    if os.environ.get("DISPLAY_QUIET"):
        print(title + (f"\n{body}" if body else ""))
        return
    run([NOTIFY, "-a", "Display", "-u", "low", "-t", "6000" if body else "2500",
         "-h", "string:x-canonical-private-synchronous:display", title] + ([body] if body else []))


# -- other apps: Qt (qt5ct / qt6ct), Firefox, Chrome ------------------------------
# The theme's window colours (cosmic.background / cosmic.foreground, else the
# terminal's) and the accent in effect (the wallpaper's, your own, or the
# theme's) handed to the apps that do not read GTK's CSS. Called by
# theme-from-wallpaper.py each time it writes the accent, which a switch and
# `apply` always do, so a new accent reaches them too.
#
#   Qt       a colour scheme ~/.config/qt{5,6}ct/colors/DesktopTheme.conf, and
#            qt?ct.conf pointed at it (what it pointed at before is kept as
#            color_scheme_path_before_themes). KeePassXC is Qt 5. New
#            windows / the next start of the app.
#   Firefox  <profile>/chrome/theme-colors.css (the tab strip, toolbars, url
#            bar, menus), @import-ed by userChrome.css, and the user.js pref
#            that lets Firefox read it -- every profile in profiles.ini.
#            Firefox reads it at its start: the next one.
#   Chrome   (Flatpak) its own "Customize Chrome" colour: browser.theme.
#            user_color2 and color_scheme2 in Default/Preferences. Chrome
#            rewrites that file while it runs, so with Chrome open a detached
#            `theme.py chrome-watch` waits for it to close and writes then.
QT_DIRS = [os.path.join(HOME, ".config", d) for d in ("qt5ct", "qt6ct")]
QT_SCHEME = "DesktopTheme.conf"
FIREFOX_DIRS = [os.path.join(HOME, ".config", "mozilla", "firefox"), os.path.join(HOME, ".mozilla", "firefox")]
FIREFOX_PREF = 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);'
CHROME_PREFS = os.path.join(HOME, ".var", "app", "com.google.Chrome", "config", "google-chrome",
                            "Default", "Preferences")
CHROME_APP = "com.google.Chrome"
CHROME_WATCH_PID = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "theme-chrome-watch.pid")


def rgb_hex(rgb):
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02x}" for c in rgb)


def mix(a, b, t):
    """t of the way from colour a to colour b (#rrggbb)."""
    return rgb_hex([x + (y - x) * t for x, y in zip(hex_rgb(a), hex_rgb(b))])


def app_colours(conf, accent=None):
    """{bg, fg, accent, light} for the apps above."""
    bg = conf.get("cosmic.background") or conf.get("term.background") or "#0d1018"
    fg = conf.get("cosmic.foreground") or conf.get("term.foreground") or "#c8d3e6"
    accent = accent or conf.get("accent") or conf.get("cosmic.accent") or "#00f0ff"
    # The accent ROLE is made for the theme's own surfaces, which may not be
    # these apps': luna's #18439a is a text colour for the cream cards, and on
    # the console-blue window here it is 1.66:1 -- Qt's links and selection,
    # Firefox's highlight and Chrome's seed would all vanish. Below 3:1 (a UI
    # colour's floor) cosmic.accent, the accent chosen for this dark
    # background, stands in, if it reads better.
    spare = conf.get("cosmic.accent")
    if spare and contrast(hex_rgb(accent), hex_rgb(bg)) < READABLE_COLOURS \
            and contrast(hex_rgb(spare), hex_rgb(bg)) > contrast(hex_rgb(accent), hex_rgb(bg)):
        accent = spare
    light = contrast(hex_rgb(bg), [0, 0, 0]) > contrast(hex_rgb(bg), [1, 1, 1])
    return {"bg": bg, "fg": fg, "accent": accent, "light": light}


def on_colour(c):
    """Black or white, whichever reads better on c."""
    return "#000000" if contrast(hex_rgb(c), [0, 0, 0]) >= contrast(hex_rgb(c), [1, 1, 1]) else "#ffffff"


def qt_text(col):
    bg, fg, acc = col["bg"], col["fg"], col["accent"]
    base = mix(bg, "#ffffff", 0.55) if col["light"] else mix(bg, fg, 0.05)
    # QPalette::ColorRole order: WindowText Button Light Midlight Dark Mid Text
    # BrightText ButtonText Base Window Shadow Highlight HighlightedText Link
    # LinkVisited AlternateBase NoRole ToolTipBase ToolTipText PlaceholderText
    roles = [fg, mix(bg, fg, 0.10), mix(bg, fg, 0.25), mix(bg, fg, 0.18), mix(bg, "#000000", 0.35),
             mix(bg, fg, 0.14), fg, "#ffffff", fg, base, bg, "#000000", acc, on_colour(acc), acc,
             mix(acc, fg, 0.3), mix(base, fg, 0.05), bg, mix(bg, fg, 0.08), fg, mix(bg, fg, 0.55)]
    faded = [mix(c, bg, 0.5) if i in (0, 6, 8, 19, 20) else c for i, c in enumerate(roles)]
    row = lambda cs: ", ".join("#ff" + c[1:] for c in cs)
    return (f"# {MARK} -- do not edit.\n[ColorScheme]\n"
            f"active_colors={row(roles)}\ndisabled_colors={row(faded)}\ninactive_colors={row(roles)}\n")


def apply_qt(col):
    for folder in QT_DIRS:
        conf_path = os.path.join(folder, os.path.basename(folder) + ".conf")
        if not os.path.isfile(conf_path):
            continue
        scheme = os.path.join(folder, "colors", QT_SCHEME)
        write_if_changed(scheme, qt_text(col))
        with open(conf_path) as handle:
            lines = handle.read().split("\n")
        out, seen = [], False
        for line in lines:
            if line.startswith("color_scheme_path="):
                old = line.split("=", 1)[1]
                if old != scheme and not any(l.startswith("color_scheme_path_before_themes=") for l in lines):
                    out.append(f"color_scheme_path_before_themes={old}")
                line, seen = f"color_scheme_path={scheme}", True
            elif line.startswith("custom_palette="):
                line = "custom_palette=true"
            out.append(line)
        if not seen:
            i = out.index("[Appearance]") + 1 if "[Appearance]" in out else len(out)
            out[i:i] = ([] if "[Appearance]" in out else ["[Appearance]"]) + \
                [f"color_scheme_path={scheme}", "custom_palette=true"]
        write_if_changed(conf_path, "\n".join(out))


def firefox_profiles():
    found = []
    for root in FIREFOX_DIRS:
        ini = os.path.join(root, "profiles.ini")
        try:
            with open(ini) as handle:
                text = handle.read()
        except OSError:
            continue
        for block in text.split("\n["):
            kv = dict(l.split("=", 1) for l in block.splitlines() if "=" in l)
            if "Path" in kv:
                path = os.path.join(root, kv["Path"]) if kv.get("IsRelative") == "1" else kv["Path"]
                if os.path.isdir(path):
                    found.append(path)
    return found


def firefox_text(col):
    bg, fg, acc = col["bg"], col["fg"], col["accent"]
    bar = mix(bg, fg, 0.07)
    field = mix(bg, "#ffffff", 0.6) if col["light"] else mix(bg, fg, 0.12)
    v = {"toolbox-bgcolor": bg, "toolbox-bgcolor-inactive": bg, "toolbox-textcolor": fg,
         "toolbox-textcolor-inactive": fg, "toolbar-bgcolor": bar, "toolbar-color": fg,
         "tab-selected-bgcolor": bar, "tab-selected-textcolor": fg, "tab-loading-fill": acc,
         "lwt-tab-line-color": acc, "toolbar-field-background-color": field, "toolbar-field-color": fg,
         "toolbar-field-focus-background-color": field, "toolbar-field-focus-color": fg,
         "toolbar-field-focus-border-color": acc, "focus-outline-color": acc,
         "arrowpanel-background": bar, "arrowpanel-color": fg, "sidebar-background-color": bg,
         "sidebar-text-color": fg, "urlbarView-highlight-background": acc,
         "urlbarView-highlight-color": on_colour(acc)}
    body = "\n".join(f"  --{k}: {c} !important;" for k, c in v.items())
    return (f"/* {MARK} -- do not edit; userChrome.css imports it. */\n"
            f":root, #navigator-toolbox {{\n{body}\n}}\n"
            f"#navigator-toolbox, #TabsToolbar {{ background-color: {bg} !important; color: {fg} !important; }}\n"
            f".tab-background[selected] {{ background: {bar} !important; "
            f"box-shadow: inset 0 2px 0 {acc} !important; }}\n")


def apply_firefox(col):
    text = firefox_text(col)
    for profile in firefox_profiles():
        chrome = os.path.join(profile, "chrome")
        write_if_changed(os.path.join(chrome, "theme-colors.css"), text)
        user_chrome = os.path.join(chrome, "userChrome.css")
        try:
            with open(user_chrome) as handle:
                current_css = handle.read()
        except OSError:
            current_css = ""
        if "theme-colors.css" not in current_css:
            # @import must come before every other rule: put it first.
            write_if_changed(user_chrome, '@import "theme-colors.css";  /* the desktop theme (theme.py) */\n'
                             + current_css)
        user_js = os.path.join(profile, "user.js")
        try:
            with open(user_js) as handle:
                js = handle.read()
        except OSError:
            js = ""
        if FIREFOX_PREF not in js:
            write_if_changed(user_js, js + ("" if js.endswith("\n") or not js else "\n")
                             + "// userChrome.css (the desktop theme's colours, theme.py)\n" + FIREFOX_PREF + "\n")


def chrome_running():
    out = run(["flatpak", "ps", "--columns=application"])
    return out is not None and CHROME_APP in out.stdout.split()


def chrome_write(col, scheme):
    """Chrome's own colour + light / dark into its Preferences (closed only)."""
    try:
        with open(CHROME_PREFS) as handle:
            prefs = json.load(handle)
    except (OSError, ValueError):
        return False
    r, g, b = (round(c * 255) for c in hex_rgb(col["accent"]))
    argb = (0xFF << 24) | (r << 16) | (g << 8) | b
    themes = prefs.setdefault("browser", {}).setdefault("theme", {})
    themes["user_color2"] = argb - (1 << 32)            # an SkColor, stored as a signed int
    themes["color_scheme2"] = {"prefer-light": 1, "prefer-dark": 2}.get(scheme, 0)
    themes["is_grayscale2"] = False
    ext = prefs.setdefault("extensions", {}).setdefault("theme", {})
    ext["id"] = ""                                      # no theme extension over it
    ext["system_theme"] = 0                             # Chrome's own colours, not GTK's
    tmp = CHROME_PREFS + ".theme-tmp"
    with open(tmp, "w") as handle:
        json.dump(prefs, handle, separators=(",", ":"))
    os.replace(tmp, CHROME_PREFS)
    return True


def apply_chrome(col, scheme):
    if not os.path.isfile(CHROME_PREFS):
        return
    if not chrome_running():
        chrome_write(col, scheme)
        return
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "chrome-watch",
                      json.dumps({"col": col, "scheme": scheme})],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_chrome_watch(arg):
    """Detached: wait for Chrome to close, then write its colour. A newer
    watcher (a newer theme or accent) replaces this one."""
    try:
        with open(CHROME_WATCH_PID) as handle:
            old = int(handle.read().strip())
        with open(f"/proc/{old}/cmdline", "rb") as handle:
            if b"chrome-watch" in handle.read() and old != os.getpid():
                os.kill(old, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    with open(CHROME_WATCH_PID, "w") as handle:
        handle.write(str(os.getpid()))
    info = json.loads(arg)
    deadline = time.time() + WATCH_FOR
    while time.time() < deadline:
        if not chrome_running():
            time.sleep(2)               # let it finish writing Preferences on the way out
            chrome_write(info["col"], info["scheme"])
            return
        time.sleep(5)


def apply_apps(accent=None, conf=None):
    """Qt, Firefox and Chrome in the theme's colours with this accent."""
    conf = conf or load()
    col = app_colours(conf, accent)
    for step in (lambda: apply_qt(col), lambda: apply_firefox(col),
                 lambda: apply_chrome(col, conf.get("gtk_color_scheme", "prefer-dark"))):
        try:
            step()
        except (OSError, ValueError) as exc:
            print(f"theme.py: apps: {exc}", file=sys.stderr)


# -- Nautilus (GTK4 reads gtk.css once) ---------------------------------------
# GTK4 reads ~/.config/gtk-4.0/gtk.css once, at process start, and Nautilus
# is ONE long-lived process for all its windows -- so even a NEW window keeps
# the old theme until that process ends, which on a desktop that is never
# logged out may be never. Found reviewing matrix (gsettings accent green,
# the new window stock Adwaita grey) and again with aero: the owner's
# Nautilus had been running since the morning, and "open Files" after a
# switch gave plain grey Adwaita, no navy glass, no Selawik. A note in the
# toast was not enough: nobody restarts a file manager by hand.
#
# So, after a switch that changed gtk.css:
#   * Nautilus running with NO window open (it stays resident after its last
#     window closes): `nautilus -q` at once. Nothing visible ends; the next
#     "open Files" starts a fresh process that reads the new gtk.css.
#   * Nautilus with windows: never quit behind the user's back. A detached
#     watcher (`theme.py nautilus-watch`) waits for the last window to close
#     and quits it then, and the toast carries a one-click "Restart Files"
#     (mako's left click is invoke-default-action) that closes its windows
#     and opens one fresh one -- the toast says so in as many words.
# "Windowless" also needs Nautilus to be idle: a copy keeps running after its
# window is closed, and -q would cancel it, so a quit waits until the
# process has moved under 1 MiB in a poll interval (/proc/<pid>/io).
NAUTILUS = "nautilus"
NAUTILUS_CLASS = "org.gnome.Nautilus"
GTK4_CSS = TARGETS["gtk4.css"][0]
WATCH_PID = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "theme-nautilus-watch.pid")
WATCH_POLL = 3                      # seconds between looks
WATCH_FOR = 24 * 3600               # give up after a day; the next switch starts another
BUSY_BYTES = 1 << 20                # I/O per poll that counts as "a file operation is running"


def nautilus_pid():
    found = run(["pgrep", "-x", NAUTILUS])
    if found is None or found.returncode != 0:
        return None
    pids = [int(p) for p in found.stdout.split() if p.isdigit()]
    return min(pids) if pids else None


def started_at(pid):
    """A process's start time, in epoch seconds (None if it is gone)."""
    try:
        with open(f"/proc/{pid}/stat") as handle:
            # Field 22 (starttime, clock ticks after boot); the command name
            # in field 2 may hold spaces, so count from its closing paren.
            ticks = int(handle.read().rsplit(")", 1)[1].split()[19])
        with open("/proc/stat") as handle:
            boot = next(int(line.split()[1]) for line in handle if line.startswith("btime "))
    except (OSError, ValueError, IndexError, StopIteration):
        return None
    return boot + ticks / os.sysconf("SC_CLK_TCK")


def nautilus_stale():
    """The running Nautilus's pid when it predates the current gtk.css (it
    still shows an older theme), else None."""
    pid = nautilus_pid()
    if pid is None:
        return None
    try:
        written = os.path.getmtime(GTK4_CSS)
    except OSError:
        return None
    start = started_at(pid)
    return pid if start is not None and start < written else None


def nautilus_windows(pid):
    """How many windows process `pid` has open, or None if Hyprland did not
    answer (then nothing may be quit). By pid as well as class: every window
    of a GApplication belongs to its one primary process, and a second,
    separate Nautilus (another D-Bus session) must not count."""
    out = run(["hyprctl", "clients", "-j"])
    try:
        return sum(1 for c in json.loads(out.stdout)
                   if c.get("class") == NAUTILUS_CLASS and c.get("pid") == pid)
    except (AttributeError, ValueError, TypeError):
        return None


def io_bytes(pid):
    try:
        with open(f"/proc/{pid}/io") as handle:
            fields = dict(line.split(":") for line in handle)
        return int(fields["rchar"]) + int(fields["wchar"])
    except (OSError, ValueError, KeyError):
        return None


def nautilus_quit(reopen=False):
    run([NAUTILUS, "-q"], timeout=10)
    for _ in range(50):             # up to 5 s for the process to end
        if nautilus_pid() is None:
            break
        time.sleep(0.1)
    if reopen:
        subprocess.Popen([NAUTILUS, "--new-window"], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def gtk4_restart(changed, title):
    """After a switch: quit a windowless Nautilus now, or hand over to the
    watcher (which sends the toast itself, with the Restart button). Returns
    True when the watcher took the toast over."""
    if "gtk4.css" not in changed:
        return False
    pid = nautilus_stale()
    if pid is None:
        return False
    windows = nautilus_windows(pid)
    if windows == 0:
        before = io_bytes(pid)
        time.sleep(1)
        after = io_bytes(pid)
        if before is not None and after is not None and after - before < BUSY_BYTES:
            nautilus_quit()
            return False
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "nautilus-watch", title],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def cmd_nautilus_watch(title):
    """The detached half of gtk4_restart (see the block comment above)."""
    # One watcher at a time: a newer switch replaces the older watcher.
    try:
        with open(WATCH_PID) as handle:
            old = int(handle.read().strip())
        with open(f"/proc/{old}/cmdline", "rb") as handle:
            if b"nautilus-watch" in handle.read() and old != os.getpid():
                os.kill(old, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    with open(WATCH_PID, "w") as handle:
        handle.write(str(os.getpid()))
    windows = nautilus_windows(nautilus_pid()) or 0
    body = (f"Files (Nautilus) keeps the old look until it restarts. It restarts by itself "
            f"once its window{'s are' if windows != 1 else ' is'} closed -- or click here to "
            f"restart it now (closes its {windows} window{'s' if windows != 1 else ''} "
            f"and opens a fresh one).")
    toast = None
    try:
        # -w: wait for the click (or the close) and print the action's name.
        # Not the "display" synchronous slot of the other theme toasts: a
        # later accent toast must not silently take the button away.
        toast = subprocess.Popen(
            [NOTIFY, "-a", "Display", "-u", "normal", "-t", "15000", "-w",
             "-A", "default=Restart Files now", title, body],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        pass
    last_io = None
    deadline = time.monotonic() + WATCH_FOR
    try:
        while time.monotonic() < deadline:
            if toast is not None and toast.poll() is not None:
                if toast.stdout.read().strip() == "default" and nautilus_stale():
                    nautilus_quit(reopen=True)
                    return
                toast = None        # closed or timed out: keep watching quietly
            pid = nautilus_stale()
            if pid is None:
                return              # restarted (or gone) some other way: done
            io = io_bytes(pid)
            idle = last_io is not None and io is not None and io - last_io < BUSY_BYTES
            last_io = io
            if idle and nautilus_windows(pid) == 0:
                nautilus_quit()
                return
            time.sleep(WATCH_POLL)
    finally:
        if toast is not None and toast.poll() is None:
            toast.terminate()
        try:
            with open(WATCH_PID) as handle:
                if handle.read().strip() == str(os.getpid()):
                    os.remove(WATCH_PID)
        except OSError:
            pass


# The switch's cross-fade (theme-fade.py: a still of every screen over the
# change, faded out after it) and its sound (theme-sound.sh switch). fade=off
# in display.conf turns the fade off (the display panel's switch); a screen
# it cannot cover just switches without one.
FADE = os.path.join(HYPR, "theme-fade.py")
THEME_SOUND = os.path.join(HYPR, "theme-sound.sh")
FADE_READY_S = 3


def start_fade():
    try:
        proc = subprocess.Popen([sys.executable, FADE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    except OSError:
        return None
    import select
    ready, _, _ = select.select([proc.stdout], [], [], FADE_READY_S)
    if ready and proc.stdout.readline().strip() == "ready":
        return proc
    proc.kill()
    return None


def end_fade(proc):
    if proc is None:
        return
    try:
        proc.stdin.write("done\n")
        proc.stdin.close()
    except (OSError, ValueError):
        pass


# -- the island hand-off ------------------------------------------------------------
# A theme may want the dynamic island a certain way (orchard: on, the black
# notch, the bar's centre matching it -- the camera housing of a menu bar).
# `set` hands island.* over to island.py and remembers what you had, once,
# in ISLAND_SNAPSHOT:
#     {"saved":   {key: your value before the first island theme},
#      "applied": {key: the value the current island theme set},
#      "theme":   that theme}
# Switching to a theme that wants none of them puts each saved key back --
# but only where the live value is still the one the theme applied: a style
# you picked in Settings while on orchard is yours and stays. Then the file
# goes. orchard -> orchard-dark keeps the FIRST snapshot (saved is only ever
# added to), so the way back is always to what you had before either.
# Only cmd_set calls this: apply, ensure (every login) and the season ticks
# never touch the island, and island.py's own DEFAULTS stay as they are.
def island_word(key, value):
    """A conf / snapshot value as `island.py set` takes it."""
    if key == "style":
        return str(value)
    return "on" if value else "off"


def island_wanted(conf):
    """{key: value} of the island.* keys this conf sets, normalised as
    island.json holds them (yes/no -> bool); unset or unreadable = absent."""
    want = {}
    for key in ISLAND_KEYS:
        raw = (conf.get(f"island.{key}") or "").strip().lower()
        if not raw:
            continue
        if key == "style":
            if raw in ISLAND_STYLES:
                want[key] = raw
        elif raw in ("yes", "no"):
            want[key] = raw == "yes"
    return want


def island_live(run=run):
    """island.json's settings through `island.py status --json`, or None
    (no island.py, a broken one, unreadable answer)."""
    out = run([sys.executable, ISLAND, "status", "--json"])
    if out is None or out.returncode != 0:
        return None
    try:
        settings = json.loads(out.stdout or "").get("settings")
    except (ValueError, AttributeError):
        return None
    return settings if isinstance(settings, dict) else None


def read_island_snapshot():
    try:
        with open(ISLAND_SNAPSHOT) as handle:
            snap = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(snap, dict):
        return None
    snap["saved"] = snap.get("saved") if isinstance(snap.get("saved"), dict) else {}
    snap["applied"] = snap.get("applied") if isinstance(snap.get("applied"), dict) else {}
    return snap


def write_island_snapshot(snap):
    os.makedirs(os.path.dirname(ISLAND_SNAPSHOT), exist_ok=True)
    tmp = f"{ISLAND_SNAPSHOT}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        json.dump(snap, handle, indent=1, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, ISLAND_SNAPSHOT)


def island_handoff(conf, run=run):
    """Give the island what theme `conf` wants, or give you back what you
    had (see above). Returns the `island.py set` calls made, as
    [(key, word)]. Any failure (island.py missing, a set refused) is a line
    on stderr, never an error: a theme switch must not fail on the island."""
    calls = []
    want = island_wanted(conf)
    snap = read_island_snapshot()
    if not want and snap is None:
        return calls                # the usual case: nothing to do, no island.py run
    live = island_live(run)
    if live is None:
        print("theme.py: island hand-off skipped (island.py status failed)", file=sys.stderr)
        return calls

    def send(key, value):
        out = run([sys.executable, ISLAND, "set", key, island_word(key, value)], timeout=30)
        if out is None or out.returncode != 0:
            why = (out.stderr or "").strip() if out is not None else "did not run"
            print(f"theme.py: island.py set {key}: {why}", file=sys.stderr)
        calls.append((key, island_word(key, value)))

    snap = snap or {"saved": {}, "applied": {}}
    # Keys the new theme no longer sets: back to yours (unless you changed
    # them meanwhile). With nothing wanted, that is all of them. Off goes
    # first when it is the way back, so the old look never flashes.
    back = [k for k in ISLAND_KEYS if k in snap["saved"] and k not in want]
    if snap["saved"].get("enabled") is False and "enabled" in back:
        back = ["enabled"] + [k for k in back if k != "enabled"]
    for key in back:
        if key in live and live[key] == snap["applied"].get(key):
            send(key, snap["saved"][key])
        snap["saved"].pop(key, None)
        snap["applied"].pop(key, None)
    if not want:
        try:
            os.remove(ISLAND_SNAPSHOT)
        except OSError:
            pass
        return calls
    for key in want:
        if key not in snap["saved"] and key in live:
            snap["saved"][key] = live[key]
    snap["applied"] = dict(want)
    snap["theme"] = conf.get("id", "")
    # Written before the calls: a switch cut short still knows the way back.
    write_island_snapshot(snap)
    for key in ISLAND_KEYS:         # style, match_bar, then enabled
        if key in want and live.get(key) != want[key]:
            send(key, want[key])
    return calls


def cmd_set(name):
    if not exists(name):
        have = ", ".join(n for n, _ in themes())
        print(f"theme.py: no theme {name!r} (have: {have})", file=sys.stderr)
        sys.exit(1)
    conf = load(name)
    state = read_state()
    fade = start_fade() if state.get("fade") != "off" and name != state.get("theme") else None
    state["theme"] = name
    if conf.get("anim") in PRESETS:
        state["anim"] = conf["anim"]
    write_state(state)
    try:
        changed = apply(conf)
        # Under the fade, so the bar's centre turning into the notch (or
        # back) is hidden with the rest of the switch.
        island_handoff(conf)
    finally:
        end_fade(fade)
    switch_sound()
    title = f"Theme: {conf.get('name') or name}"
    # The Files toast goes out even from the display panel (DISPLAY_QUIET):
    # the panel shows the theme, but it has no way to say that Files lags.
    if not gtk4_restart(changed, title):
        notify(title)


# -- check ---------------------------------------------------------------------
KNOWN = set(DEFAULTS) | {
    "term.background", "term.foreground", "term.cursor", "term.normal", "term.bright",
    "term.font", "term.font_size", "term.bright_bold",
    "cosmic.background", "cosmic.foreground", "cosmic.accent", "cosmic.radius",
    "hypr.rounding", "hypr.gaps_in", "hypr.gaps_out", "hypr.border_size",
    "hypr.active_border", "hypr.inactive_border", "hypr.accent_stops",
    "hypr.blur", "hypr.blur_size", "hypr.blur_passes", "hypr.blur_brightness",
    "hypr.blur_contrast", "hypr.blur_vibrancy", "hypr.blur_vibrancy_darkness",
    "hypr.blur_noise", "hypr.shadow", "hypr.shadow_range", "hypr.shadow_render_power",
    "hypr.shadow_color", "hypr.shadow_color_inactive", "hypr.shadow_offset", "hypr.rounding_power",
}


# Runs a theme's hypr.lua (plain data: it only returns a table) and prints
# "kind<TAB>name" per rule, or "ERR<TAB>message".
LUA_RULE_NAMES = r"""
local ok, t = pcall(dofile, os.getenv("THEME_HYPR_LUA"))
if not ok then print("ERR\t" .. tostring(t)) return end
if type(t) ~= "table" then print("ERR\tdoes not return a table") return end
for _, kind in ipairs({ "window", "layer" }) do
    for i, r in ipairs(t[kind .. "_rules"] or {}) do
        print(kind .. "\t" .. (type(r) == "table" and tostring(r.name) or "ERR"))
    end
end
"""


def hypr_rule_names(name):
    """[(kind, rule name)] of a theme's hypr.lua; None if it has none;
    [("ERR", why)] if it does not load."""
    path = os.path.join(theme_dir(name), "hypr.lua")
    if not os.path.isfile(path):
        return None
    lua = next((p for p in ("/usr/bin/luajit", "/usr/bin/lua") if os.access(p, os.X_OK)), None)
    if not lua:
        return []
    out = run([lua, "-e", LUA_RULE_NAMES], env=dict(os.environ, THEME_HYPR_LUA=path))
    if out is None:
        return [("ERR", f"{lua} did not run")]
    rows = [tuple(line.split("\t", 1)) for line in out.stdout.splitlines() if "\t" in line]
    if out.returncode and not rows:
        rows = [("ERR", out.stderr.strip())]
    return rows


def check_hypr_lua(name):
    """lua/display.lua loads hypr.lua under pcall and skips a broken one
    silently -- the theme just loses its rules -- and it keys the rules it
    creates by name, so a name another theme already used would reuse THAT
    theme's rule (enabled for the wrong theme, never with this one's fields).
    Both only show up here."""
    rows = hypr_rule_names(name)
    if not rows:
        return []
    problems = [f"hypr.lua: {why}" for kind, why in rows if kind == "ERR"]
    mine = {(k, n) for k, n in rows if k != "ERR"}
    for k, n in sorted(mine):
        if n in ("nil", "ERR"):
            problems.append(f"hypr.lua: a {k} rule without a name")
    if len(mine) < len([r for r in rows if r[0] != "ERR"]):
        problems.append("hypr.lua: the same rule name twice")
    for other, _ in themes():
        if other == name:
            continue
        clash = mine & set(hypr_rule_names(other) or [])
        for k, n in sorted(clash):
            problems.append(f"hypr.lua: {k} rule {n!r} is also in {other}/hypr.lua (names must be unique)")
    return problems


# Why a key a season's theme.conf may not set stays the theme's all year.
SEASON_FIXED_WHY = {
    "hypr.": "lua/display.lua reads it from theme.conf",
    "font": "a face that changed with the season would change every panel's size",
    "font_mono": "a face that changed with the season would change every panel's size",
    "term.font": "a face that changed with the season would change every panel's size",
    "term.font_size": "a size that changed with the season would move the terminals",
    "lang": "lua/env.lua and the bar read it from theme.conf",
    "anim": "lua/display.lua reads it from theme.conf",
    "cursor_theme": "lua/env.lua reads it from theme.conf",
    "crt_suggest": "display_panel.py reads it from theme.conf",
}
SEASON_FILE_WHY = {"hypr.lua": "lua/display.lua reads hypr.lua from the theme folder itself",
                   "sounds": "theme-sound.sh and timers.py read sounds/ from the theme folder itself"}


def check_seasons(name):
    """Problems in a seasonal theme's season/ folder: a season without its
    theme.conf or palette.css, a key its theme.conf may not set (with why
    it is the theme's all year), a file theme.py would never read."""
    problems = []
    for s in SEASONS:
        folder = season_dir(name, s)
        where = f"{SEASON_DIR}/{s}"
        if not os.path.isdir(folder):
            problems.append(f"{where}/: missing (every season needs a folder)")
            continue
        over = read_kv(os.path.join(folder, "theme.conf"))
        if over is None:
            problems.append(f"{where}/theme.conf: missing")
        for key in over or {}:
            if key not in KNOWN and not key.startswith("color."):
                problems.append(f"{where}/theme.conf: unknown key {key!r}")
            elif not season_allowed(key):
                why = SEASON_FIXED_WHY.get(key) or next(
                    (w for k, w in SEASON_FIXED_WHY.items() if k.endswith(".") and key.startswith(k)),
                    "the theme's own key, the same all year")
                problems.append(f"{where}/theme.conf: {key} is ignored -- the theme's all year: {why}")
        if not os.path.isfile(os.path.join(folder, "palette.css")):
            problems.append(f"{where}/palette.css: missing (the s-* names every GTK3 stylesheet uses)")
        for entry in sorted(os.listdir(folder)):
            if entry not in SEASON_FILES:
                why = SEASON_FILE_WHY.get(entry, f"not a season file ({', '.join(sorted(SEASON_FILES))})")
                problems.append(f"{where}/{entry}: never read -- {why}")
    try:
        stray = sorted(set(os.listdir(os.path.join(theme_dir(name), SEASON_DIR))) - set(SEASONS))
    except OSError:
        stray = []
    for entry in stray:
        problems.append(f"{SEASON_DIR}/{entry}: not a season ({', '.join(SEASONS)})")
    return problems


def cmd_check(name):
    """Lint a theme. Exit 1 on any problem. Parses each stylesheet with GTK
    as it will really be loaded: the base file with the generated override
    in place of the live one, so a missing palette name or a typo shows here
    instead of as an unstyled bar. A seasonal theme is checked in every
    season (check_seasons, then check_conf once per season); a problem the
    four share is printed once, the others with a [season] prefix."""
    if not exists(name):
        print(f"no theme {name!r} in {THEMES_DIR}")
        sys.exit(1)
    own = read_kv(os.path.join(theme_dir(name), "theme.conf")) or {}
    if not seasonal(name):
        # The theme's own, not your overrides.
        problems = check_conf(name, load(name, user=False, season=""), own)
    else:
        problems = check_seasons(name)
        per = {}
        for s in SEASONS:
            mine = read_kv(os.path.join(season_dir(name, s), "theme.conf")) or {}
            keys = dict(own, **{k: v for k, v in mine.items() if season_allowed(k)})
            per[s] = check_conf(name, load(name, user=False, season=s), keys)
        shared = set.intersection(*(set(v) for v in per.values()))
        seen = set()
        for s in SEASONS:
            for p in per[s]:
                if p in shared:
                    if p not in seen:
                        seen.add(p)
                        problems.append(p)
                else:
                    problems.append(f"[{s}] {p}")
    for p in problems:
        print("  " + p)
    print(f"{name}: {'OK' if not problems else f'{len(problems)} problem(s)'}")
    sys.exit(1 if problems else 0)


def check_layout_keys(conf):
    """The newer keys' lint, kept apart from check_conf so it needs no GTK
    and no installed fonts (tests/test_theme_island.py runs it): the window
    shape and shadow, the title-bar buttons, the island hand-off, the bar's
    layout."""
    problems = []
    if conf.get("hypr.rounding_power", ""):
        try:
            if not 1 <= float(conf["hypr.rounding_power"]) <= 10:
                raise ValueError
        except ValueError:
            problems.append(f"hypr.rounding_power={conf['hypr.rounding_power']!r}: a number 1-10")
    offset = conf.get("hypr.shadow_offset", "")
    if offset and not re.match(r"^-?\d+(\.\d+)?\s+-?\d+(\.\d+)?$", offset):
        problems.append(f"hypr.shadow_offset={offset!r}: two numbers, \"x y\" (px)")
    inactive = conf.get("hypr.shadow_color_inactive", "")
    if inactive and not re.match(r"^rgba?\([0-9a-fA-F]{6}([0-9a-fA-F]{2})?\)$", inactive):
        problems.append(f"hypr.shadow_color_inactive={inactive!r}: rgba(rrggbbaa) or empty")
    if not button_layout_ok(conf.get("gtk_button_layout", "")):
        problems.append(f"gtk_button_layout={conf.get('gtk_button_layout')!r}: words from "
                        f"{', '.join(BUTTON_WORDS)}, comma-separated, one colon at most")
    if conf.get("island.style", "") not in ("",) + ISLAND_STYLES:
        problems.append(f"island.style={conf.get('island.style')!r}: one of {', '.join(ISLAND_STYLES)}, or empty")
    for key in ("island.enabled", "island.match_bar"):
        if conf.get(key, "") not in ("", "yes", "no"):
            problems.append(f"{key}={conf.get(key)!r}: yes, no or empty")
    if conf.get("bar.clock", "") not in BAR_CLOCKS:
        problems.append(f"bar.clock={conf.get('bar.clock')!r}: menubar or empty")
    if conf.get("bar.workspaces", "") not in BAR_WORKSPACES:
        problems.append(f"bar.workspaces={conf.get('bar.workspaces')!r}: dots or empty")
    if len(conf.get("bar.logo", "")) > 4:
        problems.append(f"bar.logo={conf.get('bar.logo')!r}: a glyph or two, not text")
    start = conf.get("dock.start", "")
    if len(start) > DOCK_START_MAX or "\n" in start:
        problems.append(f"dock.start={start!r}: one short word (at most {DOCK_START_MAX} characters)")
    if conf.get("dock.magnify", "") not in DOCK_MAGNIFY:
        problems.append(f"dock.magnify={conf.get('dock.magnify')!r}: yes, no or empty")
    return problems


def check_conf(name, conf, own):
    """Problems of one resolved conf of theme `name` (`own`: the keys its
    files set): keys and colours, the terminal font, icons, wallpapers,
    hypr.lua and the GTK parse of every stylesheet."""
    problems = []
    for key in own:
        if key not in KNOWN and not key.startswith("color."):
            problems.append(f"theme.conf: unknown key {key!r}")
    if conf.get("accent") and not HEX.match(conf["accent"]):
        problems.append(f"accent={conf['accent']!r} is not #rrggbb")
    for key in (k for k in conf if k.startswith("color.")):
        if not HEX.match(conf[key]):
            problems.append(f"{key}={conf[key]!r} is not #rrggbb")
    cur = conf.get("cursor_theme", "Adwaita")
    if not (icon_theme_dir(cur) and os.path.isdir(os.path.join(icon_theme_dir(cur), "cursors"))):
        problems.append(f"cursor_theme={cur!r}: no such cursor theme (Adwaita until there is)")
    if conf.get("lang", "en") not in ("en", "ja"):
        problems.append(f"lang={conf.get('lang')!r}: en or ja")
    if conf.get("anim") not in PRESETS:
        problems.append(f"anim={conf.get('anim')!r} is not one of {PRESETS}")
    if conf.get("gtk_accent_color") not in GTK_ACCENTS:
        problems.append(f"gtk_accent_color={conf.get('gtk_accent_color')!r} not in {GTK_ACCENTS}")
    if conf.get("gtk_color_scheme") not in GTK_SCHEMES:
        problems.append(f"gtk_color_scheme={conf.get('gtk_color_scheme')!r} not in {GTK_SCHEMES}")
    if not conf.get("term.font_size", "").isdigit() or not 6 <= int(conf["term.font_size"]) <= 48:
        problems.append(f"term.font_size={conf.get('term.font_size')!r}: a whole number of px, 6-48")
    try:
        if float(conf.get("cosmic.radius", "1")) < 0:
            raise ValueError
    except ValueError:
        problems.append(f"cosmic.radius={conf.get('cosmic.radius')!r}: a number >= 0")
    for key in ("term.background", "term.foreground", "term.cursor",
                "cosmic.background", "cosmic.foreground", "cosmic.accent"):
        if not HEX.match(conf.get(key, "")):
            problems.append(f"{key}={conf.get(key)!r} is not #rrggbb")
    for key in ("term.normal", "term.bright"):
        cols = term_colours(conf, key)
        if len(cols) != 8 or not all(HEX.match(c) for c in cols):
            problems.append(f"{key}: want 8 #rrggbb colours ({' '.join(ANSI)})")
    problems += check_mpv(name, conf.get("season", ""))
    if not conf.get("glass", "").isdigit() or not 0 <= int(conf["glass"]) <= 100:
        problems.append(f"glass={conf.get('glass')!r}: 0-100")
    face = font_list(conf.get("term.font", ""))[:1]
    # mono (100) or dual (90: CJK monospace, wide glyphs two cells -- M PLUS 1 Code)
    got = run(["sh", "-c", "fc-list :spacing=mono family; fc-list :spacing=dual family"])
    if not face or (got and face[0] not in got.stdout):
        problems.append(f"term.font={conf.get('term.font')!r} is not an installed monospace face")
    else:
        # COSMIC Terminal skips a family without a Bold face (its fallback
        # needs one) and quietly uses its default -- PxPlus did exactly that.
        bold = run(["fc-list", f"{face[0]}:weight=200", "family"])
        if bold and not bold.stdout.strip():
            problems.append(f"term.font={face[0]!r} has no Bold face: COSMIC Terminal will not use it")
    icons = conf.get("icon_theme")
    if not icon_theme_dir(icons):
        built = ("Win95", "Phosphor", "Neon", "Moe", "Lofi", "Luna", "Orbit",
                 "Seasons-Spring", "Seasons-Summer", "Seasons-Autumn", "Seasons-Winter")
        hint = (" (make-icon-theme.py --all builds it)" if icons in built
                else " (sudo dnf install oxygen-icon-theme)" if icons == "oxygen"
                else " (Chicago95: see ~/.local/share/icons/Chicago95/README)" if icons == "Chicago95" else "")
        problems.append(f"icon_theme={icons!r}: no such icon theme, Adwaita until there is{hint}")
    elif icons == "Win95" and not icon_theme_dir("Chicago95"):
        problems.append("icon_theme=Win95 inherits Chicago95, which is not installed")
    for key in ("accent_follow", "hypr.blur", "hypr.shadow", "crt_suggest"):
        if conf.get(key, "no") not in ("yes", "no"):
            problems.append(f"{key}={conf.get(key)!r}: yes or no")
    for key in ("hypr.rounding", "hypr.gaps_in", "hypr.gaps_out", "hypr.border_size"):
        if key in conf and not conf[key].isdigit():
            problems.append(f"{key}={conf[key]!r} is not a whole number")
    problems += check_layout_keys(conf)
    prefix = conf.get("wallpaper_prefix", "")
    walls = os.path.join(HOME, "Pictures", "Wallpapers")
    # Every screen's folder (screens.py: the host file's screens, else the
    # live ones), measured against the primary's -- the slideshow's leader.
    mons = screens.order()
    lead = screens.primary()
    lead = lead if lead in mons else (mons[0] if mons else "")
    sets = {}
    for mon in mons:
        try:
            sets[mon] = {f for f in os.listdir(os.path.join(walls, mon)) if f.startswith(prefix)}
        except OSError:
            sets[mon] = set()
    if lead and not sets[lead]:
        problems.append(f"no {lead} wallpaper starts with {prefix!r}: the slideshow would keep the old set")
    for mon, names in sets.items():
        if names != sets[lead]:
            problems.append(f"wallpapers: {mon} has {sorted(names ^ sets[lead])} that the other folders lack "
                            "(MATCHED wants the same names everywhere)")

    video = conf.get("wallpaper_video", "")
    if video:
        missing = [mon for mon in mons
                   if not os.path.isfile(os.path.join(walls, mon, video))]
        if missing:
            problems.append(f"wallpaper_video={video!r} missing in {', '.join(missing)} "
                            "(stills only there; the theme's own render script makes it -- see its theme.conf)")
    problems += check_hypr_lua(name)

    import gi  # only here: everything else in this file must stay GTK-free
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk  # noqa: E402
    for target, (_, style, bases) in TARGETS.items():
        if style != "css" or not bases:
            continue
        text = generated_text(target, conf)
        for base in bases:
            # The override goes where the live one is imported from, so the
            # base's relative imports keep resolving.
            src = open(base).read()
            live = os.path.basename(TARGETS[target][0])
            probe_name = ".check-" + live
            probe = os.path.join(GEN, probe_name)
            with open(probe, "w") as handle:
                handle.write(text)
            tmp_base = os.path.join(os.path.dirname(base), ".check-" + os.path.basename(base))
            with open(tmp_base, "w") as handle:
                handle.write(src.replace(live + '")', probe_name + '")'))
            errors = []
            provider = Gtk.CssProvider()
            provider.connect("parsing-error",
                             lambda _p, sec, err: errors.append(f"line {sec.get_start_line() + 1}: {err.message}"))
            try:
                provider.load_from_path(tmp_base)
            except Exception as exc:  # GLib.Error; the signal has the detail
                errors.append(str(exc))
            # Named colours the override uses but nobody defines.
            defined = set(re.findall(r"@define-color\s+([\w-]+)", src + text))
            for imp in re.findall(r'@import url\("([^"]+)"\)', src):
                try:
                    defined |= set(re.findall(r"@define-color\s+([\w-]+)",
                                              open(os.path.join(os.path.dirname(base), imp)).read()))
                except OSError:
                    pass
            if base.endswith("style-toolbox.css"):
                defined |= set(re.findall(r"@define-color\s+([\w-]+)", open(os.path.join(WAYBAR, "style.css")).read()))
            used = set(re.findall(r"@([\w-]+)", re.sub(r"@(define-color|import|keyframes)", "", strip_comments(text))))
            for undefined in sorted(used - defined):
                errors.append(f"@{undefined} is used but defined nowhere")
            os.remove(tmp_base)
            os.remove(probe)
            for err in errors:
                problems.append(f"{target} (with {os.path.basename(base)}): {err}")
    return problems


# -- glass ---------------------------------------------------------------------
WORST_BEHIND = "#adadad"    # the brightest blurred wallpaper spot (gtk4.css headers)


def contrast(a, b):
    def lum(rgb):
        return sum(w * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
                   for w, c in zip((0.2126, 0.7152, 0.0722), rgb))
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


READABLE_TEXT, READABLE_COLOURS = 4.5, 3.0     # WCAG AA: body text, large text / UI


def worst_case(conf, glass):
    """(text, dimmest colour) contrast of the terminal over the brightest
    wallpaper at this much glass."""
    clear = glass / 100
    behind = hex_rgb(WORST_BEHIND)
    bg = [c * (1 - clear) + w * clear for c, w in zip(hex_rgb(conf["term.background"]), behind)]
    colours = term_colours(conf, "term.normal")[1:]
    return (contrast(hex_rgb(conf["term.foreground"]), bg),
            min(contrast(hex_rgb(c), bg) for c in colours))


def readable_glass(conf):
    """The most glass, up to the current, at which the text still reaches
    READABLE_TEXT and the colours READABLE_COLOURS -- or, for a theme whose
    own colours are dimmer than that even opaque, as good as they get."""
    _, opaque = worst_case(conf, 0)
    need = min(READABLE_COLOURS, opaque)
    for glass in range(int(conf["glass"]), -1, -1):
        text, dimmest = worst_case(conf, glass)
        if text >= READABLE_TEXT and dimmest >= need - 0.05:
            return glass
    return 0


def glass_info(conf):
    """The glass as the panel shows it: value, default, and the worst case --
    the terminal over the brightest wallpaper: its text, and the dimmest of
    its colours (normal red..white; black is a background colour) -- and
    `readable`, the glass `glass fix` would set."""
    text, dimmest = worst_case(conf, int(conf["glass"]))
    return {"theme": conf["id"], "glass": int(conf["glass"]), "default": int(conf["glass_default"]),
            "text": round(text, 1), "dimmest": round(dimmest, 1), "readable": readable_glass(conf)}


def cmd_glass(value):
    name = current()
    if value is not None:
        state = read_state()
        if value == "default":
            state.pop(f"glass_{name}", None)
        elif value == "fix":
            state[f"glass_{name}"] = str(readable_glass(load(name)))
        elif value.isdigit() and int(value) <= 100:
            state[f"glass_{name}"] = value
        else:
            sys.exit("glass: a number 0-100, default, or fix")
        write_state(state)
        if "kitty" in write_terminals(load(name)):
            run(["pkill", "-USR1", "-x", "kitty"])
    print(json.dumps(glass_info(load(name))))


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "list":
        now = current()
        for name, label in themes():
            print(f"{'*' if name == now else ' '} {name:12} {label}")
    elif cmd == "current":
        print(current())
    elif cmd == "set" and len(args) == 1:
        cmd_set(args[0])
    elif cmd == "apply":
        changed = apply(load())
        print(f"{current()}: {', '.join(changed) if changed else 'nothing changed'}")
    elif cmd == "fonts":
        changed = apply_text(load())
        print(f"{current()}: {', '.join(changed) if changed else 'nothing changed'}")
    elif cmd == "cursor":
        conf = load()
        apply_cursor(conf, force=True)
        print(f"{conf.get('cursor_theme')} {cursor_size()}")
    elif cmd == "ensure":
        write_generated(load(), only_missing=True)
    elif cmd == "check":
        cmd_check(args[0] if args else current())
    elif cmd == "season":
        cmd_season(args)
    elif cmd == "season-check" and not args:
        cmd_season_check()
    elif cmd == "chrome-watch" and len(args) == 1:
        cmd_chrome_watch(args[0])       # internal: started detached by apply_chrome
    elif cmd == "fade" and len(args) <= 1:
        if args and args[0] in ("on", "off"):
            state = read_state()
            state["fade"] = args[0]
            write_state(state)
        elif args:
            sys.exit("fade: on or off")
        print("off" if read_state().get("fade") == "off" else "on")
    elif cmd == "apps":
        apply_apps(read_state().get("accent") or None)
    elif cmd == "nautilus-watch" and len(args) == 1:
        cmd_nautilus_watch(args[0])     # internal: started detached by `set`
    elif cmd == "glass" and len(args) <= 1:
        cmd_glass(args[0] if args else None)
    elif cmd == "get" and len(args) in (1, 2):
        print(get(args[0], args[1] if len(args) == 2 else None))
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
