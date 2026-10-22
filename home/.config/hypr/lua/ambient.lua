-- lua/ambient.lua -- the ambient desktop's calmer animations
-- (scripts/ambient.py, Settings > Ambient): in a focus block and / or at
-- night the desktop moves more gently, and afterwards goes back to YOUR
-- animation preset (lua/display.lua, Settings > Screens) untouched.
--
-- How calm: level= in $XDG_RUNTIME_DIR/ambient-anim.conf, written by
-- ambient.py, which then runs `hyprctl eval 'require("lua.ambient").apply()'`
-- (the eval also loads this module: hyprland.lua does not require it, like
-- lua/focusguard.lua). Levels:
--   0  your preset: if this Lua state was calmed, lua/display.lua's apply()
--      puts the preset back; if not, nothing to undo
--   1  gentle: about 1.4x smooth's durations, ease-in-out instead of
--      overshoot, smaller pop-in and workspace slides
--   2  still: fades only, a little slower than the calm preset -- nothing
--      slides or pops
--
-- A reload starts a fresh Lua state with the preset (display.lua applies it
-- at load), so ambient.py watches Hyprland's configreloaded event and
-- display.conf (display.py re-applies the preset on any display change) and
-- evals this again. Never in gamemode: animations.enabled == false is
-- gamemode's switch (lua/gamemode.lua), and this never sets it either way.
-- The curves are lua/display.lua's (easeOutQuint, easeInOut, linear), which
-- are defined at every load before anything can call this.
--
-- The file is in the runtime dir: after a re-login nothing is calmed.

---@module 'hl'

local S = require("lua.shared")

local M = {}

M.state_file = (os.getenv("XDG_RUNTIME_DIR") or "/run/user/1000") .. "/ambient-anim.conf"

--          leaf               speed (ds)  curve           style
local LEVELS = {
    [1] = {
        { "global",           5.5, "easeInOut" },
        { "border",           5.5, "easeInOut" },
        { "windowsIn",        4,   "easeOutQuint", "popin 95%" },
        { "windowsOut",       2.5, "easeInOut",    "popin 95%" },
        { "windowsMove",      4,   "easeOutQuint" },
        { "fade",             3.5, "easeInOut" },
        { "layersIn",         3.5, "easeOutQuint", "fade" },
        { "layersOut",        2.2, "easeInOut",    "fade" },
        { "workspaces",       4,   "easeInOut",    "slidefade 8%" },
        { "specialWorkspace", 4,   "easeInOut",    "slidefadevert 8%" },
    },
    [2] = {
        { "global",           4,   "easeInOut" },
        { "border",           4,   "easeInOut" },
        { "windowsIn",        3.5, "easeInOut",    "popin 100%" },
        { "windowsOut",       2.5, "easeInOut",    "popin 100%" },
        { "windowsMove",      0.1, "linear" },
        { "fade",             3.5, "easeInOut" },
        { "layersIn",         3.5, "easeInOut",    "fade" },
        { "layersOut",        2.5, "easeInOut",    "fade" },
        { "workspaces",       4,   "easeInOut",    "fade" },
        { "specialWorkspace", 4,   "easeInOut",    "fade" },
    },
}

M.applied = 0       -- the level this Lua state shows (0 = the preset)

-- level 0..2 from the file; anything else 0.
function M.wanted()
    local kv = S.read_kv(M.state_file) or {}
    local n = tonumber(kv.level or "")
    if n ~= 1 and n ~= 2 then n = 0 end
    return n
end

function M.apply()
    if not hl.get_config("animations.enabled") then return end     -- gamemode: hands off
    local level = M.wanted()
    if level == 0 then
        if M.applied ~= 0 then
            M.applied = 0
            require("lua.display").apply()      -- the preset (and the rest of the look) again
        end
        return
    end
    for _, a in ipairs(LEVELS[level]) do
        local spec = { leaf = a[1], enabled = true, speed = a[2], bezier = a[3] }
        if a[4] then spec.style = a[4] end
        hl.animation(spec)
    end
    M.applied = level
end

return M
