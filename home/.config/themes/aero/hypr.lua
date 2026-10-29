-- ~/.config/themes/aero/hypr.lua -- Hyprland rules for the aero theme only.
-- Read by ~/.config/hypr/lua/display.lua (its "Theme rules" comment explains
-- the contract): each rule is created once, by name, and enabled only while
-- aero is the current theme, after every rule in lua/rules.lua.
--
-- Nautilus as a real frosted window. The glass itself is gtk4.css: its
-- window, view, sidebar and header backgrounds are translucent navy, and
-- Hyprland blurs whatever is behind a translucent surface. This rule makes
-- sure that blur is on for it (no_blur = false outranks any broader rule
-- that might switch it off) and fades it a touch while it is NOT focused --
-- the focused window stays at full opacity, because window opacity fades the
-- text with the glass, and the text is what has to stay readable over a busy
-- wallpaper. The translucency comes from the CSS alpha, which leaves the
-- text opaque.
---@module 'hl'

return {
    window_rules = {
        {
            name    = "aero-nautilus-glass",
            match   = { class = "^(org\\.gnome\\.Nautilus)$" },
            opacity = "1.0 0.92",
            no_blur = false,
        },
        -- mpv in a wide pane of glass: a 10 px translucent white rim with a
        -- cool highlight across it and round corners. The picture stays
        -- opaque (browsers-mpv-opaque's force_rgbx) and so does its blur
        -- setting: no_blur is left to that rule (on), because a blur pass
        -- under a playing video is redrawn every frame of it -- 24-60 times
        -- a second for something the opaque picture hides -- just to frost a
        -- 10 px rim. The rim is still translucent glass over the wallpaper.
        -- Settings > Theme > Video player "Theme" is this; any other preset
        -- there (lua/mpvframe.lua) wins over it.
        {
            name         = "aero-mpv-glass",
            match        = { class = "^(mpv)$" },
            border_size  = 10,
            border_color = "rgba(ffffff5c) rgba(bfe3ff33) rgba(ffffff5c) 135deg rgba(ffffff38) rgba(bfe3ff22) rgba(ffffff38) 135deg",
            rounding     = 12,
        },
    },
}
