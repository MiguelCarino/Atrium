-- ~/.config/themes/orchard-dark/hypr.lua -- Hyprland rules for the orchard-dark
-- theme only.
-- Read by ~/.config/hypr/lua/display.lua (its "Theme rules" comment explains
-- the contract): each rule is created once, by name, and enabled only while
-- orchard-dark is the current theme, after every rule in lua/rules.lua. Rule
-- names are unique across themes (`theme.py check`): the same set as
-- orchard/hypr.lua under orchard-dark-* names.
--
-- Vibrancy for the two windows whose stylesheets are partly translucent:
-- Nautilus's sidebar (gtk4.css: #323234 at 90%) and the LLM chat. Blur is
-- kept on for them (no_blur = false outranks any broader rule that might
-- switch it off), and each fades a touch while NOT focused. The spec asked
-- for "0.97 0.94"; the focused window stays at 1.0 instead, for the reason
-- aero and lofi give: window opacity fades the text with the glass, and the
-- translucency already comes from the CSS alpha, which leaves the text
-- opaque. The chat is a step less faded unfocused (0.95) than Files (0.94):
-- it is often read while another window has the focus.
---@module 'hl'

return {
    window_rules = {
        {
            name    = "orchard-dark-nautilus-vibrancy",
            match   = { class = "^(org\\.gnome\\.Nautilus)$" },
            opacity = "1.0 0.94",
            no_blur = false,
        },
        {
            name    = "orchard-dark-chat-vibrancy",
            match   = { class = "^(llm-chat)$" },
            opacity = "1.0 0.95",
            no_blur = false,
        },
        -- mpv as a plain window of this desktop: the 1 px neutral hairline
        -- every window has here (white at 18% focused, 10% not) and the
        -- same 10 px corners -- no frame of colour round the picture.
        -- Settings > Theme > Video player "Theme" is this; any other preset
        -- there (lua/mpvframe.lua) wins over it.
        {
            name         = "orchard-dark-mpv-window",
            match        = { class = "^(mpv)$" },
            border_size  = 1,
            border_color = "rgba(ffffff2e) rgba(ffffff1a)",
            rounding     = 10,
        },
    },
}
