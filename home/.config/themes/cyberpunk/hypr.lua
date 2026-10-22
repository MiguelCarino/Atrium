-- ~/.config/themes/cyberpunk/hypr.lua -- Hyprland rules for the cyberpunk
-- theme only (lua/display.lua enables them while cyberpunk is current; the
-- contract is in its "Theme rules" comment).
--
-- Nautilus as dark glass: gtk4.css next to this file makes its surfaces
-- translucent, and this keeps the blur behind them on and fades the window a
-- little while it is NOT focused (the focused one stays at full opacity --
-- window opacity fades the text with the glass; the CSS alpha does not).
-- The same rule aero has, under its own name (names are unique across
-- themes; `theme.py check` insists).
---@module 'hl'

return {
    window_rules = {
        {
            name    = "cyberpunk-nautilus-glass",
            match   = { class = "^(org\\.gnome\\.Nautilus)$" },
            opacity = "1.0 0.94",
            no_blur = false,
        },
        -- mpv framed in neon: a 3 px cyan-to-hot-pink tube, hard corners.
        -- Settings > Theme > Video player "Theme" is this; any other preset
        -- there (lua/mpvframe.lua) wins over it.
        {
            name         = "cyberpunk-mpv-neon",
            match        = { class = "^(mpv)$" },
            border_size  = 3,
            border_color = "rgb(00f0ff) rgb(ff0055) 45deg rgba(00f0ff66) rgba(ff005566) 45deg",
            rounding     = 0,
        },
    },
}
