-- Loaded from ~/.config/hypr/hyprland.lua (the index). Window overview: every
-- window shrunk into a grid of live previews, like GNOME's Activities or
-- macOS's Mission Control. Hover a tile to focus it, click to go there.
-- It opens on every monitor at once; scroll over a monitor to step that
-- monitor through its workspaces (down = next, up = previous) and the tiles
-- slide over to the new one.
--
-- It is the hyprview plugin (github.com/yz778/hyprview), a third-party
-- plugin, not part of Hyprland. scripts/hyprview-build.sh builds it into
-- ~/.local/lib/hyprland/hyprview.so without root. A plugin only loads into
-- the exact Hyprland version it was built against, so RERUN THAT SCRIPT AFTER
-- EVERY HYPRLAND UPDATE. Until then you get an error notification at login and
-- SUPER+D does nothing; everything else is unaffected.
--
-- The build applies scripts/hyprview.patch on top of upstream: the workspace
-- scrolling above, and the fix for rotated (portrait) monitors, where upstream
-- lays the overview out landscape and draws the tiles sideways.
--
-- The plugin runs inside the compositor, so a bug in it can take the whole
-- session down. If that ever starts happening, delete the .so (or comment out
-- the require in hyprland.lua) and the rest of the config carries on.

local S       = require("lua.shared")
local mainMod = S.mainMod

local so = os.getenv("HOME") .. "/.local/lib/hyprland/hyprview.so"
local f = io.open(so, "r")
if not f then return end
f:close()

hl.plugin.load(so)

-- Matches the window borders in settings.lua: border_size 4, rounding 4, and
-- the first stop of the active gradient (0ff0fc) for the focused tile. Colours
-- are 0xAARRGGBB integers here, not "rgb()" strings.
hl.config({ plugin = { hyprview = {
    active_border_color   = 0xFF0FF0FC,
    inactive_border_color = 0x4400F0FF,
    border_width          = 4,
    border_radius         = 4,
    margin                = 16,
    bg_dim                = 0.55,
} } })

-- The plugin exposes a plain Lua function rather than a dispatcher, so the
-- binds wrap it in a callback. hl.plugin.hyprview only exists once the plugin
-- actually loaded (a version mismatch leaves it nil), hence the check.
--
-- The overview has no keyboard handling of its own: Escape does NOT close it.
-- Press the same key again, or click a tile.
local function overview(args)
    return function()
        if hl.plugin.hyprview then
            hl.plugin.hyprview.toggle(args)
        end
    end
end

-- SUPER+D: the windows of the workspace each monitor is showing; scroll to
-- move between workspaces. SUPER+SHIFT+D: everything at once instead, every
-- workspace of each monitor plus the ALT+grave scratchpad, in one grid.
hl.bind("SUPER+D",       overview(""),            { description = "Navigation: Window overview" })
hl.bind("SUPER+SHIFT+D", overview("all special"), { description = "Navigation: Window overview, all workspaces + scratchpad" })
