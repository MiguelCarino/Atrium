-- ~/.config/hypr/hyprland.lua
-- Migrated from hyprland.conf via hyprconf2lua + manual fixes
--
-- This file is only the INDEX. The config itself lives in ~/.config/hypr/lua/,
-- one module per concern; it used to be a single ~1500-line file, and was split
-- (Oct 2026) without changing behaviour: the bind list, monitor layout,
-- workspace rules, every option the config sets and the animation tree were
-- compared before and after and came out identical.
--
--   lua/shared.lua      values more than one module needs: mainMod, scrDir.
--                       Required by the modules that use it,
--                       not from here.
--   lua/monitors.lua    hl.monitor: mode, position, rotation, HDR
--   lua/rules.lua       window rules, layer rules, workspace rules
--   lua/env.lua         hl.env (and why the NVIDIA / IME vars are NOT set)
--   lua/settings.lua    the main hl.config block
--   lua/display.lua     runtime look: the desktop theme's Hyprland half
--                       (~/.config/themes/), animation presets, screen
--                       filter, accent
--   lua/binds.lua       every bind and the resize submap, except ALT+SHIFT+G
--   lua/gamemode.lua    ALT+SHIFT+G, gamemode on/off, Steam auto-gamemode hooks
--   lua/nightlight.lua  the timers that run scripts/nightlight.sh
--   lua/autostart.lua   hl.on("hyprland.start"): daemons, bar, wallpapers
--
-- ALT+SHIFT+H opens this file and every module as tabs in cosmic-edit.
--
-- How the modules are found. Hyprland's package.path already starts with
-- ~/.config/hypr/?.lua (checked with `hyprctl repl 'return package.path'`), and
-- require turns dots into slashes, so require("lua.binds") is
-- ~/.config/hypr/lua/binds.lua with no path edit at all. The "lua." prefix is
-- doing a second job: it keeps a module name like "settings" or "shared" from
-- ever colliding with a system Lua module of the same name further down the
-- path (/usr/share/lua/5.4, ...).
--
-- Each `hyprctl reload` starts from a fresh Lua state (verified: globals and
-- package.loaded are empty afterwards), so require's cache never serves a
-- stale module -- editing a module and reloading always runs the new code.
-- Saving a module auto-reloads exactly like saving this file did (verified:
-- touching lua/env.lua alone reset the Lua state), so there is no extra step.
--
-- ORDER MATTERS, keep it as below:
--   * rules before anything else that could add a rule: window rules are
--     evaluated in declaration order.
--   * settings before binds: binds.lua makes its own small hl.config call
--     (binds.workspace_back_and_forth), and settings before gamemode, whose
--     OFF path is a reload back to these values.
--   * autostart last, as it always was at the bottom of the single file.
-- Each module is plain top-to-bottom code like the old file, so an error in one
-- stops the load at that point exactly as it used to; `hyprctl configerrors`
-- names the module and line.
--
-- Modules talk to each other ONLY through lua/shared.lua. The one deliberate
-- global is nightlight_timers (lua/nightlight.lua explains why).

---@module 'hl'

require("lua.monitors")
require("lua.rules")
require("lua.env")
require("lua.settings")
require("lua.display")
require("lua.mpvframe")     -- after display: the mpv frame preset wins over theme rules
require("lua.pip")          -- the live PiP mirror's rules (scripts/pip.py)
require("lua.focusguard")   -- focus blocks' dim rules (focus-guard.py also loads it)
require("lua.binds")
require("lua.overview")
require("lua.cube")
require("lua.gamemode")
require("lua.nightlight")
require("lua.autostart")
