-- ~/.config/hypr/lua/monitors.lua
-- Loaded from ~/.config/hypr/hyprland.lua (the index). The screens are per
-- machine: lua/hosts/<hostname>.lua holds this machine's layout (mode,
-- position, rotation, HDR; scripts/monitors-capture.py writes it), and a machine with
-- no file of its own gets every screen at its preferred mode, side by side,
-- until scripts/monitors-capture.py writes one from the live layout.
--
-- Either way the module returned has apply() and hdr_capable, so the runtime
-- callers stay the same:
--   hyprctl eval 'require("lua.monitors").apply()'     (scripts/display.py)
--
-- On top of the host file: the choices made in Settings > Screens (or with
-- scripts/display.py resolution / scale / rotate / position / mirror / vrr /
-- bitdepth / screen). They live in the display state (lua/shared.lua), one
-- key per screen, and screen() below lays them over the host file's block
-- for that screen just before it reaches hl.monitor:
--
--   rate.HDMI-A-1=60.00         refresh rate   (the "@..." of mode)
--   mode.HDMI-A-1=1280x720      resolution     (the "WxH" of mode)
--   scale.HDMI-A-1=1.25         scale
--   transform.HDMI-A-1=1        rotation, Hyprland's 0-7
--   position.HDMI-A-1=3440x0    position, always exact (display.py works out
--                               "right of DP-2" before it writes it)
--   mirror.HDMI-A-1=DP-2        show DP-2's picture instead of its own
--   vrr.HDMI-A-1=1              0 off, 1 on, 2 fullscreen only
--   bitdepth.HDMI-A-1=8         8 or 10
--   disabled.HDMI-A-1=on        switched off (nothing else of it is sent)
--   primary=HDMI-A-1            the main screen (M.primary(), below)
--
-- A key that is missing (or empty) means "what the host file says", so
-- deleting one undoes that choice and deleting the file undoes them all. The
-- host files call screen(spec) instead of hl.monitor(spec); one that still
-- calls hl.monitor itself keeps working, just without these choices.

---@module 'hl'

local S = require("lua.shared")

local function hostname()
    local f = io.open("/etc/hostname")
    local name = f and f:read("*l") or ""
    if f then f:close() end
    if name == "" then
        local p = io.popen("hostname -s 2>/dev/null")
        name = p and p:read("*l") or ""
        if p then p:close() end
    end
    return (name:match("^[^.]*") or ""):gsub("[^%w_]", "_")
end

-- The host file's spec for one screen with that screen's display-state keys
-- laid over it (see the top). Pure: the spec in, a new spec out, so
-- tests/test_settings_screens.py can run it under luajit with a stand-in hl.
local function overlay(spec, st)
    local o = spec.output
    local function key(name)
        local v = st[name .. "." .. o]
        if v ~= nil and v ~= "" then return v end
        return nil
    end
    if key("disabled") == "on" then
        return { output = o, disabled = true }
    end
    local out = {}
    for k, v in pairs(spec) do out[k] = v end
    -- mode is "WxH@Hz"; each half can be chosen on its own. A resolution
    -- chosen without a rate gets none, and Hyprland picks the best one the
    -- screen offers there (the host file's rate may not exist at it).
    local res, hz = tostring(spec.mode or ""):match("^(%d+x%d+)@?([%d%.]*)$")
    local want_res, want_hz = key("mode"), key("rate")
    if want_res and want_res ~= res then hz = nil end
    res = want_res or res
    hz = want_hz or hz
    if res then
        out.mode = res .. ((hz and hz ~= "") and ("@" .. hz) or "")
    end
    out.scale     = tonumber(key("scale")) or spec.scale
    out.transform = tonumber(key("transform")) or spec.transform
    out.position  = key("position") or spec.position
    out.vrr       = tonumber(key("vrr")) or spec.vrr
    out.bitdepth  = tonumber(key("bitdepth")) or spec.bitdepth
    out.mirror    = key("mirror") or spec.mirror
    return out
end

local function screen(spec)
    hl.monitor(overlay(spec, S.state()))
end

-- The outputs the display state names (rate.X, scale.X ...): the generic
-- fallback has no block of its own for them, so it makes one.
local FIELDS = { rate = true, mode = true, scale = true, transform = true, position = true,
                 mirror = true, vrr = true, bitdepth = true, disabled = true }
local function named_outputs(st)
    local seen, list = {}, {}
    for k, v in pairs(st) do
        local field, o = k:match("^([%w_]+)%.(.+)$")
        if field and FIELDS[field] and v ~= "" and not seen[o] then
            seen[o] = true
            list[#list + 1] = o
        end
    end
    table.sort(list)
    return list
end

local ok, host = pcall(require, "lua.hosts." .. hostname())
if not (ok and type(host) == "table") then host = nil end

-- The live screens' names, the one at 0x0 first (where Hyprland puts the
-- first screen when positions are "auto", as the generic layout below has
-- them), then the rest by id. scripts/screens.py's live_order() is the same
-- rule. pcall + type checks: at the very first load of a session Hyprland may
-- not have any screens yet (or, under luajit in the tests, no hl.get_monitors
-- at all) -- then the list is empty and the callers do without.
local function live_order()
    local okm, mons = pcall(function() return hl.get_monitors() end)
    if not okm or type(mons) ~= "table" then return {} end
    local list = {}
    for _, m in ipairs(mons) do
        if type(m) == "table" and m.name then list[#list + 1] = m end
    end
    table.sort(list, function(a, b) return (a.id or 0) < (b.id or 0) end)
    local names, first = {}, nil
    for _, m in ipairs(list) do
        if first == nil and (m.x or 0) == 0 and (m.y or 0) == 0 then first = m.name end
    end
    if first then names[1] = first end
    for _, m in ipairs(list) do
        if m.name ~= first then names[#names + 1] = m.name end
    end
    return names
end

-- The screens in order: the host file's M.screens (its first is the primary,
-- its second and third get workspaces 4 and 6 -- lua/rules.lua), or the live
-- ones by the rule above when the machine has no host file.
local function order()
    if host and type(host.screens) == "table" and #host.screens > 0 then return host.screens end
    return live_order()
end

-- The primary screen: the one workspace 1 (and the bar) belong on.
-- scripts/display.py primary writes primary=<output>; missing means order()'s
-- first. nil only when nothing knows a screen at all (no host file, no screen
-- up yet): lua/rules.lua then leaves the workspaces unpinned. For a module
-- loaded after this one:  require("lua.monitors").primary()
-- scripts/screens.py primary() answers the same for the scripts.
local function primary(st)
    local p = (st or S.state()).primary
    if p ~= nil and p ~= "" then return p end
    return order()[1]
end

local M = { overlay = overlay, screen = screen, primary = primary, order = order }
if host then
    M.hdr_capable = host.hdr_capable or {}
    -- A screen the host file has no block for (one plugged in since it was
    -- written) still gets its Settings > Screens choices: Hyprland's own
    -- default (preferred, auto, 1) with the display state laid over it.
    function M.apply()
        local done = {}
        host.apply(function(spec)
            if spec.output then done[spec.output] = true end
            screen(spec)
        end)
        for _, o in ipairs(named_outputs(S.state())) do
            if not done[o] then
                screen({ output = o, mode = "preferred", position = "auto", scale = 1 })
            end
        end
    end
else
    M.hdr_capable = {}
    function M.apply()
        hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })
        for _, o in ipairs(named_outputs(S.state())) do
            screen({ output = o, mode = "preferred", position = "auto", scale = 1 })
        end
    end
end

M.apply()

return M
