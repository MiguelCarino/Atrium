"""Animations, blur, gamemode latency and the themed lock screen
(lua/display.lua, lua/gamemode.lua, scripts/hyprlock_theme.py, hyprlock.conf).

The Lua halves run under luajit with a stand-in `hl` that records what the
config would have done (skipped when luajit is missing); HOME and the XDG
folders point at scratch folders, so no real state or theme is read."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import helpers

HYPR = os.path.dirname(helpers.SCRIPTS)
LUA_DIR = os.path.join(HYPR, "lua")
LOCK_CONF = os.path.join(HYPR, "hyprlock.conf")
hyprlock_theme = helpers.import_script("hyprlock_theme.py")
lock_screen = helpers.import_script("lock-screen.py")
theme = helpers.import_script("theme.py")

# A stand-in hl: every call is recorded in the globals below, and the
# script given to run_lua() prints what it wants as JSON (a tiny encoder,
# luajit has none).
FAKE_HL = r"""
package.path = '%(hypr)s/?.lua;' .. package.path
anims, curves, lrules, wrules, wins, configs, ons = {}, {}, {}, {}, {}, {}, {}
monitors = monitors or {}
local live = { ["animations.enabled"] = true, ["decoration.screen_shader"] = "" }
local function rule(t, list)
    list[#list + 1] = t
    t._on = true
    return { set_enabled = function(_, v) t._on = v end }
end
local function merge(dst, src)
    for k, v in pairs(src) do
        if type(v) == "table" and type(dst[k]) == "table" then merge(dst[k], v) else dst[k] = v end
    end
end
local cfg = {}
local any = setmetatable({}, { __index = function(t) return t end, __call = function() return {} end })
hl = {
    curve = function(name) curves[name] = true end,
    animation = function(s) anims[#anims + 1] = s end,
    config = function(t)
        configs[#configs + 1] = t
        merge(cfg, t)
        if t.animations and t.animations.enabled ~= nil then live["animations.enabled"] = t.animations.enabled end
    end,
    get_config = function(k) return live[k] end,
    layer_rule = function(t) return rule(t, lrules) end,
    window_rule = function(t) return rule(t, wins) end,
    workspace_rule = function(t) return rule(t, wrules) end,
    get_monitors = function() return monitors end,
    get_windows = function() return {} end,
    on = function(ev, f) ons[ev] = f end,
    bind = function() end,
    timer = function() return { set_enabled = function() end } end,
    exec_cmd = function() end,
    notification = { create = function() end },
    dsp = any,
}
function cfg_get() return cfg end
local function enc(v)
    local t = type(v)
    if t == "table" then
        if #v > 0 or next(v) == nil then
            local out = {}
            for _, x in ipairs(v) do out[#out + 1] = enc(x) end
            return "[" .. table.concat(out, ",") .. "]"
        end
        local out = {}
        for k, x in pairs(v) do out[#out + 1] = string.format("%%q", tostring(k)) .. ":" .. enc(x) end
        return "{" .. table.concat(out, ",") .. "}"
    elseif t == "string" then return string.format("%%q", v)
    elseif t == "number" or t == "boolean" then return tostring(v)
    else return "null" end
end
function emit(v) io.write(enc(v)) end
"""


def run_lua(body, state=None, monitors="{}"):
    """Run `body` after the fake hl, with HOME / XDG_* in a scratch folder
    (`state`: display.conf's text). Returns the JSON it emitted."""
    root = tempfile.mkdtemp(dir=helpers.SCRATCH)
    try:
        os.makedirs(os.path.join(root, "state", "hypr"))
        os.makedirs(os.path.join(root, "run"))
        if state is not None:
            with open(os.path.join(root, "state", "hypr", "display.conf"), "w") as f:
                f.write(state)
        script = f"monitors = {monitors}\n" + FAKE_HL % {"hypr": HYPR} + body
        env = {**os.environ, "HOME": root, "XDG_STATE_HOME": os.path.join(root, "state"),
               "XDG_RUNTIME_DIR": os.path.join(root, "run")}
        out = subprocess.run(["luajit", "-e", script], capture_output=True, text=True, env=env, timeout=30)
        if out.returncode != 0:
            raise AssertionError(out.stderr)
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(root, True)


PORTRAIT = '{ { name = "DP-1", transform = 0 }, { name = "HDMI-A-1", transform = 1 } }'
# Leaves a keypress or a click causes: none may take more than 0.4 s.
FREQUENT = ("windowsIn", "windowsOut", "windowsMove", "layersIn", "layersOut", "fade", "fadeIn",
            "fadeOut", "fadeSwitch", "fadeLayersIn", "fadeLayersOut", "fadePopupsIn", "fadePopupsOut",
            "border", "workspaces", "specialWorkspace")


@unittest.skipUnless(shutil.which("luajit"), "luajit not installed")
class Presets(unittest.TestCase):
    def preset(self, name):
        return run_lua("""
local M = require('lua.display')
emit({ anims = anims, curves = curves, leaves = M.leaves, lrules = lrules, wrules = wrules })
""", state=f"anim={name}\n", monitors=PORTRAIT)

    def presets(self):
        return run_lua("emit(require('lua.display').presets)")

    def test_every_preset_sets_every_leaf_once_with_a_known_curve(self):
        for name in self.presets():
            got = self.preset(name)
            leaves = [leaf[0] for leaf in got["leaves"]]
            set_ = [a["leaf"] for a in got["anims"]]
            self.assertEqual(set_, leaves, name)            # each once, parents first
            for a in got["anims"]:
                self.assertIn(a["bezier"], got["curves"], f"{name}: {a['leaf']}")
                self.assertTrue(a["enabled"])

    def test_frequent_actions_are_snappy_and_exits_are_quicker(self):
        for name in self.presets():
            by = {a["leaf"]: a for a in self.preset(name)["anims"]}
            for leaf in FREQUENT:
                self.assertLessEqual(by[leaf]["speed"], 4, f"{name}: {leaf}")
            self.assertLess(by["windowsOut"]["speed"], by["windowsIn"]["speed"], name)
            self.assertLessEqual(by["layersOut"]["speed"], by["layersIn"]["speed"], name)
            self.assertLessEqual(by["fadeOut"]["speed"], by["fadeIn"]["speed"], name)

    def test_unknown_preset_is_smooth(self):
        self.assertEqual(self.preset("nonsense")["anims"], self.preset("smooth")["anims"])

    def test_calm_never_moves(self):
        got = self.preset("calm")
        for a in got["anims"]:
            style = a.get("style") or ""
            self.assertNotIn("slide", style, a["leaf"])
            if style.startswith("popin"):
                self.assertEqual(style, "popin 100%", a["leaf"])
        on = {r["name"]: r["_on"] for r in got["lrules"]}
        self.assertTrue(on["anim-layers-still"])
        for name in ("anim-panels", "anim-launcher", "anim-notifications", "anim-dock", "anim-dock-preview"):
            self.assertFalse(on[name], name)
        self.assertTrue(on["anim-bar-xray"])           # cost, not motion: always
        self.assertTrue(on["anim-dock-edge"])
        enabled = [r for r in got["wrules"] if r["_on"]]
        self.assertEqual([(r["workspace"], r["animation"]) for r in enabled], [("m[HDMI-A-1]", "fade")])

    def test_layer_rules_in_a_moving_preset(self):
        got = self.preset("smooth")
        rules = {r["name"]: r for r in got["lrules"]}
        self.assertFalse(rules["anim-layers-still"]["_on"])
        self.assertEqual(rules["anim-notifications"]["animation"], "slide right")
        self.assertTrue(rules["anim-bar-xray"]["xray"])
        self.assertEqual(rules["anim-bar-xray"]["match"]["namespace"], "^(waybar-main)$")
        self.assertTrue(rules["anim-panel-dismiss"]["no_anim"])
        # the dock slides in from its edge, its previews pop in, its hot edge never animates
        self.assertEqual(rules["anim-dock"]["animation"], "slide")
        self.assertEqual(rules["anim-dock"]["match"]["namespace"], "^(waybar-dock|waybar-taskbar)$")
        self.assertTrue(rules["anim-dock"]["_on"])
        self.assertEqual(rules["anim-dock-preview"]["animation"], "popin 94%")
        self.assertTrue(rules["anim-dock-edge"]["no_anim"])
        # the still rule is declared last, so it wins any tie
        self.assertEqual(got["lrules"][-1]["name"], "anim-layers-still")

    def test_portrait_screen_slides_vertically(self):
        got = self.preset("smooth")
        self.assertEqual([(r["workspace"], r["animation"]) for r in got["wrules"] if r["_on"]],
                         [("m[HDMI-A-1]", "slidefadevert 20%")])
        got = self.preset("fancy")
        self.assertEqual([r["animation"] for r in got["wrules"] if r["_on"]], ["slidevert"])

    def test_switching_presets_reuses_rules(self):
        got = run_lua("""
local M = require('lua.display')
local f = io.open(os.getenv('XDG_STATE_HOME') .. '/hypr/display.conf', 'w') f:write('anim=calm\\n') f:close()
M.apply()
f = io.open(os.getenv('XDG_STATE_HOME') .. '/hypr/display.conf', 'w') f:write('anim=smooth\\n') f:close()
M.apply()
emit({ n = #lrules, w = wrules })
""", state="anim=smooth\n", monitors=PORTRAIT)
        self.assertEqual(got["n"], 9)                                   # created once each
        self.assertEqual(len(got["w"]), 2)                              # smooth's and calm's
        self.assertEqual([r["animation"] for r in got["w"] if r["_on"]], ["slidefadevert 20%"])

    def test_vertical_and_portrait(self):
        got = run_lua("""
local M = require('lua.display')
emit({ M.vertical('slide'), M.vertical('slidefade 20%'), M.vertical('fade'),
       M.vertical('slidefadevert 10%'), tostring(M.vertical(nil)),
       M.portrait(0), M.portrait(1), M.portrait(3), M.portrait(5), M.portrait(2) })
""")
        self.assertEqual(got, ["slidevert", "slidefadevert 20%", "fade", "slidefadevert 10%", "nil",
                               False, True, True, True, False])

    def test_expand_inherits_from_the_parent(self):
        got = run_lua("""
local M = require('lua.display')
local out = {}
for _, a in ipairs(M.expand({ { 'global', 3, 'linear' }, { 'fade', 2, 'quick' } })) do out[a[1]] = a end
emit({ out.fadeLayersIn, out.windowsIn })
""")
        self.assertEqual(got, [["fadeLayersIn", 2, "quick"], ["windowsIn", 3, "linear"]])


@unittest.skipUnless(shutil.which("luajit"), "luajit not installed")
class Gamemode(unittest.TestCase):
    def test_on_clears_the_shader_and_allows_tearing_for_games(self):
        got = run_lua("""
package.preload['lua.mpvframe'] = function() return { apply = function() end } end
local G = require('lua.gamemode')
local before = wins[1]._on
G.set(true, 'test')
local c = cfg_get()
emit({ before = before, after = wins[1]._on, match = wins[1].match.class, imm = wins[1].immediate,
       anim = c.animations.enabled, shader = c.decoration.screen_shader,
       tearing = c.general.allow_tearing, scanout = c.render.direct_scanout })
""")
        self.assertFalse(got["before"])                 # off on the desktop
        self.assertTrue(got["after"])
        self.assertTrue(got["imm"])
        self.assertIn("steam_app_", got["match"])
        self.assertFalse(got["anim"])
        self.assertEqual(got["shader"], "")
        self.assertTrue(got["tearing"])
        self.assertEqual(got["scanout"], 2)

    def test_load_puts_tearing_and_scanout_back_off(self):
        # A reload (gamemode OFF) must not leave either option on, and the
        # rule tags games content=game so scanout "auto" can pick them up.
        got = run_lua("""
package.preload['lua.mpvframe'] = function() return { apply = function() end } end
require('lua.gamemode')
local c = cfg_get()
emit({ tearing = c.general.allow_tearing, scanout = c.render.direct_scanout,
       content = wins[1].content })
""")
        self.assertEqual(got, {"tearing": False, "scanout": 0, "content": "game"})

    def test_shader_kept_when_capture_says_so(self):
        root_state = """
local d = os.getenv('XDG_STATE_HOME') .. '/hypr/capture.conf'
local f = io.open(d, 'w') f:write('gamemode_shader=off\\n') f:close()
package.preload['lua.mpvframe'] = function() return { apply = function() end } end
require('lua.gamemode').set(true)
emit({ shader = tostring(cfg_get().decoration.screen_shader) })
"""
        self.assertEqual(run_lua(root_state)["shader"], "nil")

    def test_filter_is_not_set_in_gamemode(self):
        got = run_lua("""
local M = require('lua.display')
hl.config({ animations = { enabled = false } })
local n = #configs
local f = io.open(os.getenv('XDG_STATE_HOME') .. '/hypr/display.conf', 'w') f:write('filter=vibrance\\n') f:close()
M.apply()
local shader = nil
for i = n + 1, #configs do
    local d = configs[i].decoration
    if d and d.screen_shader then shader = d.screen_shader end
end
emit({ shader = tostring(shader) })
""")
        self.assertEqual(got["shader"], "nil")


class LockTheme(unittest.TestCase):
    def defined(self, text):
        return re.findall(r"^\$([A-Za-z_0-9]+)\s*=", text, re.M)

    def test_cyberpunk_is_the_hand_drawn_neon(self):
        self.assertEqual(hyprlock_theme.values({"id": "cyberpunk"}), hyprlock_theme.NEON)

    def test_include_defines_exactly_the_conf_variables(self):
        with open(LOCK_CONF) as f:
            conf = f.read()
        for t in ({"id": "cyberpunk"}, {"id": "x", "accent": "#4aa3f0"}):
            self.assertEqual(sorted(self.defined(hyprlock_theme.text(t))), sorted(self.defined(conf)))

    def test_no_variable_is_a_prefix_of_another(self):
        # hyprlang swaps $name in as text: $a next to $ab must never be ambiguous.
        names = list(hyprlock_theme.NEON)
        for a in names:
            for b in names:
                self.assertFalse(a != b and b.startswith(a), (a, b))

    def test_every_variable_the_widgets_use_is_defined(self):
        with open(LOCK_CONF) as f:
            conf = f.read()
        code = "\n".join(lock_screen.strip_comment(ln) for ln in conf.splitlines())
        used = set(re.findall(r"\$([a-z_][a-z_0-9]*)", code))   # lower case: ours (hyprlock's are upper)
        self.assertTrue(used)
        self.assertLessEqual(used, set(self.defined(conf)))

    def test_conf_names_no_screen_and_keeps_its_editor_working(self):
        with open(LOCK_CONF) as f:
            conf = f.read()
        self.assertEqual(re.findall(r"^[ \t]*monitor[ \t]*=[ \t]*(\S+)", conf, re.M), [])
        self.assertIn("source = ~/.config/waybar/generated/" + hyprlock_theme.NAME, conf)
        items = lock_screen.parse(conf)
        self.assertEqual(lock_screen.render(items), conf)
        st = lock_screen.status(items)
        self.assertEqual(st["screen"], "")
        self.assertTrue(st["date"] and st["layout"])
        self.assertTrue(lock_screen.balanced(conf))

    def test_a_dark_theme(self):
        v = hyprlock_theme.values({"id": "aero", "accent": "#4aa3f0", "cosmic.background": "#0c2240",
                                   "cosmic.foreground": "#f4f9ff", "font": "Selawik, IBM Plex Sans",
                                   "font_mono": "IBM Plex Mono", "hypr.rounding": "8"})
        self.assertEqual(v["lock_accent"], "rgb(4aa3f0)")
        self.assertEqual(v["lock_text"], "rgb(f4f9ff)")
        self.assertEqual(v["lock_inner"], "rgba(0c2240d9)")
        self.assertEqual(v["font_display"], "Selawik, IBM Plex Sans")
        self.assertEqual(v["lock_rounding"], "8")

    def test_a_light_theme_is_turned_round_and_stays_readable(self):
        v = hyprlock_theme.values({"id": "paper", "accent": "#18439a", "cosmic.background": "#f4f1e6",
                                   "cosmic.foreground": "#20242c"})
        text = "#" + v["lock_text"][4:-1]
        inner = "#" + v["lock_inner"][5:11]
        accent = "#" + v["lock_accent"][4:-1]
        self.assertGreater(hyprlock_theme.contrast(text, inner), 7)
        self.assertGreaterEqual(hyprlock_theme.contrast(accent, inner), 3)

    def test_bad_values_fall_back(self):
        v = hyprlock_theme.values({"id": "odd", "accent": "teal", "hypr.rounding": "lots"})
        self.assertEqual(v["lock_rounding"], "8")
        self.assertTrue(v["lock_accent"].startswith("rgb("))

    def test_hash_is_escaped(self):
        with mock.patch.object(hyprlock_theme, "values", return_value={"lock_prompt": "#1"}):
            self.assertIn("$lock_prompt = ##1", hyprlock_theme.text({"id": "x"}))

    def test_theme_writes_it_with_the_generated_files(self):
        gen = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, gen, True)
        written = {}
        with mock.patch.object(theme, "GEN", gen), \
                mock.patch.object(theme, "write_if_changed",
                                  side_effect=lambda p, t: written.__setitem__(p, t) or True), \
                mock.patch.object(theme, "write_terminals", return_value=[]), \
                mock.patch.object(theme, "fix_wofi_import", return_value=False), \
                mock.patch.object(theme, "generated_text", return_value=""):
            changed = theme.write_generated({"id": "aero", "accent": "#4aa3f0"})
        self.assertIn("hyprlock", changed)
        self.assertIn("$lock_accent = rgb(4aa3f0)", written[os.path.join(gen, hyprlock_theme.NAME)])


if __name__ == "__main__":
    unittest.main()
