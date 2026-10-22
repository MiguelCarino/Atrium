"""scripts/notify-digest.py: which notifications count as missed, the plain
(no model) digest, the mark, and the fall back to plain counts when the
model cannot run. Hermetic: mako is never asked (the notifications module's
all_entries is stubbed), the mark lives in helpers.py's scratch runtime dir,
no model is loaded (llm-worker's ready is stubbed) and nothing is shown."""
import json
import os
import unittest

import helpers

D = helpers.import_script("notify-digest.py", "notify_digest")


def note(nid, app="Slack", summary="hi", body="", urgency="normal", source="history"):
    return {"id": nid, "app_name": app, "summary": summary, "body": body, "urgency": urgency, "source": source}


class Missed(unittest.TestCase):
    def test_after_the_mark_without_toasts_or_ours(self):
        items = [note(5), note(6, urgency="low"), note(7, app="Digest"), note(8, app="Mail"), note(3)]
        self.assertEqual([n["id"] for n in D.missed(items, 4)], [5, 8])

    def test_mako_restarted_means_all_of_them(self):
        self.assertEqual([n["id"] for n in D.missed([note(1), note(2)], 40)], [1, 2])

    def test_groups_busiest_first(self):
        items = [note(1, app="Mail"), note(2), note(3), note(4, app="")]
        self.assertEqual([(a, len(ns)) for a, ns in D.groups(items)], [("Slack", 2), ("Mail", 1), ("Unknown", 1)])


class Plain(unittest.TestCase):
    def test_few_are_listed_as_they_are(self):
        text = D.plain([note(1, summary="Build failed", body="main", urgency="critical")])
        self.assertEqual(text, "Slack: Build failed — main (urgent)")

    def test_many_are_counted_and_urgent_named_once(self):
        items = [note(i) for i in range(12)] + [note(20 + i, app="Mail") for i in range(3)]
        items += [note(40, app="FUMonitor", summary="Failed unit", urgency="critical")] * 2
        text = D.plain(items)
        self.assertTrue(text.startswith("Slack 12, Mail 3, FUMonitor 2"))
        self.assertEqual(text.count("Failed unit"), 1)

    def test_title_and_span(self):
        self.assertEqual(D.span(130 * 60), "2 h 10 min")
        self.assertEqual(D.span(20), "1 min")
        self.assertEqual(D.title([note(1)] * 3, 600, True),
                         "While Do Not Disturb was on (10 min): at least 3 notifications")


class Model(unittest.TestCase):
    def setUp(self):
        self.worker = D._module("llm_worker", "llm-worker.py")
        self.saved = (self.worker.ready, self.worker.ask)
        self.addCleanup(lambda: (setattr(self.worker, "ready", self.saved[0]),
                                 setattr(self.worker, "ask", self.saved[1])))

    def test_falls_back_to_counts_when_the_model_cannot_run(self):
        self.worker.ready = lambda role="worker": (None, "gamemode is on")
        body, how = D.digest([note(i) for i in range(6)])
        self.assertEqual((body, how), ("Slack 6", "plain"))

    def test_uses_the_worker_role_and_its_answer(self):
        seen = {}

        class M:
            name = "tiny"
        self.worker.ready = lambda role="worker": (seen.setdefault("role", role), M)[1:] + (None,)
        self.worker.ask = lambda model, prompt, system=None, extra=None: "**Slack**: 6 pings"
        body, how = D.digest([note(i, urgency="critical" if i == 0 else "normal") for i in range(6)])
        self.assertEqual((body, how, seen["role"]), ("Slack: 6 pings", "model", "worker"))

    def test_few_never_wake_the_model(self):
        self.worker.ready = lambda role="worker": self.fail("must not load a model for two notifications")
        self.assertEqual(D.digest([note(1), note(2)])[1], "plain")

    def test_prompt_flags_critical(self):
        self.assertIn("[Slack] [critical] boom", D.prompt_for([note(1, summary="boom", urgency="critical")]))


class Mark(unittest.TestCase):
    def setUp(self):
        n = D.notifications()
        self.saved = n.all_entries
        n.all_entries = lambda: [note(9), note(12, source="shown")]
        self.addCleanup(lambda: setattr(n, "all_entries", self.saved))
        D.clear_mark()
        self.addCleanup(D.clear_mark)

    def test_mark_is_the_newest_id_and_fresh_false_keeps_it(self):
        D.mark()
        self.assertEqual(D.read_mark()["from_id"], 12)
        with open(D.MARK, "w") as handle:
            json.dump({"from_id": 3, "since": 0}, handle)
        D.mark(fresh=False)
        self.assertEqual(D.read_mark()["from_id"], 3)
        D.mark()
        self.assertEqual(D.read_mark()["from_id"], 12)
        self.assertTrue(D.MARK.startswith(os.environ["XDG_RUNTIME_DIR"]))


if __name__ == "__main__":
    unittest.main()
