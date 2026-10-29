-- ~/.config/hypr/lua/userbinds.lua
-- Your own changes to the shortcuts: a key moved somewhere else, a key turned
-- off, a key of your own that runs a command or opens an app. Made in
-- Settings > Keyboard shortcuts (settings_pages/shortcuts.py), or from a
-- terminal with ~/.config/hypr/scripts/shortcuts.py, and kept in one small
-- file of their own -- never in lua/binds.lua, which stays the defaults:
--
--   ~/.local/state/hypr/userbinds.conf      (one change per line, TAB between fields)
--     off    ALT+Q          Apps: Terminal              the shortcut is gone
--     move   ALT+Q  SUPER+T Apps: Terminal              ALT+Q's action now on SUPER+T
--     add    SUPER+ALT+K    Custom: Notes   <command>   a shortcut of your own
--
-- off/move name a shortcut by its DEFAULT keys (as the config binds it); the
-- description at the end is only there for the people reading the file and
-- for the settings page, which lists a shortcut that is off by it. A missing
-- file is "no changes", so deleting it is a full reset (Reset all does that).
--
-- How it works. Every bind in this config is a Lua function or a dispatcher
-- object, so `hyprctl binds` cannot tell what a key does and a key cannot be
-- re-created from the outside. So this module is required at the TOP of
-- lua/binds.lua and wraps hl.bind: each bind made from then on (binds.lua,
-- and overview.lua / cube.lua / gamemode.lua after it) is remembered with its
-- action and options, and is bound on the keys this file says -- its own keys,
-- the new ones, or none. finish(), called at the END of binds.lua, adds your
-- own shortcuts and the key-capture mode below.
--
-- Changes apply without a reload: the settings page writes the file and runs
--   hyprctl eval 'userbinds.apply()'
-- which re-reads it and moves only what changed, using each bind's own handle
-- (Keybind:remove()). hl.unbind(keys) exists too -- checked with hyprctl eval
-- on an unused SUPER+CTRL+ALT+F12, which it removed -- but it takes every
-- bind on those keys with it, which would also drop a second bind that
-- happens to share them, so it is not used here. A reload re-reads the file
-- from scratch anyway (each reload is a fresh Lua state).
--
-- Nothing in here may break the config: a line it cannot read is skipped, a
-- key Hyprland refuses leaves that shortcut on its own keys, and the errors
-- are listed by userbinds.report() (`shortcuts.py status`) instead of
-- stopping the load. Binds inside a submap (the resize mode's arrows) are left
-- exactly as they are -- they are only live inside that mode.

---@module 'hl'

local M = {}

M.file = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")) .. "/hypr/userbinds.conf"
M.binds  = {}      -- every bind made through hl.bind: { orig, keys, dsp, opts, kb, now }
M.custom = {}      -- the Keybind handles of your own shortcuts
M.errors = {}

local real_bind   = hl.bind
local real_submap = hl.define_submap
local in_submap   = nil

-- "ALT + shift+q", "SHIFT+ALT+Q" -> "ALT+SHIFT+Q": modifiers in one order,
-- everything upper case, so the same keys always compare equal however they
-- were written. scripts/shortcuts.py canon() does exactly the same. nil for
-- anything else (a modifier it does not know is left to Hyprland untouched).
local MOD_ALIAS = { SUPER = "SUPER", WIN = "SUPER", LOGO = "SUPER", MOD4 = "SUPER", META = "SUPER",
                    CTRL = "CTRL", CONTROL = "CTRL", ALT = "ALT", MOD1 = "ALT", SHIFT = "SHIFT" }
local MOD_ORDER = { "SUPER", "CTRL", "ALT", "SHIFT" }

local function canon(keys)
    if type(keys) ~= "string" then return nil end
    -- "SUPER+" has no key (the modifier is not the key); scripts/shortcuts.py too.
    if keys:match("%+%s*$") then return nil end
    local parts = {}
    for p in keys:gmatch("[^+]+") do parts[#parts + 1] = p:match("^%s*(.-)%s*$") end
    local key = table.remove(parts)
    if not key or key == "" then return nil end
    local have = {}
    for _, m in ipairs(parts) do
        local a = MOD_ALIAS[m:upper()]
        if not a then return nil end
        have[a] = true
    end
    local out = {}
    for _, m in ipairs(MOD_ORDER) do
        if have[m] then out[#out + 1] = m end
    end
    out[#out + 1] = key:upper()
    return table.concat(out, "+")
end
M.canon = canon

-- A key Hyprland could not parse is a config error, and a config error at
-- login makes hypr-guard restore the "last working" config -- so keys from
-- the file get a sanity check before they reach hl.bind: an xkb-style name
-- (letters, digits, _), a mouse button or wheel, a keycode, or one
-- character. scripts/shortcuts.py checks every key it writes against xkb's
-- own list; this only stops a hand edit with a stray space or symbol.
local function sane(keys)
    local c = canon(keys)
    if not c then return false end
    local key = c:match("([^+]+)$")
    return key:match("^[%w_]+$") ~= nil or key:match("^MOUSE:%d+$") ~= nil
        or key:match("^CODE:%d+$") ~= nil or #key == 1
end

local function split_tabs(line)
    local t, start = {}, 1
    while true do
        local i = line:find("\t", start, true)
        if not i then t[#t + 1] = line:sub(start) return t end
        t[#t + 1] = line:sub(start, i - 1)
        start = i + 1
    end
end

-- The file, as { off = {CANON = true}, moves = {CANON = "NEW+KEYS"}, adds = {...} }.
local function read_file()
    local o = { off = {}, moves = {}, adds = {} }
    local f = io.open(M.file, "r")
    if not f then return o end
    for raw in f:lines() do
        local line = raw:gsub("\r$", "")   -- a new local: Lua 5.5 loop variables are const
        if line:match("%S") and not line:match("^%s*#") then
            local fld = split_tabs(line)
            local kind, a = fld[1], canon(fld[2])
            if kind == "off" and a then
                o.off[a] = true
            elseif kind == "move" and a and sane(fld[3]) then
                o.moves[a] = fld[3]
            elseif kind == "add" and a and sane(fld[2]) and fld[4] and fld[4]:match("%S") then
                o.adds[#o.adds + 1] = { keys = fld[2], desc = fld[3] or "", cmd = fld[4] }
            else
                M.errors[#M.errors + 1] = "userbinds.conf: skipped a line it could not read: " .. line
            end
        end
    end
    f:close()
    return o
end
local over = read_file()

-- Where a remembered bind should be now: its own keys, the new ones, or false (off).
local function target(e)
    if over.off[e.orig] then return false end
    return over.moves[e.orig] or e.keys
end

-- Bind e on `want`; when Hyprland refuses the new keys, back on its own.
local function place(e, want)
    e.kb, e.now = nil, want
    if want == false then return end
    -- hl.bind does not raise on keys it cannot parse: it returns nil and
    -- files a config error (which hypr-guard then sees). Both are caught.
    local ok, kb = pcall(real_bind, want, e.dsp, e.opts)
    if ok and kb then e.kb = kb return end
    M.errors[#M.errors + 1] = "could not bind " .. tostring(want) .. " (" .. tostring(kb) .. "); left on " .. e.keys
    e.now = e.keys
    e.kb = real_bind(e.keys, e.dsp, e.opts)
end

hl.bind = function(keys, dsp, opts)
    local orig = (not in_submap) and canon(keys) or nil
    if not orig then return real_bind(keys, dsp, opts) end
    local e = { orig = orig, keys = keys, dsp = dsp, opts = opts }
    M.binds[#M.binds + 1] = e
    place(e, target(e))
    return e.kb
end

-- Binds made inside hl.define_submap's function belong to that submap and are
-- passed straight through (see the top).
hl.define_submap = function(name, a, b)
    local function inside(fn)
        if type(fn) ~= "function" then return fn end
        return function(...)
            local prev = in_submap
            in_submap = name
            local ok, err = pcall(fn, ...)
            in_submap = prev
            if not ok then error(err, 0) end
        end
    end
    if b == nil then return real_submap(name, inside(a)) end
    return real_submap(name, inside(a), inside(b))
end

local function add_custom()
    for _, kb in ipairs(M.custom) do pcall(function() kb:remove() end) end
    M.custom = {}
    for _, c in ipairs(over.adds) do
        local desc = c.desc ~= "" and c.desc or ("Custom: " .. c.cmd)
        local ok, kb = pcall(real_bind, c.keys, hl.dsp.exec_cmd(c.cmd), { description = desc })
        if ok and kb then
            M.custom[#M.custom + 1] = kb
        else
            M.errors[#M.errors + 1] = "could not bind " .. c.keys .. " (" .. tostring(kb) .. ")"
        end
    end
end

-- The end of lua/binds.lua: your own shortcuts, and the key-capture mode.
--
-- "keycapture" is a submap with a single bind, so while it is on every other
-- key goes to the focused window instead of firing its shortcut: the settings
-- page's "press the new keys" box turns it on, reads the keys you press,
-- and turns it off again (also when the box closes, loses focus, or after 15
-- seconds). SUPER+Escape leaves it by hand if anything ever went wrong; the
-- bar's submap label shows "keycapture" while it is on.
--
-- "dictation" is the same kind of mode for voice typing (scripts/voice.py):
-- on only while it types a phrase, so a key still held from SUPER+CTRL+V
-- (or pressed meanwhile) cannot turn the typed letters into shortcuts --
-- switching workspaces, spinning the cube, moving windows. Its own key
-- stops the dictation; SUPER+Escape leaves the mode by hand.
function M.finish()
    add_custom()
    real_submap("keycapture", function()
        real_bind("SUPER+Escape", hl.dsp.submap("reset"))
    end)
    real_submap("dictation", function()
        real_bind("SUPER+Escape", hl.dsp.submap("reset"))
        real_bind("SUPER+H", hl.dsp.exec_cmd("~/.config/hypr/scripts/voice.py toggle"))
        real_bind("SUPER+CTRL+V", hl.dsp.exec_cmd("~/.config/hypr/scripts/voice.py toggle"))
    end)
end

-- `hyprctl eval 'userbinds.apply()'`: read the file again and move only the
-- binds whose place changed, then put your own shortcuts back.
function M.apply()
    M.errors = {}
    over = read_file()
    for _, e in ipairs(M.binds) do
        local want = target(e)
        if want ~= e.now then
            if e.kb then pcall(function() e.kb:remove() end) end
            place(e, want)
        end
    end
    add_custom()
    return #M.errors
end

-- `hyprctl repl 'return userbinds.report()'`: one line per remembered bind,
-- "bind<TAB>default keys<TAB>keys now (or -)<TAB>description", then the
-- errors as "error<TAB>text".
function M.report()
    local out = {}
    for _, e in ipairs(M.binds) do
        local desc = type(e.opts) == "table" and (e.opts.description or e.opts.desc) or ""
        out[#out + 1] = table.concat({ "bind", e.orig, e.now and canon(e.now) or "-", desc }, "\t")
    end
    for _, err in ipairs(M.errors) do out[#out + 1] = "error\t" .. err end
    return table.concat(out, "\n")
end

-- A global on purpose: `hyprctl eval` runs in the config's Lua state but
-- cannot require() its way back to this table.
userbinds = M

return M
