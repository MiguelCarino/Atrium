-- lua/focusguard.lua -- Focus guard's dimming (scripts/focus-guard.py): while
-- a focus block runs, the windows it calls distracting (the apps on its
-- list, a browser on one of its sites) are see-through, NOT closed or
-- blocked -- they still work, they just stop calling for attention.
--
-- Which windows: focus-guard.py tags them "focus-dim" (hl.dsp.window.tag,
-- one window at a time, and untags them when the block ends or a browser
-- tab moves off the site), so the list of apps and sites never has to be a
-- regex in here. Verified on 0.56.2: a rule matching a tag reaches a window
-- the moment the tag is added or the rule is switched on, and lets it go the
-- moment either is undone -- no reload, nothing to re-open.
--
-- How see-through: opacity= in $XDG_RUNTIME_DIR/focus-guard-dim.conf
-- (20-95, %), on=1 while a block wants dimming. Same scheme as lua/pip.lua
-- and lua/mpvframe.lua: one rule per opacity value, made once per Lua state
-- by name and then only switched with set_enabled, so moving the slider back
-- and forth never stacks duplicates. focus-guard.py writes the file and runs
-- `hyprctl eval 'require("lua.focusguard").apply()'` at a block's start and
-- end, when the setting changes, and after a config reload (Hyprland's
-- configreloaded event: a reload starts a fresh Lua state without this
-- module unless hyprland.lua requires it) -- the eval also loads it.
--
-- The file is in the runtime dir (a block lasts a login, like the timer
-- that drives it): after a re-login nothing is dimmed.

---@module 'hl'

local S = require("lua.shared")

local M = {}

M.state_file = (os.getenv("XDG_RUNTIME_DIR") or "/run/user/1000") .. "/focus-guard-dim.conf"
M.tag = "focus-dim"

local made = {}     -- rule name -> HL rule

-- (on, percent): percent 20..95 from the file, anything else 55.
function M.wanted()
    local kv = S.read_kv(M.state_file) or {}
    local n = tonumber(kv.opacity or "")
    if not n or n < 20 or n > 95 then n = 55 end
    return kv.on == "1", math.floor(n)
end

function M.apply()
    local on, pct = M.wanted()
    local want = on and ("focus-guard-dim-" .. pct) or nil
    if want and not made[want] then
        local a = string.format("%.2f", pct / 100)
        -- "active inactive": the same focused or not.
        made[want] = hl.window_rule({ name = want, match = { tag = M.tag }, opacity = a .. " " .. a })
    end
    for name, r in pairs(made) do r:set_enabled(name == want) end
end

M.apply()

return M
