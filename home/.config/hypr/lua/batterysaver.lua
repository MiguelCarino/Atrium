-- lua/batterysaver.lua -- the battery saver's half of the compositor
-- (scripts/battery-saver.py; on by hand, or by itself through power-watch).
-- While it is on the desktop draws less per frame and fewer frames:
--
--   blur     off (decoration.blur.enabled): the biggest GPU cost on this
--            desktop -- every translucent terminal, the bar and its panels
--            re-blur what is behind them on every frame that changes
--   shadows  off: one more pass per window
--   motion   every animation leaf disabled (lua/display.lua's still()):
--            windows, workspaces and layers appear at once, so a workspace
--            switch is one frame instead of ~25
--   scanout  render.direct_scanout = 1: a fullscreen window (a video, a
--            browser in fullscreen) hands its buffer straight to the screen,
--            skipping the compositor's copy -- a large saving for video.
--            (A screen filter rules it out; the filter is your choice and
--            is left alone.)
--
-- Why not animations.enabled = false, the obvious switch: that one IS
-- gamemode (lua/gamemode.lua, display.lua, ambient.lua, the wallpaper
-- slideshow and several scripts all read "animations off" as "gamemode
-- on"). Using it here would make the saver look like gamemode to all of
-- them and make gamemode OFF -- a reload -- undo the saver. Per-leaf
-- `enabled = false` stills everything just the same and leaves that switch
-- to gamemode alone.
--
-- Where the state is: battery-saver.py's own state file,
-- $XDG_RUNTIME_DIR/battery-saver.json ({"active": true, ...}), the same file
-- power_state.saver_active() reads, so the Lua side and the Python side can
-- never disagree about whether the saver is on. It is read at every config
-- load: lua/display.lua asks M.active() while it lays down the look and the
-- animations, and lua/gamemode.lua while it resets direct scanout -- so a
-- reload, a theme switch or gamemode OFF (which IS a reload) all land on
-- the saver's look while it is on, and nothing has to re-apply it.
--
-- Gamemode and the saver never fight, because neither restores a list of
-- values -- both re-run the config's own code:
--   * gamemode ON while the saver is on: gamemode strips what it strips;
--     display.lua leaves gamemode's keys alone while it is on, except that
--     blur and shadows stay OFF while the saver is (gamemode only ever
--     switches them off too, so that cannot fight it -- and capture.conf's
--     gamemode_blur=off, "keep blur for recording", must not keep the
--     saver's blur on). M.apply() below does not touch scanout then
--     (gamemode's 2, game content only, wins).
--   * gamemode OFF while the saver is on: the reload lands in display.lua
--     and gamemode.lua with the saver's file still saying active -> the
--     saver's look, not the full one.
--   * the saver OFF while gamemode is on: display.apply() puts the theme's
--     colours back, and blur / shadows only where gamemode does not strip
--     them (lua/gamemode.lua's strips()); gaps, rounding and borders stay
--     gamemode's; the animation leaves go back to the preset under a global
--     switch that is still off. Gamemode OFF later reloads into the full
--     look.
--
-- Not checked against a running Hyprland when this was written (the tests
-- run it under luajit with a stand-in `hl`): after `battery-saver.py on`,
-- `hyprctl getoption render:direct_scanout` should say 1,
-- decoration:blur:enabled 0 and animations:enabled still 1. If fullscreen
-- video glitches with scanout 1 on this amdgpu (flicker, a wrong colour
-- format, the cursor), M.SCANOUT = 2 below limits it to game content.
--
-- battery-saver.py runs `hyprctl eval 'require("lua.batterysaver").apply()'`
-- after writing the file (the eval also loads this module, which
-- lua/display.lua requires anyway).

---@module 'hl'

local M = {}

M.state_file = (os.getenv("XDG_RUNTIME_DIR") or "/run/user/1000") .. "/battery-saver.json"

-- True when the state file says "active": true. Read with a pattern, not a
-- JSON parser (Hyprland's Lua has none): battery-saver.py writes the file
-- with json.dump, so the key and value are always `"active": true` (any
-- whitespace allowed); anything unreadable is "off" -- the full look is the
-- safe side to fail to.
function M.active()
    local f = io.open(M.state_file, "r")
    if not f then return false end
    local text = f:read("a") or ""
    f:close()
    return text:match('"active"%s*:%s*true') ~= nil
end

-- What render.direct_scanout should be outside gamemode: M.SCANOUT while
-- the saver is on, else 0 -- the value lua/gamemode.lua has always reset it
-- to. 1 is any fullscreen window (video above all); 2 would be game content
-- only, the fallback if 1 misbehaves on this machine.
M.SCANOUT = 1

function M.scanout()
    return M.active() and M.SCANOUT or 0
end

-- The whole saver, on or off, from the file as it is now. display.apply()
-- does blur, shadow and the animation leaves (it asks M.active() itself);
-- ambient.lua's calm level is laid over the preset again when the saver
-- goes off (its applied= is reset so it really re-applies); scanout is set
-- here, except in gamemode.
function M.apply()
    require("lua.display").apply()
    local ok, ambient = pcall(require, "lua.ambient")
    if ok and ambient and ambient.apply then
        ambient.applied = 0
        ambient.apply()             -- does nothing while the saver is on, or at level 0
    end
    if hl.get_config("animations.enabled") then        -- not in gamemode: scanout is gamemode's there
        hl.config({ render = { direct_scanout = M.scanout() } })
    end
end

return M
