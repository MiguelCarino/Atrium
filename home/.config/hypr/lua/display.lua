-- ~/.config/hypr/lua/display.lua
-- Loaded from ~/.config/hypr/hyprland.lua (the index), right after settings.
-- The parts of the look that are chosen at runtime rather than written down:
--
--   desktop theme      ~/.config/themes/<name>/theme.conf: border colours,
--                      rounding, gaps, border size, blur, shadow, and the
--                      theme's own window/layer rules (hypr.lua)
--   animation preset   snappy / smooth / fancy / calm / spring, plus the
--                      layer animations and portrait-screen workspace slides
--   screen filter      a GLSL screen shader from ~/.config/hypr/shaders/
--   accent             the focused-window border, from the wallpaper
--   your window look   hyprlook.* overrides of the theme's look (gaps,
--                      borders, corners, blur, shadow, dimming, the tiling
--                      layout): the Settings window's "Windows & workspaces"
--                      page, through ~/.config/hypr/scripts/window-look.py
--
-- Each choice lives in the display state file (lua/shared.lua explains it) and
-- is applied here at every load, so a reload -- gamemode OFF is one -- puts it
-- back instead of dropping to the defaults. Changing one at runtime goes
-- through ~/.config/hypr/scripts/display.py (or theme.py for the theme),
-- which writes the state and runs
--     hyprctl eval 'require("lua.display").apply()'
-- so the same code path does both, and nothing here has to be duplicated in
-- Python.

---@module 'hl'

local S = require("lua.shared")

local M = {}

-- ========================= Animations =========================
-- The reasoning behind every preset:
--
-- Hyprland's stock global speed is 10, and speed is in deciseconds, so the
-- default for anything not overridden was a full second. On a 144-180 Hz
-- panel that reads as the desktop waiting for you. The target is "present but
-- never in the way": nothing a keypress causes takes more than 0.4 s (0.3 s
-- in the default), and things leaving are faster than things arriving,
-- because you already know where a closed window went.
--
-- The curves do most of the work. A decelerating curve (easeOutQuint,
-- easeOutExpo, emphasized) covers most of the distance in the first third of
-- the time, so a 0.3 s animation feels finished at ~0.1 s and the rest is
-- settling -- that is what makes short durations look smooth rather than
-- abrupt. Things leaving use an ACCELERATING curve (exitAccel): they start
-- gently and are gone quickly, instead of decelerating into nothing, which
-- is what made a closing window look like it hesitated.
--
-- The presets (scripts/display.py anim <preset>|cycle, Settings > Screens):
--   smooth  the default and the reference: ~0.3 s arrivals on emphasized /
--           easeOutQuint, ~0.15 s exits on exitAccel, a short slide-and-fade
--           between workspaces.
--   snappy  about 60% of smooth's durations, smaller pop-in. For working fast.
--   fancy   a little longer, with a short springy overshoot (softBack, ~4%
--           and one settle, never a wobble) on windows and layers arriving,
--           and a full workspace slide. Still under 0.4 s everywhere: it used
--           to run windows at 0.45 s and everything else at 0.6 s.
--   calm    no movement at all, only fades: windows and workspaces cross-fade
--           in place, layers (bar panels, launcher, notifications, the
--           island) fade instead of sliding or popping. The reduced-motion
--           preset: Settings > Accessibility > Reduce motion picks it.
--   spring  macOS-like (orchard's): windows pop in from 92% on a curve that
--           overshoots by ~3% and settles, leave faster on an ease-in
--           (macExit), and workspaces glide as one sheet (spaceSlide, a full
--           slide with no fade) -- bouncy, but never wobbly.
--
-- Every preset sets EVERY leaf in LEAVES below, the children included
-- (fadeIn, fadeLayersOut, ...): a child set by one preset keeps that value
-- when a later preset only sets its parent -- Hyprland only passes a parent
-- down to children nobody set -- so switching snappy -> calm at runtime
-- would otherwise keep snappy's fades. A leaf a preset leaves out takes its
-- parent's values (the same inheritance Hyprland uses), so the tables only
-- list what differs.
--
-- None of them sets animations.enabled = false: that is gamemode's switch,
-- and lua/gamemode.lua reads it to tell whether gamemode is on.
-- ALT+SHIFT+G still turns everything off in one press, whatever the preset.
hl.curve("easeOutQuint", { type = "bezier", points = { {0.23, 1},    {0.32, 1}    } })
hl.curve("linear",       { type = "bezier", points = { {0, 0},       {1, 1}       } })
hl.curve("quick",        { type = "bezier", points = { {0.15, 0},    {0.1, 1}     } })
hl.curve("overshot",     { type = "bezier", points = { {0.05, 0.9},  {0.1, 1.08}  } })
hl.curve("easeInOut",    { type = "bezier", points = { {0.65, 0},    {0.35, 1}    } })
-- easeOutExpo: even more front-loaded than quint -- most of a workspace slide
-- is done in the first frames, the rest is a soft landing.
hl.curve("easeOutExpo",  { type = "bezier", points = { {0.16, 1},    {0.30, 1}    } })
-- Material 3's pair: emphasized (decelerate) for things arriving,
-- exitAccel (its emphasized-accelerate) for things leaving.
hl.curve("emphasized",   { type = "bezier", points = { {0.05, 0.7},  {0.10, 1}    } })
hl.curve("exitAccel",    { type = "bezier", points = { {0.30, 0},    {0.80, 0.15} } })
-- softBack: easeOutBack with the overshoot cut to ~4% -- a pop-in that
-- lands, rather than one that bounces.
hl.curve("softBack",     { type = "bezier", points = { {0.34, 1.25}, {0.64, 1}    } })
-- spring's: a bezier whose first handle rises past 1 (1.12) overshoots by
-- about 3% and settles back -- the springy arrival without a second bounce;
-- macEase is the gentle ease-out the system uses for everything else,
-- macExit an ease-in (things leaving speed up as they go), spaceSlide a
-- quick start that coasts in, like swiping between full-screen spaces.
hl.curve("spring",       { type = "bezier", points = { {0.20, 1.12}, {0.30, 1.00} } })
hl.curve("macEase",      { type = "bezier", points = { {0.25, 0.10}, {0.25, 1.00} } })
hl.curve("macExit",      { type = "bezier", points = { {0.40, 0.00}, {1.00, 1.00} } })
hl.curve("spaceSlide",   { type = "bezier", points = { {0.32, 0.72}, {0.00, 1.00} } })

-- Hyprland's animation tree, parents before children: { leaf, parent }.
-- workspacesIn/Out and specialWorkspaceIn/Out are left out on purpose:
-- nothing needs them apart from their parent, and lua/ambient.lua calms the
-- desktop by setting the parents only.
local LEAVES = {
    { "global" },
    { "windows",          "global" },
    { "windowsIn",        "windows" },
    { "windowsOut",       "windows" },
    { "windowsMove",      "windows" },
    { "layers",           "global" },
    { "layersIn",         "layers" },
    { "layersOut",        "layers" },
    { "fade",             "global" },
    { "fadeIn",           "fade" },
    { "fadeOut",          "fade" },
    { "fadeSwitch",       "fade" },
    { "fadeShadow",       "fade" },
    { "fadeDim",          "fade" },
    { "fadeLayers",       "fade" },
    { "fadeLayersIn",     "fadeLayers" },
    { "fadeLayersOut",    "fadeLayers" },
    { "fadePopups",       "fade" },
    { "fadePopupsIn",     "fadePopups" },
    { "fadePopupsOut",    "fadePopups" },
    { "fadeDpms",         "fade" },
    { "border",           "global" },
    { "workspaces",       "global" },
    { "specialWorkspace", "workspaces" },
    { "zoomFactor",       "global" },
    { "monitorAdded",     "global" },
}
M.leaves = LEAVES

--          leaf               speed (ds)  curve           style
local PRESETS = {
    smooth = {
        { "global",           3,   "easeOutQuint" },
        { "border",           3,   "easeOutQuint" },
        { "windowsIn",        3,   "emphasized",   "popin 90%" },
        { "windowsOut",       1.6, "exitAccel",    "popin 92%" },
        { "windowsMove",      2.8, "easeOutQuint" },
        -- Layers (the bar's panels, the launcher, notifications, the island)
        -- get their own style from the layer rules further down; this is
        -- their timing, and the style of any other layer surface.
        { "layersIn",         2.2, "easeOutExpo",  "fade" },
        { "layersOut",        1.4, "exitAccel",    "fade" },
        { "fade",             2.2, "easeOutQuint" },
        { "fadeOut",          1.5, "exitAccel" },
        { "fadeSwitch",       2.4, "easeOutQuint" },
        { "fadeDim",          2.6, "easeOutQuint" },
        { "fadeLayersIn",     2,   "easeOutQuint" },
        { "fadeLayersOut",    1.3, "exitAccel" },
        { "fadePopupsIn",     1.4, "easeOutQuint" },
        { "fadePopupsOut",    1,   "exitAccel" },
        { "fadeDpms",         3,   "easeInOut" },
        -- Workspaces slide rather than fade so you can tell which way you
        -- went: e+1 / e-1 (ALT+wheel) and SUPER+Tab get a direction, not just
        -- a cut. On a portrait screen they slide vertically (see "Portrait
        -- screens" below).
        { "workspaces",       3,   "easeOutQuint", "slidefade 20%" },
        -- Scratchpads (ALT+grave, SUPER+Return, SUPER+A) drop in vertically,
        -- so an overlay never looks like a workspace switch.
        { "specialWorkspace", 2.8, "easeOutQuint", "slidefadevert 15%" },
    },
    snappy = {
        { "global",           2,   "easeOutQuint" },
        { "border",           2,   "easeOutQuint" },
        { "windowsIn",        1.8, "easeOutExpo",  "popin 95%" },
        { "windowsOut",       1.1, "exitAccel",    "popin 96%" },
        { "windowsMove",      1.8, "easeOutQuint" },
        { "layersIn",         1.5, "easeOutExpo",  "fade" },
        { "layersOut",        1,   "exitAccel",    "fade" },
        { "fade",             1.5, "quick" },
        { "fadeOut",          1,   "exitAccel" },
        { "fadeLayersIn",     1.3, "quick" },
        { "fadeLayersOut",    0.9, "exitAccel" },
        { "fadePopupsIn",     1,   "quick" },
        { "fadePopupsOut",    0.8, "exitAccel" },
        { "fadeDpms",         2,   "easeInOut" },
        { "workspaces",       1.8, "easeOutExpo",  "slidefade 10%" },
        { "specialWorkspace", 1.8, "easeOutExpo",  "slidefadevert 10%" },
    },
    fancy = {
        { "global",           4,   "easeOutQuint" },
        { "border",           4,   "easeOutQuint" },
        { "windowsIn",        3.8, "softBack",     "popin 85%" },
        { "windowsOut",       2,   "exitAccel",    "popin 88%" },
        { "windowsMove",      3.5, "softBack" },
        { "layersIn",         3,   "softBack",     "popin 90%" },
        { "layersOut",        1.6, "exitAccel",    "fade" },
        { "fade",             2.8, "easeOutQuint" },
        { "fadeOut",          1.8, "exitAccel" },
        { "fadeDim",          3,   "easeOutQuint" },
        { "fadeLayersIn",     2.4, "easeOutQuint" },
        { "fadeLayersOut",    1.5, "exitAccel" },
        { "fadePopupsIn",     1.6, "easeOutQuint" },
        { "fadePopupsOut",    1.1, "exitAccel" },
        { "fadeDpms",         3.5, "easeInOut" },
        { "workspaces",       3.8, "easeOutExpo",  "slide" },
        { "specialWorkspace", 3.5, "softBack",     "slidefadevert 20%" },
    },
    calm = {
        { "global",           3,   "easeInOut" },
        { "border",           3,   "easeInOut" },
        { "windowsIn",        2.5, "easeInOut",    "popin 100%" },
        { "windowsOut",       2,   "easeInOut",    "popin 100%" },
        { "windowsMove",      0.1, "linear" },
        { "layersIn",         2.5, "easeInOut",    "fade" },
        { "layersOut",        2,   "easeInOut",    "fade" },
        { "fade",             2.5, "easeInOut" },
        { "fadeOut",          2,   "easeInOut" },
        { "workspaces",       3,   "easeInOut",    "fade" },
        { "specialWorkspace", 3,   "easeInOut",    "fade" },
        -- The magnifier jumps rather than glides: a zoom is motion too.
        { "zoomFactor",       0.1, "linear" },
    },
    spring = {
        { "global",           4,   "macEase" },
        { "border",           3,   "macEase" },
        { "windowsIn",        3,   "spring",       "popin 92%" },
        { "windowsOut",       1.5, "macExit",      "popin 94%" },
        { "windowsMove",      3.5, "spring" },
        { "layersIn",         2.5, "spring",       "popin 96%" },
        { "layersOut",        1.5, "macExit",      "fade" },
        { "fade",             2.5, "macEase" },
        { "fadeOut",          1.5, "macExit" },
        { "fadeLayersOut",    1.4, "macExit" },
        { "fadePopupsOut",    1,   "macExit" },
        { "workspaces",       4,   "spaceSlide",   "slide" },
        { "specialWorkspace", 3.5, "spring",       "slidefadevert 10%" },
    },
}
-- scripts/theme.py PRESETS and scripts/display.py PRESETS list the same
-- names (tests/test_theme_island.py keeps the three equal).
M.presets = { "snappy", "smooth", "fancy", "calm", "spring" }
-- The presets in which nothing moves, only fades: the layer rules below
-- switch every layer to a fade while one of these is on.
local STILL = { calm = true }

-- A list in the PRESETS shape -> one { leaf, speed, curve, style } per leaf
-- of LEAVES, in tree order, a missing leaf taking its parent's values.
-- Public so lua/ambient.lua (or anything else that sets animations at
-- runtime) can lay down a complete set the same way.
function M.expand(list)
    local own, out, resolved = {}, {}, {}
    for _, a in ipairs(list) do own[a[1]] = a end
    for _, node in ipairs(LEAVES) do
        local leaf, parent = node[1], node[2]
        local a = own[leaf]
        local spec
        if a then
            spec = { leaf, a[2], a[3], a[4] }
        elseif parent and resolved[parent] then
            local p = resolved[parent]
            spec = { leaf, p[2], p[3], p[4] }
        else
            spec = { leaf, 10, "default" }      -- Hyprland's own global
        end
        resolved[leaf] = spec
        out[#out + 1] = spec
    end
    return out
end

function M.preset(name)
    return PRESETS[name] and name or "smooth"
end

function M.animate(list)
    for _, a in ipairs(M.expand(list)) do
        local spec = { leaf = a[1], enabled = true, speed = a[2], bezier = a[3] }
        if a[4] then spec.style = a[4] end
        hl.animation(spec)
    end
end

-- ---- Layers: the bar, its panels, the launcher, notifications ----
-- Declared here, after every rule in lua/rules.lua, so they win a tie with
-- the island-slide rule there (wofi-glass only frosts and dims, it sets no
-- animation any more); created once per Lua state
-- and only switched with set_enabled, like the theme rules below.
--
--   panels         the bar's cards (waybar-panel, scripts/panelui.py):
--                  a short pop-in from 95% with the fade -- a card appearing
--                  under the pill you clicked, not a sheet sliding over the
--                  bar from the screen's edge
--   launcher       a smaller pop than rules.lua's 80%: 92% reads as the card
--                  arriving, 80% as it growing
--   notifications  mako sits in the top-right corner: it slides in from the
--                  right edge and back out
--   the island     keeps rules.lua's slide from the top edge
--   the dock       scripts/dock.py's dock and taskbar slide in from the edge
--                  they sit on and back out (an auto-hiding dock stepping
--                  away and coming back); its window previews pop in from
--                  94%, like a panel under its pill
--   panel-dismiss  the invisible click-catcher under a panel: never animated
--                  (fading a transparent sheet is GPU time for nothing);
--                  nor is the hidden dock's hot edge (dock-edge), a 3px
--                  strip nobody sees
--
-- In a STILL preset (calm) every one of them, the island included, fades
-- in place instead -- reduce motion means nothing slides or pops.
--
-- xray: the bar sits in its own reserved strip, where nothing but the
-- wallpaper is ever behind it, so it can blur the wallpaper alone -- which
-- Hyprland renders once and caches -- instead of re-blurring the live scene
-- under it every frame something below changes. It looks the same (the only
-- difference: a floating window dragged under the bar is not frosted into
-- it). The island is NOT on it: expanded (a notification, a track, a timer)
-- it hangs well below the strip over windows, where xray would frost the
-- wallpaper instead of the window under it -- a hole in the desktop. The
-- panels, the toolbox, the launcher and mako float over windows too, so
-- they keep the real blur.
local LAYER_RULES = {
    { name = "anim-bar-xray",       always = true,
      match = { namespace = "^(waybar-main)$" }, xray = true },
    { name = "anim-panel-dismiss",  always = true,
      match = { namespace = "^(panel-dismiss)$" }, no_anim = true },
    { name = "anim-panels",         motion = true,
      match = { namespace = "^(waybar-panel)$" }, animation = "popin 95%" },
    { name = "anim-launcher",       motion = true,
      match = { namespace = "^(wofi|launcher)$" }, animation = "popin 92%" },
    { name = "anim-notifications",  motion = true,
      match = { namespace = "^(notifications)$" }, animation = "slide right" },
    { name = "anim-dock",           motion = true,
      match = { namespace = "^(waybar-dock|waybar-taskbar)$" }, animation = "slide" },
    { name = "anim-dock-preview",   motion = true,
      match = { namespace = "^(waybar-dock-preview)$" }, animation = "popin 94%" },
    { name = "anim-dock-edge",      always = true,
      match = { namespace = "^(dock-edge)$" }, no_anim = true },
    { name = "anim-layers-still",   motion = false,
      match = { namespace = "^(waybar-.*|wofi|launcher|notifications)$" }, animation = "fade" },
}
local layer_rules = {}      -- name -> HL rule

-- name -> on, for a preset (pure: tests/test_animations.py).
function M.layer_rules_for(name)
    local still = STILL[M.preset(name)] == true
    local on = {}
    for _, r in ipairs(LAYER_RULES) do
        if r.always then on[r.name] = true
        else on[r.name] = (r.motion == not still) end
    end
    return on
end

local function apply_layer_rules(name)
    local on = M.layer_rules_for(name)
    for _, r in ipairs(LAYER_RULES) do         -- in order: the still rule last
        if not layer_rules[r.name] then
            local spec = { name = r.name, match = r.match }
            for _, k in ipairs({ "xray", "no_anim", "animation" }) do spec[k] = r[k] end
            layer_rules[r.name] = hl.layer_rule(spec)
        end
        layer_rules[r.name]:set_enabled(on[r.name] == true)
    end
end

-- ---- Portrait screens ----
-- A workspace switch slides sideways, which on a screen turned on its side
-- moves the picture along its SHORT edge. A workspace rule for every rotated
-- monitor (transform 1, 3, 5, 7: 90 / 270, flipped or not) gives its
-- workspaces the vertical form of the preset's style instead -- slide ->
-- slidevert, slidefade 20% -> slidefadevert 20%; a fade stays a fade, so
-- calm stays still. Created once per (monitor, style) and switched with
-- set_enabled; re-checked when a monitor comes, goes or is rotated.

-- "slidefade 20%" -> "slidefadevert 20%" (pure: tests/test_animations.py).
function M.vertical(style)
    if not style or style == "" then return nil end
    local word, rest = style:match("^(%S+)(.*)$")
    if word == "slide" or word == "slidefade" then return word .. "vert" .. rest end
    return style
end

function M.portrait(transform)
    return type(transform) == "number" and transform % 2 == 1
end

local ws_rules = {}         -- "<monitor>|<style>" -> HL workspace rule
local current_anim = "smooth"

local function apply_orientation(name)
    local style
    for _, a in ipairs(PRESETS[M.preset(name)]) do
        if a[1] == "workspaces" then style = a[4] end
    end
    local vert = M.vertical(style)
    local wanted = {}
    if vert then
        for _, m in ipairs(hl.get_monitors and hl.get_monitors() or {}) do
            if M.portrait(m.transform) and m.name then
                local key = m.name .. "|" .. vert
                wanted[key] = true
                if not ws_rules[key] then
                    ws_rules[key] = hl.workspace_rule({ workspace = "m[" .. m.name .. "]", animation = vert })
                end
            end
        end
    end
    for key, rule in pairs(ws_rules) do rule:set_enabled(wanted[key] == true) end
end

local function apply_animations(name)
    name = M.preset(name)
    current_anim = name
    M.animate(PRESETS[name])
    apply_layer_rules(name)
    apply_orientation(name)
end

for _, ev in ipairs({ "monitor.added", "monitor.removed", "monitor.layout_changed" }) do
    hl.on(ev, function() apply_orientation(current_anim) end)
end

-- ========================= Screen filter =========================
-- One screen shader at a time is all Hyprland has, and night light can use the
-- same slot: scripts/nightlight.sh falls back to a shader when hyprsunset is
-- missing. hyprsunset is installed, so night light is a colour matrix and the
-- slot is free -- but a filter never overwrites a shader that is not one of
-- ours, so the fallback cannot be clobbered silently.
local SHADER_DIR = os.getenv("HOME") .. "/.config/hypr/shaders/"

local function apply_filter(name)
    -- Gamemode clears the shader (lua/gamemode.lua: a screen shader is a
    -- full-screen pass every frame and rules out direct scanout); a filter
    -- picked mid-game is written to the state and comes back with gamemode OFF.
    if not hl.get_config("animations.enabled") then return end
    local current = hl.get_config("decoration.screen_shader") or ""
    local ours = current == "" or current:sub(1, #SHADER_DIR) == SHADER_DIR
    if not ours then return end
    local want = (name and name ~= "") and (SHADER_DIR .. name .. ".frag") or ""
    if want ~= current then
        hl.config({ decoration = { screen_shader = want } })
    end
end

-- ========================= Theme =========================
-- The desktop theme's Hyprland half. ~/.config/hypr/scripts/theme.py owns
-- themes (the stylesheets, mako, gsettings, the wallpaper set) and writes
-- theme=<name> into the state file; this reads that theme's theme.conf on
-- every apply and sets the look from it, so a `hyprctl reload` -- and
-- gamemode OFF, which IS a reload -- comes back to the THEME's look, not to
-- the bare values in lua/settings.lua. settings.lua still holds the
-- cyberpunk values, so with no themes folder at all nothing changes.
--
-- theme.conf is key=value (S.read_kv); every theme inherits cyberpunk for the
-- keys it leaves out, or the theme named by inherit= -- the same rules as
-- theme.py's chain(). The hypr.* keys used here:
--   hypr.rounding  hypr.gaps_in  hypr.gaps_out  hypr.border_size   numbers
--   hypr.active_border  hypr.inactive_border   "rgb(..) rgba(..) 135deg"
--   hypr.accent_stops   active_border stops the accent replaces ("1 2")
--   hypr.blur=yes|no  hypr.blur_size  _passes  _brightness  _contrast
--                     _vibrancy  _vibrancy_darkness  _noise
--   hypr.shadow=yes|no  hypr.shadow_range  _render_power  _color
--   hypr.shadow_color_inactive   "" = transparent (settings.lua's value), so
--                       leaving a theme that set one really resets it
--   hypr.shadow_offset  "x y" px ("0 0" = no offset; orchard: "0 14")
-- A key that is missing everywhere leaves that option alone.
--
-- Gamemode: animations.enabled == false means gamemode is on (lua/gamemode.lua
-- reads it the same way). While it is on, the stripped keys -- rounding,
-- gaps, border size, blur, shadow -- are NOT applied, so picking a theme or a
-- filter mid-game cannot undo the strip; colours and rules still are. OFF
-- reloads, and the reload lands here with gamemode off.
local THEMES_DIR = os.getenv("HOME") .. "/.config/themes/"
local BASE_THEME = "cyberpunk"

function M.theme(name)
    local layers, seen = {}, {}
    name = (name and name ~= "") and name or BASE_THEME
    while name ~= "" and not seen[name] do
        local kv = S.read_kv(THEMES_DIR .. name .. "/theme.conf")
        if not kv then break end
        seen[name] = true
        layers[#layers + 1] = kv
        local parent = kv.inherit or ""
        if parent == "" and name ~= BASE_THEME then parent = BASE_THEME end
        name = parent
    end
    if not seen[BASE_THEME] then
        -- The named theme is gone (or its chain is): fall back to the base.
        layers[#layers + 1] = S.read_kv(THEMES_DIR .. BASE_THEME .. "/theme.conf") or {}
    end
    local conf = {}
    for i = #layers, 1, -1 do
        for k, v in pairs(layers[i]) do conf[k] = v end
    end
    return conf
end

-- "rgb(0ff0fc) rgba(00f0ff33) 135deg" -> { colors = {...}, angle = 135 }
local function gradient(spec)
    if not spec or spec == "" then return nil end
    local colors, angle = {}, 0
    for tok in spec:gmatch("%S+") do
        local deg = tok:match("^(%-?[%d%.]+)deg$")
        if deg then angle = tonumber(deg) else colors[#colors + 1] = tok end
    end
    if #colors == 0 then return nil end
    return { colors = colors, angle = angle }
end

local function flag(v)
    if v == nil or v == "" then return nil end
    return v == "yes" or v == "on" or v == "true" or v == "1"
end

local function apply_look(t)
    local gamemode = not hl.get_config("animations.enabled")
    local general = { col = {
        active_border   = gradient(t["hypr.active_border"]),
        inactive_border = gradient(t["hypr.inactive_border"]),
    } }
    -- The unfocused shadow: the theme's, else transparent -- never left at
    -- the last theme's (an empty key would otherwise leave it alone).
    local inactive = t["hypr.shadow_color_inactive"]
    if inactive == nil or inactive == "" then inactive = "rgba(00000000)" end
    local decoration = { shadow = { color = t["hypr.shadow_color"], color_inactive = inactive } }
    if not gamemode then
        general.gaps_in      = tonumber(t["hypr.gaps_in"])
        general.gaps_out     = tonumber(t["hypr.gaps_out"])
        general.border_size  = tonumber(t["hypr.border_size"])
        decoration.rounding  = tonumber(t["hypr.rounding"])
        decoration.blur = {
            enabled           = flag(t["hypr.blur"]),
            size              = tonumber(t["hypr.blur_size"]),
            passes            = tonumber(t["hypr.blur_passes"]),
            brightness        = tonumber(t["hypr.blur_brightness"]),
            contrast          = tonumber(t["hypr.blur_contrast"]),
            vibrancy          = tonumber(t["hypr.blur_vibrancy"]),
            vibrancy_darkness = tonumber(t["hypr.blur_vibrancy_darkness"]),
            noise             = tonumber(t["hypr.blur_noise"]),
        }
        decoration.shadow.enabled      = flag(t["hypr.shadow"])
        decoration.shadow.range        = tonumber(t["hypr.shadow_range"])
        decoration.shadow.render_power = tonumber(t["hypr.shadow_render_power"])
        -- "x y" -> { x, y }, the vec2 shape lua/settings.lua sets it in.
        local ox, oy = (t["hypr.shadow_offset"] or "0 0"):match("^%s*(%-?[%d%.]+)%s+(%-?[%d%.]+)%s*$")
        decoration.shadow.offset = { tonumber(ox) or 0, tonumber(oy) or 0 }
    end
    hl.config({ general = general, decoration = decoration })
end

-- Theme rules: a theme may ship ~/.config/themes/<name>/hypr.lua returning
--     return {
--         window_rules = { { name = "aero-nautilus-glass",
--                            match = { class = "^(org\\.gnome\\.Nautilus)$" },
--                            opacity = "1.0 0.92" }, ... },
--         layer_rules  = { { name = ..., match = { namespace = ... }, ... } },
--     }
-- -- the same tables hl.window_rule / hl.layer_rule take (lua/rules.lua is
-- full of examples). Each rule is created once per Lua state, by name, and
-- then only switched with set_enabled: on while its theme is current, off
-- otherwise, so switching themes back and forth never stacks duplicates.
-- They are declared after every rule in lua/rules.lua, so they win a tie.
-- Only the current theme's own file is read (rules do not inherit). Editing
-- an existing rule's fields needs a `hyprctl reload` to take; a NEW name
-- takes at the next apply. Names must be unique across all themes.
local theme_rules = {}      -- "window:<name>" / "layer:<name>" -> HL rule

local function apply_rules(theme_name)
    local wanted = {}
    local chunk = loadfile(THEMES_DIR .. theme_name .. "/hypr.lua")
    if chunk then
        local ok, spec = pcall(chunk)
        if ok and type(spec) == "table" then
            for _, kind in ipairs({ "window", "layer" }) do
                local make = kind == "window" and hl.window_rule or hl.layer_rule
                for _, r in ipairs(spec[kind .. "_rules"] or {}) do
                    local key = kind .. ":" .. tostring(r.name)
                    wanted[key] = true
                    if not theme_rules[key] then theme_rules[key] = make(r) end
                end
            end
        end
    end
    for key, rule in pairs(theme_rules) do rule:set_enabled(wanted[key] == true) end
end

-- ========================= Accent =========================
-- The focused-window border is the theme's gradient (hypr.active_border,
-- applied just above). With a wallpaper accent set
-- (scripts/theme-from-wallpaper.py), the stops listed in hypr.accent_stops
-- take the accent instead -- in cyberpunk the two leading cyan ones -- so the
-- frame matches the bar and the wallpaper; the rest of the gradient stays.
-- No accent = the theme's border untouched (apply_look has just set it, so
-- turning the accent off needs no reload any more).
local function apply_accent(hex, t)
    if not hex or not hex:match("^#%x%x%x%x%x%x$") then return end
    local g = gradient(t["hypr.active_border"])
    if not g then return end
    local c = "rgb(" .. hex:sub(2) .. ")"
    local any = false
    for stop in (t["hypr.accent_stops"] or ""):gmatch("%d+") do
        local i = tonumber(stop)   -- a new local: Lua 5.5 loop variables are const
        if g.colors[i] then g.colors[i] = c; any = true end
    end
    if any then hl.config({ general = { col = { active_border = g } } }) end
end

-- ========================= Your window look =========================
-- The theme decides how windows look; you get the last word. Any hypr.* key
-- of a theme can be overridden in the display state file (lua/shared.lua) as
-- hyprlook.<the same key without "hypr.">:
--
--     hyprlook.gaps_out=12        wins over the theme's hypr.gaps_out
--     hyprlook.blur=no            ... over hypr.blur
--
-- The overrides are laid over the resolved theme before ANY of it is applied,
-- so they go through exactly the code above: gamemode still strips gaps /
-- borders / rounding / blur / shadow while it is on (and your values come
-- back with everything else when it goes off), the accent is still laid over
-- the border gradient, and switching themes keeps your overrides -- they are
-- yours, not the theme's. Removing the hyprlook.* lines ("Use the theme's
-- look" on the page, `window-look.py reset`) is the whole undo.
--
-- ~/.config/hypr/scripts/window-look.py is the writer: it validates and
-- clamps each value, drops an override that equals the theme's own value,
-- and re-runs M.apply() through `hyprctl eval`. The page and that script
-- offer the keys below plus the theme's gaps_in, gaps_out, border_size,
-- rounding, blur, blur_size, blur_passes, shadow and shadow_range; others
-- (hyprlook.active_border, hyprlook.blur_noise, ...) work when written by
-- hand.
--
-- The behaviour keys. No theme sets these today, but a theme may (as
-- hypr.<key>), so they are read from the same merged table. A key nobody
-- sets gets the value below, which is also the plain config's (Hyprland's
-- defaults, and general.layout from lua/settings.lua), so clearing an
-- override really goes back -- unlike the theme keys, which the base theme
-- always supplies. scripts/window-look.py KEYS lists the same defaults
-- (tests/test_settings_windows.py checks that they agree).
local LOOK_DEFAULTS = {
    rounding_power   = "2",        -- corner shape: 2 round, higher = squircle
    dim_inactive     = "no",       -- darken the windows you are not using
    dim_strength     = "0.5",      -- by how much (0-1)
    inactive_opacity = "1.0",      -- see-through unfocused windows (0-1)
    layout           = "dwindle",  -- dwindle | master | scrolling
    force_split      = "0",        -- dwindle: new window 0 by the mouse, 1 left/top, 2 right/bottom
    new_status       = "slave",    -- master: new window master | slave (the stack) | inherit
    orientation      = "left",     -- master: where the master sits
    resize_on_border = "no",       -- drag a window's border to resize it
    snap             = "no",       -- floating windows snap to edges and each other
}
local LOOK_CHOICES = {
    layout      = { dwindle = true, master = true, scrolling = true },
    new_status  = { master = true, slave = true, inherit = true },
    orientation = { left = true, right = true, top = true, bottom = true, center = true },
    force_split = { ["0"] = true, ["1"] = true, ["2"] = true },
}

-- theme table + the state's hyprlook.* keys, as one new table (the theme's
-- own table is left as M.theme returned it).
function M.with_overrides(t, st)
    local out = {}
    for k, v in pairs(t) do out[k] = v end
    for k, v in pairs(st) do
        local key = k:match("^hyprlook%.([%w_]+)$")
        if key and v ~= "" then out["hypr." .. key] = v end
    end
    return out
end

local function clamp(v, lo, hi)
    v = tonumber(v)
    if not v then return nil end
    return math.max(lo, math.min(hi, v))
end

local function apply_behaviour(t)
    local function v(key)
        local x = t["hypr." .. key]
        if x == nil or x == "" or (LOOK_CHOICES[key] and not LOOK_CHOICES[key][x]) then
            x = LOOK_DEFAULTS[key]     -- a hand-typed "masterr" must not break the load
        end
        return x
    end
    hl.config({
        general = {
            resize_on_border = flag(v("resize_on_border")),
            snap = { enabled = flag(v("snap")) },
        },
        decoration = {
            rounding_power   = clamp(v("rounding_power"), 1, 10),
            dim_inactive     = flag(v("dim_inactive")),
            dim_strength     = clamp(v("dim_strength"), 0, 1),
            inactive_opacity = clamp(v("inactive_opacity"), 0.1, 1),
        },
        dwindle = { force_split = tonumber(v("force_split")) },
        master  = { new_status = v("new_status"), orientation = v("orientation") },
    })
    -- Only when it changes: a layout switch re-tiles every workspace, and
    -- apply() runs for every filter / animation / accent change too.
    local layout = v("layout")
    if hl.get_config("general.layout") ~= layout then
        hl.config({ general = { layout = layout } })
    end
end

function M.apply()
    local st = S.state()
    local name = (st.theme and st.theme ~= "") and st.theme or BASE_THEME
    local t = M.with_overrides(M.theme(name), st)
    apply_look(t)
    apply_behaviour(t)
    apply_rules(name)
    apply_animations(st.anim or t.anim)
    apply_filter(st.filter)
    apply_accent(st.accent, t)
end

M.apply()

return M
