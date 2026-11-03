"""The battery saver (scripts/battery-saver.py, lua/batterysaver.lua and
its hooks in lua/display.lua, lua/gamemode.lua, lua/ambient.lua, and the
moving wallpaper's pause in scripts/wallpaper-slideshow.py).

Python: on / off / toggle / auto / status against a fake power_supply tree
(helpers.fake_power_supply) and the scratch runtime dir, with the power
profile, `hyprctl eval` and the notification replaced by recorders -- the
profile is a variable here, never tuned-ppd, and nothing reaches Hyprland
or mako. Covered: the profile remembered and put back (but not over one
you picked meanwhile), the reasons auto switches on for and the only case
it switches off, a declined reason staying declined until plugged in, a
desktop that never sees a write (not even the lock), the state file in the
shape the Lua side reads, the profile owed across a reboot
($XDG_STATE_HOME) and given back by the next session, "plugged in" asked
positively (an Unknown reading with the charger out changes nothing), an
unreadable profile asked twice and then left alone, and automations.py's
`on|off --why rule`.

Lua: under luajit with test_animations.py's stand-in `hl` (skipped without
luajit): the look and the animation leaves with the saver on and off,
animations.enabled never touched (it is gamemode's), scanout across
gamemode, blur and shadows off mid-game even where capture.conf keeps
them for gamemode (and back when the saver ends), settings.lua's switches
as the fallback when no theme says, ambient's calm level held off and
brought back.

Wallpaper: Motion.step() with the players, Hyprland and the power faked;
wallpaper-motion.py's React timer removed while paused and added once
again when playing (skipped without its GI typelibs)."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
import test_animations as anim

bs = helpers.import_script("battery-saver.py")
slide = helpers.import_script("wallpaper-slideshow.py")
ps = bs.power_state          # the module battery-saver.py itself imported


class World:
    """The outside world battery-saver.py touches, recorded."""

    def __init__(self, profile="balanced", eval_error=None, set_error=None):
        self.profile = profile
        self.eval_error, self.set_error = eval_error, set_error
        self.sets, self.evals, self.notes = [], [], []
        self.unreadable = 0         # this many get_profile() calls answer None first
        self.reads = 0

    def get_profile(self):
        self.reads += 1
        if self.unreadable:
            self.unreadable -= 1
            return None
        return self.profile

    def set_profile(self, name):
        self.sets.append(name)
        if self.set_error:
            return self.set_error
        self.profile = name
        return None

    def hypr_eval(self, code):
        # What the Lua side would see at this moment: the file must already say so.
        self.evals.append((code, bs.read_state()["active"]))
        return self.eval_error

    def notify(self, title, body):
        self.notes.append((title, body))

    def patches(self):
        return [mock.patch.object(bs, "get_profile", self.get_profile),
                mock.patch.object(bs, "set_profile", self.set_profile),
                mock.patch.object(bs, "hypr_eval", self.hypr_eval),
                mock.patch.object(bs, "notify", self.notify),
                mock.patch.object(bs, "gamemode", lambda: False),
                mock.patch.object(bs, "RETRY_S", 0)]


def _forget():
    """No saver state or battery settings left for the next test -- in any
    module: an active saver file would make every later frugal() say yes."""
    for path in (ps.SAVER_STATE, ps.SETTINGS_FILE, bs.owed_path(), bs.lock_path()):
        if os.path.exists(path):
            os.remove(path)
    ps.reset_cache()


class Base(unittest.TestCase):
    def setUp(self):
        _forget()
        self.addCleanup(_forget)
        self.sys = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.sys, True)
        env = mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": self.sys})
        env.start()
        self.addCleanup(env.stop)
        self.world = World()
        for p in self.world.patches():
            p.start()
            self.addCleanup(p.stop)

    def laptop(self, capacity=80, unplugged=True):
        helpers.fake_power_supply(self.sys, battery={"capacity": capacity,
                                                     "status": "Discharging" if unplugged else "Charging"},
                                  ac=not unplugged)

    def settings(self, **kw):
        ps.save_settings(kw)

    def state(self):
        with open(ps.SAVER_STATE) as handle:
            return json.load(handle)


class Manual(Base):
    def test_on_saves_the_profile_and_applies_the_look_after_writing(self):
        self.assertEqual(bs.switch_on("manual"), [])
        st = self.state()
        self.assertTrue(st["active"])
        self.assertEqual(st["why"], "manual")
        self.assertEqual(st["previous_profile"], "balanced")
        self.assertGreater(st["since"], 0)
        self.assertEqual(self.world.sets, ["power-saver"])
        self.assertEqual(self.world.evals, [(bs.LUA_APPLY, True)])
        self.assertEqual(self.world.notes, [])          # you pressed it: no need to be told
        self.assertTrue(ps.saver_active())              # the shared API agrees

    def test_off_restores_the_profile_and_the_look(self):
        bs.switch_on("manual")
        self.assertEqual(bs.switch_off(), [])
        st = self.state()
        self.assertFalse(st["active"])
        self.assertEqual((st["why"], st["since"], st["previous_profile"]), ("", 0, None))
        self.assertEqual(self.world.profile, "balanced")
        self.assertEqual(self.world.evals[-1], (bs.LUA_APPLY, False))
        self.assertFalse(ps.saver_active())

    def test_a_profile_picked_while_on_is_kept(self):
        bs.switch_on("manual")
        self.world.profile = "performance"              # you, from the Power page
        bs.switch_off()
        self.assertEqual(self.world.profile, "performance")
        self.assertEqual(self.world.sets, ["power-saver"])

    def test_already_power_saver_is_left_alone_both_ways(self):
        self.world.profile = "power-saver"
        bs.switch_on("manual")
        bs.switch_off()
        self.assertEqual(self.world.sets, [])
        self.assertEqual(self.world.profile, "power-saver")

    def test_no_profile_daemon_still_switches_the_look(self):
        # The profile cannot be read (asked twice): left alone, reported --
        # never a change the saver would not know how to undo.
        self.world.profile = None
        errors = bs.switch_on("manual")
        self.assertEqual(errors, ["power profile: could not read the current one, left alone"])
        self.assertEqual(self.world.reads, 2)
        self.assertTrue(self.state()["active"])
        self.assertIsNone(self.state()["previous_profile"])
        self.assertEqual(len(self.world.evals), 1)
        self.assertFalse(os.path.exists(bs.owed_path()))
        bs.switch_off()
        self.assertEqual(self.world.sets, [])               # nothing to put back

    def test_a_slow_first_answer_is_asked_again(self):
        self.world.unreadable = 1
        self.assertEqual(bs.switch_on("manual"), [])
        self.assertEqual(self.state()["previous_profile"], "balanced")
        self.assertEqual(self.world.sets, ["power-saver"])

    def test_a_failed_switch_owes_nothing(self):
        self.world.set_error = "denied"
        self.assertEqual(bs.switch_on("manual"), ["power profile: denied"])
        self.assertFalse(os.path.exists(bs.owed_path()))

    def test_off_that_cannot_read_the_profile_says_so(self):
        bs.switch_on("manual")
        self.world.unreadable = 2
        errors = bs.switch_off()
        self.assertEqual(errors, ["power profile: could not read the current one, balanced not put back"])
        self.assertEqual(self.world.profile, "power-saver")
        self.assertFalse(os.path.exists(bs.owed_path()))    # reported, not retried behind your back

    def test_on_twice_keeps_the_first_profile_and_manual_wins(self):
        self.laptop(15)
        bs.switch_on("auto")
        bs.switch_on("manual")
        st = self.state()
        self.assertEqual(st["why"], "manual")
        self.assertEqual(st["previous_profile"], "balanced")
        self.assertEqual(self.world.sets, ["power-saver"])

    def test_off_when_off_does_nothing(self):
        self.assertEqual(bs.switch_off(), [])
        self.assertFalse(os.path.exists(ps.SAVER_STATE))
        self.assertEqual(self.world.evals, [])

    def test_compositor_error_is_reported(self):
        self.world.eval_error = "no Hyprland"
        self.assertEqual(bs.switch_on("manual"), ["compositor: no Hyprland"])
        self.assertTrue(self.state()["active"])         # the next config load picks it up

    def test_file_shape_matches_the_lua_pattern(self):
        bs.switch_on("manual")
        with open(ps.SAVER_STATE) as handle:
            self.assertRegex(handle.read(), r'"active":\s*true')

    def test_broken_file_reads_as_off(self):
        os.makedirs(os.path.dirname(ps.SAVER_STATE), exist_ok=True)
        for text in ("{nope", "[]", '{"active": "yes", "why": "bogus", "declined": "x"}'):
            with open(ps.SAVER_STATE, "w") as handle:
                handle.write(text)
            st = bs.read_state()
            self.assertFalse(st["active"])
            self.assertEqual((st["why"], st["declined"]), ("", []))


class Owed(Base):
    """The profile the saver owes, kept across a reboot (tuned-ppd keeps the
    profile; the runtime dir does not keep previous_profile)."""

    def owed(self):
        with open(bs.owed_path()) as handle:
            return json.load(handle)

    def lose_the_session(self):
        os.remove(ps.SAVER_STATE)
        ps.reset_cache()

    def test_on_writes_it_and_off_drops_it(self):
        bs.switch_on("manual")
        self.assertEqual(self.owed(), {"previous_profile": "balanced"})
        self.assertTrue(bs.owed_path().startswith(os.path.dirname(ps.SETTINGS_FILE)))
        bs.switch_off()
        self.assertFalse(os.path.exists(bs.owed_path()))

    def test_already_power_saver_owes_nothing(self):
        self.world.profile = "power-saver"
        bs.switch_on("manual")
        self.assertFalse(os.path.exists(bs.owed_path()))

    def test_a_lost_session_gets_the_profile_back(self):
        self.laptop(15)
        bs.auto()                                           # on: auto, then the session ends
        self.lose_the_session()
        self.laptop(60, unplugged=False)                    # next boot, on the charger
        self.assertEqual(bs.recover(), [])
        self.assertEqual(self.world.profile, "balanced")
        self.assertFalse(os.path.exists(bs.owed_path()))

    def test_a_profile_you_changed_meanwhile_is_left_alone(self):
        bs.switch_on("manual")
        self.lose_the_session()
        self.world.profile = "performance"
        bs.recover()
        self.assertEqual(self.world.profile, "performance")
        self.assertEqual(self.world.sets, ["power-saver"])
        self.assertFalse(os.path.exists(bs.owed_path()))

    def test_still_held_while_the_saver_is_on(self):
        bs.switch_on("manual")
        bs.recover()
        self.assertEqual(self.world.profile, "power-saver")
        self.assertTrue(os.path.exists(bs.owed_path()))

    def test_unreadable_at_login_is_kept_for_the_next_command(self):
        bs.switch_on("manual")
        self.lose_the_session()
        self.world.unreadable = 2
        bs.recover()
        self.assertTrue(os.path.exists(bs.owed_path()))
        bs.recover()
        self.assertEqual(self.world.profile, "balanced")

    def test_power_watchs_first_auto_recovers_then_switches_on_fresh(self):
        self.laptop(15)
        bs.auto()
        self.lose_the_session()
        with mock.patch("sys.stdout"):
            self.assertEqual(bs.main(["auto"]), 0)
        st = self.state()
        self.assertTrue(st["active"])
        self.assertEqual(st["previous_profile"], "balanced")   # not power-saver
        self.assertEqual(self.world.sets, ["power-saver", "balanced", "power-saver"])

    def test_a_desktop_that_switched_it_on_by_hand_recovers_too(self):
        bs.switch_on("manual")                              # no battery here
        self.lose_the_session()
        with mock.patch("sys.stdout"):
            bs.main(["auto"])
        self.assertEqual(self.world.profile, "balanced")


class Plugged(Base):
    """'Plugged in' asked positively: an unsure reading changes nothing."""

    def test_unknown_with_the_charger_out_keeps_an_automatic_saver(self):
        self.settings(saver_on_unplug=True)
        self.laptop(15)
        bs.auto()
        bs.manual_off()                                     # declines auto and unplug
        bs.switch_on("manual")
        bs.switch_off(None)                                 # back off, declines kept
        self.assertEqual(self.state()["declined"], ["auto", "unplug"])
        helpers.fake_power_supply(self.sys, battery={"status": "Unknown"}, ac=False)
        self.assertIs(bs.plugged(), False)                  # ACAD says out; the battery is unsure
        self.assertEqual(bs.auto(), ("", []))
        self.assertEqual(self.state()["declined"], ["auto", "unplug"])

    def test_not_charging_with_acad_offline_leaves_the_saver_on(self):
        self.laptop(15)
        bs.auto()
        for status in ("Unknown", "Not charging", "Full"):
            helpers.fake_power_supply(self.sys, battery={"status": status}, ac=False)
            self.assertEqual(bs.auto(), ("", []), status)
            self.assertTrue(self.state()["active"])
        self.assertEqual(len(self.world.notes), 1)
        self.assertEqual(json.loads(json.dumps(bs.status()))["auto_would"], "")

    def test_without_a_charger_entry_the_status_decides(self):
        helpers.fake_power_supply(self.sys, battery={"capacity": 15, "status": "Discharging"})
        self.assertFalse(bs.plugged())
        self.assertEqual(bs.auto()[0], "on:auto")
        helpers.fake_power_supply(self.sys, battery={"status": "Unknown"})
        self.assertIsNone(bs.plugged())
        self.assertEqual(bs.auto(), ("", []))
        helpers.fake_power_supply(self.sys, battery={"status": "Full"})
        self.assertTrue(bs.plugged())
        self.assertEqual(bs.auto(), ("off", []))


class Rule(Base):
    """automations.py's `on|off --why rule`."""

    def run_main(self, *argv):
        with mock.patch("sys.stdout"):
            return bs.main(list(argv))

    def test_automations_sees_the_reason(self):
        auto = helpers.import_script("automations.py", "automations")
        self.assertTrue(auto.saver_takes_reason(os.path.join(helpers.SCRIPTS, "battery-saver.py")))

    def test_a_rules_on_is_undone_by_plugging_in_and_does_not_notify(self):
        self.laptop(80)
        self.assertEqual(self.run_main("on", "--why", "rule"), 0)
        self.assertEqual(self.state()["why"], "rule")
        self.assertEqual(self.world.notes, [])
        self.laptop(80, unplugged=False)
        self.assertEqual(bs.auto(), ("off", []))
        self.assertEqual(self.world.profile, "balanced")

    def test_a_rules_on_over_an_automatic_saver_keeps_it_automatic(self):
        self.laptop(15)
        bs.auto()
        self.run_main("on", "--why", "rule")
        self.assertEqual(self.state()["why"], "auto")

    def test_a_rules_on_over_a_manual_saver_keeps_it_manual(self):
        bs.switch_on("manual")
        self.run_main("on", "--why", "rule")
        self.assertEqual(self.state()["why"], "manual")

    def test_a_rules_off_on_battery_declines_nothing(self):
        self.laptop(15)
        bs.auto()
        self.assertEqual(self.run_main("off", "--why", "rule"), 0)
        self.assertEqual(self.state()["declined"], [])
        self.assertEqual(self.world.profile, "balanced")
        self.laptop(14)
        self.assertEqual(bs.auto()[0], "on:auto")           # saver_auto_at still counts

    def test_a_rules_off_keeps_what_you_declined(self):
        self.laptop(15)
        bs.auto()
        bs.manual_off()
        bs.switch_on("manual")
        self.run_main("off", "--why", "rule")
        self.assertEqual(self.state()["declined"], ["auto"])

    def test_only_on_and_off_take_a_reason(self):
        with mock.patch("sys.stderr"):
            for argv in (["toggle", "--why", "rule"], ["on", "--why", "auto"], ["on", "--why"],
                         ["auto", "--why", "rule"]):
                self.assertEqual(bs.main(argv), 2, argv)


class Auto(Base):
    def test_low_battery_switches_on_with_a_notification(self):
        self.laptop(20)
        did, errors = bs.auto()
        self.assertEqual((did, errors), ("on:auto", []))
        self.assertEqual(self.state()["why"], "auto")
        self.assertEqual(len(self.world.notes), 1)
        self.assertIn("20%", self.world.notes[0][1])

    def test_above_the_threshold_nothing_happens(self):
        self.laptop(21)
        self.assertEqual(bs.auto(), ("", []))
        self.assertFalse(os.path.exists(ps.SAVER_STATE))

    def test_zero_means_never(self):
        self.settings(saver_auto_at=0)
        self.laptop(3)
        self.assertEqual(bs.auto(), ("", []))

    def test_unplug_setting(self):
        self.settings(saver_on_unplug=True)
        self.laptop(90)
        self.assertEqual(bs.auto()[0], "on:unplug")
        self.assertIn("On battery", self.world.notes[0][1])

    def test_low_battery_is_the_stronger_reason(self):
        self.settings(saver_on_unplug=True)
        self.laptop(10)
        self.assertEqual(bs.auto()[0], "on:auto")

    def test_plugging_in_switches_an_automatic_saver_off(self):
        self.laptop(15)
        bs.auto()
        self.laptop(16, unplugged=False)
        self.assertEqual(bs.auto(), ("off", []))
        self.assertFalse(self.state()["active"])
        self.assertEqual(self.world.profile, "balanced")

    def test_plugging_in_leaves_a_manual_saver_on(self):
        self.laptop(15)
        bs.switch_on("manual")
        self.laptop(16, unplugged=False)
        self.assertEqual(bs.auto(), ("", []))
        self.assertTrue(self.state()["active"])

    def test_already_on_is_not_switched_again(self):
        self.laptop(15)
        bs.auto()
        self.laptop(14)
        self.assertEqual(bs.auto(), ("", []))
        self.assertEqual(len(self.world.notes), 1)
        self.assertEqual(self.world.sets, ["power-saver"])

    def test_off_by_hand_on_battery_is_not_undone_by_the_next_percent(self):
        self.laptop(15)
        bs.auto()
        bs.manual_off()
        self.assertEqual(self.state()["declined"], ["auto"])
        self.laptop(14)
        self.assertEqual(bs.auto(), ("", []))
        self.assertFalse(self.state()["active"])

    def test_a_new_reason_still_counts_after_declining(self):
        self.settings(saver_on_unplug=True)
        self.laptop(50)
        bs.auto()                                           # on: unplug
        bs.manual_off()                                     # declines unplug only
        self.assertEqual(self.state()["declined"], ["unplug"])
        self.laptop(20)
        self.assertEqual(bs.auto()[0], "on:auto")

    def test_plugging_in_forgets_what_was_declined(self):
        self.laptop(15)
        bs.auto()
        bs.manual_off()
        self.laptop(15, unplugged=False)
        bs.auto()
        self.assertEqual(self.state()["declined"], [])
        self.laptop(15)
        self.assertEqual(bs.auto()[0], "on:auto")

    def test_charger_in_but_firmware_still_says_discharging_is_not_on_battery(self):
        helpers.fake_power_supply(self.sys, battery={"capacity": 10, "status": "Discharging"}, ac=True)
        self.assertEqual(bs.auto(), ("", []))

    def test_a_desktop_never_writes_anything(self):
        helpers.fake_power_supply(self.sys, extra={"hidpp_battery_0": {
            "type": "Battery", "scope": "Device", "status": "Discharging", "capacity": 5}})
        self.settings(saver_on_unplug=True, saver_auto_at=99)
        self.assertEqual(bs.auto(), ("", []))
        self.assertFalse(os.path.exists(ps.SAVER_STATE))
        self.assertEqual((self.world.sets, self.world.evals, self.world.notes), ([], [], []))


class Cli(Base):
    def run_main(self, *argv):
        with mock.patch("sys.stdout") as out:
            code = bs.main(list(argv))
        text = "".join(c.args[0] for c in out.write.call_args_list)
        return code, text

    def test_status_is_json(self):
        self.laptop(15)
        code, text = self.run_main("status")
        got = json.loads(text)
        self.assertEqual(code, 0)
        self.assertEqual(got["auto_would"], "on:auto")
        self.assertEqual(got["capacity"], 15)
        self.assertTrue(got["on_battery"])
        self.assertEqual(got["settings"], {"saver_auto_at": 20, "saver_on_unplug": False})
        self.assertFalse(got["active"])
        self.assertFalse(os.path.exists(ps.SAVER_STATE))  # status never writes

    def test_toggle(self):
        code, text = self.run_main("toggle")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(text)["active"])
        code, text = self.run_main("toggle")
        self.assertFalse(json.loads(text)["active"])

    def test_errors_give_exit_1(self):
        self.world.eval_error = "nope"
        code, text = self.run_main("on")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(text)["errors"], ["compositor: nope"])

    def test_auto_says_nothing_when_nothing_happens(self):
        self.assertEqual(self.run_main("auto"), (0, ""))

    def test_auto_on_a_desktop_leaves_no_lock_file(self):
        self.assertEqual(self.run_main("auto"), (0, ""))
        self.assertFalse(os.path.exists(bs.lock_path()))
        self.assertFalse(os.path.exists(ps.SAVER_STATE))

    def test_status_says_plugged_and_owed(self):
        self.laptop(50)
        bs.switch_on("manual")
        got = json.loads(self.run_main("status")[1])
        self.assertIs(got["plugged"], False)
        self.assertEqual(got["profile_owed"], "balanced")

    def test_bad_command(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(bs.main(["sideways"]), 2)


@unittest.skipUnless(shutil.which("luajit"), "luajit not installed")
class Lua(unittest.TestCase):
    SAVER_ON = """
local f = io.open(os.getenv('XDG_RUNTIME_DIR') .. '/battery-saver.json', 'w')
f:write('{"active": true, "why": "manual", "since": 1}') f:close()
"""
    SAVER_OFF = """
local f = io.open(os.getenv('XDG_RUNTIME_DIR') .. '/battery-saver.json', 'w')
f:write('{"active": false, "why": "", "since": 0}') f:close()
"""
    NO_MPV = "package.preload['lua.mpvframe'] = function() return { apply = function() end } end\n"

    @staticmethod
    def leaves_on(anims):
        """leaf -> enabled, the last call for each."""
        out = {}
        for a in anims:
            out[a["leaf"]] = a["enabled"]
        return out

    def test_display_with_the_saver_on(self):
        got = anim.run_lua(self.SAVER_ON + """
require('lua.display')
local c = cfg_get()
emit({ blur = c.decoration.blur.enabled, shadow = c.decoration.shadow.enabled,
       anims = anims, live = hl.get_config('animations.enabled'),
       size = c.decoration.blur.size or 'nil' })
""")
        self.assertFalse(got["blur"])
        self.assertFalse(got["shadow"])
        leaves = self.leaves_on(got["anims"])
        self.assertTrue(leaves)
        self.assertFalse(any(leaves.values()))
        self.assertIn("global", leaves)
        self.assertTrue(got["live"])                    # gamemode's switch untouched

    def test_display_with_the_saver_off_is_the_preset(self):
        got = anim.run_lua(self.SAVER_OFF + """
require('lua.display')
emit({ anims = anims })
""")
        self.assertTrue(all(self.leaves_on(got["anims"]).values()))

    def test_apply_switches_off_and_on_at_runtime(self):
        got = anim.run_lua(self.NO_MPV + """
require('lua.gamemode')
local B = require('lua.batterysaver')
""" + self.SAVER_ON + """
B.apply()
local c = cfg_get()
local on = { blur = c.decoration.blur.enabled, scanout = c.render.direct_scanout }
local n = #anims
""" + self.SAVER_OFF + """
B.apply()
local after = {}
for i = n + 1, #anims do after[anims[i].leaf] = anims[i].enabled end
c = cfg_get()
emit({ on = on, off = { scanout = c.render.direct_scanout, glob = after.global } })
""")
        self.assertEqual(got["on"]["scanout"], 1)
        self.assertEqual(got["off"]["scanout"], 0)
        self.assertTrue(got["off"]["glob"])

    def test_reload_with_the_saver_on_keeps_scanout(self):
        got = anim.run_lua(self.SAVER_ON + self.NO_MPV + """
require('lua.gamemode')
emit({ scanout = cfg_get().render.direct_scanout, tearing = cfg_get().general.allow_tearing })
""")
        self.assertEqual(got, {"scanout": 1, "tearing": False})

    def test_saver_does_not_touch_gamemode(self):
        # Gamemode on, then the saver on and off: scanout stays gamemode's
        # 2, animations stay globally off, blur is not put back.
        got = anim.run_lua(self.NO_MPV + """
local G = require('lua.gamemode')
G.set(true, 'test')
local B = require('lua.batterysaver')
""" + self.SAVER_ON + """
B.apply()
""" + self.SAVER_OFF + """
local n = #configs
B.apply()
local blur = nil
for i = n + 1, #configs do
    local d = configs[i].decoration
    if d and d.blur ~= nil then blur = d.blur end
end
local c = cfg_get()
emit({ scanout = c.render.direct_scanout, anim = c.animations.enabled, blur = tostring(blur),
       on = G.is_on() })
""")
        self.assertEqual(got, {"scanout": 2, "anim": False, "blur": "nil", "on": True})

    # settings.lua's switches, as the real hl.get_config would report them
    # (the stand-in knows only animations.enabled and the shader).
    BASE_ON = """
local real_get = hl.get_config
hl.get_config = function(k)
    if k == 'decoration.blur.enabled' or k == 'decoration.shadow.enabled' then return true end
    return real_get(k)
end
"""
    KEEP_FOR_RECORDING = """
local f = io.open(os.getenv('XDG_STATE_HOME') .. '/hypr/capture.conf', 'w')
f:write('gamemode_blur=off\\ngamemode_shadow=off\\n') f:close()
"""

    def test_off_without_a_theme_puts_settings_blur_back(self):
        # No themes folder (HOME is a scratch dir): the theme says nothing,
        # so the saver going off must fall back to settings.lua's values.
        got = anim.run_lua(self.BASE_ON + self.SAVER_ON + """
local B = require('lua.batterysaver')
require('lua.display')
local c = cfg_get()
local on = { blur = c.decoration.blur.enabled, shadow = c.decoration.shadow.enabled }
""" + self.SAVER_OFF + """
B.apply()
c = cfg_get()
emit({ on = on, off = { blur = c.decoration.blur.enabled, shadow = c.decoration.shadow.enabled } })
""")
        self.assertEqual(got["on"], {"blur": False, "shadow": False})
        self.assertEqual(got["off"], {"blur": True, "shadow": True})

    def test_saver_mid_game_switches_off_blur_gamemode_kept(self):
        # capture.conf keeps blur and shadows in gamemode (for recording):
        # the saver still switches them off, and gives them back when it ends.
        got = anim.run_lua(self.BASE_ON + self.KEEP_FOR_RECORDING + self.NO_MPV + """
local G = require('lua.gamemode')
require('lua.display')
G.set(true, 'test')
local B = require('lua.batterysaver')
""" + self.SAVER_ON + """
B.apply()
local c = cfg_get()
local on = { blur = c.decoration.blur.enabled, shadow = c.decoration.shadow.enabled }
""" + self.SAVER_OFF + """
B.apply()
c = cfg_get()
emit({ on = on, off = { blur = c.decoration.blur.enabled, shadow = c.decoration.shadow.enabled },
       anim = c.animations.enabled, scanout = c.render.direct_scanout })
""")
        self.assertEqual(got["on"], {"blur": False, "shadow": False})
        self.assertEqual(got["off"], {"blur": True, "shadow": True})
        self.assertEqual((got["anim"], got["scanout"]), (False, 2))     # still gamemode's

    def test_ambient_holds_off_while_the_saver_is_on(self):
        got = anim.run_lua(self.SAVER_ON + """
local f = io.open(os.getenv('XDG_RUNTIME_DIR') .. '/ambient-anim.conf', 'w') f:write('level=2\\n') f:close()
require('lua.display')
local A = require('lua.ambient')
local n = #anims
A.apply()
local during = #anims - n
""" + self.SAVER_OFF + """
require('lua.batterysaver').apply()
local last = {}
for i = n + 1, #anims do last[anims[i].leaf] = anims[i] end
emit({ during = during, applied = A.applied, global_on = last.global.enabled,
       global_speed = last.global.speed })
""")
        self.assertEqual(got["during"], 0)
        self.assertEqual(got["applied"], 2)             # the calm level came back
        self.assertTrue(got["global_on"])
        self.assertEqual(got["global_speed"], 4)        # ambient level 2's global


class FakeProc:
    def __init__(self):
        self.signals = []

    def poll(self):
        return None

    def send_signal(self, sig):
        self.signals.append(sig)


class Wallpaper(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.dir, True)
        with open(os.path.join(self.dir, "rain.mp4"), "w") as handle:
            handle.write("x")
        self.motion = slide.Motion.__new__(slide.Motion)     # no pkill of a real player
        self.motion.procs = {}
        self.started = []
        self.why = ""
        for name, value in (("video_name", lambda: "rain.mp4"), ("motion_on", lambda: True),
                            ("gamemode", lambda: False), ("folder", lambda _o: self.dir),
                            ("frugal_why", lambda: self.why)):
            p = mock.patch.object(slide, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(slide.Motion, "unseen", staticmethod(lambda: {}))
        p.start()
        self.addCleanup(p.stop)

        def start(output, path):
            self.started.append(output)
            self.motion.procs[output] = [FakeProc(), path, False]
        self.motion.start = start

    def test_not_started_on_battery(self):
        self.why = "on battery"
        self.motion.step({"eDP-1": (False, "")})
        self.assertEqual(self.started, [])

    def test_paused_on_battery_and_played_again_on_mains(self):
        self.motion.step({"eDP-1": (False, "")})
        proc = self.motion.procs["eDP-1"][0]
        self.why = "battery saver"
        self.motion.step({"eDP-1": (False, "")})
        self.assertEqual(proc.signals, [slide.signal.SIGUSR1])
        self.motion.step({"eDP-1": (False, "")})            # no second signal
        self.why = ""
        self.motion.step({"eDP-1": (False, "")})
        self.assertEqual(proc.signals, [slide.signal.SIGUSR1, slide.signal.SIGUSR2])

    def test_unlock_on_battery_stays_paused(self):
        self.motion.step({"eDP-1": (False, "")})
        proc = self.motion.procs["eDP-1"][0]
        self.why = "on battery"
        with mock.patch.object(slide.Motion, "unseen", staticmethod(lambda: {"eDP-1": "locked"})):
            self.motion.step({"eDP-1": (False, "")})
        self.motion.step({"eDP-1": (False, "")})            # unlocked, still on battery
        self.assertEqual(proc.signals, [slide.signal.SIGUSR1])


try:
    motion = helpers.import_script("wallpaper-motion.py")
except (ImportError, ValueError):            # no Gst / GtkLayerShell typelibs here
    motion = None


@unittest.skipUnless(motion, "wallpaper-motion.py's GI libraries are not installed")
class ReactTimer(unittest.TestCase):
    """wallpaper-motion.py's React: its REACT_S timer gone while paused (a
    still frame wakes nobody), exactly one again when playing."""

    def setUp(self):
        self.live, self.next_id, self.removed = set(), 0, []

        def add(_secs, _fn):
            self.next_id += 1
            self.live.add(self.next_id)
            return self.next_id

        def remove(source):
            self.removed.append(source)
            self.live.discard(source)
        for p in (mock.patch.object(motion.GLib, "timeout_add_seconds", add),
                  mock.patch.object(motion.GLib, "source_remove", remove),
                  mock.patch.object(motion, "cpu_times", lambda: (0, 0))):
            p.start()
            self.addCleanup(p.stop)

    def test_suspend_and_resume(self):
        r = motion.React(mock.Mock(playing=True))
        self.assertEqual(self.live, {1})
        r.suspend()
        self.assertIsNone(r.source)
        self.assertEqual((self.live, self.removed), (set(), [1]))
        r.suspend()                                         # twice: nothing more
        self.assertEqual(self.removed, [1])
        r.resume()
        r.resume()                                          # twice: still one
        self.assertEqual(self.live, {2})
        self.assertEqual(r.source, 2)


class FrugalWhy(unittest.TestCase):
    def setUp(self):
        self.sys = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.sys, True)
        p = mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": self.sys})
        p.start()
        self.addCleanup(p.stop)
        if os.path.exists(ps.SAVER_STATE):
            os.remove(ps.SAVER_STATE)
        slide.power_state.reset_cache()
        self.addCleanup(slide.power_state.reset_cache)

    def test_desktop(self):
        self.assertEqual(slide.frugal_why(), "")

    def test_on_battery(self):
        helpers.fake_power_supply(self.sys, battery={"status": "Discharging"}, ac=False)
        self.assertEqual(slide.frugal_why(), "on battery")

    def test_saver(self):
        os.makedirs(os.path.dirname(ps.SAVER_STATE), exist_ok=True)
        with open(ps.SAVER_STATE, "w") as handle:
            json.dump({"active": True}, handle)
        self.addCleanup(os.remove, ps.SAVER_STATE)
        self.assertEqual(slide.frugal_why(), "battery saver")


if __name__ == "__main__":
    unittest.main()
