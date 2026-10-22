-- ~/.config/themes/win95/hypr.lua -- Hyprland rules for the win95 theme only.
-- Read by ~/.config/hypr/lua/display.lua (its "Theme rules" comment explains
-- the contract): each rule is created once, by name, and enabled only while
-- win95 is the current theme, after every rule in lua/rules.lua.
---@module 'hl'

return {
    window_rules = {
        -- mpv in a raised 3-D frame: light top-left fading to dark
        -- bottom-right fakes the Windows 95 bevel; square corners.
        -- Settings > Theme > Video player "Theme" is this; any other preset
        -- there (lua/mpvframe.lua) wins over it.
        {
            name         = "win95-mpv-bevel",
            match        = { class = "^(mpv)$" },
            border_size  = 4,
            border_color = "rgb(dfdfdf) rgb(808080) 135deg rgb(c0c0c0) rgb(808080) 135deg",
            rounding     = 0,
        },
    },
}
