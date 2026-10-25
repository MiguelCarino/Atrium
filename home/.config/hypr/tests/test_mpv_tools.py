"""mpv's player tools: scripts/mpv-pip.py (the mpv window into a screen
corner and back), the mpv scripts behind the controls-row buttons
(~/.config/mpv/scripts/sleep-timer.lua, window-pip.lua, sub-tools.lua, run
under a stub `mp` in luajit), and the controls row itself in
themes/mpv-base.conf, parsed the way uosc parses it.

Hermetic: the records file is helpers.py's scratch XDG_RUNTIME_DIR, the
hyprctl calls are stubbed, no mpv is started and no window is moved."""
import json
import os
import re
import shutil
import subprocess
import unittest

import helpers

mpv_pip = helpers.import_script("mpv-pip.py")
# ~/.config, found from this file (tests/ is in ~/.config/hypr/), so the
# tests read the files next to them wherever the tree is checked out.
CONFIG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(CONFIG, "mpv", "scripts")
BASE = os.path.join(CONFIG, "themes", "mpv-base.conf")

DP1 = {"id": 1, "name": "DP-1", "x": 0, "y": 0, "width": 3440, "height": 1440, "scale": 1, "transform": 0,
       "focused": True}
SIDE = {"id": 0, "name": "HDMI-A-1", "x": 3440, "y": -1046, "width": 1920, "height": 1080, "scale": 1,
        "transform": 1, "focused": False}


def mpv_client(**over):
    c = {"address": "0xabc", "pid": 4242, "class": "mpv", "mapped": True, "floating": False, "pinned": False,
         "fullscreen": 0, "monitor": 1, "at": [1730, 51], "size": [1697, 1376]}
    c.update(over)
    return c


class Window(unittest.TestCase):
    def test_find_client_by_pid(self):
        clients = [mpv_client(pid=1, address="0x1"), mpv_client(pid=4242, mapped=False, address="0x2"),
                   mpv_client(address="0x3")]
        self.assertEqual(mpv_pip.find_client(clients, 4242)["address"], "0x3")   # the mapped one
        self.assertIsNone(mpv_pip.find_client(clients, 999))
        self.assertIsNone(mpv_pip.find_client(None, 4242))

    def test_on_means_floating_and_pinned(self):
        self.assertTrue(mpv_pip.is_on(mpv_client(floating=True, pinned=True)))
        self.assertFalse(mpv_pip.is_on(mpv_client(floating=True)))
        self.assertFalse(mpv_pip.is_on(mpv_client(pinned=True)))

    def test_monitor_of(self):
        self.assertEqual(mpv_pip.monitor_of(mpv_client(monitor=0), [DP1, SIDE])["name"], "HDMI-A-1")
        self.assertEqual(mpv_pip.monitor_of(mpv_client(monitor=7), [SIDE, DP1])["name"], "DP-1")  # focused

    def test_enter_from_maximized_tile(self):
        calls, record = mpv_pip.enter_calls(mpv_client(fullscreen=1), DP1,
                                            {"width": "480", "corner": "bottom-right"}, (1920, 804))
        t = '"address:0xabc"'
        # 1920x804 (2.39:1) at 480 wide is 480x201; bottom-right of the
        # 3440x1440 screen, 24 px in: x = 3440 - 480 - 24, y = 1440 - 201 - 24.
        self.assertEqual(calls, [
            f'hl.dsp.window.fullscreen({{ mode = "maximized", action = "unset", window = {t} }})',
            f'hl.dsp.window.float({{ action = "enable", window = {t} }})',
            f"hl.dsp.window.resize({{ x = 480, y = 201, window = {t} }})",
            f"hl.dsp.window.move({{ x = 2936, y = 1215, window = {t} }})",
            f"hl.dsp.window.pin({{ window = {t} }})",
        ])
        self.assertEqual(record, {"floating": False, "at": [1730, 51], "size": [1697, 1376], "fullscreen": 1})

    def test_enter_already_floating_uses_window_shape_without_video(self):
        calls, _ = mpv_pip.enter_calls(mpv_client(floating=True, size=[800, 600]), DP1,
                                       {"width": "400", "corner": "top-left"}, None)
        self.assertFalse(any("float(" in c or "fullscreen(" in c for c in calls))
        self.assertIn('hl.dsp.window.resize({ x = 400, y = 300, window = "address:0xabc" })', calls)
        # top-left: 24 px in, and below the bar (pip.BAR_H).
        self.assertIn(f'hl.dsp.window.move({{ x = 24, y = {24 + mpv_pip.pip.BAR_H}, window = "address:0xabc" }})',
                      calls)

    def test_leave_back_to_tile_or_float(self):
        t = '"address:0xabc"'
        here = mpv_client(floating=True, pinned=True)
        self.assertEqual(mpv_pip.leave_calls(here, {"floating": False, "fullscreen": 0, "at": [0, 0], "size": [1, 1]}),
                         [f"hl.dsp.window.pin({{ window = {t} }})",
                          f'hl.dsp.window.float({{ action = "disable", window = {t} }})'])
        self.assertEqual(mpv_pip.leave_calls(here, None)[-1],            # by hand (SUPER+SHIFT+P): tiled
                         f'hl.dsp.window.float({{ action = "disable", window = {t} }})')
        back = mpv_pip.leave_calls(here, {"floating": True, "fullscreen": 1, "at": [100, 80], "size": [900, 500]})
        self.assertEqual(back, [f"hl.dsp.window.pin({{ window = {t} }})",
                                f"hl.dsp.window.resize({{ x = 900, y = 500, window = {t} }})",
                                f"hl.dsp.window.move({{ x = 100, y = 80, window = {t} }})",
                                f'hl.dsp.window.fullscreen({{ mode = "maximized", action = "set", window = {t} }})'])

    def test_leave_with_a_bad_record_tiles_and_keeps_text_out_of_lua(self):
        """The record is read back from a file: anything but four numbers
        is no record (tiled back), never text spliced into the Lua."""
        t = '"address:0xabc"'
        here = mpv_client(floating=True, pinned=True)
        tiled = [f"hl.dsp.window.pin({{ window = {t} }})",
                 f'hl.dsp.window.float({{ action = "disable", window = {t} }})']
        evil = "0 }) os.execute('touch /tmp/x') --"
        for record in ({"floating": True, "fullscreen": 0, "at": [0, 0], "size": [evil, 5]},
                       {"floating": True, "fullscreen": 0, "at": [0, 0], "size": [1, 2, 3]},
                       {"floating": True, "fullscreen": 0, "at": None, "size": [9, 9]},
                       {"floating": True}, "junk", ["a"]):
            calls = mpv_pip.leave_calls(here, record)
            self.assertEqual(calls, tiled, record)
            self.assertNotIn("os.execute", mpv_pip.lua(calls))
        # Numbers written as strings or floats still read, as ints.
        back = mpv_pip.leave_calls(here, {"floating": True, "fullscreen": 0, "at": ["100", 80.0], "size": [900, 500]})
        self.assertIn(f"hl.dsp.window.move({{ x = 100, y = 80, window = {t} }})", back)

    def test_lua_chunk(self):
        self.assertEqual(mpv_pip.lua(["a()", "b()"]), "hl.dispatch(a()); hl.dispatch(b())")


class Run(unittest.TestCase):
    def setUp(self):
        if os.path.exists(mpv_pip.RECORDS):
            os.remove(mpv_pip.RECORDS)
        self.client = mpv_client()
        self.evals = []

    tearDown = setUp

    def hypr_json(self, what):
        return [self.client, mpv_client(pid=1, address="0xother")] if what == "clients" else [DP1, SIDE]

    def run_cmd(self, cmd, video=None):
        return mpv_pip.run(cmd, 4242, video, hypr_json=self.hypr_json, hypr_eval=self.evals.append)

    def test_toggle_in_and_back(self):
        self.assertEqual(self.run_cmd("toggle", (1920, 1080)), "on")
        self.assertEqual(len(self.evals), 1)                       # one round trip
        self.assertIn("hl.dispatch(hl.dsp.window.pin(", self.evals[0])
        self.assertEqual(mpv_pip.load_records()["0xabc"]["floating"], False)
        self.client = mpv_client(floating=True, pinned=True, at=[2936, 1145], size=[480, 270])
        self.assertEqual(self.run_cmd("toggle"), "off")
        self.assertIn('action = "disable"', self.evals[1])
        self.assertEqual(mpv_pip.load_records(), {})

    def test_on_and_off_are_idempotent(self):
        self.assertEqual(self.run_cmd("off"), "off")
        self.client = mpv_client(floating=True, pinned=True)
        self.assertEqual(self.run_cmd("on"), "on")
        self.assertEqual(self.run_cmd("status"), "on")
        self.assertEqual(self.evals, [])

    def test_no_window(self):
        self.assertIsNone(mpv_pip.run("toggle", 999, hypr_json=self.hypr_json, hypr_eval=self.evals.append))
        self.assertEqual(self.evals, [])

    def test_records_of_closed_windows_are_dropped(self):
        mpv_pip.save_records({"0xgone": {"floating": True}, "0xabc": {"floating": False}}, [self.client])
        self.assertEqual(list(mpv_pip.load_records()), ["0xabc"])


def run_lua(test, body):
    """BODY under a stub mpv `mp` (timers on a fake clock, properties in a
    table); returns its stdout lines."""
    if not shutil.which("luajit"):
        test.skipTest("luajit not installed")
    stub = r"""
now, timers, props, osd, sent, handlers, observers, asyncs = 0, {}, {}, {}, {}, {}, {}, {}
local function timer(s, fn, every)
    local t = {at = now + s, every = every, fn = fn, alive = true}
    function t.kill(self) self.alive = false end
    timers[#timers + 1] = t
    return t
end
function advance(s)
    local stop = now + s
    while true do
        local next_t
        for _, t in ipairs(timers) do
            if t.alive and t.at <= stop and (not next_t or t.at < next_t.at) then next_t = t end
        end
        if not next_t then break end
        now = next_t.at
        if next_t.every then next_t.at = now + next_t.every else next_t.alive = false end
        next_t.fn()
    end
    now = stop
end
local function str(v) if v == nil then return nil end return tostring(v) end
mp = {
    get_time = function() return now end,
    add_timeout = function(s, fn) return timer(s, fn, nil) end,
    add_periodic_timer = function(s, fn) return timer(s, fn, s) end,
    set_property_native = function(k, v) props[k] = v end,
    set_property = function(k, v) props[k] = v end,
    set_property_bool = function(k, v) props[k] = v end,
    set_property_number = function(k, v) props[k] = v end,
    get_property = function(k, d) local v = str(props[k]) if v == nil then return d end return v end,
    get_property_bool = function(k, d) local v = props[k] if v == nil then return d end return v end,
    get_property_number = function(k) return props[k] end,
    osd_message = function(m) osd[#osd + 1] = m end,
    commandv = function(...) sent[#sent + 1] = table.concat({...}, " ") end,
    command_native = function(c) return c[2] end,
    command_native_async = function(c, cb) asyncs[#asyncs + 1] = {args = c.args, cb = cb} end,
    register_script_message = function(n, f) handlers[n] = f end,
    add_key_binding = function(_, n, f) handlers["key:" .. n] = f end,
    observe_property = function(n, _, f) observers[n] = f end,
    register_event = function() end,
}
package.preload["mp.utils"] = function() return {getpid = function() return 4242 end} end
function out(...) local t = {} for i, v in ipairs({...}) do t[i] = tostring(v) end print(table.concat(t, " ")) end
"""
    res = subprocess.run(["luajit", "-e", stub + body], capture_output=True, text=True, timeout=20)
    test.assertEqual(res.returncode, 0, res.stderr)
    return res.stdout.splitlines()


class SleepTimer(unittest.TestCase):
    LOAD = f"props['keep-open'], props['keep-open-pause'], props.pause = 'no', 'yes', false\n" \
           f"T = dofile('{SCRIPTS}/sleep-timer.lua')\n"

    def test_cycle_order(self):
        lines = run_lua(self, self.LOAD + "local m, seen = 'off', {} for i = 1, 7 do seen[i] = m m = T.next_mode(m) end\n"
                                          "out(table.concat(seen, ' '))")
        self.assertEqual(lines, ["off 15 30 60 90 eof off"])

    def test_minutes_count_down_and_pause(self):
        lines = run_lua(self, self.LOAD + """
handlers.set('sleep_timer', '30')
out(props['user-data/sleep-timer/mode'], props['user-data/sleep-timer/badge'], sent[#sent], osd[#osd]:match('^[^-]+'))
advance(61) out('after 61 s', props['user-data/sleep-timer/badge'])
advance(29 * 60) out('fired', tostring(props.pause), props['user-data/sleep-timer/mode'],
                     props['user-data/sleep-timer/badge'], osd[#osd], sent[#sent])
""")
        self.assertEqual(lines[0], "30 30 script-message-to uosc set sleep_timer 30 Sleep timer: 30 min ")
        self.assertEqual(lines[1], "after 61 s 29")
        self.assertEqual(lines[2], "fired true off 0 Sleep timer: paused script-message-to uosc set sleep_timer off")

    def test_end_of_file_borrows_keep_open_and_gives_it_back(self):
        lines = run_lua(self, self.LOAD + """
handlers.set('sleep_timer', 'eof')
out(props['keep-open'], props['keep-open-pause'], props['user-data/sleep-timer/badge'])
observers['eof-reached']('eof-reached', true)
out(tostring(props.pause), props['keep-open'], props['keep-open-pause'], props['user-data/sleep-timer/mode'])
handlers.set('sleep_timer', 'eof') handlers.set('sleep_timer', '15')
out('eof then 15', props['keep-open'])
observers['eof-reached']('eof-reached', true)
out('15 ignores eof', props['user-data/sleep-timer/mode'])
""")
        self.assertEqual(lines, ["always yes end", "true no yes off", "eof then 15 no", "15 ignores eof 15"])

    def test_off_and_junk(self):
        lines = run_lua(self, self.LOAD + """
handlers.set('sleep_timer', '60') handlers.set('sleep_timer', 'off')
advance(3700) out(tostring(props.pause), props['user-data/sleep-timer/mode'])
handlers.set('sleep_timer', '7') handlers.set('other', '15') out(props['user-data/sleep-timer/mode'])
props.pause = true handlers.set('sleep_timer', '15') advance(901) out(osd[#osd])
handlers['key:cycle']() out(props['user-data/sleep-timer/mode'])
""")
        self.assertEqual(lines, ["false off", "off", "Sleep timer: done (already paused)", "15"])


class SubTools(unittest.TestCase):
    def test_shown_flag(self):
        lines = run_lua(self, f"dofile('{SCRIPTS}/sub-tools.lua')\n" + """
local function shown() return tostring(props['user-data/sub-tools/shown']) end
observers['sid']('sid', 'auto') observers['sub-visibility']('sub-visibility', true) out(shown())
observers['sid']('sid', 1) out(shown())
observers['sub-visibility']('sub-visibility', false) out(shown())
observers['sub-visibility']('sub-visibility', true) observers['sid']('sid', false) out(shown())
""")
        self.assertEqual(lines, ["false", "true", "false", "false"])

    def test_lift_margin(self):
        lines = run_lua(self, f"S = dofile('{SCRIPTS}/sub-tools.lua')\n" + """
out(S.lift_margin(34, 0), S.lift_margin(34, nil), S.lift_margin(34, 0.1), S.lift_margin(120, 0.05))
""")
        # hidden: the resting 34; b 0.1 of the window is 72 of 720, + the 10 gap;
        # a resting margin already higher than the controls stays put
        self.assertEqual(lines, ["34 34 82 120"])

    def test_subtitles_ride_over_the_controls_and_back(self):
        lines = run_lua(self, f"props['sub-margin-y'] = 34\ndofile('{SCRIPTS}/sub-tools.lua')\n" + """
local m = observers['user-data/osc/margins']
m('user-data/osc/margins', {l = 0, r = 0, t = 0, b = 0.1}) out(props['sub-margin-y'])
m('user-data/osc/margins', {l = 0, r = 0, t = 0, b = 0}) out(props['sub-margin-y'])
props['sub-margin-y'] = 50          -- a preset moved it while the controls were hidden
m('user-data/osc/margins', {b = 0.02}) out(props['sub-margin-y'])
m('user-data/osc/margins', {b = 0}) out(props['sub-margin-y'])
m('user-data/osc/margins', nil) out(props['sub-margin-y'])
""")
        self.assertEqual(lines, ["82", "34", "50", "50", "50"])


class WindowPipLua(unittest.TestCase):
    LOAD = f"props.dwidth, props.dheight = 1920, 1080\ndofile('{SCRIPTS}/window-pip.lua')\n" \
           "local function answer(text, status) local a = table.remove(asyncs, 1)\n" \
           "    a.cb(true, {status = status or 0, stdout = text}) return a.args end\n"

    def test_from_fullscreen_and_back(self):
        lines = run_lua(self, self.LOAD + """
props.fullscreen = true
handlers.set('pip', 'yes')
out('left fullscreen first', tostring(props.fullscreen), #asyncs)
advance(0.2)
local args = answer('on\\n')
out(table.concat(args, ' ', 3), tostring(props['user-data/window-pip/on']), sent[#sent])
handlers.set('pip', 'no')
answer('off\\n')
out('back', tostring(props.fullscreen), sent[#sent])
""")
        self.assertEqual(lines[0], "left fullscreen first false 0")
        self.assertEqual(lines[1], "on 4242 1920 1080 true script-message-to uosc set pip yes")
        self.assertEqual(lines[2], "back true script-message-to uosc set pip no")

    def test_key_toggles_and_no_hyprland(self):
        lines = run_lua(self, self.LOAD + """
handlers['key:toggle']()
handlers['key:toggle']()                 -- ignored while the first is running
out(#asyncs, asyncs[1].args[3])
answer('off\\n', 1)
out(tostring(props['user-data/window-pip/on']), osd[#osd])
""")
        self.assertEqual(lines, ["1 toggle", "false Picture-in-picture needs Hyprland"])


class ControlsRow(unittest.TestCase):
    """themes/mpv-base.conf's uosc-controls, split as uosc 5.13's
    Controls:init_options splits it."""

    @classmethod
    def setUpClass(cls):
        with open(BASE) as handle:
            line = next(l for l in handle if "uosc-controls=" in l and not l.startswith("#"))
        cls.raw = line.strip()
        value = cls.raw.split("=", 1)[1]
        cls.quoted = value.startswith('"') and value.endswith('"')
        items, cur, disp, in_disp = [], "", "", False
        for c in value.strip('"').split("=", 1)[1]:
            if c == "<" and not cur:
                in_disp = True
            elif c == ">" and not cur:
                in_disp = False
            elif c == "," and not in_disp:
                items.append((disp, cur))
                cur, disp = "", ""
            elif in_disp:
                disp += c
            else:
                cur += c
        items.append((disp, cur))
        cls.items = items

    def test_quoted_for_the_badge_hash(self):
        # Unquoted, mpv's config reader would cut the row at the first '#'.
        self.assertTrue(self.quoted, "the controls line must be quoted (it holds a #badge)")

    def test_every_button_parses(self):
        want = {"command": 2, "cycle": 3, "toggle": 2}
        for _, config in self.items:
            body = re.split(r" *\? *", config)[0]
            body = re.split(r" *# *", body)[0]
            kind, *params = re.split(r" *: *", body)
            if kind in want:
                self.assertEqual(len(params), want[kind], f"{config!r}: a ':' in its command?")
                self.assertIn("?", config, f"{config!r} has no tooltip")

    def test_new_tools(self):
        configs = {c for _, c in self.items}
        disp = dict((c, d) for d, c in self.items)
        sleep = next(c for c in configs if "sleep_timer@sleep_timer" in c)
        self.assertIn("off/15!/30!/60!/90!/eof!", sleep)
        self.assertIn("#user-data/sleep-timer/badge>0", sleep)
        pip_btn = next(c for c in configs if "pip@window_pip" in c)
        self.assertTrue(pip_btn.startswith("toggle:"))
        delays = [c for c in configs if "sub-delay" in c]
        self.assertEqual(sorted(re.search(r"sub-delay (\S+)\?", c).group(1) for c in delays), ["-0.1", "0.1"])
        for c in delays:
            self.assertEqual(disp[c], "user-data/sub-tools/shown")
        # The owners named are the script files' names (mpv: '-' -> '_').
        for f in ("sleep-timer.lua", "window-pip.lua", "sub-tools.lua"):
            self.assertTrue(os.path.exists(os.path.join(SCRIPTS, f)), f)

    def test_order_ends_with_pip_then_fullscreen(self):
        self.assertEqual([c for _, c in self.items][-1], "fullscreen")
        self.assertIn("pip@window_pip", self.items[-2][1])


if __name__ == "__main__":
    unittest.main()
