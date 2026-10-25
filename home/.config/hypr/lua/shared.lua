-- ~/.config/hypr/lua/shared.lua
-- The values more than one module needs, in ONE table, returned to whoever
-- requires it. This is the replacement for the file-level locals of the
-- single-file config: a `local` cannot cross a file boundary, and making them
-- globals instead would let any typo silently create a new one.
--
--   local S = require("lua.shared")
--   local mainMod = S.mainMod
--
-- require() caches the module, so every caller in one config load gets the SAME
-- table -- there is one mainMod, not one per module. A `hyprctl
-- reload` starts from a fresh Lua state (verified: a global set with `hyprctl
-- eval` and the package.loaded entry of a test module were both nil after a
-- reload), so editing this file and reloading always picks up the new values.
--
-- Values that only one module uses stay local to it (resize_delta and
-- monitor_dir in lua/binds.lua, the gamemode helpers in lua/gamemode.lua).

---@module 'hl'

local M = {}

-- ========================= Variables =========================
local mainMod = "ALT"
local scrDir  = (os.getenv("HOME") or "") .. "/Pictures/Screenshots"   -- absolute: XDG_SCREENSHOTS_DIR in lua/env.lua

M.mainMod          = mainMod
M.scrDir           = scrDir

-- ========================= Display state =========================
-- Choices made at runtime that must survive a reload -- and a reload happens
-- more than you would think: gamemode OFF is one (lua/gamemode.lua). Kept in
-- one small key=value file, written by ~/.config/hypr/scripts/display.py (the
-- display panel, the launcher's commands, the binds) and read here:
--
--   ~/.local/state/hypr/display.conf
--     theme=cyberpunk         desktop theme, ~/.config/themes/<name>/
--                             (lua/display.lua; set by scripts/theme.py)
--     anim=smooth             animation preset            (lua/display.lua)
--     filter=grayscale        screen filter, or empty     (lua/display.lua)
--     accent=#4fc3ff          wallpaper accent, or empty  (lua/display.lua)
--     theme_auto=on           accent follows the wallpaper (theme-from-wallpaper.py)
--     glass_aero=40           that theme's window glass, 0-100 (scripts/theme.py
--                             glass; the display panel's slider). Not read by Lua
--     wallpaper_motion=off    the theme's moving wallpaper off (scripts/wallpaper-
--                             slideshow.py motion). Not read by Lua
--     season_hemisphere=auto  a seasonal theme's hemisphere: north, south or
--                             auto (scripts/theme.py season). Not read by Lua
--     season_pin=winter       hold one season; empty or auto = follow the
--                             date (scripts/theme.py season pin). Not read by Lua
--     hdr.DP-1=off            HDR off for that output     (lua/monitors.lua)
--     sdr_white.DP-1=220      SDR white level in HDR, nits (lua/monitors.lua)
--
-- A missing file or key means "the config's own default", so deleting the
-- file is always a full reset.
--
-- Keyboard, mouse and touchpad choices follow the same pattern in a file of
-- their own, written by ~/.config/hypr/scripts/input-settings.py (Settings >
-- Keyboard, mouse & touchpad) and applied by lua/input.lua, which lists the
-- keys and their defaults:
--
--   ~/.local/state/hypr/input.conf
--     layouts=us,latam        xkb layouts in order, variant in brackets
--     switch=grp:win_space_toggle   the layout-switch key (an xkb option)
--     repeat_rate=25  repeat_delay=600  numlock=off
--     sensitivity=0  accel=adaptive  natural_scroll=off  scroll_factor=1
--     follow_mouse=1  touchpad.tap_to_click=on  ...
--
-- Same reader (read_kv below), same "missing = default" rule. Not JSON: Hyprland's Lua has no JSON parser,
-- and a line per key is trivial on both sides.
M.state_file = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state"))
               .. "/hypr/display.conf"

-- One key=value file, read into a table; nil when the file cannot be opened
-- (so a caller can tell "missing" from "empty"). Lines starting with # are
-- comments. Also the reader for the themes' theme.conf (lua/display.lua),
-- which is the same format on purpose -- ~/.config/hypr/scripts/theme.py
-- writes and reads both with the same rules.
function M.read_kv(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local t = {}
    for line in f:lines() do
        if not line:match("^%s*#") then
            local k, v = line:match("^%s*([%w%._%-]+)%s*=%s*(.-)%s*$")
            if k then t[k] = v end
        end
    end
    f:close()
    return t
end

function M.state()
    return M.read_kv(M.state_file) or {}
end

return M
