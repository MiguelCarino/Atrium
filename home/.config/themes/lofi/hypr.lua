-- ~/.config/themes/lofi/hypr.lua -- Hyprland rules for the lofi theme only
-- (lua/display.lua enables them while lofi is current; the contract is in its
-- "Theme rules" comment).
--
-- Nautilus as dusk glass: gtk4.css next to this file makes its surfaces a
-- little translucent; this keeps the blur behind them on (so the film grain of
-- hypr.blur_noise shows in the frost) and fades the window a touch while it is
-- NOT focused (the focused one stays opaque, so the text never fades with the
-- glass). Same rule as moe's and aero's, under its own name -- rule names are
-- unique across themes (`theme.py check`).
---@module 'hl'

return {
    window_rules = {
        {
            name    = "lofi-nautilus-glass",
            match   = { class = "^(org\\.gnome\\.Nautilus)$" },
            opacity = "1.0 0.94",
            no_blur = false,
        },
        -- mpv as a cassette: a 4 px peach-lilac band (the tape label's two
        -- colours), the inactive band the same at 60%, round corners like the
        -- theme's panes. Settings > Theme > Video player "Theme" is this; any
        -- other preset there (lua/mpvframe.lua) wins over it.
        {
            name         = "lofi-mpv-cassette",
            match        = { class = "^(mpv)$" },
            border_size  = 4,
            border_color = "rgb(f2a477) rgb(b9a3ea) 45deg rgba(f2a47799) rgba(b9a3ea99) 45deg",
            rounding     = 14,
        },
    },
}
