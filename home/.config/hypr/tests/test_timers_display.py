import datetime
import unittest

import helpers

timers = helpers.import_script("timers.py", "timers")
display = helpers.import_script("display.py", "display")


class Durations(unittest.TestCase):
    def test_forms(self):
        cases = {"5": (300, ""), "1h 30m tea": (5400, "tea"), "90s": (90, ""), "1h30m": (5400, ""),
                 "2.5h": (9000, ""), "5 min pasta": (300, "pasta"), "1:30:00": (5400, ""),
                 "10:00 x": (600, "x"), "1 hour and 5 minutes": (3900, "")}
        for text, want in cases.items():
            self.assertEqual(timers.parse_duration(text), want, text)

    def test_not_a_duration(self):
        self.assertEqual(timers.parse_duration("tea"), (None, "tea"))
        self.assertEqual(timers.parse_duration(""), (None, ""))


class Clock(unittest.TestCase):
    def test_parse_hm(self):
        self.assertEqual(timers.parse_hm("7:30 wake"), ((7, 30), "wake"))
        self.assertEqual(timers.parse_hm("7pm"), ((19, 0), ""))
        self.assertEqual(timers.parse_hm("12am"), ((0, 0), ""))
        self.assertEqual(timers.parse_hm("19:45"), ((19, 45), ""))
        self.assertEqual(timers.parse_hm("7"), (None, "7"))          # a bare number is a duration
        self.assertEqual(timers.parse_hm("25:00"), (None, "25:00"))

    def test_next_at(self):
        now = datetime.datetime(2026, 10, 20, 10, 0)                # a Tuesday
        self.assertEqual(timers.next_at((9, 0), now=now), datetime.datetime(2026, 10, 21, 9, 0))
        self.assertEqual(timers.next_at((11, 0), now=now), datetime.datetime(2026, 10, 20, 11, 0))
        self.assertEqual(timers.next_at((9, 0), days=(5, 6), now=now), datetime.datetime(2026, 10, 24, 9, 0))


class Repeats(unittest.TestCase):
    def test_phrases(self):
        self.assertEqual(timers.parse_repeat("weekdays tea"), ((0, 1, 2, 3, 4), "tea"))
        self.assertEqual(timers.parse_repeat("every day"), (tuple(range(7)), ""))
        self.assertEqual(timers.parse_repeat("mon wed fri gym")[0], (0, 2, 4))
        self.assertEqual(timers.parse_repeat("tea"), (None, "tea"))

    def test_then(self):
        self.assertEqual(timers.parse_then("pasta then suspend"), ("pasta", "suspend"))
        self.assertEqual(timers.parse_then("x then !notify-send hi"), ("x", "!notify-send hi"))
        self.assertEqual(timers.parse_then("then what"), ("then what", None))

    def test_words(self):
        self.assertEqual(timers.clock(65), "1:05")
        self.assertEqual(timers.clock(3723), "1:02:03")
        self.assertEqual(timers.span(5400), "1 h 30 min")
        self.assertEqual(timers.span(0), "0 s")
        self.assertEqual(timers.days_text((5, 6)), "weekends")
        self.assertEqual(timers.fold("Miércoles"), "miercoles")


class Rates(unittest.TestCase):
    MON = {"width": 2560, "height": 1080, "refreshRate": 144.00101,
           "availableModes": ["2560x1080@59.94Hz", "2560x1080@144.00Hz", "2560x1080@119.88Hz",
                              "1920x1080@60.00Hz", "2560x1080@120.00Hz"]}

    def test_rates_at_current_resolution(self):
        self.assertEqual(display.rates(self.MON), ["144.00", "120.00", "119.88", "59.94"])

    def test_current_rate_is_nearest_offered(self):
        self.assertEqual(display.current_rate(self.MON), "144.00")

    def test_hz_label(self):
        self.assertEqual(display.hz_label("144.00"), "144")
        self.assertEqual(display.hz_label("119.88"), "119.88")
        self.assertEqual(display.hz_label("59.90"), "59.9")


if __name__ == "__main__":
    unittest.main()
