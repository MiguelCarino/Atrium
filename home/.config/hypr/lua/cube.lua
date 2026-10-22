-- Loaded from ~/.config/hypr/hyprland.lua (the index). Compiz-style cube
-- workspace switching: ALT+mouse wheel spins the cube to the next / previous
-- workspace, ALT+CTRL+left-drag turns it by hand (release snaps to the
-- nearest face, Escape puts it back).
--
-- It is the hypr-cube plugin (github.com/dmty/hypr-cube), a third-party
-- plugin, not part of Hyprland. scripts/hypr-cube-build.sh builds it into
-- ~/.local/lib/hyprland/hypr-cube.so without root. A plugin only loads into
-- the exact Hyprland version it was built against, so RERUN THAT SCRIPT AFTER
-- EVERY HYPRLAND UPDATE. Until then the wheel binds (lua/binds.lua) fall back
-- to a plain workspace switch; everything else is unaffected.
--
-- Faces: with scripts/hypr-cube.patch (applied by the build script), each
-- monitor's cube is the workspaces that live on it, sorted by id -- DP-1 spins
-- through 1, 2, 3, 5. Upstream uses workspaces 1..faces, which here would spin
-- DP-1 onto workspace 4 and yank focus over to DP-2; `faces` below is now only
-- the fallback for a monitor with fewer than three workspaces. ALT+n jumps stay
-- plain; the cube's keyboard binds live in lua/binds.lua next to the wheel ones:
-- SUPER+CTRL+n spins straight to n, SUPER+CTRL+SHIFT+n takes the window along,
-- SUPER+CTRL+comma / period are previous / next.
--
-- Queued spins (local patch): a wheel tick or key that arrives mid-spin moves
-- the target instead of being dropped, so fast scrolling turns several faces in
-- one go (at most a lap minus one ahead); SUPER+CTRL+n mid-spin re-aims it.
--
-- Fling (local patch): letting go of a drag mid-motion carries the cube on --
-- it lands where it would be 200 ms later at that speed, at most two faces
-- further (constants at the top of src/cube/state.cpp).
--
-- Floating windows (also a local patch): with float_depth > 0, each face's
-- floating windows are captured on a layer of their own that lifts off the
-- face while the cube turns -- furthest out half-way between faces and while
-- dragging, back flush with the face when it lands -- so tiled windows stay on
-- the cube and floating ones hover in front of it. 0 turns it off. Pinned
-- windows, and floats on a workspace with a fullscreen window, stay flat.
--
-- Live faces (local patch too): with live = 1 the faces turned toward you are
-- re-rendered every frame of the spin instead of being frozen at its start, and
-- their apps get frame callbacks, so a video keeps playing on the cube. It
-- costs up to a few extra workspace renders per frame; live = 0 is the old
-- still snapshots.
--
-- The plugin runs inside the compositor, so a bug in it can take the whole
-- session down. If that ever starts happening, delete the .so (or comment out
-- the require in hyprland.lua) and the rest of the config carries on.

local S       = require("lua.shared")
local mainMod = S.mainMod

local so = os.getenv("HOME") .. "/.local/lib/hyprland/hypr-cube.so"
local f = io.open(so, "r")
if not f then return end
f:close()

hl.plugin.load(so)

local cfg = {
    faces       = 4,
    duration_ms = 450,
    fov         = 60,                 -- wider = camera nearer the cube mid-spin (was 45)
    drag_zoom   = 0.75,               -- how far it pulls back while dragging; 1 = none (default 0.6)
    background  = "rgba(060810ff)",   -- the bar's glass colour, behind the cube
}
-- float_depth and live exist only in a build with scripts/hypr-cube.patch
-- (the build script leaves hypr-cube.so.patched next to it); plain upstream
-- would reject them as unknown options.
local marker = io.open(so .. ".patched", "r")
if marker then
    marker:close()
    cfg.float_depth = 200             -- px floating windows hover off the face
    cfg.live        = 1               -- keep faces (videos) moving during a spin
end
hl.config({ plugin = { hypr_cube = cfg } })

hl.bind(mainMod .. "+CTRL+mouse:272", function()
    if hl.plugin.cube then hl.plugin.cube.drag() end
end, { description = "Workspaces: Drag the cube" })
