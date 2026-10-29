"""printing.py: which CUPS changes become toasts (new job, held, stopped,
ended as printed / cancelled / failed, printer trouble that starts or
clears), the words of each toast, and the bar pill (hidden, count, red,
shown only while jobs are queued).

Hermetic: snapshots are built here; no CUPS, D-Bus or notify-send call."""
import os
import unittest

import helpers

printing = helpers.import_script("printing.py")
P = printing


def job(jid, state=P.PENDING, mine=True, name="report.pdf", printer="L396", **kw):
    row = {"id": jid, "name": name, "state": state, "reasons": [], "printer": printer, "user": "me" if mine else "ana",
           "pages": 0, "kb": 12, "created": 0, "completed": 0, "mine": mine}
    row.update(kw)
    return row


def printer(state=3, reasons=(), message=""):
    return {"state": state, "reasons": list(reasons), "message": message, "accepting": True, "info": "L396"}


def snap(jobs=(), printers=None):
    return {"jobs": list(jobs), "printers": printers if printers is not None else {"L396": printer()}}


def kinds(prev, cur, gone=None):
    return [(k, item.get("id", item.get("name"))) for k, item, _ in P.changes(prev, cur, gone or {})]


class Reasons(unittest.TestCase):
    def test_suffixes_and_unknown(self):
        self.assertEqual(P.troubles(["media-empty-error", "none", "cups-waiting-for-job-completed", "paused"]),
                         [("media-empty", "Out of paper")])
        self.assertEqual(P.troubles(["marker-supply-low-warning", "marker-supply-low-report"]),
                         [("marker-supply-low", "Ink is low")])

    def test_severe(self):
        self.assertTrue(P.severe(["media-jam-error"]))
        self.assertTrue(P.severe(["media-empty"]))
        self.assertTrue(P.severe(["anything-error"]))
        self.assertFalse(P.severe(["marker-supply-low-warning"]))
        self.assertFalse(P.severe([]))

    def test_printer_of(self):
        self.assertEqual(P.printer_of("ipp://localhost/printers/L396-Series"), "L396-Series")
        self.assertEqual(P.printer_of(None), "")


class Changes(unittest.TestCase):
    def test_new_job_of_mine_only(self):
        self.assertEqual(kinds(snap(), snap([job(1), job(2, mine=False)])), [("sent", 1)])

    def test_held_and_stopped(self):
        self.assertEqual(kinds(snap([job(1)]), snap([job(1, P.HELD)])), [("held", 1)])
        self.assertEqual(kinds(snap([job(1, P.PROCESSING)]), snap([job(1, P.STOPPED)])), [("stopped", 1)])
        # no repeat while it stays held
        self.assertEqual(kinds(snap([job(1, P.HELD)]), snap([job(1, P.HELD)])), [])

    def test_sent_straight_to_hold(self):
        self.assertEqual(kinds(snap(), snap([job(1, P.HELD)])), [("held", 1)])

    def test_ended_carries_the_final_row(self):
        final = job(1, P.COMPLETED, pages=3)
        out = P.changes(snap([job(1, P.PROCESSING)]), snap(), {1: final})
        self.assertEqual(out, [("ended", job(1, P.PROCESSING), final)])
        # someone else's job leaving says nothing
        self.assertEqual(kinds(snap([job(2, mine=False)]), snap()), [])

    def test_trouble_once_until_it_clears(self):
        ok, jam = snap(), snap(printers={"L396": printer(5, ["media-jam-error"], "Clear the jam")})
        out = P.changes(ok, jam, {})
        self.assertEqual([(k, x) for k, _i, x in out], [("trouble", "Paper jam")])
        self.assertEqual(P.changes(jam, jam, {}), [])
        self.assertEqual(kinds(jam, ok), [("cleared", "L396")])
        self.assertEqual([(k, x) for k, _i, x in P.changes(ok, jam, {})], [("trouble", "Paper jam")])

    def test_a_new_printer_is_not_compared(self):
        self.assertEqual(P.changes(snap(printers={}), snap(printers={"L396": printer(5, ["media-empty-error"])}), {}),
                         [])


class Toasts(unittest.TestCase):
    def test_sent(self):
        title, body, urgency, actions = P.toast_for("sent", job(4), None)
        self.assertEqual((title, body, urgency), ("Printing “report.pdf”", "L396", "low"))
        self.assertEqual([k for k, _ in actions], ["queue", "cancel"])

    def test_ended(self):
        self.assertEqual(P.toast_for("ended", job(4), job(4, P.COMPLETED, pages=2))[:3],
                         ("Printed “report.pdf”", "L396 · 2 pages", "low"))
        self.assertEqual(P.toast_for("ended", job(4), job(4, P.COMPLETED, pages=1))[1], "L396 · 1 page")
        self.assertEqual(P.toast_for("ended", job(4), job(4, P.CANCELED))[0], "Cancelled “report.pdf”")
        title, body, urgency, _ = P.toast_for("ended", job(4), job(4, P.ABORTED, reasons=["job-canceled-at-device"]))
        self.assertEqual((title, urgency), ("Printing failed: “report.pdf”", "critical"))
        self.assertIn("job-canceled-at-device", body)
        self.assertEqual(P.toast_for("ended", job(4), None)[0], "Done: “report.pdf”")

    def test_summary(self):
        ended = [(job(i), job(i, P.CANCELED)) for i in range(4)]
        self.assertEqual(P.summary(ended)[:3], ("Cancelled 4 print jobs", "4 cancelled", "low"))
        ended.append((job(9), job(9, P.ABORTED)))
        self.assertEqual(P.summary(ended)[:3], ("5 print jobs ended", "4 cancelled · 1 failed", "critical"))

    def test_nameless_job(self):
        self.assertEqual(P.toast_for("sent", job(4, name=""), None)[0], "Printing Your document")

    def test_trouble(self):
        p = dict(printer(5, ["media-empty-error"], "Load paper"), name="L396")
        self.assertEqual(P.toast_for("trouble", p, "Out of paper")[:3], ("L396: Out of paper", "Load paper", "critical"))
        p = dict(printer(3, ["marker-supply-low-warning"]), name="L396")
        self.assertEqual(P.toast_for("trouble", p, "Ink is low")[2], "normal")


class Bar(unittest.TestCase):
    def test_hidden_when_idle(self):
        self.assertEqual(P.bar_json(snap())["text"], "")

    def test_hidden_without_jobs_even_with_trouble(self):
        self.assertEqual(P.bar_json(snap(printers={"L396": printer(5, ["media-empty-error"])}))["text"], "")

    def test_count_and_tooltip(self):
        out = P.bar_json(snap([job(1, P.PROCESSING, pages=2), job(2)]))
        self.assertEqual((out["text"], out["class"]), (" 2", "printing"))
        self.assertIn("report.pdf  —  printing · L396 · 2 pages", out["tooltip"])

    def test_held_and_error(self):
        self.assertEqual(P.bar_json(snap([job(1, P.HELD)]))["class"], "held")
        self.assertEqual(P.bar_json(snap([job(1, P.STOPPED)]))["class"], "error")
        out = P.bar_json(snap([job(1)], printers={"L396": printer(3, ["media-empty-error"])}))
        self.assertEqual((out["text"], out["class"]), ("\uf02f 1", "error"))
        self.assertIn("Out of paper", out["tooltip"])

    def test_daemon_alive(self):
        self.assertTrue(P.daemon_alive({"pid": os.getpid()}))
        self.assertFalse(P.daemon_alive({}))
        self.assertFalse(P.daemon_alive(None))


if __name__ == "__main__":
    unittest.main()
