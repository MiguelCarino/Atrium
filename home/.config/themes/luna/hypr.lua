-- ~/.config/themes/luna/hypr.lua -- Hyprland rules for the luna theme only.
-- Read by ~/.config/hypr/lua/display.lua (its "Theme rules" comment explains
-- the contract): each rule is created once, by name, and enabled only while
-- luna is the current theme, after every rule in lua/rules.lua.
--
-- No Nautilus rule: gtk4.css next to this file is OPAQUE (XP had no glass),
-- so there is nothing for a "<theme>-nautilus-glass" rule to frost. aero
-- and moe need one because their gtk4.css is translucent.
---@module 'hl'

return {
    window_rules = {
        -- mpv in a thick XP title-bar frame: the same blue as theme.conf's
        -- window border (lit at the top, deep blue at the bottom, 90deg),
        -- and the pale inactive title blue when it is not focused. 4 px, a
        -- touch thicker than the 3 px windows, so the picture reads as framed.
        -- Settings > Theme > Video player "Theme" is this; any other preset
        -- there (lua/mpvframe.lua) wins over it.
        {
            name         = "luna-mpv-titlebar",
            match        = { class = "^(mpv)$" },
            border_size  = 4,
            border_color = "rgb(3d86f0) rgb(2058d0) rgb(1a46a6) 90deg rgb(9db0e0) rgb(7a90c8) 90deg",
            rounding     = 8,
        },
    },
}
