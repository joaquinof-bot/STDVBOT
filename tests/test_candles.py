import unittest
from datetime import datetime

from stdvbot.bars import EXCHANGE_TZ, Bar
from stdvbot.candles import Direction, detect, fires

ET = EXCHANGE_TZ
T = datetime(2025, 1, 6, 9, 30, tzinfo=ET)
T2 = datetime(2025, 1, 6, 9, 31, tzinfo=ET)


def b(o, h, l, c, when=T):
    return Bar(when, o, h, l, c, 1)


def names(bars, index=-1):
    return {hit.name for hit in detect(bars, index)}


class EngulfingTests(unittest.TestCase):
    def test_bullish_engulfing_fires(self):
        prior = b(105, 106, 100, 101)          # bearish
        current = b(100, 107, 99, 106, T2)     # bullish, swallows prior body
        self.assertIn("bullish_engulfing", names([prior, current]))
        self.assertTrue(fires([prior, current], Direction.LONG))

    def test_bearish_engulfing_fires(self):
        prior = b(101, 106, 100, 105)          # bullish
        current = b(106, 107, 99, 100, T2)     # bearish, swallows prior body
        self.assertIn("bearish_engulfing", names([prior, current]))
        self.assertTrue(fires([prior, current], Direction.SHORT))

    def test_same_direction_pair_does_not_engulf(self):
        prior = b(100, 106, 99, 105)
        current = b(105, 110, 104, 109, T2)
        self.assertNotIn("bullish_engulfing", names([prior, current]))

    def test_engulfing_needs_a_prior_bar(self):
        self.assertEqual(names([b(100, 101, 99, 100.5)]) & {"bullish_engulfing"}, set())


class WickTests(unittest.TestCase):
    def test_hammer_fires_long(self):
        hammer = b(100, 100.5, 94, 100.2)  # tiny body up top, long lower wick
        self.assertIn("hammer", names([hammer]))
        self.assertTrue(fires([hammer], Direction.LONG))
        self.assertFalse(any(h.name == "hammer" for h in detect([hammer])
                             if h.direction is Direction.SHORT))

    def test_shooting_star_fires_short(self):
        star = b(100, 106, 99.8, 100.2)  # tiny body at the low, long upper wick
        self.assertIn("shooting_star", names([star]))
        self.assertTrue(fires([star], Direction.SHORT))

    def test_hammer_requires_a_small_upper_wick(self):
        # Long wicks on both sides is indecision, not a hammer.
        both = b(100, 106, 94, 100.2)
        self.assertNotIn("hammer", names([both]))

    def test_pin_bar_fires_regardless_of_body_colour(self):
        bearish_body_bullish_pin = b(100, 100.2, 94, 99.9)
        self.assertIn("bullish_pin_bar", names([bearish_body_bullish_pin]))


class DojiTests(unittest.TestCase):
    def test_doji_supports_both_directions(self):
        doji = b(100, 103, 97, 100.05)
        self.assertIn("doji", names([doji]))
        self.assertTrue(fires([doji], Direction.LONG))
        self.assertTrue(fires([doji], Direction.SHORT))


class EdgeCaseTests(unittest.TestCase):
    def test_empty_input_returns_no_hits(self):
        self.assertEqual(detect([]), [])
        self.assertFalse(fires([], Direction.LONG))

    def test_zero_range_bar_fires_nothing(self):
        flat = b(100, 100, 100, 100)
        self.assertEqual(detect([flat]), [])

    def test_index_selects_the_evaluated_bar(self):
        prior = b(105, 106, 100, 101)
        current = b(100, 107, 99, 106, T2)
        trailing = b(106, 106.1, 105.9, 106.0, T2)
        # Evaluating at index 1 sees the engulfing; the default -1 does not.
        self.assertIn("bullish_engulfing", names([prior, current, trailing], index=1))
        self.assertNotIn("bullish_engulfing", names([prior, current, trailing]))

    def test_direction_opposite(self):
        self.assertIs(Direction.LONG.opposite, Direction.SHORT)
        self.assertIs(Direction.SHORT.opposite, Direction.LONG)


if __name__ == "__main__":
    unittest.main()
