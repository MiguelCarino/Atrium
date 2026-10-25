-- ~/.config/themes/seasons/hypr.lua -- Hyprland rules for the seasons theme
-- only. Read by ~/.config/hypr/lua/display.lua (its "Theme rules" comment
-- explains the contract): each rule is created once, by name, and enabled
-- only while seasons is the current theme, after every rule in
-- lua/rules.lua. Rule names are unique across themes (`theme.py check`).
--
-- The theme's all year: lua/display.lua reads this file from the theme
-- folder and does not see seasons, so a season folder may not hold one
-- (theme.py check says so) and the colours below are fixed -- the autumn
-- copper the base theme.conf's border starts from, which sits well enough
-- beside any season's wallpaper on a 3 px frame. The windows' own border
-- does follow the season (hypr.accent_stops=1: the season's accent= is
-- stop 1).
--
-- No Nautilus rule: gtk4.css next to this file is OPAQUE, so there is
-- nothing for a "<theme>-nautilus-glass" rule to frost.
---@module 'hl'

return {
    window_rules = {
        -- mpv in a picture frame: copper into the theme's dark moss at 3 px,
        -- a touch thicker than the 2 px windows so the picture reads as a
        -- framed print; unfocused, the moss alone. The theme's 10 px corners.
        -- Settings > Theme > Video player "Theme" is this; any other preset
        -- there (lua/mpvframe.lua) wins over it.
        {
            name         = "seasons-mpv-frame",
            match        = { class = "^(mpv)$" },
            border_size  = 3,
            border_color = "rgb(ee9a62) rgb(262c2a) 45deg rgb(262c2a) rgb(1d2321) 45deg",
            rounding     = 10,
        },
    },
}
