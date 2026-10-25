-- ~/.config/themes/orbit/hypr.lua -- Hyprland rules for the orbit theme only.
-- Read by ~/.config/hypr/lua/display.lua (its "Theme rules" comment explains
-- the contract): each rule is created once, by name, and enabled only while
-- orbit is the current theme, after every rule in lua/rules.lua. Rule names
-- are unique across themes (`theme.py check`).
--
-- No Nautilus rule: gtk4.css next to this file is OPAQUE (a console has no
-- glass), so there is nothing for a "<theme>-nautilus-glass" rule to frost;
-- aero, moe and lofi need one because theirs is translucent.
---@module 'hl'

return {
    window_rules = {
        -- mpv in a monitor bezel: the windows' teal -> steel border at 3 px,
        -- a touch thicker than the 2 px windows so the picture reads as a
        -- screen on the console; unfocused, plain steel. Square-ish corners
        -- like the panes (4). Settings > Theme > Video player "Theme" is
        -- this; any other preset there (lua/mpvframe.lua) wins over it.
        {
            name         = "orbit-mpv-bezel",
            match        = { class = "^(mpv)$" },
            border_size  = 3,
            border_color = "rgb(5cc8db) rgb(2a3a57) 45deg rgb(2a3a57) rgb(1c2840) 45deg",
            rounding     = 4,
        },
    },
}
