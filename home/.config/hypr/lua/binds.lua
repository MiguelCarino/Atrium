-- ~/.config/hypr/lua/binds.lua
-- Loaded from ~/.config/hypr/hyprland.lua (the index). Every key bind and the
-- resize submap, EXCEPT ALT+SHIFT+G (gamemode), which is defined next to the
-- functions it calls in lua/gamemode.lua.
--
-- Every hl.bind carries { description = "Section: what it does" }: the
-- shortcuts panel (SUPER+F1, waybar scripts/keybinds_panel.py) reads them
-- from `hyprctl binds -j` and groups by the part before ": ".

---@module 'hl'

local S       = require("lua.shared")
local mainMod = S.mainMod
local scrDir  = S.scrDir

-- Your own shortcut changes (Settings > Keyboard shortcuts): lua/userbinds.lua
-- wraps hl.bind from here on, so every bind below -- and the ones overview.lua,
-- cube.lua and gamemode.lua make after this file -- lands on the keys
-- ~/.local/state/hypr/userbinds.conf gives it (its own, new ones, or none).
-- The defaults stay written here as they are. Loaded through pcall: if the
-- module ever failed, the binds below must still all be made, just without
-- the changes, so a broken override can never cost you the keyboard.
local userbinds_ok, UB = pcall(require, "lua.userbinds")
if not userbinds_ok then
    local err = UB
    UB = nil
    hl.notification.create({ text = "Your shortcut changes were not loaded: " .. tostring(err),
                             timeout = 8000, color = "rgb(fffb00)" })
end

-- ========================= Keybinds =========================
-- The terminal and file manager keys go through default-apps.py,
-- so they start whatever Settings > Default apps (or `default-apps.py set
-- terminal kitty`) chose: the terminal from $XDG_STATE_HOME/hypr/
-- default-apps.conf, the file manager from ~/.config/mimeapps.list
-- -- the same folder handler xdg-open uses, so ALT+W and a
-- double-clicked folder always open the same app. The script exec()s the
-- app (nothing stays in between) and falls back to cosmic-term / nautilus
-- --new-window, what these keys ran before, if anything goes wrong.
local defaultApps = "~/.config/hypr/scripts/default-apps.py run "
hl.bind(mainMod .. "+Q", hl.dsp.exec_cmd(defaultApps .. "terminal"), { description = "Apps: Terminal" })
-- hl.bind(mainMod .. "+Q", hl.dsp.exec_cmd("kitty --single-instance"))
-- Close -- but only ever a window you can actually see.
--
-- A bare hl.dsp.window.close() closes the *active* window, and "active" is a
-- single compositor-wide pointer that does not necessarily follow your eyes.
-- Two ordinary moves in this setup leave it behind:
--
--   * Switching to an empty workspace. Workspaces 1-6 are persistent = true,
--     so they can exist with nothing on them. Landing on one
--     gives Hyprland no window to hand focus to, so the pointer stays on
--     whatever you were last in on the workspace you left.
--   * Walking the mouse onto another monitor. follow_mouse = 1 moves focus
--     when the cursor enters a *window*; crossing onto empty desktop space on
--     DP-2 or HDMI-A-1 changes which monitor is focused but leaves the active
--     window sitting on DP-1.
--
-- Either way the next ALT+C closes something on a screen you are not looking
-- at -- which is exactly the bug this replaces.
--
-- The guard is "does this window sit on the workspace the focused monitor is
-- currently showing". That one comparison covers both cases: a workspace only
-- ever belongs to one monitor, so matching the workspace also proves you are
-- on the right screen.
--
-- Do not be tempted to use win.visible instead -- it is a mapped/hidden flag,
-- not a "you can see it" flag. Windows parked on workspaces 2 and 3 report
-- visible = true while DP-1 is showing workspace 1, so a visible check alone
-- lets the empty-workspace case straight through.
--
-- active_special_workspace is the second half because the scratchpad
-- (ALT+grave) puts its windows on special:magic rather than on the numbered
-- workspace, and closing from inside it should still work.
--
-- The notification exists so the blocked case is not a dead key. Drop the
-- hl.notification.create call if you would rather it fail silently.
hl.bind(mainMod .. "+C", function()
    local win = hl.get_active_window()
    local mon = hl.get_active_monitor()
    if not win or not mon then return end

    local ws      = win.workspace
    local shown   = mon.active_workspace
    local special = mon.active_special_workspace

    local here = ws ~= nil and ((shown ~= nil and ws.id == shown.id)
                             or (special ~= nil and ws.id == special.id))

    if not here then
        hl.notification.create({
            text    = "ALT+C ignored: focus is on workspace " ..
                      (ws and ws.name or "?") .. ", not here",
            timeout = 1500,
            color   = "rgb(fffb00)",
        })
        return
    end

    hl.dispatch(hl.dsp.window.close())
end, { description = "Windows: Close (only on the screen you see)" })
hl.bind(mainMod .. "+F", hl.dsp.window.fullscreen(), { description = "Windows: Fullscreen" })

-- Split fullscreen state, same three actions as the gamepad pill in waybar.
-- See ~/.config/waybar/scripts/fsstate.py for what the two modes mean.
--
-- These exist because the button cannot be reached in the case it is for: a
-- game that opens genuinely fullscreen covers the bar, so there is nothing to
-- click. Compositor binds still fire over a fullscreen window, which is the
-- whole reason this is the right layer to solve it at.
--
-- They call the script rather than dispatching directly so that the key and
-- the button cannot drift apart -- the "read current state, set the result
-- outright" logic lives in exactly one place. Pressing the A key while B is
-- active lands on A, matching the button.
hl.bind(mainMod .. "+SHIFT+F",
    hl.dsp.exec_cmd("~/.config/waybar/scripts/fsstate.py a"), { description = "Games: Fullscreen mode A" })
hl.bind(mainMod .. "+CTRL+F",
    hl.dsp.exec_cmd("~/.config/waybar/scripts/fsstate.py b"), { description = "Games: Fullscreen mode B" })
hl.bind(mainMod .. "+CTRL+SHIFT+F",
    hl.dsp.exec_cmd("~/.config/waybar/scripts/fsstate.py reset"), { description = "Games: Reset fullscreen state" })

-- Exit Hyprland. Deliberately NOT a bare ALT+M: it ends the session with no
-- confirmation and M sits right next to N and B.
--
-- Through session-exit.sh rather than hl.dsp.exit(): in the uwsm-managed
-- session the clean exit is `uwsm stop` (it also stops the systemd services
-- bound to the session); in the plain session the script falls back to
-- hl.dsp.exit(). The power menu's Log out uses the same script.
hl.bind("SUPER+SHIFT+M", hl.dsp.exec_cmd("~/.config/hypr/scripts/session-exit.sh"),
    { description = "Session: Exit Hyprland" })
hl.bind(mainMod .. "+W", hl.dsp.exec_cmd(defaultApps .. "files"), { description = "Apps: File manager" })
hl.bind(mainMod .. "+V", hl.dsp.window.float(), { description = "Windows: Toggle floating" })
hl.bind(mainMod .. "+E", hl.dsp.exec_cmd("~/.config/hypr/scripts/launcher.py"), { description = "Apps: Launcher" })
hl.bind(mainMod .. "+P", hl.dsp.window.pseudo(), { description = "Windows: Pseudo-tile" })
hl.bind(mainMod .. "+R", hl.dsp.layout("togglesplit"), { description = "Windows: Toggle split direction" })

-- Focus / swap / resize per direction
--
-- relative = true is required. Without it x/y are an absolute window size, so
-- { x = -60 } asks for a window -60px wide and every press pops "Runtime error
-- in lua: Invalid size" -- tested. With it they are a delta, as intended.
local resize_delta = {
    left  = { x = -60, y = 0,   relative = true },
    right = { x = 60,  y = 0,   relative = true },
    up    = { x = 0,   y = -60, relative = true },
    down  = { x = 0,   y = 60,  relative = true },
}
for _, d in ipairs({ "left", "right", "up", "down" }) do
    hl.bind(mainMod .. "+" .. d,            hl.dsp.focus({ direction = d }), { description = "Windows: Focus" })
    hl.bind(mainMod .. "+SHIFT+" .. d,      hl.dsp.window.swap({ direction = d }), { description = "Windows: Swap" })
    hl.bind(mainMod .. "+CTRL+" .. d,       hl.dsp.window.resize(resize_delta[d]), { description = "Windows: Resize step" })
end

-- A submap is a mode: while it is active its binds are the only ones that
-- answer, so the bare arrow keys can mean "resize" without being stolen from
-- everything else the rest of the time.
--
-- This is what the bar's hyprland/submap module was always for. It has been
-- rendering an empty string because no submap existed to report; entering this
-- one is what finally puts something in it, which is also your only on-screen
-- cue that the arrows have changed meaning.
--
-- ALT+CTRL+arrows above still nudge a window by one step without any of this.
-- The submap is for the case where one step is never enough and you want to
-- sit on the key instead -- hence repeating = true.
--
-- escape and return both leave. Bind at least one of them or the mode is a
-- trap: nothing else responds while it is active.
hl.define_submap("resize", function()
    for _, d in ipairs({ "left", "right", "up", "down" }) do
        hl.bind(d, hl.dsp.window.resize(resize_delta[d]), { repeating = true })
    end
    hl.bind("escape", hl.dsp.submap("reset"))
    hl.bind("return", hl.dsp.submap("reset"))
end)
hl.bind("SUPER+R", hl.dsp.submap("resize"), { description = "Windows: Resize mode (Esc to leave)" })

-- Workspaces: focus (ALT+n) and silent move (ALT+SHIFT+n)
--
-- Six, not ten. The loop used to run to 10 and bind ALT+7,8,9,0, but there are
-- only six workspace_rules (lua/rules.lua) -- so 7-10 were second-class in a
-- way that was invisible until you hit one. They had no monitor, which meant
-- they materialised on whichever screen happened to be focused, and no
-- persistent flag, which meant Hyprland collected them the instant you moved
-- away with nothing on them. A workspace that appears somewhere unpredictable
-- and then evaporates is worse than no workspace: you put a window on it,
-- switch away to check something, come back and the pill is gone.
--
-- They were also invisible to the bar in a misleading way. waybar colours the
-- pills by position (see the :nth-child block in style.css), and a workspace with
-- no home monitor has no colour to be -- it fell through to the neutral
-- @mon-unknown fill, which is honest but only ever showed up as a surprise.
--
-- If you ever want more than six, the fix is both halves at once: raise this
-- bound AND add a matching hl.workspace_rule with a monitor and persistent = true,
-- AND add the :nth-child entry in style.css. Raising just this number gives back
-- the disappearing workspaces.
--
-- ALT+n summons rather than travels
--
-- A bare hl.dsp.focus({ workspace = n }) goes to where the workspace already is.
-- With every workspace pinned to a monitor that made ALT+n a *monitor* jump in
-- disguise: standing at the upper screen and pressing ALT+5 did not put workspace
-- 5 there, it threw focus down to the primary, because that is where 5 lives. You
-- asked for a blank desktop on the screen in front of you and got teleported to
-- a different screen instead.
--
-- The rule that fixes it turns on one question -- does the workspace have
-- windows on it? -- and NOT on whether it happens to be visible:
--
--   has windows    travel to it. Plain focus, the original behaviour. Windows
--                  have a screen they live on; the size, rotation and position
--                  of that screen is part of how they are laid out, and dragging
--                  a populated workspace to a different monitor relayouts
--                  everything for no reason. If work is there, you go to it.
--
--   empty          summon it. Nobody is looking at a blank desktop, so there is
--                  nothing to disturb by moving it: workspace.move it onto the
--                  focused monitor, then focus it. move on its own only re-homes
--                  a workspace, it does NOT put it on screen -- verified -- so
--                  the focus call after it is load-bearing, not belt-and-braces.
--
-- This is why there is no swap here even though swap_monitors exists and the
-- Monitors section below binds it. Swapping to make room would push the
-- workspace you were on -- windows and all -- onto the other screen, which is
-- exactly the relayout the first rule is there to avoid. Deliberate swapping
-- stayed a deliberate gesture: SUPER+ALT+arrow.
--
-- One consequence, and it is the acceptable kind. If the empty workspace you
-- summon is the only one homed on a single-workspace monitor AND that monitor
-- is showing it, that screen is left with nothing and Hyprland invents a
-- workspace to fill the hole (the ws-7 trap described in the Monitors section
-- below). Here that trades one blank desktop for another blank desktop -- no
-- window is touched -- so the only trace is an unpinned, @mon-unknown-coloured
-- pill in waybar until you navigate away and it is collected. Not worth a
-- guard.
--
-- Lookup walks hl.get_workspaces() and matches on numeric id rather than calling
-- hl.get_workspace("5"), because a string selector is ambiguous between an id and
-- a workspace *name* and those coincide for numbered workspaces. Matching id
-- directly means the answer cannot depend on which way that is resolved.
-- is_empty is read straight off the workspace (verified to agree with hyprctl's
-- own window counts) rather than counting hl.get_workspace_windows() by hand.
--
-- Note summoning re-homes a workspace for the session: after ALT+5 on the upper
-- screen, workspace 5 IS that screen's workspace until you summon it elsewhere
-- or restart. The workspace_rules in lua/rules.lua still decide where each one is *born*, which
-- is why a fresh session always comes back to the 1/2/3/5 + 4 + 6 layout. It
-- also means waybar's pill colours (:nth-child in style.css, keyed to position
-- and so to home monitor) go stale for a summoned workspace until it goes home.
--
-- ALT+SHIFT+n is deliberately NOT summoned. Throwing a window to a workspace is
-- a "put this away" gesture and follow = false says you are staying put; making
-- it also drag the destination workspace onto your screen would defeat that.
local function summon(id)
    return function()
        local mon = hl.get_active_monitor()
        if not mon then return end

        local target
        for _, w in ipairs(hl.get_workspaces()) do
            if w.id == id then target = w break end
        end

        -- Unknown workspace, no home monitor, already here, or occupied:
        -- every one of these is "just go there".
        if not target
            or not target.monitor
            or target.monitor.name == mon.name
            or not target.is_empty
        then
            hl.dispatch(hl.dsp.focus({ workspace = id }))
            return
        end

        -- Empty and on another screen: bring it to this one.
        hl.dispatch(hl.dsp.workspace.move({ workspace = id, monitor = mon.name }))
        hl.dispatch(hl.dsp.focus({ workspace = id }))
    end
end

for i = 1, 6 do
    local key = tostring(i % 10)
    local ws  = tostring(i)
    hl.bind(mainMod .. "+" .. key,          summon(i), { description = "Workspaces: Go to (pulls an empty one here)" })
    hl.bind(mainMod .. "+SHIFT+" .. key,    hl.dsp.window.move({ workspace = ws, follow = false }), { description = "Workspaces: Send window to" })
end
-- Spins the cube (lua/cube.lua) when the hypr-cube plugin is loaded; a plain
-- relative switch when it is not (not built, or built for another Hyprland).
local function step(dir)
    return function()
        local cube = hl.plugin.cube
        if cube then
            if dir > 0 then cube.next() else cube.prev() end
        else
            hl.dispatch(hl.dsp.focus({ workspace = dir > 0 and "e+1" or "e-1" }))
        end
    end
end
hl.bind(mainMod .. "+mouse_down", step(1),  { description = "Workspaces: Next" })
hl.bind(mainMod .. "+mouse_up",   step(-1), { description = "Workspaces: Previous" })

-- SUPER+CTRL+n is ALT+n with the cube: when workspace n already lives on this
-- monitor the cube spins straight to it, the short way round (cube.goN, a local
-- addition in scripts/hypr-cube.patch -- one function per number because the
-- plugin cannot read a Lua argument). Anything else -- n on another screen,
-- not created yet, or no plugin -- is exactly ALT+n, summoning included.
local function cube_go(id)
    local plain = summon(id)
    return function()
        local cube = hl.plugin.cube
        local mon  = hl.get_active_monitor()
        if cube and mon then
            for _, w in ipairs(hl.get_workspaces()) do
                if w.id == id then
                    -- goN is the patch's; plain upstream has no such call
                    if w.monitor and w.monitor.name == mon.name and cube["go" .. id] then
                        return cube["go" .. id]()
                    end
                    break
                end
            end
        end
        plain()
    end
end
-- SUPER+CTRL+SHIFT+n takes the focused window along: it is moved first, so the
-- cube already shows it on the face it spins to.
local function cube_take(id)
    local go = cube_go(id)
    return function()
        hl.dispatch(hl.dsp.window.move({ workspace = tostring(id), follow = false }))
        go()
    end
end
for i = 1, 6 do
    hl.bind("SUPER+CTRL+" .. i,       cube_go(i),   { description = "Workspaces: Go to (spins the cube)" })
    hl.bind("SUPER+CTRL+SHIFT+" .. i, cube_take(i), { description = "Workspaces: Take window to (spins the cube)" })
end
-- The wheel's next / previous on the keyboard. Comma and period rather than
-- brackets: they sit on the same keys in both the us and latam layouts.
hl.bind("SUPER+CTRL+period", step(1),  { description = "Workspaces: Next (spins the cube)" })
hl.bind("SUPER+CTRL+comma",  step(-1), { description = "Workspaces: Previous (spins the cube)" })

-- ========================= Monitors =========================
-- Three screens with no way to address them from the keyboard was the biggest
-- hole in this config: every ALT bind above works inside one monitor, so moving
-- between them meant reaching for the mouse.
--
-- SUPER rather than ALT because ALT+arrows is already focus-within-monitor and
-- ALT+SHIFT+arrows already swaps windows -- overloading either would make the
-- same gesture mean two things depending on where the focus happens to be.
--
-- The direction letters are physical, and they match the layout declared in
-- the host file (lua/hosts/<host>.lua). On the desk this was written at, DP-2
-- sits above DP-1 and HDMI-A-1 to its right: up reaches the upper screen, right
-- the portrait one.
--
-- follow = false on the move binds mirrors the workspace binds above: throw the
-- window to the other screen and stay where you are. Drop it if you would
-- rather travel with the window.
local monitor_dir = { left = "l", right = "r", up = "u", down = "d" }
for _, d in ipairs({ "left", "right", "up", "down" }) do
    hl.bind("SUPER+" .. d,       hl.dsp.focus({ monitor = monitor_dir[d] }), { description = "Monitors: Focus" })
    hl.bind("SUPER+SHIFT+" .. d, hl.dsp.window.move({ monitor = monitor_dir[d], follow = false }), { description = "Monitors: Send window to" })
end

-- Whole-workspace moves between monitors
--
-- The four binds above move *focus* and *one window*. Neither of them changes
-- which desktop a screen is showing, and with every workspace pinned by the
-- workspace_rules in lua/rules.lua, that was the missing third verb:
-- DP-2 owns only workspace 4 and HDMI-A-1 only workspace 6, so pressing ALT+2
-- while looking at the upper screen does not switch it -- it drags focus back
-- down to the primary, because workspace 2 lives there and nowhere else. There
-- was no keystroke that put a different desktop on the upper screen at all.
--
-- These two fill that hole, and they are deliberately different verbs:
--
--   swap (SUPER+ALT)   trades the two screens' active workspaces. Both monitors
--                      change; nothing is displaced. This is the one to reach
--                      for by default -- it is symmetric, and pressing the same
--                      binding again is its own undo (verified: DP-1/DP-2 swap
--                      to 4/1 and back to 1/4 with the identical keystroke).
--
--   move  (SUPER+CTRL) pushes only the current workspace to the other screen.
--                      One-way, asymmetric, and NOT self-inverse -- to undo it
--                      you have to go to the other screen and push the workspace
--                      back.
--
--                      It has one sharp edge worth knowing before you use it on
--                      DP-2 or HDMI-A-1. A monitor cannot show nothing, so when
--                      you push away the only workspace it owns, Hyprland does
--                      not fall back -- it invents a new one. Moving 4 off DP-2
--                      left the upper screen showing a freshly created workspace 7:
--                      exactly the unpinned, non-persistent, @mon-unknown-
--                      coloured workspace the ALT+n comment above spends a
--                      paragraph warning about. It evaporated again when 4 came
--                      back, so nothing was lost, but that is only because it
--                      was still empty. Put a window on it and you now have a
--                      window on a workspace with no home monitor.
--
--                      This does not happen on DP-1, which owns 1/2/3/5 and so
--                      always has somewhere to land. On the two single-workspace
--                      screens, prefer swap.
--
-- Both accept Hyprland's directional monitor selectors, so "current" and l/r/u/d
-- resolve at press time and the binds do not have to name DP-1/DP-2/HDMI-A-1.
-- That matters because the directions are physical, and this desk is an L, not a
-- row: DP-2 sits above DP-1 and HDMI-A-1 to its right, so DP-2 and HDMI-A-1 are
-- diagonal to each other with no shared edge. up/right/down/left always work
-- through the primary in the middle; upper-to-portrait directly has no direction to
-- name and those presses simply do nothing. Two hops, or use the mouse.
--
-- Note these moves are runtime-only. The workspace_rules in lua/rules.lua
-- decide where a workspace is *created*, not where it must stay, so a workspace
-- parked on a foreign monitor stays there until you move it back or Hyprland
-- restarts -- a reload does not haul it home. If you swap and then forget, a
-- fresh session is the reset.
for _, d in ipairs({ "left", "right", "up", "down" }) do
    hl.bind("SUPER+ALT+" .. d,
        hl.dsp.workspace.swap_monitors({ monitor1 = "current", monitor2 = monitor_dir[d] }), { description = "Monitors: Swap workspaces with" })
    hl.bind("SUPER+CTRL+" .. d,
        hl.dsp.workspace.move({ monitor = monitor_dir[d] }), { description = "Monitors: Push workspace to" })
end

-- ========================= Scratchpad =========================
-- A special workspace is a single overlay that any monitor can summon and
-- dismiss without disturbing the workspace underneath it -- the usual home for
-- a terminal, notes, or a music player you want two keystrokes away rather than
-- parked on a numbered workspace.
--
-- Named "magic" only because the name has to match on both binds; it never
-- appears in the bar (show-special is off there).
--
-- toggle_special takes the bare name as a STRING. The table form
-- { workspace = "magic" } parses, returns ok, and toggles a workspace called
-- special:special instead -- tested. That was this bind for a while: ALT+SHIFT+
-- grave sent windows to special:magic and ALT+grave could never show them.
hl.bind(mainMod .. "+grave",       hl.dsp.workspace.toggle_special("magic"), { description = "Scratchpads: Toggle scratchpad" })
hl.bind(mainMod .. "+SHIFT+grave", hl.dsp.window.move({ workspace = "special:magic", follow = false }), { description = "Scratchpads: Send window to scratchpad" })

-- Per-app scratchpads. Same idea as "magic" above, but each one belongs to a
-- single app and the key launches it if it is not running -- so SUPER+Return
-- is "give me my drop-down terminal" whether or not one exists yet, and the
-- same key puts it away again.
--
-- The app is matched on class, so it has to be one this function can tell
-- apart from ordinary windows of the same program: the terminal is kitty with
-- its own --class, never your cosmic-term windows. pavucontrol is unique
-- anyway; it also picks up the float-utilities rule, so it opens centred.
--
-- Launching goes through exec_cmd's rules table rather than a window_rule, so
-- an ordinary `kitty` or pavucontrol started some other way still opens where
-- you launched it.
--
local function scratchpad(name, class, cmd)
    return function()
        for _, w in ipairs(hl.get_windows()) do
            if w.class == class then
                hl.dispatch(hl.dsp.workspace.toggle_special(name))
                return
            end
        end
        hl.exec_cmd(cmd, { workspace = "special:" .. name })
    end
end
hl.bind("SUPER+Return", scratchpad("term",  "scratch-term",
    "kitty --class scratch-term"), { description = "Scratchpads: Drop-down terminal" })

-- The terminal hangs from the top edge as a drop-down: DROP_W of the
-- monitor's width, DROP_H of its height, so specialWorkspace's slidefadevert
-- (lua/display.lua) reads as it sliding down and back up. Done on open with
-- the same dispatches as SUPER+SHIFT+P below, sized from the monitor it opens
-- on (HDMI-A-1 is portrait: transform swaps width and height). A
-- window_rule's "2% 4%" move put it mid-screen instead -- tested.
local DROP_W, DROP_H, DROP_TOP = 0.96, 0.45, 0.04
hl.on("window.open", function(w)
    if w.class ~= "scratch-term" then return end
    local target = "address:" .. w.address
    local mon = w.monitor or hl.get_active_monitor()
    local mw, mh = mon.width / mon.scale, mon.height / mon.scale
    if mon.transform % 2 == 1 then mw, mh = mh, mw end
    local ww = math.floor(mw * DROP_W)
    hl.dispatch(hl.dsp.window.float({ action = "enable", window = target }))
    hl.dispatch(hl.dsp.window.resize({ x = ww, y = math.floor(mh * DROP_H), window = target }))
    hl.dispatch(hl.dsp.window.move({ x = math.floor(mon.x + (mw - ww) / 2),
                                     y = math.floor(mon.y + mh * DROP_TOP), window = target }))
end)
hl.bind("SUPER+A",      scratchpad("mixer", "org.pulseaudio.pavucontrol",
    "pavucontrol"), { description = "Scratchpads: Volume mixer" })

-- ========================= Navigation =========================
-- Pressing ALT+n for the workspace you are already on goes back to the one you
-- came from, so ALT+1 is also "get me out of 1 and back to where I was".
hl.config({ binds = { workspace_back_and_forth = true } })

-- SUPER+Tab: previous workspace. The single most-used navigation key once you
-- have it -- flip between the two things you are actually working on without
-- remembering their numbers. Global, not per monitor: it can take you to the
-- other screen, which is where "the other thing" usually is.
hl.bind("SUPER+Tab", hl.dsp.focus({ workspace = "previous" }), { description = "Navigation: Previous workspace" })

-- ALT+Tab / ALT+SHIFT+Tab: cycle windows on the current workspace, forward
-- and back. bring_to_top is for floating windows -- without it focus moves to
-- a window that stays hidden underneath another one.
--
-- { next = false } is backwards; tested, as is the fact that unknown keys
-- ({ prev = true }) are silently ignored and cycle FORWARD, which is easy to
-- mistake for working.
local function cycle(forward)
    return function()
        hl.dispatch(hl.dsp.window.cycle_next({ next = forward }))
        hl.dispatch(hl.dsp.window.bring_to_top())
    end
end
hl.bind(mainMod .. "+Tab",       cycle(true), { description = "Navigation: Next window" })
hl.bind(mainMod .. "+SHIFT+Tab", cycle(false), { description = "Navigation: Previous window" })

-- ALT+U: jump to the window that is asking for attention (a chat ping, a
-- finished build, a dialog that opened behind something); if nothing is, back
-- to the last focused window. Works across workspaces and monitors.
hl.bind(mainMod .. "+U", hl.dsp.focus({ urgent_or_last = true }), { description = "Navigation: Urgent or last window" })

-- SUPER+W: every window on every workspace in a wofi list, most recent first.
-- The script has the details.
hl.bind("SUPER+W", hl.dsp.exec_cmd("~/.config/hypr/scripts/window-switcher.py"), { description = "Navigation: Window switcher" })

-- ALT+SHIFT+P: pin a floating window so it follows you across workspaces (a
-- video, a reference doc, a calculator). Pin only applies to floating windows;
-- ALT+V first if it is tiled.
hl.bind(mainMod .. "+SHIFT+P", hl.dsp.window.pin(), { description = "Windows: Pin floating window" })

-- SUPER+SHIFT+P: picture-in-picture for ANY window -- an mpv video, a stream,
-- a call, a doc you are copying from. Floats it, shrinks it to PIP_W wide
-- (height from its current aspect ratio, so a video keeps its shape), parks it
-- in the bottom-right corner of the monitor it is on, and pins it so it
-- follows you across workspaces. Again on a pinned float puts it back: unpin,
-- tile. The "pip" window rule in lua/rules.lua does the same for browsers' own
-- Picture-in-Picture windows at map time; this is the by-hand version.
local PIP_W, PIP_MARGIN = 640, 24
hl.bind("SUPER+SHIFT+P", function()
    local w = hl.get_active_window()
    if not w then return end
    local target = "address:" .. w.address
    if w.floating and w.pinned then
        hl.dispatch(hl.dsp.window.pin({ window = target }))
        hl.dispatch(hl.dsp.window.float({ action = "disable", window = target }))
        return
    end
    local mon = w.monitor or hl.get_active_monitor()
    local ww, wh = w.size[1] or 16, w.size[2] or 9
    local h = math.floor(PIP_W * wh / math.max(ww, 1))
    if h > PIP_W then h = PIP_W end        -- a tall window: cap at a square
    local mw, mh = mon.width / mon.scale, mon.height / mon.scale
    if mon.transform % 2 == 1 then mw, mh = mh, mw end
    hl.dispatch(hl.dsp.window.float({ action = "enable", window = target }))
    hl.dispatch(hl.dsp.window.resize({ x = PIP_W, y = h, window = target }))
    hl.dispatch(hl.dsp.window.move({ x = math.floor(mon.x + mw - PIP_W - PIP_MARGIN),
                                     y = math.floor(mon.y + mh - h - PIP_MARGIN),
                                     window = target }))
    if not w.pinned then hl.dispatch(hl.dsp.window.pin({ window = target })) end
end, { description = "Windows: Picture-in-picture (again to put back)" })

-- ========================= Groups =========================
-- Groups stack windows into one tabbed frame instead of splitting the space
-- between them, which is what you want for several terminals or docs that are
-- each usable at full width but not side by side.
--
-- ALT+T toggles the focused window in or out of a group; the brackets step
-- through the tabs once there is more than one.
hl.bind(mainMod .. "+T",            hl.dsp.group.toggle(), { description = "Groups: Toggle group" })
hl.bind(mainMod .. "+bracketright", hl.dsp.group.next(), { description = "Groups: Next tab" })
hl.bind(mainMod .. "+bracketleft",  hl.dsp.group.prev(), { description = "Groups: Previous tab" })

-- Screenshots (hyprshot, through scripts/screenshot.sh so the shots follow
-- Settings > Screenshots & recording: the folder, the file format, the sound
-- and copy-to-clipboard all come from ~/.local/state/hypr/capture.conf).
hl.bind(mainMod .. "+S",        hl.dsp.exec_cmd("~/.config/hypr/scripts/screenshot.sh output"), { description = "Screenshots: Monitor" })
hl.bind(mainMod .. "+SHIFT+S",  hl.dsp.exec_cmd("~/.config/hypr/scripts/screenshot.sh region"), { description = "Screenshots: Region" })
hl.bind(mainMod .. "+CTRL+S",   hl.dsp.exec_cmd("~/.config/hypr/scripts/screenshot.sh window"), { description = "Screenshots: Window" })

-- Screenshot extras (scripts/screenshot.sh) -- the SUPER twins of the ALT+S
-- family, for when the shot is a means rather than a file to keep:
--   SUPER+S        region straight to the clipboard, nothing written to disk
--                  (paste into chat/issue without littering Screenshots/)
--   SUPER+SHIFT+S  region -> satty to draw arrows/boxes/blur; saves into
--                  scrDir as *_annotated.png and copies via wl-copy
--   SUPER+O        region -> tesseract OCR (eng+spa, whichever are installed)
--                  -> text on the clipboard, preview in a notification
-- The script uses slurp+grim directly instead of hyprshot because hyprshot has
-- no "PNG on stdout" mode, which satty and tesseract need. satty and tesseract
-- are optional: if one is missing the bind pops a notification with the exact
-- dnf command instead of silently doing nothing.
hl.bind("SUPER+S",       hl.dsp.exec_cmd("~/.config/hypr/scripts/screenshot.sh region-copy"), { description = "Screenshots: Region to clipboard (no file)" })
hl.bind("SUPER+SHIFT+S", hl.dsp.exec_cmd("~/.config/hypr/scripts/screenshot.sh annotate"),    { description = "Screenshots: Annotate region (satty)" })
hl.bind("SUPER+CTRL+S",  hl.dsp.exec_cmd("~/.config/hypr/scripts/screenshot.sh pretty"),      { description = "Screenshots: Pretty window (rounded, shadow, gradient)" })
hl.bind("SUPER+O",       hl.dsp.exec_cmd("~/.config/hypr/scripts/screenshot.sh ocr"),         { description = "Screenshots: OCR region to clipboard" })

-- Screen recording (gpu-screen-recorder, NVENC) via ~/.config/hypr/scripts/record.sh.
--
-- The ShadowPlay keys, deliberately: ALT+F9 records, ALT+F10 saves the instant
-- replay, ALT+SHIFT+F10 turns the replay buffer on/off. With a 4090 in the box
-- those are the keys your hands already reach for mid-game, and the whole
-- F9/F10 column was free on every modifier.
--
-- The record keys toggle: pressing the same key again stops the recording and
-- finalises the file (SIGINT, so the mp4 gets its index -- a killed mp4 does
-- not play). That is why there is no separate "stop" bind; the red REC pill
-- in the bar (waybar custom/recording) stops it too. ALT+SHIFT+F9 picks a
-- region with slurp first; a plain click with no drag records the whole
-- monitor under the pointer.
--
-- The replay buffer is the last 30s (by default; Settings > Screenshots &
-- recording sets the length) of the monitor that was focused when it
-- was switched on, held in RAM (~150 MB). Codec, quality, the output folder
-- (~/Videos/Recordings) and the pid files the bar reads are all explained at
-- the top of the script.
--
-- ALT+CTRL+F9 flips the next capture between SDR (h264, plays anywhere) and
-- HDR (HEVC HDR10, for an HDR player on an HDR screen). The choice sticks
-- across reboots; HDR only applies to a monitor that is in HDR mode.
hl.bind(mainMod .. "+F9",        hl.dsp.exec_cmd("~/.config/hypr/scripts/record.sh monitor"),       { description = "Recording: Record monitor (again to stop)" })
hl.bind(mainMod .. "+SHIFT+F9",  hl.dsp.exec_cmd("~/.config/hypr/scripts/record.sh region"),        { description = "Recording: Record region (again to stop)" })
hl.bind(mainMod .. "+F10",       hl.dsp.exec_cmd("~/.config/hypr/scripts/record.sh save-replay"),   { description = "Recording: Save instant replay" })
hl.bind(mainMod .. "+SHIFT+F10", hl.dsp.exec_cmd("~/.config/hypr/scripts/record.sh toggle-replay"), { description = "Recording: Instant replay on / off" })
hl.bind(mainMod .. "+CTRL+F9",   hl.dsp.exec_cmd("~/.config/hypr/scripts/record.sh toggle-range"),  { description = "Recording: Switch SDR / HDR" })

-- The screen magnifier (scripts/accessibility.py, Settings > Accessibility):
-- SUPER+ALT with = / - steps the zoom around the pointer in and out, SUPER+ALT+0
-- turns it off. The level is saved, so it comes back after a reload. The
-- descriptions start "Accessibility: Zoom" because the Accessibility page
-- lists the keys it finds bound under those names.
hl.bind("SUPER+ALT+equal", hl.dsp.exec_cmd("~/.config/hypr/scripts/accessibility.py zoom in"),    { description = "Accessibility: Zoom in" })
hl.bind("SUPER+ALT+minus", hl.dsp.exec_cmd("~/.config/hypr/scripts/accessibility.py zoom out"),   { description = "Accessibility: Zoom out" })
hl.bind("SUPER+ALT+0",     hl.dsp.exec_cmd("~/.config/hypr/scripts/accessibility.py zoom reset"), { description = "Accessibility: Zoom off" })

-- Mouse drag move/resize -- ALT+LMB moves, ALT+RMB resizes.
--
-- These take NO opts table, and that is the whole fix. They used to pass
-- { drag = true }, which reads like "this is a drag bind" and is why it went
-- unnoticed: it parses, it logs nothing, and the bind registers.
--
-- drag = true is a different feature. In hl.bind it sets kb.release, giving you
-- a bind that fires once on button *release*, and only if the pointer moved in
-- between -- a "the user dragged" gesture, not a drag session. So holding ALT
-- and moving did nothing at all; the dispatcher only ran when you let go, and
-- then started a grab that tracked the cursor until you clicked again to drop
-- it. That trailing click was the second click. The window always did move --
-- it just started one full click late.
--
-- Nothing is needed in its place because hl.dsp.window.drag() is already the
-- press-and-hold dispatcher. It sets releasePending on the bind, which is what
-- makes Hyprland deliver the button *release* to a bind that fired on press --
-- press starts the grab, release ends it. Adding release/drag/click on top
-- breaks exactly that: the press half never happens.
--
-- Do not add { mouse = true } either, even though Hyprland's own bundled
-- example config (the one embedded in the binary) uses it. hl.bind in 0.56.2
-- never reads that field -- it is only tested for conflicts, so it is silently
-- a no-op, and hl.dsp.window.drag() does not need it. Re-check this if the
-- Lua config API changes; the field may start working.
--
-- To verify: `hyprctl binds | grep -B3 mouse:272` must print a bare `bind`
-- header. `bindr` means a release flag crept back in and the two-click
-- behaviour is back.
hl.bind(mainMod .. "+mouse:272", hl.dsp.window.drag(), { description = "Windows: Move with mouse" })
hl.bind(mainMod .. "+mouse:273", hl.dsp.window.resize(), { description = "Windows: Resize with mouse" })

-- Volume + mic
--
-- These four were bound to pamixer, which is not installed on this machine, so
-- every one of them was a silent no-op -- the binds registered with Hyprland
-- fine, they just ran a command that does not exist. wpctl replaces it: it
-- ships with wireplumber, which is already what PipeWire runs here, and it is
-- what waybar's own pulseaudio module calls for its click actions.
--
-- -l 1.0 is the flag that matters. Without it wpctl walks straight past 100%
-- into software gain -- 100% + 5% measured as 120% -- and on a dial that is one
-- idle spin away from a distorted output you did not ask for. The limit applies
-- only to this relative raise, so an explicit `wpctl set-volume 130%` from a
-- terminal still works if you ever want the headroom.
--
-- Raising also unmutes, which is what turning a dial up implies and what every
-- other desktop does. It costs a second process per detent; if a fast spin ever
-- feels laggy, delete the set-mute half of that line and it goes back to one.
--
-- 5 is the step. A full sweep is 20 detents -- change both numbers together if
-- that feels coarse or fine on this particular dial.
--
-- locked = true keeps them working on the lock screen. repeating = true is for
-- holding a key down; a dial sends discrete events so it never applies there,
-- but it does if these keys are also on a normal keyboard.
-- Each one goes through scripts/osd.py, which changes the value (same wpctl
-- calls, same 5 % step and 100 % cap) and shows the on-screen pill.
hl.bind("XF86AudioRaiseVolume",
    hl.dsp.exec_cmd("~/.config/hypr/scripts/osd.py vol up"),
    { locked = true, repeating = true, description = "Media: Volume up" })
hl.bind("XF86AudioLowerVolume",
    hl.dsp.exec_cmd("~/.config/hypr/scripts/osd.py vol down"),
    { locked = true, repeating = true, description = "Media: Volume down" })
hl.bind("XF86AudioMute",
    hl.dsp.exec_cmd("~/.config/hypr/scripts/osd.py vol mute"),
    { locked = true, description = "Media: Mute" })
-- The line here used to be `pamixer --default-source -m`, which mutes rather
-- than toggles: even with pamixer installed, that key could only ever mute the
-- microphone and never bring it back.
hl.bind("XF86AudioMicMute",
    hl.dsp.exec_cmd("~/.config/hypr/scripts/osd.py mic mute"),
    { locked = true, description = "Media: Mic mute" })
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("~/.config/hypr/scripts/osd.py bright up"),
    { locked = true, repeating = true, description = "Media: Brightness up (all screens)" })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("~/.config/hypr/scripts/osd.py bright down"),
    { locked = true, repeating = true, description = "Media: Brightness down (all screens)" })

-- Screen actions (scripts/screen-actions.py): read the text in a box you drag,
-- or take the selected text, then copy / translate / look up / add to calendar.
hl.bind("SUPER+SHIFT+T", hl.dsp.exec_cmd("~/.config/hypr/scripts/screen-actions.py region"),
    { description = "Screen: Actions on a region (reads its text)" })
hl.bind("SUPER+ALT+T", hl.dsp.exec_cmd("~/.config/hypr/scripts/screen-actions.py selection"),
    { description = "Screen: Actions on the selected text" })

-- Media playback
--
-- The volume keys above were wired up but the transport keys never were, even
-- though the bar carries a player module -- so the dial could change how loud
-- something was but not what was playing.
--
-- playerctl talks MPRIS, the same bus scripts/player.py already reads, so these
-- act on whatever that module is showing rather than on one hardcoded app.
--
-- locked = true keeps them alive on the lock screen, which is the one place
-- skipping a track without unlocking is genuinely useful.
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true, description = "Media: Play / pause" })
hl.bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true, description = "Media: Next track" })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true, description = "Media: Previous track" })
hl.bind("XF86AudioStop",  hl.dsp.exec_cmd("playerctl stop"),       { locked = true, description = "Media: Stop" })

-- Colour picker (scripts/colorpick.sh, around hyprpicker): the hex goes on the
-- clipboard, a toast shows a swatch with its rgb()/hsl() forms, and it joins a
-- history of the last 30 -- the launcher's "#" mode lists them to copy again.
hl.bind("SUPER+P", hl.dsp.exec_cmd("~/.config/hypr/scripts/colorpick.sh"), { description = "Tools: Colour picker" })

-- Quick note (scripts/quicknote.py): one line, Enter, gone -- appended with the
-- time to ~/Documents/Notes/inbox.md. Ctrl+O in the box opens the inbox.
hl.bind("SUPER+SHIFT+N", hl.dsp.exec_cmd("~/.config/hypr/scripts/quicknote.py"), { description = "Tools: Quick note" })

-- Display (scripts/display.py; the panel is waybar scripts/display_panel.py).
-- The filter key flips between off and the last filter used, so it is one key
-- for "my filter on / off"; pick which filter in the panel or the launcher.
hl.bind("SUPER+ALT+D", hl.dsp.exec_cmd("~/.config/waybar/scripts/panel.py toggle display --at bar-right"),
    { description = "Display: Display panel (HDR, filters, animations, theme)" })
hl.bind("SUPER+I", hl.dsp.exec_cmd("~/.config/hypr/scripts/settings.py"), { description = "Settings: Open Settings (every page, searchable)" })
-- "auto": the primary screen if it has HDR, else the first that has (the host
-- file's M.hdr_capable) -- so the key names no connector.
hl.bind("SUPER+ALT+H", hl.dsp.exec_cmd("~/.config/hypr/scripts/display.py hdr auto toggle --confirm"), { description = "Display: HDR on / off (main screen)" })
hl.bind("SUPER+SHIFT+F", hl.dsp.exec_cmd("~/.config/hypr/scripts/display.py filter toggle"), { description = "Display: Screen filter on / off" })

-- Night light (scripts/nightlight.sh). Flips whatever is in effect right now
-- and holds it only until the next scheduled boundary (20:00 / 07:00), after
-- which the schedule owns the screen again -- "off tonight" should not quietly
-- become "off forever". `nightlight.sh on 3500` from a terminal forces a
-- specific temperature the same way. Schedule timers:
-- lua/nightlight.lua.
hl.bind("SUPER+N", hl.dsp.exec_cmd("~/.config/hypr/scripts/nightlight.sh toggle"), { description = "Tools: Night light toggle" })

-- Lock. See hypridle.conf for the idle timings that call the same command.
--
-- SUPER+ALT+L rather than a bare SUPER+L: locking is irreversible from the
-- keyboard's point of view -- you cannot undo it, you can only type the
-- password back in -- so it is worth one extra finger to make it hard to fire
-- by accident.
hl.bind("SUPER+ALT+L", hl.dsp.exec_cmd("hyprlock"), { description = "Session: Lock" })

-- Power menu: the same panel as the power pill at the far right of the bar
-- (lock, suspend, log out, reboot, power off). --at bar-right opens it under
-- that pill wherever the pointer is: panel.py otherwise centres a panel on the
-- pointer, which for a key press could be on DP-2 or HDMI-A-1 -- monitors with
-- no bar, where a menu hanging from nothing looks like a bug. SUPER+Escape because Escape is
-- the "get me out" key and SUPER is already the session / help modifier here;
-- a bare Escape belongs to the resize submap. Nothing destructive fires from
-- the key itself: log out / reboot / power off still need two clicks in the
-- panel, so a mis-press only ever opens a menu (press again to close it).
hl.bind("SUPER+Escape", hl.dsp.exec_cmd("~/.config/waybar/scripts/panel.py toggle power --at bar-right"),
    { description = "Session: Power menu" })

-- Notifications (mako). Criteria and colours live in ~/.config/mako/config.
--
-- -t on the mode toggle is what makes ALT+SHIFT+D a single key for both
-- directions; without it you would need two binds and a way to remember which
-- state you were in.
--
-- dismiss-all is bound as well as being mako's own right-click because a stack
-- that arrived while you were on another monitor is quicker to clear from the
-- keyboard than to chase with the pointer.
-- notifications.py dnd is that same makoctl toggle, plus a signal so the
-- bar's bell turns into a struck bell right away.
hl.bind(mainMod .. "+SHIFT+D", hl.dsp.exec_cmd("~/.config/waybar/scripts/notifications.py dnd"), { description = "Notifications: Do not disturb" })
-- History: every notification this session, newest first (the bell's panel).
hl.bind("SUPER+ALT+N", hl.dsp.exec_cmd("~/.config/waybar/scripts/panel.py toggle notifications --at bar-right"),
    { description = "Notifications: History" })
hl.bind(mainMod .. "+SHIFT+X", hl.dsp.exec_cmd("makoctl dismiss --all"), { description = "Notifications: Dismiss all" })
-- Bring back the last dismissed notification -- the counterpart to history=1.
hl.bind(mainMod .. "+SHIFT+R", hl.dsp.exec_cmd("makoctl restore"), { description = "Notifications: Restore last" })

-- Clipboard history (cliphist, fed by the two wl-paste watchers in
-- lua/autostart.lua).
-- scripts/clipboard.py shows it as tiles, newest entry big (images as
-- thumbnails); pick one and it goes back onto the clipboard, ready to paste.
-- Escape leaves the clipboard alone.
-- Checks for cliphist first: without it the picker opens empty (or
-- nothing) and you are left guessing why; a toast names the missing package,
-- like screenshot.sh / record.sh / nightlight.sh do for theirs.
hl.bind("SUPER+V", hl.dsp.exec_cmd([[command -v cliphist >/dev/null || { notify-send -u normal "cliphist is not installed" "sudo dnf install cliphist"; exit 0; }; exec ~/.config/hypr/scripts/clipboard.py]]), { description = "Tools: Clipboard history" })

-- Config edit shortcuts
--
-- The Hyprland one opens the index AND every module as tabs: since the split
-- the index alone is only a table of contents, and the line you want is almost
-- always in lua/*.lua. exec_cmd runs through /bin/sh -c, so the glob expands.
hl.bind(mainMod .. "+SHIFT+H", hl.dsp.exec_cmd("cosmic-edit ~/.config/hypr/hyprland.lua ~/.config/hypr/lua/*.lua"), { description = "Tools: Edit Hyprland config" })
hl.bind(mainMod .. "+SHIFT+W", hl.dsp.exec_cmd("cosmic-edit ~/.config/waybar/config"), { description = "Tools: Edit Waybar config" })

-- Shortcuts panel: every bind in the config with a description, grouped by the
-- part before the colon. Same panel as the keyboard pill in the bar. The list
-- is read live from `hyprctl binds`, so a new bind shows up there with no other
-- edit -- as long as it is given a { description = "Section: what it does" }.
hl.bind("SUPER+F1", hl.dsp.exec_cmd("~/.config/waybar/scripts/panel.py toggle keybinds"),
    { description = "Help: Show all shortcuts" })

-- Waybar signals. SIGUSR1 goes to the main bar's process only: a plain
-- `pkill -SIGUSR1 waybar` would also flip the hidden toolbox section
-- (waybar-toolbox.service) open as the bar disappears.
hl.bind(mainMod .. "+B", hl.dsp.exec_cmd("~/.config/waybar/scripts/toolbox.sh hide; systemctl --user kill -s USR1 --kill-whom=main waybar.service"), { description = "Bar: Show / hide bar" })
-- ALT+G restarts waybar as a new process instead of sending SIGUSR2. In
-- waybar 0.15 a SIGUSR2 reload rebuilds the modules in place and stops their
-- worker threads with pthread_cancel. If a cancel arrives while a custom
-- module is in fork(), the child aborts before exec (in hyprland::IPC's
-- destructor) and is never reaped: one coredump and one [waybar] zombie per
-- unlucky reload. bar-restart.sh closes the popup panels, ends waybar with
-- SIGTERM (no handler, so no teardown and no race), and has Hyprland start
-- the new one, the same way autostart does.
hl.bind(mainMod .. "+G", hl.dsp.exec_cmd("~/.config/waybar/scripts/bar-restart.sh"), { description = "Bar: Restart bar" })

-- Sessions, voice and the live mirror (scripts/closed-windows.py, sessions.py,
-- voice.py, pip.py). Push-to-talk: let go of V before SUPER/ALT, or the
-- release may not fire (SUPER+CTRL+V or the bar pill stop it too).
hl.bind("ALT+SHIFT+T", hl.dsp.exec_cmd("~/.config/hypr/scripts/closed-windows.py reopen"), { description = "Windows: Reopen the last closed window" })
hl.bind(mainMod .. "+CTRL+T", hl.dsp.exec_cmd("~/.config/hypr/scripts/sessions.py where-was-i"), { description = "Windows: Restore the last session" })
hl.bind("SUPER+CTRL+V", hl.dsp.exec_cmd("~/.config/hypr/scripts/voice.py toggle"), { description = "Tools: Voice typing (start / stop and type)" })
hl.bind("SUPER+ALT+V", hl.dsp.exec_cmd("~/.config/hypr/scripts/voice.py ptt start"), { description = "Tools: Voice typing, hold to talk" })
hl.bind("SUPER+ALT+V", hl.dsp.exec_cmd("~/.config/hypr/scripts/voice.py ptt stop"), { release = true, description = "Tools: Voice typing, hold to talk (release)" })
hl.bind("SUPER+SHIFT+V", hl.dsp.exec_cmd("~/.config/hypr/scripts/voice.py captions toggle"), { description = "Tools: Live captions on / off" })
hl.bind("SUPER+CTRL+P", hl.dsp.exec_cmd("~/.config/hypr/scripts/pip.py toggle"), { description = "Windows: Live mirror of this window (again closes it)" })
hl.bind("SUPER+ALT+P", hl.dsp.exec_cmd("~/.config/hypr/scripts/pip.py region"), { description = "Windows: Live mirror of a screen region" })

-- Voice commands, project contexts, screen questions, desktop memory, the
-- daily brief, phone handoff, smart layout and presence (scripts/voice.py
-- command, contexts.py, screen-ask.py, launcher "remember", brief.py,
-- phone.py, smartlayout.py, presence.py).
hl.bind("SUPER+CTRL+C", hl.dsp.exec_cmd("~/.config/hypr/scripts/voice.py command"), { description = "Tools: Voice command (start / stop and do it)" })
hl.bind("SUPER+ALT+C", hl.dsp.exec_cmd("~/.config/hypr/scripts/voice.py command-ptt start"), { description = "Tools: Voice command, hold to talk" })
hl.bind("SUPER+ALT+C", hl.dsp.exec_cmd("~/.config/hypr/scripts/voice.py command-ptt stop"), { release = true, description = "Tools: Voice command, hold to talk (release)" })
hl.bind("SUPER+CTRL+J", hl.dsp.exec_cmd("~/.config/hypr/scripts/contexts.py pick"), { description = "Projects: Switch project (picker)" })
hl.bind("SUPER+CTRL+SHIFT+J", hl.dsp.exec_cmd("~/.config/hypr/scripts/contexts.py leave"), { description = "Projects: Leave the current project" })
hl.bind("SUPER+CTRL+A", hl.dsp.exec_cmd("~/.config/hypr/scripts/screen-ask.py region"), { description = "Screen: Ask a local vision model about a region" })
hl.bind("SUPER+ALT+A", hl.dsp.exec_cmd("~/.config/hypr/scripts/screen-ask.py window"), { description = "Screen: Ask a local vision model about the focused window" })
hl.bind("SUPER+CTRL+O", hl.dsp.exec_cmd("~/.config/hypr/scripts/screen-ask.py ocr region"), { description = "Screenshots: Copy text from a region" })
hl.bind("SUPER+CTRL+M", hl.dsp.exec_cmd("~/.config/hypr/scripts/launcher.py 'remember '"), { description = "Tools: Desktop memory (ask what you saw, copied or were sent)" })
hl.bind("SUPER+CTRL+B", hl.dsp.exec_cmd("~/.config/hypr/scripts/brief.py panel"), { description = "Tools: Daily brief" })
hl.bind("SUPER+CTRL+SHIFT+B", hl.dsp.exec_cmd("~/.config/hypr/scripts/brief.py journal --notify"), { description = "Tools: Write today's journal entry" })
hl.bind("SUPER+CTRL+SHIFT+O", hl.dsp.exec_cmd("~/.config/hypr/scripts/phone.py open"), { description = "Phone: Open this page on the phone" })
hl.bind("SUPER+CTRL+F", hl.dsp.exec_cmd("~/.config/hypr/scripts/phone.py file"), { description = "Phone: Send a file to the phone" })
hl.bind("SUPER+CTRL+R", hl.dsp.exec_cmd("~/.config/hypr/scripts/smartlayout.py arrange"), { description = "Windows: Arrange this workspace as usual" })
hl.bind("SUPER+CTRL+SHIFT+P", hl.dsp.exec_cmd("~/.config/hypr/scripts/presence.py toggle-pause"), { description = "Privacy: Pause / resume presence (webcam) for an hour" })

-- The assistant, speech, background tasks, health, suggestions, focus guard,
-- ambient, gestures/gaze, other machines and the Smart desktop hub
-- (scripts/assistant.py, tts.py, tasks.py, suggest.py, focus-guard.py,
-- ambient.py, gestures.py, peers.py; settings.py PAGE opens that page).
-- SUPER+space stays the keyboard layout switch.
hl.bind("SUPER+K", hl.dsp.exec_cmd("~/.config/hypr/scripts/assistant.py toggle"), { description = "Assistant: Show / hide the desktop assistant" })
hl.bind("SUPER+SHIFT+K", hl.dsp.exec_cmd("~/.config/hypr/scripts/assistant.py open --voice"), { description = "Assistant: Open and listen (say the question)" })
hl.bind("SUPER+ALT+S", hl.dsp.exec_cmd("~/.config/hypr/scripts/tts.py selection"), { description = "Speech: Read the highlighted text aloud (again: stop)" })
hl.bind("SUPER+ALT+Q", hl.dsp.exec_cmd("~/.config/hypr/scripts/tts.py stop"), { description = "Speech: Stop talking" })
hl.bind("SUPER+ALT+W", hl.dsp.exec_cmd("~/.config/hypr/scripts/tasks.py watch-window"), { description = "Tasks: Tell me when the job in this terminal ends" })
hl.bind("SUPER+ALT+K", hl.dsp.exec_cmd("~/.config/hypr/scripts/settings.py tasks"), { description = "Tasks: Open background tasks" })
hl.bind("SUPER+CTRL+H", hl.dsp.exec_cmd("~/.config/hypr/scripts/settings.py health"), { description = "Health: Open Desktop health (last checkup, fixes to approve)" })
hl.bind("SUPER+ALT+G", hl.dsp.exec_cmd("~/.config/hypr/scripts/suggest.py snooze toggle"), { description = "Suggestions: Pause for an hour / resume" })
hl.bind("SUPER+CTRL+G", hl.dsp.exec_cmd("~/.config/hypr/scripts/focus-guard.py toggle"), { description = "Focus: Start / stop a focus block" })
hl.bind("SUPER+ALT+E", hl.dsp.exec_cmd("~/.config/hypr/scripts/ambient.py set toggle"), { description = "Ambient: Desktop follows time, weather and focus on/off" })
hl.bind("SUPER+ALT+B", hl.dsp.exec_cmd("~/.config/hypr/scripts/ambient.py soundscape toggle"), { description = "Ambient: Soundscape now / back to the mood" })
hl.bind("SUPER+CTRL+SHIFT+G", hl.dsp.exec_cmd("~/.config/hypr/scripts/gestures.py toggle gestures"), { description = "Camera: Hand gestures on/off" })
hl.bind("SUPER+CTRL+SHIFT+E", hl.dsp.exec_cmd("~/.config/hypr/scripts/gestures.py toggle gaze"), { description = "Camera: Gaze (which monitor you look at) on/off" })
hl.bind("SUPER+ALT+M", hl.dsp.exec_cmd("~/.config/hypr/scripts/peers.py send-window"), { description = "Machines: Send this window's page or file to the other machine" })
hl.bind("SUPER+ALT+SHIFT+M", hl.dsp.exec_cmd("~/.config/hypr/scripts/peers.py send-clipboard"), { description = "Machines: Send the clipboard's text to the other machine" })
hl.bind("SUPER+ALT+SHIFT+K", hl.dsp.exec_cmd("~/.config/hypr/scripts/peers.py kvm toggle"), { description = "Machines: Shared keyboard and mouse on/off" })
hl.bind("SUPER+CTRL+I", hl.dsp.exec_cmd("~/.config/hypr/scripts/settings.py intelligence"), { description = "Settings: Smart desktop (every smart feature, privacy at a glance)" })

-- Last: your own shortcuts from userbinds.conf and the key-capture mode the
-- settings page uses (lua/userbinds.lua finish()).
if UB then
    local ok, err = pcall(UB.finish)
    if not ok then
        hl.notification.create({ text = "Your own shortcuts were not added: " .. tostring(err),
                                 timeout = 8000, color = "rgb(fffb00)" })
    end
end
