-- ~/.config/themes/matrix/hypr.lua -- Hyprland rules for the matrix theme only.
-- Read by ~/.config/hypr/lua/display.lua (its "Theme rules" comment explains
-- the contract): each rule is created once, by name, and enabled only while
-- matrix is the current theme, after every rule in lua/rules.lua.
---@module 'hl'

return {
    window_rules = {
        -- mpv on a phosphor screen: a 2 px green line that fades along it,
        -- square corners.
        -- Settings > Theme > Video player "Theme" is this; any other preset
        -- there (lua/mpvframe.lua) wins over it.
        {
            name         = "matrix-mpv-phosphor",
            match        = { class = "^(mpv)$" },
            border_size  = 2,
            border_color = "rgb(00ff41) rgba(00ff4140) 90deg rgba(00ff4166) rgba(00ff4120) 90deg",
            rounding     = 0,
        },
    },
}
