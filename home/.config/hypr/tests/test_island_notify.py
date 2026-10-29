"""Notifications in the dynamic island (scripts/island_notify.py and the
parts of island.py that use it): reading a Notify call and a `makoctl list
-j` entry, how long each urgency shows, what mako itself would have hidden
(its invisible= rules for the current modes: Do Not Disturb, its urgent
break-through, a project-focus filter, the island's own mode ignored), the
queue (one at a time, critical first, sticky ones stepping aside, hovering,
floods, replaces_id), the Railguard twin and the island's ordering.

Hermetic and pure: no bus, no makoctl, no GTK; mako configs are written to
a temporary folder."""
import os
import tempfile
import unittest

import helpers

nq = None
isl = None


def setUpModule():
    global nq, isl
    os.environ["ISLAND_DRY"] = "1"
    nq = helpers.import_script("island_notify.py")
    isl = helpers.import_script("island.py")


def tearDownModule():
    os.environ.pop("ISLAND_DRY", None)


def item(nid, urgency="normal", dur=5.0, visible=True, app="app", summary=None, **kw):
    it = {"id": nid, "app": app, "summary": summary or f"n{nid}", "body": "", "urgency": urgency,
          "actions": [], "icon": "", "data": False, "expire": -1, "dur": dur, "visible": visible}
    it.update(kw)
    return it


class Reading(unittest.TestCase):
    def test_urgency_name(self):
        self.assertEqual([nq.urgency_name(v) for v in (0, 1, 2, 3, None, "LOW", "critical", "x", True)],
                         ["low", "normal", "critical", "normal", "normal", "low", "critical", "normal",
                          "normal"])

    def test_plain_text(self):
        self.assertEqual(nq.plain_text("<b>Hi</b> &amp; <i>bye</i>"), "Hi & bye")
        self.assertEqual(nq.plain_text("a<br>b\n\n\n\nc   d"), "a\nb\n\nc d")
        self.assertEqual(nq.plain_text(None), "")

    def test_pair_actions(self):
        self.assertEqual(nq.pair_actions(["default", "Open", "x", "Do X", "odd"]),
                         [("default", "Open"), ("x", "Do X")])
        self.assertEqual(nq.pair_actions(None), [])

    def test_from_notify(self):
        it = nq.from_notify(7, "Firefox", "firefox", "<b>Done</b>", "file.zip &gt; 2 MB",
                            ["default", "Open"], {"urgency": 2, "image-path": "/tmp/x.png"}, 3000)
        self.assertEqual((it["id"], it["app"], it["summary"], it["body"], it["urgency"]),
                         (7, "Firefox", "Done", "file.zip > 2 MB", "critical"))
        self.assertEqual(it["icon"], "/tmp/x.png")                 # image-path beats app_icon
        self.assertEqual((it["expire"], it["actions"]), (3000, [("default", "Open")]))
        self.assertFalse(it["data"])
        self.assertTrue(nq.from_notify(1, "", "", "", "", [], {"image-data": True}, -1)["data"])

    def test_from_mako(self):
        it = nq.from_mako({"id": 205, "app_name": "Thunderbird", "app_icon": None, "summary": "Mail",
                           "body": "a…", "urgency": None,
                           "actions": {"default": "Activate", "mark": "Mark as Read"}})
        self.assertEqual((it["id"], it["urgency"], it["icon"], it["expire"]), (205, "normal", "", -1))
        self.assertEqual(it["actions"], [("default", "Activate"), ("mark", "Mark as Read")])

    def test_buttons_leave_out_default_and_are_short(self):
        it = item(1, actions=[("default", "Open"), ("a", "Reply"), ("b", "A very long action label here"),
                              ("c", "C"), ("d", "D"), ("e", "")])
        got = nq.buttons(it)
        self.assertEqual([k for k, _ in got], ["a", "b", "c"])
        self.assertTrue(got[1][1].endswith("…") and len(got[1][1]) == 18)


class Timing(unittest.TestCase):
    def test_per_urgency(self):
        conf = {"timeout_low": 2, "timeout_normal": 6, "timeout_critical": 0}
        self.assertEqual(nq.duration({"urgency": "low", "expire": -1}, conf), 2.0)
        self.assertEqual(nq.duration({"urgency": "normal", "expire": -1}, conf), 6.0)
        self.assertIsNone(nq.duration({"urgency": "critical", "expire": -1}, conf))
        self.assertEqual(nq.duration({"urgency": "critical", "expire": -1}, dict(conf, timeout_critical=30)),
                         30.0)

    def test_defaults_and_junk(self):
        self.assertEqual(nq.duration({"urgency": "normal", "expire": -1}, {}), 5.0)
        self.assertEqual(nq.duration({"urgency": "low", "expire": -1}, {"timeout_low": "x"}), 3.0)
        self.assertEqual(nq.duration({"urgency": "low", "expire": -1}, None), 3.0)

    def test_app_timeouts(self):
        self.assertEqual(nq.duration({"urgency": "normal", "expire": 8000}, {}), 8.0)
        self.assertEqual(nq.duration({"urgency": "normal", "expire": 100}, {}), nq.MIN_S)
        self.assertIsNone(nq.duration({"urgency": "normal", "expire": 0}, {}))
        ignore = {"ignore_app_timeouts": True}
        self.assertEqual(nq.duration({"urgency": "normal", "expire": 0}, ignore), 5.0)


MAKO = """# base
invisible=0
include={sections}
[urgency=low]
default-timeout=3000
include=~/nowhere/that/exists
"""
SECTIONS = """[mode=do-not-disturb]
invisible=1
on-notify=none

[mode=do-not-disturb urgency=critical]
invisible=0

[mode=project-focus]
invisible=1
[mode=project-focus summary~="(Atrium|atrium|ATRIUM)"]
invisible=0
[mode=project-focus app-name="Sessions"]
invisible=0

[mode=island]
invisible=1
"""


class MakoRules(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="island-mako-")
        self.sections = os.path.join(self.dir, "sections")
        with open(self.sections, "w") as fh:
            fh.write(SECTIONS)
        self.config = os.path.join(self.dir, "config")
        with open(self.config, "w") as fh:
            fh.write(MAKO.format(sections=self.sections))
        self.rules = nq.mako_rules(self.config)

    def vis(self, modes, **kw):
        return nq.mako_visible(item(1, **kw), modes, self.rules)

    def test_rules_in_order_through_includes(self):
        self.assertEqual(self.rules[0], ("", "0"))
        self.assertEqual(self.rules[1], ("mode=do-not-disturb", "1"))
        self.assertEqual(self.rules[-1], ("mode=island", "1"))
        self.assertEqual(nq.mako_rules(os.path.join(self.dir, "missing")), [])

    def test_plain_and_island_mode_show(self):
        self.assertTrue(self.vis(["default"]))
        self.assertTrue(self.vis(["default", "island"]))          # the island's own mode never counts

    def test_dnd_holds_back_but_urgent_breaks_through(self):
        self.assertFalse(self.vis(["default", "do-not-disturb", "island"]))
        self.assertTrue(self.vis(["default", "do-not-disturb", "island"], urgency="critical"))

    def test_dnd_fully_silent(self):
        # Settings > Notifications "urgent ones break through" off: generated/settings repeats it
        with open(self.config, "a") as fh:
            fh.write("[mode=do-not-disturb urgency=critical]\ninvisible=1\n")
        rules = nq.mako_rules(self.config)
        self.assertFalse(nq.mako_visible(item(1, urgency="critical"), ["do-not-disturb"], rules))

    def test_project_focus_filter(self):
        modes = ["default", "project-focus"]
        self.assertFalse(self.vis(modes, summary="build finished"))
        self.assertTrue(self.vis(modes, summary="Atrium build finished"))
        self.assertTrue(self.vis(modes, app="Sessions"))

    def test_criteria_tokens_and_unknown_criteria(self):
        self.assertEqual(nq.parse_criteria('mode=x summary~="a \\"b\\" c" grouped'),
                         [("mode", "=", "x"), ("summary", "~", 'a "b" c'), ("grouped", "=", "true")])
        # an unknown criterion matches nothing: it never hides by mistake
        self.assertTrue(nq.mako_visible(item(1), ["default"], [("frobnicate=1", "1")]))
        self.assertTrue(nq.mako_visible(item(1), ["default"], [('summary~="(unclosed"', "1")]))


class Queue(unittest.TestCase):
    def q(self, *items, now=0.0):
        queue = []
        for seq, it in enumerate(items, 1):
            nq.upsert(queue, it, now, seq)
        return queue

    def test_one_at_a_time_oldest_first(self):
        queue = self.q(item(1), item(2))
        cur, done, wake = nq.pick(queue, 0.0)
        self.assertEqual((cur["id"], done), (1, []))
        self.assertEqual(wake, nq.QUEUE_STEP_S)                     # shorter while one waits
        self.assertEqual(nq.waiting_count(queue, cur), 1)
        cur, done, wake = nq.pick(queue, nq.QUEUE_STEP_S)
        self.assertEqual((cur["id"], done), (2, [1]))               # 1 goes to the history
        self.assertEqual(wake, nq.QUEUE_STEP_S + 5.0)               # alone: its whole time
        cur, done, wake = nq.pick(queue, nq.QUEUE_STEP_S + 5.0)
        self.assertEqual((cur, done, wake), (None, [2], None))

    def test_critical_first_and_sticky(self):
        queue = self.q(item(1), item(2, "critical", dur=None))
        cur, _done, _wake = nq.pick(queue, 0.0)
        self.assertEqual(cur["id"], 2)
        # alone, it stays as long as it takes
        queue = self.q(item(3, "critical", dur=None))
        cur, done, wake = nq.pick(queue, 1000.0)
        self.assertEqual((cur["id"], done, wake), (3, [], None))

    def test_sticky_steps_aside_and_comes_back(self):
        queue = self.q(item(1, "critical", dur=None), item(2, dur=3.0))
        cur, _d, wake = nq.pick(queue, 0.0)
        self.assertEqual((cur["id"], wake), (1, nq.STICKY_HOLD_S))
        cur, done, _w = nq.pick(queue, nq.STICKY_HOLD_S)
        self.assertEqual((cur["id"], done), (2, []))                 # parked, not dismissed
        cur, done, wake = nq.pick(queue, nq.STICKY_HOLD_S + 3.0)
        self.assertEqual((cur["id"], done, wake), (1, [2], None))    # back, for good

    def test_hovering_stops_the_clock(self):
        queue = self.q(item(1, dur=2.0))
        nq.pick(queue, 0.0)
        cur, done, wake = nq.pick(queue, 50.0, hovering=True)
        self.assertEqual((cur["id"], done, wake), (1, [], None))
        nq.after_hover(cur, 50.0)
        cur, done, wake = nq.pick(queue, 50.0)
        self.assertEqual(cur["id"], 1)
        self.assertAlmostEqual(wake, 50.0 + nq.AFTER_HOVER_S)

    def test_held_back_never_shows_and_expires(self):
        queue = self.q(item(1, visible=False, dur=5.0), item(2, visible=False, dur=None))
        cur, done, wake = nq.pick(queue, 1.0)
        self.assertEqual((cur, done, wake), (None, [], 5.0))
        cur, done, wake = nq.pick(queue, 5.0)
        self.assertEqual((cur, done, wake), (None, [1], None))       # 2 stays (sticky) in mako
        self.assertEqual([it["id"] for it in queue], [2])

    def test_flood_goes_to_the_history(self):
        queue = self.q(*[item(i) for i in range(1, nq.QUEUE_MAX + 4)])
        cur, done, _wake = nq.pick(queue, 0.0)
        self.assertEqual(cur["id"], 1)
        self.assertEqual(done, [2, 3])                                # the oldest waiting
        self.assertEqual(nq.waiting_count(queue, cur), nq.QUEUE_MAX)

    def test_replaces_id_updates_in_place(self):
        queue = self.q(item(1, summary="Volume 10%"), item(2))
        nq.pick(queue, 0.0)
        self.assertFalse(nq.upsert(queue, item(1, summary="Volume 20%"), 3.0, 99))
        self.assertEqual(len(queue), 2)
        cur, _done, _wake = nq.pick(queue, 3.0)
        self.assertEqual((cur["id"], cur["summary"], cur["seq"]), (1, "Volume 20%", 1))
        self.assertEqual(cur["shown_at"], 3.0)                        # its clock starts again
        self.assertTrue(nq.upsert(queue, item(3), 3.0, 100))

    def test_remove(self):
        queue = self.q(item(1), item(2))
        self.assertTrue(nq.remove(queue, 1))
        self.assertFalse(nq.remove(queue, 1))
        self.assertEqual([it["id"] for it in queue], [2])


class Twins(unittest.TestCase):
    def test_railguard_alert_then_notification(self):
        alert = {"title": "Railguard: memory is running out", "at": 10.0}
        rg = item(5, "critical", app="Railguard", summary="Railguard: memory is running out")
        self.assertTrue(nq.is_railguard_twin(rg, alert, 12.0))
        self.assertFalse(nq.is_railguard_twin(rg, alert, 10.0 + nq.RAILGUARD_TWIN_S + 1))
        self.assertFalse(nq.is_railguard_twin(dict(rg, app="Other"), alert, 12.0))
        self.assertFalse(nq.is_railguard_twin(rg, None, 12.0))

    def test_notification_then_railguard_alert(self):
        queue = []
        nq.upsert(queue, item(5, app="Railguard", summary="Railguard: panic"), 1.0, 1)
        self.assertEqual(nq.railguard_twin(queue, "Railguard: panic", 2.0)["id"], 5)
        self.assertIsNone(nq.railguard_twin(queue, "Railguard: other", 2.0))
        self.assertIsNone(nq.railguard_twin(queue, "Railguard: panic", 100.0))


class IslandSide(unittest.TestCase):
    def test_notifications_on_by_default(self):
        self.assertIs(isl.DEFAULTS["notifications"], True)

    def test_a_notification_leads_a_compact_activity(self):
        vis = {"record": {"src": "record", "ongoing": True, "expand": False},
               "notify": {"src": "notify", "nid": 4}}
        self.assertEqual(isl.lead(vis), ["notify", "record"])
        vis["record"]["expand"] = True                            # a new recording keeps its turn
        self.assertEqual(isl.lead(vis), ["record", "notify"])
        legacy = {"railguard": {"src": "railguard"}, "notify": {"src": "notify"}}
        self.assertEqual(isl.lead(legacy), ["railguard", "notify"])

    def test_critical_drops_below_the_bar(self):
        self.assertTrue(isl.drops({"src": "notify", "urgency": "critical"}))
        self.assertFalse(isl.drops({"src": "notify", "urgency": "normal"}))

    def test_notify_act_and_describe(self):
        it = item(9, "critical", dur=None, app="Mail", summary="New mail", body="hello",
                  actions=[("default", "Open"), ("read", "Mark read")])
        act = isl.notify_act(it, 2)
        self.assertEqual((act["nid"], act["key"], act["expand"], act["ongoing"], act["until"]),
                         (9, 9, True, False, None))
        v = isl.describe(dict(act, src="notify"), 0)
        self.assertEqual((v["title"], v["app"], v["sub"], v["count"]), ("New mail", "Mail", "hello", "+2"))
        self.assertEqual(v["text"], "Mail · New mail")
        self.assertIn("island-notify-critical", v["extra_cls"])
        self.assertEqual(v["glyph"], isl.CRITICAL_ICON)
        self.assertEqual([b[0] for b in v["buttons"]], ["notif-action:read", "notif-dismiss"])
        self.assertTrue(v["body"])

    def test_notify_image(self):
        self.assertEqual(isl.notify_image({"data": True, "nid": 3}), ("nid", 3))
        self.assertEqual(isl.notify_image({"icon": "firefox"}), ("icon", "firefox"))
        self.assertIsNone(isl.notify_image({"icon": "/no/such/file.png"}))
        self.assertIsNone(isl.notify_image({"icon": ""}))
        with tempfile.NamedTemporaryFile(suffix=".png") as fh:
            self.assertEqual(isl.notify_image({"icon": fh.name}), ("art", fh.name))
            self.assertEqual(isl.notify_image({"icon": "file://" + fh.name}), ("art", fh.name))

    def test_mascot_on_every_card(self):
        on = {"icon": True, "toasts": False}
        firefox = ("icon", "firefox")
        self.assertEqual(isl.notify_mascot({"urgency": "normal"}, firefox, on),
                         ("mascot", ("calm", firefox)))
        self.assertEqual(isl.notify_mascot({"urgency": "critical"}, None, on), ("mascot", ("alert", None)))
        self.assertEqual(isl.notify_mascot({"mood": "relieved"}, ("nid", 4), on),
                         ("mascot", ("relieved", ("nid", 4))))
        # generic icons go: the mood says the same
        self.assertEqual(isl.notify_mascot({}, ("icon", "dialog-warning"), on), ("mascot", ("calm", None)))
        # left alone: switched off, a toast with toasts off, already the mascot
        self.assertIsNone(isl.notify_mascot({}, firefox, {"icon": False}))
        self.assertIsNone(isl.notify_mascot({"urgency": "low"}, firefox, on))
        self.assertIsNotNone(isl.notify_mascot({"urgency": "low"}, firefox, dict(on, toasts=True)))
        import mascot_icons
        own = ("art", os.path.join(mascot_icons.CACHE, "moe-calm-0.png"))
        self.assertIsNone(isl.notify_mascot({}, own, on))
        v = isl.describe(dict(isl.notify_act(item(5, "normal", app="Mail", summary="Hi"), 0),
                              src="notify", icon="firefox"), 0)
        self.assertEqual(v["image"][0] == "mascot", isl.mascot_prefs()["icon"])

    def test_mako_mode_is_never_touched_dry(self):
        self.assertFalse(isl.set_mako_mode(True))
        self.assertFalse(isl.set_mako_mode(False))

    def test_sd_notify_outside_a_service(self):
        old = os.environ.pop("NOTIFY_SOCKET", None)
        try:
            self.assertFalse(isl.sd_notify("WATCHDOG=1"))
        finally:
            if old is not None:
                os.environ["NOTIFY_SOCKET"] = old


class ReviewFixes(unittest.TestCase):
    """Mode changes after arrival, category / desktop-entry rules, the
    hover grace while others wait."""

    DND = [("mode=do-not-disturb", "1"), ("mode=do-not-disturb urgency=critical", "1"),
           ("mode=island", "1")]

    def test_dnd_ends_and_the_held_sticky_one_shows(self):
        queue = []
        nq.upsert(queue, item(1, "critical", dur=None, visible=False), 0.0, 1)
        self.assertEqual(nq.pick(queue, 1.0)[0], None)
        self.assertTrue(nq.revisit(queue, ["default", "island"], self.DND))
        cur, _done, _wake = nq.pick(queue, 2.0)
        self.assertEqual((cur["id"], cur["shown_at"]), (1, 2.0))
        self.assertFalse(nq.revisit(queue, ["default", "island"], self.DND))   # nothing new

    def test_dnd_starts_and_the_queue_is_held(self):
        queue = []
        nq.upsert(queue, item(1, dur=5.0), 0.0, 1)
        nq.pick(queue, 0.0)
        self.assertTrue(nq.revisit(queue, ["default", "do-not-disturb", "island"], self.DND))
        cur, done, wake = nq.pick(queue, 1.0)
        self.assertEqual((cur, done, wake), (None, [], 5.0))          # held, then to the history

    def test_category_and_desktop_entry_rules(self):
        it = nq.from_notify(3, "Firefox", "", "Download", "", [],
                            {"category": "transfer.complete", "desktop-entry": "firefox"}, -1)
        self.assertEqual((it["category"], it["desktop_entry"]), ("transfer.complete", "firefox"))
        self.assertFalse(nq.mako_visible(it, ["default"], [("category=transfer.complete", "1")]))
        self.assertFalse(nq.mako_visible(it, ["default"], [("desktop-entry=firefox", "1")]))
        m = nq.from_mako({"id": 4, "category": "im", "desktop_entry": "signal"})
        self.assertEqual((m["category"], m["desktop_entry"]), ("im", "signal"))

    def test_hover_grace_while_others_wait(self):
        queue = []
        nq.upsert(queue, item(1, dur=10.0), 0.0, 1)
        nq.upsert(queue, item(2), 0.0, 2)
        cur, _d, _w = nq.pick(queue, 0.0)
        nq.after_hover(cur, 50.0, waiting=nq.waiting_count(queue, cur) > 0)
        cur, done, wake = nq.pick(queue, 50.0)
        self.assertEqual((cur["id"], done), (1, []))                  # not gone at once
        self.assertAlmostEqual(wake, 50.0 + nq.AFTER_HOVER_S)


class NotificationsPageNote(unittest.TestCase):
    """Settings > Notifications says when the island has the popups."""

    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from settings_pages import notifications as page
        except Exception as exc:                                    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.notifications not importable: {exc}")
        cls.page = page

    def test_island_takes_popups(self):
        f = self.page.island_takes_popups
        self.assertTrue(f({"enabled": True}))                        # notifications: on by default
        self.assertTrue(f({"enabled": True, "notifications": True}))
        self.assertFalse(f({"enabled": True, "notifications": False}))
        self.assertFalse(f({"enabled": False, "notifications": True}))
        self.assertFalse(f(None))
        self.assertEqual(self.page.island_note({}), "")
        self.assertIn("island", self.page.island_note({"enabled": True}))


if __name__ == "__main__":
    unittest.main()
