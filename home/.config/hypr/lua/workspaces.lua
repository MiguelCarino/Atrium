-- ~/.config/hypr/lua/workspaces.lua
-- Which workspace lives on which screen, worked out from the screens in order
-- (lua/monitors.lua's order(): the host file's M.screens, else the live ones)
-- and the primary. Pure -- no hl calls -- so lua/rules.lua (the workspace
-- rules) and lua/binds.lua (the mainMod+n loops) agree on one list, and
-- tests/test_workspace_homes.py runs it under luajit.
--
--   local W = require("lua.workspaces")
--   for _, h in ipairs(W.homes(SCREENS, P)) do ... end   -- one entry per workspace
--   W.last(SCREENS)                                       -- highest workspace (the keys' loop)
--
-- The rule, unchanged for the first three screens:
--   the primary            1 (where it lands), 2, 3, 5
--   the 2nd screen         4      the 3rd   6
--   the 4th screen         7      the 5th   8 ... (one each, n + 3)
--   by place in the list, NOT "whatever is not the primary", so picking
--   another primary in Settings > Screens moves 1/2/3/5 and leaves the rest.
-- Every one is persistent and has a home: 4 and 6 stay even on a machine
-- with fewer screens (the bar's pills stay; they sit on the primary then,
-- without default). Nothing past the last screen's workspace is declared,
-- and lua/binds.lua binds mainMod+1..last() -- exactly these -- so no key
-- ever reaches a homeless workspace that evaporates when empty (the reason
-- the loops once stopped at 6; see the note above them).

local M = {}

-- The workspace the n-th screen (n >= 2) gets as its own.
function M.slot(n)
    if n == 2 then return 4 end
    if n == 3 then return 6 end
    return n + 3
end

-- The highest workspace number a key reaches: 6, or the last screen's own
-- (7 with four screens). 10 at most -- the 0 key; a screen past the seventh
-- gets no workspace of its own.
function M.last(screens)
    local n = type(screens) == "table" and #screens or 0
    local top = 6
    if n >= 4 then top = M.slot(n) end
    if top > 10 then top = 10 end
    return top
end

-- { {ws = 1, monitor = "DP-1", default = true, persistent = true}, ... }
-- sorted by ws. monitor is nil only when no screen is known at all (primary
-- nil: the first load of a session on a machine with no host file); the
-- caller then declares the persistent ones without a home and the next
-- reload pins them.
function M.homes(screens, primary)
    screens = type(screens) == "table" and screens or {}
    local by_ws = {}
    local function put(ws, mon, default, persistent)
        if ws > 10 or by_ws[ws] then return end
        by_ws[ws] = { ws = ws, monitor = mon, default = default and mon ~= nil or false,
                      persistent = persistent }
    end
    put(1, primary, true, true)
    put(2, primary, false, true)
    put(3, primary, false, true)
    put(5, primary, false, true)
    for n = 2, #screens do
        put(M.slot(n), screens[n], true, true)
    end
    -- 4 and 6 stay (on the primary) with fewer screens.
    put(4, primary, false, true)
    put(6, primary, false, true)
    local list = {}
    for ws = 1, 10 do
        if by_ws[ws] then list[#list + 1] = by_ws[ws] end
    end
    return list
end

return M
