"""lua/edgejump.lua under luajit with a stand-in hl: the slow / fast polling
(IDLE_MS everywhere, TICK_MS only near an edge it can jump across or while a
push is being counted), the jump itself, and REACH from the input state
(edge_reach=, Settings > Keyboard & mouse) and set_reach()."""
import json
import os
import shutil
import subprocess
import unittest

import helpers

HYPR = os.path.dirname(helpers.SCRIPTS)
INPUT_CONF = os.path.join(os.environ["XDG_STATE_HOME"], "hypr", "input.conf")

# Two screens like the desk this was written on: a 3440x1440 one at 0x0 and a
# 3200-wide one (2560 at scale 0.8) above it -- so the top edge of the lower
# one from x 3200 to 3440 has nothing beyond it.
STUB = """
package.path = %(hypr)s .. "/?.lua;" .. package.path
local cursor = { x = 1000, y = 700 }
moves = {}
timers = {}
hl = {
    get_monitors = function()
        return {
            { name = "DP-1", x = 0, y = 0,     width = 3440, height = 1440, scale = 1,   transform = 0 },
            { name = "DP-2", x = 0, y = -1350, width = 2560, height = 1080, scale = 0.8, transform = 0 },
        }
    end,
    get_monitor_at_cursor = function()
        for _, m in ipairs(hl.get_monitors()) do
            local w, h = m.width / m.scale, m.height / m.scale
            if cursor.x >= m.x and cursor.x < m.x + w and cursor.y >= m.y and cursor.y < m.y + h then return m end
        end
    end,
    get_cursor_pos = function() return { x = cursor.x, y = cursor.y } end,
    get_config = function() return true end,
    timer = function(fn, opts)
        local t = { fn = fn, timeout = opts.timeout, on = true }
        function t:set_enabled(v) self.on = v end
        function t:is_enabled() return self.on end
        timers[#timers + 1] = t
        return t
    end,
    dispatch = function(d) if d.x then cursor.x, cursor.y = d.x, d.y; moves[#moves + 1] = d end end,
    dsp = { cursor = { move = function(p) return p end } },
}
function at(x, y) cursor.x, cursor.y = x, y end
function pos() return cursor.x, cursor.y end
-- one tick of whichever timer is on; its rate
function step()
    for _, t in ipairs(timers) do
        if t.on then t.fn() return end
    end
end
function rate()
    for _, t in ipairs(timers) do if t.on then return t.timeout end end
    return 0
end
"""


@unittest.skipUnless(shutil.which("luajit"), "luajit is not installed")
class EdgeJump(unittest.TestCase):
    def tearDown(self):
        try:
            os.remove(INPUT_CONF)
        except FileNotFoundError:
            pass

    def run_lua(self, body):
        lua = STUB % {"hypr": json.dumps(HYPR)} + 'E = require("lua.edgejump")\n' + body
        out = subprocess.run(["luajit", "-e", lua], capture_output=True, text=True, timeout=10,
                             env=dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.split()

    def test_slow_away_from_edges(self):
        out = self.run_lua("at(1000, 700) step() print(rate(), E.IDLE_MS)")
        self.assertEqual(out[0], out[1])
        self.assertEqual(int(out[0]), 150)

    def test_fast_near_a_jumpable_edge_only(self):
        # Near the dead stretch of the top edge: fast. Near the top edge under
        # the upper screen (an open edge, Hyprland crosses it itself): slow.
        out = self.run_lua("at(3300, 8) step() print(rate()) at(1000, 8) step() print(rate())")
        self.assertEqual(out, ["10", "150"])

    def test_pushing_jumps_across_the_gap(self):
        out = self.run_lua("""
            at(3300, 0)
            for i = 1, 12 do
                local x, y = pos()
                if y >= 0 and y <= 2 then at(x, 0) end   -- keep pushing up
                step()
            end
            local x, y = pos()
            print(x, y)
        """)
        x, y = float(out[0]), float(out[1])
        self.assertLess(y, 0)              # on the upper screen now
        self.assertLessEqual(x, 3200)

    def test_back_to_slow_after_the_push(self):
        out = self.run_lua("""
            at(3300, 0) step() print(rate())
            at(1000, 700)
            for i = 1, 6 do step() end
            print(rate())
        """)
        self.assertEqual(out, ["10", "150"])

    def test_reach_from_the_input_state_and_set_reach(self):
        os.makedirs(os.path.dirname(INPUT_CONF), exist_ok=True)
        with open(INPUT_CONF, "w") as handle:
            handle.write("edge_reach=50\n")
        out = self.run_lua("""
            print(E.reach())
            at(3300, 8) step() print(rate())       -- the upper screen is ~100 px away: out of reach
            E.set_reach(0) at(3300, 0) step() print(rate())
            E.set_reach(600) at(3300, 8) step() print(rate())
        """)
        self.assertEqual(out, ["50", "150", "150", "10"])

    def test_the_handle_stops_both_timers(self):
        out = self.run_lua("""
            edgejump_timer:set_enabled(false) print(rate(), tostring(edgejump_timer:is_enabled()))
            edgejump_timer:set_enabled(true) print(rate())
        """)
        self.assertEqual(out, ["0", "false", "150"])


if __name__ == "__main__":
    unittest.main()
