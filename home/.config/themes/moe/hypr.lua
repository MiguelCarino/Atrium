-- ~/.config/themes/moe/hypr.lua -- Hyprland rules for the moe theme only
-- (lua/display.lua enables them while moe is current; the contract is in its
-- "Theme rules" comment).
--
-- Nautilus as pastel glass: gtk4.css next to this file makes its surfaces a
-- little translucent; this keeps the blur behind them on and fades the window
-- a touch while it is NOT focused (the focused one stays opaque, so the text
-- never fades with the glass). Same rule as aero's and cyberpunk's, under its
-- own name -- rule names are unique across themes (`theme.py check`).
---@module 'hl'

return {
    window_rules = {
        {
            name    = "moe-nautilus-glass",
            match   = { class = "^(org\\.gnome\\.Nautilus)$" },
            opacity = "1.0 0.94",
            no_blur = false,
        },
        -- mpv in a ribbon: a 6 px sakura-lilac-sky band, extra-round corners.
        -- Settings > Theme > Video player "Theme" is this; any other preset
        -- there (lua/mpvframe.lua) wins over it.
        {
            name         = "moe-mpv-ribbon",
            match        = { class = "^(mpv)$" },
            border_size  = 6,
            border_color = "rgb(f78fb3) rgb(b8a4e3) rgb(9fd3f5) 45deg rgba(f78fb399) rgba(b8a4e399) rgba(9fd3f599) 45deg",
            rounding     = 18,
        },
    },
}
