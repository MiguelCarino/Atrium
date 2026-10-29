-- ~/.config/hypr/lua/input.lua
-- Required from the end of lua/settings.lua. Keyboard, mouse and touchpad:
-- every input.* option the desktop sets, plus the two pointer habits that
-- live in other sections (cursor.hide_on_key_press, misc.middle_click_paste).
--
-- The values are chosen at runtime -- Settings > Keyboard, mouse & touchpad,
-- or ~/.config/hypr/scripts/input-settings.py from a terminal -- and kept in
-- their own small key=value file, the same format as the display state
-- (lua/shared.lua explains both):
--
--   ~/.local/state/hypr/input.conf
--
-- A missing key means DEFAULTS below, so deleting the file is a full reset.
-- This module applies the file at every config load (so a reload, gamemode
-- OFF and a re-login all put the choices back), and input-settings.py writes
-- the file and then runs
--     hyprctl eval 'require("lua.input").apply()'
-- so a change takes at once through the very same code. Nothing else sets
-- these options: the input block that used to sit in lua/settings.lua moved
-- here, with its values as the defaults, so the desktop with no state file
-- is exactly the desktop it was before.
--
-- Why a file of its own and not more keys in display.conf: display.py and
-- theme.py rewrite display.conf as a whole (read, change one key, write), and
-- two writers racing on one file can lose each other's key. One file per
-- writer cannot.

---@module 'hl'

local S = require("lua.shared")

local M = {}

M.state_file = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state"))
               .. "/hypr/input.conf"

-- ========================= Defaults =========================
-- Strings, in the state file's own format, so this table is ALSO what
-- input-settings.py reads for "the default" (it parses the lines between the
-- two markers -- keep one `["key"] = "value",` per line). The values are the
-- old lua/settings.lua input block and Hyprland's own defaults for the rest.
--
--   layouts     the xkb layouts in switching order, a variant in brackets:
--               "us,latam" or "us(intl),es". xkb allows at most 4.
--   switch      the xkb option that switches layout ("grp:win_space_toggle"
--               is SUPER+Space). Empty = no key; the bar's language pill
--               still switches. Not a Hyprland bind, so `hyprctl binds`
--               does not list it -- except SUPER+Space, which is one (see
--               xkb_options below) and also cycles into Japanese.
--   caps        what Caps Lock does (an xkb caps:/ctrl: option), or empty
--   compose     the Compose key (an xkb compose: option), or empty
--   xkb_extra   any other xkb options, comma separated, passed through
--   follow_mouse  0 click to focus, 1 focus follows the mouse, 2 click
--               focuses but the hovered window gets the scroll wheel
--   hide_after  seconds of a still mouse before the pointer hides
--               (cursor.inactive_timeout), 0 = never
--   hide_on_typing  the pointer hides while you type (cursor.hide_on_key_press)
--   edge_reach  the widest gap between screens, logical px, that pushing the
--               cursor on a screen edge jumps across (lua/edgejump.lua); 0 =
--               no jumps at all
--   main_mod    the everyday keys' modifier, ALT or SUPER. Read by
--               lua/shared.lua (mainMod), not here, and only at a reload --
--               input-settings.py reloads for it
-- INPUT-DEFAULTS-BEGIN
local DEFAULTS = {
    ["layouts"]                    = "us,latam",
    ["switch"]                     = "grp:win_space_toggle",
    ["caps"]                       = "",
    ["compose"]                    = "",
    ["xkb_extra"]                  = "",
    ["repeat_rate"]                = "25",
    ["repeat_delay"]               = "600",
    ["numlock"]                    = "off",
    ["sensitivity"]                = "0",
    ["accel"]                      = "adaptive",
    ["natural_scroll"]             = "off",
    ["left_handed"]                = "off",
    ["scroll_factor"]              = "1",
    ["middle_click_paste"]         = "on",
    ["hide_on_typing"]             = "on",
    ["hide_after"]                 = "3",
    ["edge_reach"]                 = "600",
    ["main_mod"]                   = "ALT",
    ["follow_mouse"]               = "1",
    ["touchpad.natural_scroll"]    = "off",
    ["touchpad.tap_to_click"]      = "on",
    ["touchpad.disable_while_typing"] = "on",
    ["touchpad.clickfinger"]       = "off",
    ["touchpad.scroll_factor"]     = "1",
}
-- INPUT-DEFAULTS-END
M.defaults = DEFAULTS

-- ========================= Reading =========================
-- A value from the state file when it is there and usable, else the
-- default: a hand-edited file with "repeat_rate=fast" falls back to 25 for
-- that one key instead of breaking the whole config load (and hypr-guard.py
-- then restoring the last good config over an input typo).
local function flag(v)
    return v == "on" or v == "yes" or v == "true" or v == "1"
end

local function number(st, key, lo, hi)
    local n = tonumber(st[key])
    if n == nil or n < lo or n > hi then n = tonumber(DEFAULTS[key]) end
    return n
end

local function str(st, key)
    local v = st[key]
    if v == nil then v = DEFAULTS[key] end
    return v
end

local function bool(st, key)
    return flag(str(st, key))
end

-- "us,latam(deadtilde)" -> kb_layout "us,latam", kb_variant ",deadtilde".
-- kb_variant stays "" when no layout has one (what Hyprland had before).
function M.split_layouts(spec)
    local codes, variants, any = {}, {}, false
    for tok in (spec or ""):gmatch("[^,%s]+") do
        local code, variant = tok:match("^([%w_%-]+)%(([%w_%-]*)%)$")
        if not code then code, variant = tok, "" end
        if code:match("^[%w_%-]+$") and #codes < 4 then
            codes[#codes + 1] = code
            variants[#variants + 1] = variant
            if variant ~= "" then any = true end
        end
    end
    if #codes == 0 then return M.split_layouts(DEFAULTS.layouts) end
    return table.concat(codes, ","), any and table.concat(variants, ",") or ""
end

-- switch, caps, compose and the extras, as one kb_options string.
-- grp:win_space_toggle is left out: SUPER+Space is a Hyprland bind instead
-- (lua/binds.lua -> input-settings.py cycle), so the same key also reaches
-- Japanese (Mozc) after the last layout. xkb alone only knows its groups.
local function xkb_options(st)
    local parts = {}
    for _, key in ipairs({ "switch", "caps", "compose", "xkb_extra" }) do
        for opt in str(st, key):gmatch("[^,%s]+") do
            if opt:match("^[%w_%-]+:[%w_%-]+$") and opt ~= "grp:win_space_toggle" then
                parts[#parts + 1] = opt
            end
        end
    end
    return table.concat(parts, ",")
end

function M.state()
    return S.read_kv(M.state_file) or {}
end

-- ========================= Apply =========================
function M.apply()
    local st = M.state()
    local layout, variant = M.split_layouts(str(st, "layouts"))
    local accel = str(st, "accel")
    if accel ~= "flat" and accel ~= "adaptive" then accel = DEFAULTS.accel end
    local follow = number(st, "follow_mouse", 0, 3)
    hl.config({
        input = {
            kb_layout          = layout,
            kb_variant         = variant,
            kb_options         = xkb_options(st),
            repeat_rate        = math.floor(number(st, "repeat_rate", 1, 100)),
            repeat_delay       = math.floor(number(st, "repeat_delay", 100, 2000)),
            numlock_by_default = bool(st, "numlock"),
            sensitivity        = number(st, "sensitivity", -1, 1),
            accel_profile      = accel,
            natural_scroll     = bool(st, "natural_scroll"),
            left_handed        = bool(st, "left_handed"),
            scroll_factor      = number(st, "scroll_factor", 0.1, 5),
            follow_mouse       = math.floor(follow),
            touchpad = {
                natural_scroll       = bool(st, "touchpad.natural_scroll"),
                tap_to_click         = bool(st, "touchpad.tap_to_click"),
                disable_while_typing = bool(st, "touchpad.disable_while_typing"),
                clickfinger_behavior = bool(st, "touchpad.clickfinger"),
                scroll_factor        = number(st, "touchpad.scroll_factor", 0.1, 5),
            },
        },
        cursor = {
            hide_on_key_press = bool(st, "hide_on_typing"),
            inactive_timeout  = math.floor(number(st, "hide_after", 0, 60)),
        },
        misc   = { middle_click_paste = bool(st, "middle_click_paste") },
    })
    -- edgejump keeps its reach in a local; tell it when it is loaded (it is
    -- required after this file, and reads the same key itself at load).
    local ej = package.loaded["lua.edgejump"]
    if type(ej) == "table" and ej.set_reach then
        ej.set_reach(math.floor(number(st, "edge_reach", 0, 2000)))
    end
end

M.apply()

return M
