-- ~/.config/hypr/lua/accessibility.lua
-- Required from the end of lua/settings.lua. The parts of Settings >
-- Accessibility that are Hyprland's to do:
--
--   * the screen magnifier, cursor.zoom_factor: Hyprland magnifies the screen
--     the pointer is on, around the pointer, and follows it
--   * the visual alert's flash (scripts/accessibility.py flash) appears at
--     once: no layer animation, the script fades it itself
--   * at login, Orca is started when the screen reader is switched on (its own
--     autostart entry says OnlyShowIn=GNOME, so nothing else would)
--
-- The magnifier's factor is chosen at runtime -- the Accessibility page, the
-- zoom keys, or ~/.config/hypr/scripts/accessibility.py zoom -- and kept in a
-- small key=value file of its own, the display state's format (lua/shared.lua
-- explains it; one file per writer, like lua/input.lua's):
--
--   ~/.local/state/hypr/accessibility.conf
--     zoom=2              the magnifier, 1 (off) to 10; missing = 1
--
-- (The script keeps a few before.* lines there too, for putting things back;
-- nothing here reads them.) apply() runs at every config load, so a reload,
-- gamemode OFF and a re-login keep the zoom, and accessibility.py runs
--     hyprctl eval 'require("lua.accessibility").apply()'
-- after writing the file, so a change takes at once through the same code.

---@module 'hl'

local S = require("lua.shared")

local M = {}

M.state_file = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state"))
               .. "/hypr/accessibility.conf"

-- The factor from the file, clamped the way the script clamps it, so a hand
-- edit cannot ask Hyprland for something it would refuse.
local function zoom(st)
    local z = tonumber(st.zoom or "") or 1
    if z ~= z then z = 1 end                 -- NaN
    return math.max(1, math.min(10, z))
end

function M.apply()
    local st = S.read_kv(M.state_file) or {}
    hl.config({ cursor = { zoom_factor = zoom(st) } })
end

hl.layer_rule({
    name    = "a11y-flash",
    match   = { namespace = "^(a11y-flash)$" },
    no_anim = true,
})

hl.on("hyprland.start", function()
    hl.exec_cmd("~/.config/hypr/scripts/accessibility.py login")
end)

M.apply()

return M
