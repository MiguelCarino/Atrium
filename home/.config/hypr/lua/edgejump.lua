-- lua/edgejump.lua -- the cursor crosses gaps between screens
--
-- Hyprland only lets the cursor onto a screen whose edge touches the one it
-- is on. Screens of different widths leave gaps: a 3200-wide screen above a
-- 3440-wide one leaves 240 px of the top edge with nothing beyond it, and
-- the cursor stops there. Here, pushing on such an edge for a moment jumps
-- the cursor to the nearest point of the screen across the gap (within
-- REACH). A screen's outer edges, with nothing across them, stay walls.
--
-- "Pushing" and not "touching": the bar's buttons sit on the top edge, and a
-- quick flick up to them must not throw the cursor onto another screen.
-- Hyprland does not report motion the cursor could not make, so each time it
-- reaches such an edge it is set back NUDGE px; coming back to the edge again
-- is one more push. PUSHES pushes in a row (about a tenth of a second of
-- steady pushing) make the jump; a flick that stops is only a few, and
-- IDLE_TICKS without a push start the count over. The nudge leaves the cursor
-- on the bar, so its buttons still work from there.
--
-- A repeat timer reads the cursor (Hyprland has no pointer motion event in
-- Lua): every IDLE_MS while the cursor is anywhere else, every TICK_MS while
-- it is within NEAR px of an edge it could jump across (or a push is being
-- counted). The fast rate is what the push counting is tuned for; the slow
-- one is all the rest of the time, so the desktop no longer wakes a hundred
-- times a second for this. A flick straight onto the edge between two slow
-- reads is caught at the next one -- at most IDLE_MS late, well inside the
-- tenth of a second a jump takes anyway. It only looks at the screens when
-- the cursor is near an edge. Off in gamemode (animations.enabled == false,
-- lua/gamemode.lua), so a game's pointer is never moved. Like
-- nightlight_timers, the timers are kept in a global, which is also the
-- handle:
--   hyprctl eval 'edgejump_timer:set_enabled(false)'
-- stops it until the next reload. Two repeat timers, one per rate, and only
-- one of them enabled: HL.Timer:set_timeout() does not change the interval
-- of a running repeat timer (checked on 0.56: a 1000 ms timer set to 50 kept
-- firing once a second), and making a new timer at every switch would pile
-- disabled ones up for the whole session.
--
-- REACH is a setting: edge_reach= in the input state (Settings > Keyboard,
-- mouse & touchpad > Mouse; input-settings.py set edge_reach 400), 0 = no
-- jumps at all (the timer then stays at the slow rate and does nothing).
-- lua/input.lua passes a change on through set_reach() below.

---@module 'hl'

local TICK_MS    = 10      -- near a jumpable edge: the rate pushes are counted at
local IDLE_MS    = 150     -- everywhere else
local NEAR       = 16      -- logical px from such an edge that switch to TICK_MS
local PUSHES     = 10
local IDLE_TICKS = 4
local NUDGE      = 2
local REACH      = 600     -- logical px: the widest gap a jump crosses (edge_reach)

do
    local S = require("lua.shared")
    local st = S.read_kv(S.input_file) or {}
    local n = tonumber(st.edge_reach)
    if n and n >= 0 and n <= 2000 then REACH = math.floor(n) end
end

-- A screen's area in the layout (logical px): its mode over its scale, turned
-- for a rotated screen.
local function rect(m)
    local w, h = m.width / m.scale, m.height / m.scale
    if m.transform % 2 == 1 then w, h = h, w end
    return { name = m.name, x = m.x, y = m.y, w = w, h = h }
end

local function on(r, x, y)
    return x >= r.x and x < r.x + r.w and y >= r.y and y < r.y + r.h
end

local function clamp(v, lo, hi) return math.max(lo, math.min(hi, v)) end

-- Per direction: how far the cursor is from that edge of r, the point just
-- beyond the edge, whether screen o lies wholly across it, and where the
-- cursor sits after a nudge back from it.
local EDGES = {
    up = {
        dist   = function(r, x, y) return y - r.y end,
        beyond = function(r, x, y) return x, r.y - 1 end,
        across = function(r, o) return o.y + o.h <= r.y + 1 end,
        nudge  = function(r, x, y) return x, r.y + NUDGE end,
    },
    down = {
        dist   = function(r, x, y) return r.y + r.h - 1 - y end,
        beyond = function(r, x, y) return x, r.y + r.h end,
        across = function(r, o) return o.y >= r.y + r.h - 1 end,
        nudge  = function(r, x, y) return x, r.y + r.h - 1 - NUDGE end,
    },
    left = {
        dist   = function(r, x, y) return x - r.x end,
        beyond = function(r, x, y) return r.x - 1, y end,
        across = function(r, o) return o.x + o.w <= r.x + 1 end,
        nudge  = function(r, x, y) return r.x + NUDGE, y end,
    },
    right = {
        dist   = function(r, x, y) return r.x + r.w - 1 - x end,
        beyond = function(r, x, y) return r.x + r.w, y end,
        across = function(r, o) return o.x >= r.x + r.w - 1 end,
        nudge  = function(r, x, y) return r.x + r.w - 1 - NUDGE, y end,
    },
}

-- The edge of r the cursor is on with nothing beyond it, and the nearest point
-- of a screen across it: edge name, the edge, target x, y. nil otherwise.
-- within (default 0.5, "on it") widens "on" to "this close to it", which is
-- how the timer tells it is worth reading the cursor quickly. mons: the
-- monitors, for the tests; hl.get_monitors() when nil.
local function dead_edge(r, x, y, within, mons)
    local rects
    within = within or 0.5
    for name, e in pairs(EDGES) do
        if e.dist(r, x, y) < within then
            if not rects then
                rects = {}
                for _, m in ipairs(mons or hl.get_monitors()) do rects[#rects + 1] = rect(m) end
            end
            local bx, by = e.beyond(r, x, y)
            local open = false
            for _, o in ipairs(rects) do
                if on(o, bx, by) then open = true break end
            end
            if not open then
                local best, tx, ty
                for _, o in ipairs(rects) do
                    if o.name ~= r.name and e.across(r, o) then
                        local px = clamp(bx, o.x, o.x + o.w - 1)
                        local py = clamp(by, o.y, o.y + o.h - 1)
                        local d = math.sqrt((px - bx) ^ 2 + (py - by) ^ 2)
                        if d <= REACH and (not best or d < best) then best, tx, ty = d, px, py end
                    end
                end
                if best then return name, e, tx, ty end
            end
        end
    end
end

local pushes, idle, edge_key = 0, 0, nil
local rate = nil       -- the rate now (TICK_MS or IDLE_MS)
local timers = {}      -- [TICK_MS] = fast timer, [IDLE_MS] = slow timer
local stopped = false  -- edgejump_timer:set_enabled(false) by hand

local function set_rate(ms)
    if ms ~= rate and not stopped and timers[ms] then
        rate = ms
        for t_ms, t in pairs(timers) do t:set_enabled(t_ms == ms) end
    end
end

local function move(x, y)
    hl.dispatch(hl.dsp.cursor.move({ x = math.floor(x), y = math.floor(y) }))
end

local function tick()
    if REACH <= 0 or not hl.get_config("animations.enabled") then
        pushes, edge_key = 0, nil
        set_rate(IDLE_MS)
        return
    end
    local m = hl.get_monitor_at_cursor()
    if not m then return end
    local p = hl.get_cursor_pos()
    if not p then return end
    local r = rect(m)
    local name, e, tx, ty = dead_edge(r, p.x, p.y)
    if not name then
        if edge_key then
            idle = idle + 1
            if idle > IDLE_TICKS then pushes, edge_key = 0, nil end
        end
        -- Fast while a push is still being counted or the cursor is close
        -- to an edge it could jump across; slow otherwise.
        set_rate((edge_key or dead_edge(r, p.x, p.y, NEAR)) and TICK_MS or IDLE_MS)
        return
    end
    set_rate(TICK_MS)
    local key = r.name .. ":" .. name
    if key ~= edge_key then pushes, edge_key = 0, key end
    pushes, idle = pushes + 1, 0
    if pushes >= PUSHES then
        pushes, edge_key = 0, nil
        move(tx, ty)
    else
        move(e.nudge(r, p.x, p.y))
    end
end

if edgejump_timer then edgejump_timer:set_enabled(false) end
timers[IDLE_MS] = hl.timer(tick, { timeout = IDLE_MS, type = "repeat" })
timers[TICK_MS] = hl.timer(tick, { timeout = TICK_MS, type = "repeat" })
timers[TICK_MS]:set_enabled(false)
rate = IDLE_MS
-- The handle (see the top): both timers at once.
edgejump_timer = {
    set_enabled = function(_, on)
        stopped = not on
        if on then
            rate = nil
            set_rate(IDLE_MS)
        else
            for _, t in pairs(timers) do t:set_enabled(false) end
        end
    end,
    is_enabled = function()
        return not stopped
    end,
    rate = function() return rate end,
}

-- lua/input.lua, after input-settings.py set edge_reach N.
local function set_reach(n)
    n = tonumber(n)
    if n and n >= 0 then REACH = math.floor(n) end
    pushes, edge_key = 0, nil
end

return { dead_edge = dead_edge, rect = rect, set_reach = set_reach,
         reach = function() return REACH end, TICK_MS = TICK_MS, IDLE_MS = IDLE_MS }
