-- ~/.config/hypr/lua/gamemode.lua
-- Loaded from ~/.config/hypr/hyprland.lua (the index). The ALT+SHIFT+G bind,
-- the functions behind it, the Steam auto-gamemode hooks, and hiding the
-- Steam client while a game runs.

---@module 'hl'

local S       = require("lua.shared")
local mainMod = S.mainMod

-- ========================= Gamemode =========================
-- ALT+SHIFT+G toggles a stripped-down compositor for games: no animations, no
-- blur, no rounding, no gaps, 1px borders -- all of them unless Settings >
-- Screenshots & recording says to keep some (see capture_on below). (It also
-- used to kill the two mpvpaper video wallpapers for their ~2.3 GB of VRAM; they are still images
-- now, and the slideshow pauses by itself while a game covers the screen.)
--
-- State is read from the live config rather than kept in a Lua variable:
-- animations off == gamemode on. A Lua variable would reset on every reload
-- and drift from what is actually on screen; this cannot.
--
-- Turning it OFF is a `hyprctl reload`, not a hand-written list of the values
-- to restore. The config is the one source of truth for the normal look, so
-- editing gaps or blur can never leave gamemode restoring stale numbers. The
-- normal look is the desktop THEME's: the reload runs lua/display.lua, which
-- re-applies the current theme (~/.config/themes/<name>/theme.conf) over
-- lua/settings.lua's cyberpunk defaults. While gamemode is on, display.lua
-- leaves the stripped options alone, so switching a theme, a filter or the
-- animations mid-game cannot undo the strip.
--
-- Automatic for Steam games, but it never fights you. Opening a steam_app_*
-- window switches gamemode ON; closing the last one switches it back OFF --
-- ONLY if it was the auto hook that switched it on. The rules:
--   * gamemode already on when the game opens (you pressed ALT+SHIFT+G first)
--     -> left alone, and left on when the game closes.
--   * you press ALT+SHIFT+G while a game is open, in either direction
--     -> the hook backs off for the rest of that game session: no auto-OFF on
--        close, no auto-ON from a second steam_app window (launcher -> game).
--   * the last steam_app window closes -> session over, next game starts fresh.
-- Same selector as the fs-render-windowed-steam / idle-inhibit rules in
-- lua/rules.lua:
-- steam_app_<appid> is assigned by Steam itself, so it covers every game.
--
-- The auto/manual state lives in a file under $XDG_RUNTIME_DIR, not in a Lua
-- variable, for the same reason gamemode's own state is read from the live
-- config: gamemode OFF is a `hyprctl reload`, which re-runs the whole config
-- and would wipe a variable mid-session. The file is tmpfs, per-user, and gone
-- at logout, so a crash can never leave a stale "auto" behind across boots.
--   (absent)  no game session, or one where the hook did nothing
--   auto      the hook turned gamemode on and may turn it off
--   manual    you toggled during this game session; hook stays out of it
local gamemode_state_file = (os.getenv("XDG_RUNTIME_DIR") or "/tmp") .. "/hypr-gamemode-auto"

-- What gamemode strips, whether Steam games switch it on by themselves and
-- whether Steam is tucked away mid-game are Settings > Screenshots &
-- recording's (~/.config/hypr/scripts/capture-settings.py), kept in
-- ~/.local/state/hypr/capture.conf as key=value lines. Read at the moment
-- they matter -- each time gamemode turns on, each time a game window opens --
-- so a change needs no reload. A key that is missing, or the whole file, is
-- "on": the behaviour this file always had.
--   gamemode_blur / _shadow / _rounding / _gaps / _borders   what is stripped
--   gamemode_auto        Steam games turn gamemode on (and off again)
--   gamemode_hide_steam  the Steam client goes to special:steam mid-game
-- Animations are not on the list: animations off IS gamemode on -- the test
-- below, lua/display.lua's and wallpaper-slideshow.py's -- so they always go.
local capture_file = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state"))
                     .. "/hypr/capture.conf"

local function capture_on(key)
    local kv = S.read_kv(capture_file) or {}
    return kv[key] ~= "off"
end

-- The graphics card's memory: a local model in LM Studio can hold 20 GB of
-- it, so gamemode ON unloads them all and OFF says so (Settings > AI &
-- models, ~/.config/hypr/scripts/llm-gpu.py; its unload_for_games /
-- reload_after_games switches decide, and with LM Studio not running it
-- does nothing, without starting it). Run in the background: lms takes a
-- second or two, the game should not wait for it.
local llm_gpu = "~/.config/hypr/scripts/llm-gpu.py gamemode "

local function gamemode_is_on()
    return not hl.get_config("animations.enabled")
end

-- why: shown in the notification, so an auto switch is never a mystery
-- ("Gamemode ON (steam_app_1245620)") -- the only visible difference between
-- the hook and the key.
local function gamemode_on(why)
    -- Only what is ticked; the rest keeps the theme's look. lua/display.lua
    -- leaves all five alone while gamemode is on either way, so a theme
    -- switch mid-game neither strips nor restores them.
    local decoration, general = {}, {}
    if capture_on("gamemode_rounding") then decoration.rounding = 0 end
    if capture_on("gamemode_blur")     then decoration.blur   = { enabled = false } end
    if capture_on("gamemode_shadow")   then decoration.shadow = { enabled = false } end
    if capture_on("gamemode_gaps")     then general.gaps_in, general.gaps_out = 0, 0 end
    if capture_on("gamemode_borders")  then general.border_size = 1 end
    hl.config({
        animations = { enabled = false },
        decoration = decoration,
        general    = general,
    })
    -- The mpv frame preset is a window rule, which beats the stripped look;
    -- it switches itself off while animations are (gamemode OFF reloads it).
    require("lua.mpvframe").apply()
    hl.notification.create({ text = "Gamemode ON" .. (why and (" (" .. why .. ")") or ""),
                             timeout = 1500, color = "rgb(39ff14)" })
    hl.exec_cmd(llm_gpu .. "on")
end

local function gamemode_off(why)
    hl.exec_cmd(llm_gpu .. "off")
    hl.exec_cmd("hyprctl reload")
    hl.notification.create({ text = "Gamemode OFF" .. (why and (" (" .. why .. ")") or ""),
                            timeout = 1500, color = "rgb(0ff0fc)" })
end

local function gamemode_state_read()
    local f = io.open(gamemode_state_file, "r")
    if not f then return nil end
    local s = f:read("l")
    f:close()
    return s
end

local function gamemode_state_write(s)
    if s == nil then
        os.remove(gamemode_state_file)
        return
    end
    local f = io.open(gamemode_state_file, "w")
    if f then f:write(s) f:close() end
end

local function is_steam_game(w)
    return w ~= nil and (w.class or ""):find("^steam_app_") ~= nil
end

-- except: address of a window to leave out. window.close fires while the
-- closing window is still listed by hl.get_windows() (and still mapped=true --
-- measured), so counting "the last one" has to exclude it explicitly.
local function steam_game_count(except)
    local n = 0
    for _, w in ipairs(hl.get_windows()) do
        if w.address ~= except and is_steam_game(w) then n = n + 1 end
    end
    return n
end

-- The 3 s off-timer below is the only thing that clears the state file, and a
-- config reload (or Hyprland restart) inside that window starts a fresh Lua
-- state and drops the pending timer. The file would then keep "auto"/"manual"
-- with no game open, and gamemode_auto_check would ignore the next game. No
-- game session can exist without a steam_app window, so with none open any
-- state found at load is leftover from a lost timer: clear it.
if steam_game_count() == 0 then gamemode_state_write(nil) end

hl.bind(mainMod .. "+SHIFT+G", function()
    if gamemode_is_on() then gamemode_off() else gamemode_on() end
    -- A press while a game is open is you deciding; the hook backs off until
    -- the last game window closes. With no game open there is no session to
    -- hand over, so the state just clears.
    gamemode_state_write(steam_game_count() > 0 and "manual" or nil)
end, { description = "Games: Gamemode" })

local function gamemode_auto_check(w)
    if not is_steam_game(w) then return end
    -- Switched off in Settings: Steam games leave gamemode to the key.
    if not capture_on("gamemode_auto") then return end
    -- "auto": already done for this session. "manual": you took over.
    if gamemode_state_read() ~= nil then return end
    -- Already on with no state means you switched it on yourself before
    -- launching. Leave the state empty so closing the game does not revert it.
    if gamemode_is_on() then return end
    gamemode_state_write("auto")
    gamemode_on(w.class)
end
-- ========================= Hide Steam while a game runs =========================
-- A Steam game opening tucks the Steam client's windows (main window, friends
-- list, ...) onto special:steam, out of sight; the last game closing brings
-- them back to workspace 5, their home from the launchers-to-ws5 rule in
-- lua/rules.lua. Neither move takes focus with it -- tested. Independent of
-- the gamemode auto/manual state above: Steam hides even with gamemode off.
--
-- Only the game's arrival hides Steam. A Steam window you open yourself mid-
-- game (tray icon, Shift+Tab overlay links) is left where it appears.
local steam_hidden_ws = "special:steam"
local steam_home_ws   = "5"

local function is_steam_client(w)
    return w ~= nil and w.class == "steam"
end

local function steam_move(from_hidden, to)
    for _, w in ipairs(hl.get_windows()) do
        local on_hidden = w.workspace ~= nil and w.workspace.name == steam_hidden_ws
        if is_steam_client(w) and on_hidden == from_hidden then
            hl.dispatch(hl.dsp.window.move({ workspace = to, follow = false,
                                             window = "address:" .. w.address }))
        end
    end
end

local function steam_hide(w)
    if is_steam_game(w) and capture_on("gamemode_hide_steam") then steam_move(false, steam_hidden_ws) end
end

local function steam_restore()
    steam_move(true, steam_home_ws)
end

-- Same lost-timer reasoning as the state file above: a reload inside the
-- 3 s close timer would otherwise leave Steam hidden with no game open.
if steam_game_count() == 0 then steam_restore() end

hl.on("window.open",  steam_hide)
hl.on("window.class", steam_hide)

-- Peek at the hidden Steam over the game; again to tuck it away. Bare name as a
-- string: see the toggle_special note on the scratchpad bind in lua/binds.lua.
hl.bind(mainMod .. "+CTRL+G", hl.dsp.workspace.toggle_special("steam"), { description = "Games: Show / hide Steam" })

hl.on("window.open", gamemode_auto_check)
-- Some games (Proton titles in particular) map first and set their final
-- WM_CLASS a moment later; catching the class change covers those. Measured
-- Oct 2026 with an Xwayland window that changed its WM_CLASS after mapping:
-- the callback gets one argument, the HL.Window, with .class already the NEW
-- value; it also fires once at map with the initial class.
hl.on("window.class", gamemode_auto_check)

-- Auto-OFF waits 3 s and then re-counts, instead of reacting to the close
-- itself. Games that go launcher window -> game window close one steam_app
-- window just before mapping the next; reacting instantly would reload the
-- compositor in the gap, then strip it again.
local gamemode_off_timer = nil
hl.on("window.close", function(w)
    if not is_steam_game(w) then return end
    if steam_game_count(w.address) > 0 then return end
    if gamemode_off_timer then gamemode_off_timer:set_enabled(false) end
    gamemode_off_timer = hl.timer(function()
        gamemode_off_timer = nil
        if steam_game_count() > 0 then return end   -- the next window arrived
        steam_restore()
        local st = gamemode_state_read()
        gamemode_state_write(nil)                     -- session over either way
        if st == "auto" and gamemode_is_on() then gamemode_off("game closed") end
    end, { timeout = 3000, type = "oneshot" })
end)

-- For scripts: `hyprctl eval 'require("lua.gamemode").set(true, "why")'` is
-- scripts/automations.py's "gamemode on|off" action. It behaves like the key
-- (switching while a game is open is a decision: the auto hook backs off for
-- that game session), but does nothing when gamemode is already that way.
return {
    is_on = gamemode_is_on,
    set = function(on, why)
        if on == gamemode_is_on() then return end
        if on then gamemode_on(why) else gamemode_off(why) end
        gamemode_state_write(steam_game_count() > 0 and "manual" or nil)
    end,
}
