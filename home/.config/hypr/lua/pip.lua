-- lua/pip.lua -- the live picture-in-picture mirror (scripts/pip.py): an mpv
-- window, app id desktop.pip, showing a window or a piece of the screen.
--
-- Not the "pip" rule in lua/rules.lua: that one is for the browsers' own
-- Picture-in-Picture windows (matched by title), and SUPER+SHIFT+P moves a
-- real window into the corner. This is a COPY of something, live, in a
-- small window of its own; the original stays where it is.
--
-- The rules: floating, pinned (on every workspace of its screen), never
-- takes the focus when it opens (you keep typing where you were), no border
-- or shadow, the aspect ratio kept when ALT+right-drag resizes it. Size and
-- place are NOT here: pip.py sets them after the window maps, from the
-- source's own shape and the corner in Settings -- 0.56's move expressions
-- do not resolve window_w / window_h (see the note on the "pip" rule).
--
-- The opacity is pip.py's setting (opacity= in ~/.local/state/hypr/pip.conf,
-- 30-100). Same scheme as lua/mpvframe.lua: one rule per value, made once
-- per Lua state by name and then only switched with set_enabled, so moving
-- the slider back and forth never stacks duplicates. pip.py runs
-- `hyprctl eval 'require("lua.pip").apply()'` before each mirror opens and
-- after the setting changes -- which also loads this module if
-- hyprland.lua does not require it.

---@module 'hl'

local S = require("lua.shared")

local M = {}

M.state_file = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state"))
               .. "/hypr/pip.conf"

local MATCH = { class = "^(desktop\\.pip)$" }

local made = {}     -- rule name -> HL rule

local function rule(name, fields)
    if not made[name] then
        local r = { name = name, match = MATCH }
        for k, v in pairs(fields) do r[k] = v end
        made[name] = hl.window_rule(r)
    end
    return made[name]
end

-- 30..100 from the file, anything else 100.
function M.opacity()
    local n = tonumber((S.read_kv(M.state_file) or {}).opacity or "")
    if not n or n < 30 or n > 100 then return 100 end
    return math.floor(n)
end

function M.apply()
    rule("pip-mirror", {
        float             = true,
        pin               = true,
        no_initial_focus  = true,
        keep_aspect_ratio = true,
        border_size       = 0,
        no_shadow         = true,
        no_blur           = true,
        rounding          = 10,
    })
    local pct = M.opacity()
    local want = "pip-mirror-opacity-" .. pct
    if pct < 100 then
        local a = string.format("%.2f", pct / 100)
        -- "active inactive": the same both ways, focused or not.
        rule(want, { opacity = a .. " " .. a })
    end
    for name, r in pairs(made) do
        if name:match("^pip%-mirror%-opacity%-") then r:set_enabled(name == want) end
    end
end

M.apply()

return M
