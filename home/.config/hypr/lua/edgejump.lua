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
-- A repeat timer reads the cursor every TICK_MS (Hyprland has no pointer
-- motion event in Lua); it only looks at the screens when the cursor is on an
-- edge. Off in gamemode (animations.enabled == false, lua/gamemode.lua), so a
-- game's pointer is never moved. Like nightlight_timers, the timer is kept in
-- a global, which is also the handle:
--   hyprctl eval 'edgejump_timer:set_enabled(false)'
-- stops it until the next reload.

---@module 'hl'

local TICK_MS    = 10
local PUSHES     = 10
local IDLE_TICKS = 4
local NUDGE      = 2
local REACH      = 600     -- logical px: the widest gap a jump crosses

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
local function dead_edge(r, x, y)
    local rects
    for name, e in pairs(EDGES) do
        if e.dist(r, x, y) < 0.5 then
            if not rects then
                rects = {}
                for _, m in ipairs(hl.get_monitors()) do rects[#rects + 1] = rect(m) end
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

local function move(x, y)
    hl.dispatch(hl.dsp.cursor.move({ x = math.floor(x), y = math.floor(y) }))
end

local function tick()
    if not hl.get_config("animations.enabled") then pushes, edge_key = 0, nil return end
    local m = hl.get_monitor_at_cursor()
    if not m then return end
    local p = hl.get_cursor_pos()
    local r = rect(m)
    local name, e, tx, ty = dead_edge(r, p.x, p.y)
    if not name then
        if edge_key then
            idle = idle + 1
            if idle > IDLE_TICKS then pushes, edge_key = 0, nil end
        end
        return
    end
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
edgejump_timer = hl.timer(tick, { timeout = TICK_MS, type = "repeat" })

return { dead_edge = dead_edge, rect = rect }
