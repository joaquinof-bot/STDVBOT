import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from stdvbot.bars import (
    EXCHANGE_TZ,
    Bar,
    Session,
    aggregate,
    bars_in_session,
    load_csv,
    resample,
    resample_daily,
    session_date_of,
    session_window,
)

ET = EXCHANGE_TZ


def bar(hour, minute=0, day=6, o=100.0, h=101.0, l=99.0, c=100.5, v=10, month=1):
    return Bar(datetime(2025, month, day, hour, minute, tzinfo=ET), o, h, l, c, v)


class BarTests(unittest.TestCase):
    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            Bar(datetime(2025, 1, 6, 9, 30), 1, 2, 0, 1, 1)

    def test_inverted_high_low_is_rejected(self):
        with self.assertRaises(ValueError):
            Bar(datetime(2025, 1, 6, 9, 30, tzinfo=ET), 1, 0.0, 2.0, 1, 1)

    def test_wick_and_body_geometry(self):
        b = Bar(datetime(2025, 1, 6, 9, 30, tzinfo=ET), 100.0, 105.0, 98.0, 101.0, 5)
        self.assertEqual(b.body, 1.0)
        self.assertEqual(b.range, 7.0)
        self.assertEqual(b.upper_wick, 4.0)   # 105 - max(100, 101)
        self.assertEqual(b.lower_wick, 2.0)   # min(100, 101) - 98
        self.assertTrue(b.is_bullish)


class SessionDateTests(unittest.TestCase):
    def test_evening_bar_belongs_to_the_next_session_date(self):
        self.assertEqual(session_date_of(datetime(2025, 1, 6, 20, 0, tzinfo=ET)),
                         date(2025, 1, 7))

    def test_boundary_hour_rolls_forward(self):
        self.assertEqual(session_date_of(datetime(2025, 1, 6, 18, 0, tzinfo=ET)),
                         date(2025, 1, 7))

    def test_one_minute_before_boundary_stays_put(self):
        self.assertEqual(session_date_of(datetime(2025, 1, 6, 17, 59, tzinfo=ET)),
                         date(2025, 1, 6))

    def test_morning_bar_keeps_its_calendar_date(self):
        self.assertEqual(session_date_of(datetime(2025, 1, 7, 9, 30, tzinfo=ET)),
                         date(2025, 1, 7))

    def test_asia_and_ny_share_a_session_date_in_the_right_order(self):
        asia_start, _ = session_window(Session.ASIA, date(2025, 1, 7))
        ny_start, _ = session_window(Session.NY, date(2025, 1, 7))
        self.assertLess(asia_start, ny_start)
        self.assertEqual(session_date_of(asia_start), date(2025, 1, 7))
        self.assertEqual(session_date_of(ny_start), date(2025, 1, 7))

    def test_asia_window_opens_the_previous_evening(self):
        start, end = session_window(Session.ASIA, date(2025, 1, 7))
        self.assertEqual(start, datetime(2025, 1, 6, 18, 0, tzinfo=ET))
        self.assertEqual(end, datetime(2025, 1, 6, 19, 0, tzinfo=ET))

    def test_utc_input_is_converted_before_classifying(self):
        utc_moment = datetime(2025, 1, 7, 1, 0, tzinfo=ZoneInfo("UTC"))  # 20:00 ET Jan 6
        self.assertEqual(session_date_of(utc_moment), date(2025, 1, 7))


class WindowTests(unittest.TestCase):
    def test_bars_in_session_selects_only_the_window(self):
        bars = [bar(17, 59), bar(18, 0), bar(18, 30), bar(18, 59), bar(19, 0)]
        selected = bars_in_session(bars, Session.ASIA, date(2025, 1, 7))
        self.assertEqual([b.timestamp.hour * 60 + b.timestamp.minute for b in selected],
                         [1080, 1110, 1139])  # 18:00, 18:30, 18:59 — end exclusive


class AggregateTests(unittest.TestCase):
    def test_aggregate_takes_first_open_last_close_and_extremes(self):
        bars = [
            bar(9, 30, o=100, h=102, l=99, c=101, v=5),
            bar(9, 31, o=101, h=105, l=97, c=98, v=7),
            bar(9, 32, o=98, h=103, l=98, c=102, v=3),
        ]
        merged = aggregate(bars)
        self.assertEqual((merged.open, merged.high, merged.low, merged.close), (100, 105, 97, 102))
        self.assertEqual(merged.volume, 15)

    def test_aggregate_of_nothing_is_none(self):
        self.assertIsNone(aggregate([]))


class ResampleTests(unittest.TestCase):
    def test_four_hour_buckets_anchor_on_the_session_open(self):
        bars = [
            Bar(datetime(2025, 1, 6, 18, 0, tzinfo=ET), 1, 1, 1, 1, 1),
            Bar(datetime(2025, 1, 6, 21, 59, tzinfo=ET), 2, 2, 2, 2, 1),
            Bar(datetime(2025, 1, 6, 22, 0, tzinfo=ET), 3, 3, 3, 3, 1),
            Bar(datetime(2025, 1, 7, 2, 0, tzinfo=ET), 4, 4, 4, 4, 1),
        ]
        buckets = resample(bars, 4)
        starts = [b.timestamp.hour for b in buckets]
        self.assertEqual(starts, [18, 22, 2])
        self.assertEqual(buckets[0].close, 2)  # 18:00 bucket closed by the 21:59 bar

    def test_resample_rejects_non_positive_period(self):
        with self.assertRaises(ValueError):
            resample([bar(9, 30)], 0)

    def test_daily_resample_produces_one_bar_per_session(self):
        bars = [
            Bar(datetime(2025, 1, 6, 20, 0, tzinfo=ET), 1, 5, 1, 4, 1),   # session Jan 7
            Bar(datetime(2025, 1, 7, 9, 30, tzinfo=ET), 4, 9, 2, 8, 1),   # session Jan 7
            Bar(datetime(2025, 1, 7, 20, 0, tzinfo=ET), 8, 8, 6, 7, 1),   # session Jan 8
        ]
        daily = resample_daily(bars)
        self.assertEqual(len(daily), 2)
        self.assertEqual((daily[0].open, daily[0].high, daily[0].low, daily[0].close), (1, 9, 1, 8))


class LoadCsvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "bars.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_headerless_firstrate_style_rows(self):
        self.path.write_text(
            "2025-01-06 09:30:00,100.0,101.0,99.0,100.5,120\n"
            "2025-01-06 09:31:00,100.5,102.0,100.0,101.5,80\n"
        )
        bars = load_csv(self.path)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].open, 100.0)
        self.assertEqual(bars[0].timestamp.tzinfo, ET)
        self.assertEqual(bars[1].volume, 80)

    def test_header_row_is_skipped(self):
        self.path.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2025-01-06 09:30:00,100.0,101.0,99.0,100.5,120\n"
        )
        self.assertEqual(len(load_csv(self.path)), 1)

    def test_rows_are_sorted_by_timestamp(self):
        self.path.write_text(
            "2025-01-06 09:32:00,3,3,3,3,1\n"
            "2025-01-06 09:30:00,1,1,1,1,1\n"
            "2025-01-06 09:31:00,2,2,2,2,1\n"
        )
        self.assertEqual([b.open for b in load_csv(self.path)], [1, 2, 3])

    def test_explicit_offset_is_respected(self):
        self.path.write_text("2025-01-06T14:30:00+00:00,1,1,1,1,1\n")
        loaded = load_csv(self.path)[0]
        self.assertEqual(loaded.timestamp.astimezone(ET).hour, 9)

    def test_malformed_row_names_the_line(self):
        self.path.write_text(
            "2025-01-06 09:30:00,100.0,101.0,99.0,100.5,120\n"
            "2025-01-06 09:31:00,not-a-price,1,1,1,1\n"
        )
        with self.assertRaises(ValueError) as ctx:
            load_csv(self.path)
        self.assertIn(":2:", str(ctx.exception))

    def test_blank_lines_are_ignored(self):
        self.path.write_text("2025-01-06 09:30:00,1,1,1,1,1\n\n\n")
        self.assertEqual(len(load_csv(self.path)), 1)


if __name__ == "__main__":
    unittest.main()
