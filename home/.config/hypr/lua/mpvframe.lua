-- lua/mpvframe.lua -- the mpv window's frame: a preset picked in Settings >
-- Theme (or `mpv-style.py frame NAME`), laid over the theme's own border.
--
--   theme     no rule: the mpv window looks like every other window
--   cinema    no border, square corners, no shadow -- just the picture
--   thin      a 1 px border
--   bold      a 4 px border
--   accent    3 px, a gradient of the accent colour (display state accent=)
--   rainbow   3 px, a rainbow gradient
--   soft      big squircle corners and a 2 px border
--   square    square corners and a 2 px border
--
-- The choice is frame= in ~/.local/state/hypr/mpv-style.conf (written by
-- scripts/mpv-style.py, which then runs
-- `hyprctl eval 'require("lua.mpvframe").apply()'`). Same scheme as the
-- themes' own rules in lua/display.lua: each rule is created once per Lua
-- state, by name, and then only switched with set_enabled, so picking presets
-- back and forth never stacks duplicates. The accent preset's name carries
-- the colour, so a new accent gets a new rule instead of needing a reload.
-- Required after lua.display, so these rules come after the theme's and win
-- a tie. While gamemode is on (it strips borders and rounding) none is on.

---@module 'hl'

local S = require("lua.shared")

local M = {}

M.state_file = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state"))
               .. "/hypr/mpv-style.conf"

local MATCH = { class = "^(mpv)$" }

-- Each preset's window-rule fields (besides name and match).
function M.presets(accent)
    local a = (accent or ""):match("^#?(%x%x%x%x%x%x)$")
    return {
        cinema  = { border_size = 0, rounding = 0, no_shadow = true },
        thin    = { border_size = 1 },
        bold    = { border_size = 4 },
        -- Colours are "focused gradient  unfocused gradient": without the
        -- second one an unfocused mpv falls back to the theme's grey border.
        accent  = a and { border_size = 3, border_color = "rgb(" .. a .. ") rgba(" .. a .. "55) 45deg "
                                                     .. "rgba(" .. a .. "99) rgba(" .. a .. "33) 45deg" }
                    or { border_size = 3 },
        rainbow = { border_size = 3,
                    border_color = "rgb(ff0055) rgb(ffb000) rgb(39ff14) rgb(00c8ff) rgb(9f00ff) 45deg "
                                .. "rgba(ff005588) rgba(ffb00088) rgba(39ff1488) rgba(00c8ff88) rgba(9f00ff88) 45deg" },
        soft    = { border_size = 2, rounding = 20, rounding_power = 4 },
        square  = { border_size = 2, rounding = 0 },
    }
end

local made = {}     -- rule name -> HL rule

function M.apply()
    local choice = (S.read_kv(M.state_file) or {}).frame or "theme"
    local accent = S.state().accent
    local gaming = not hl.get_config("animations.enabled")
    local spec = M.presets(accent)[choice]
    local want
    if spec and not gaming then
        want = "mpv-frame-" .. choice
        if choice == "accent" and accent then want = want .. "-" .. accent:gsub("#", "") end
        if not made[want] then
            local rule = { name = want, match = MATCH }
            for k, v in pairs(spec) do rule[k] = v end
            made[want] = hl.window_rule(rule)
        end
    end
    for name, rule in pairs(made) do rule:set_enabled(name == want) end
end

M.apply()

return M
