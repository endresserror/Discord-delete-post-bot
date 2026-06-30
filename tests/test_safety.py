import unittest
from datetime import date, datetime, timezone
from tempfile import TemporaryDirectory
from pathlib import Path

import bot


class Author:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeMessage:
    def __init__(self, message_id: int, author_id: int) -> None:
        self.id = message_id
        self.author = Author(author_id)
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class SafetyTest(unittest.IsolatedAsyncioTestCase):
    def test_normalize_datetime_range_accepts_reversed_values(self) -> None:
        start_at, end_at = bot._normalize_datetime_range(
            "2026-06-30 18:00",
            "2026-06-30 09:00",
        )

        self.assertLess(start_at, end_at)

    def test_datetime_without_timezone_is_treated_as_jst(self) -> None:
        parsed = bot._parse_local_datetime(
            "2026-06-30 09:00",
            "start_datetime",
            is_end=False,
        )

        self.assertEqual(parsed, datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc))

    def test_end_datetime_with_minute_precision_includes_the_whole_minute(self) -> None:
        parsed = bot._parse_local_datetime(
            "2026-06-30 18:30",
            "end_datetime",
            is_end=True,
        )

        self.assertEqual(
            parsed,
            datetime(2026, 6, 30, 9, 30, 59, 999999, tzinfo=timezone.utc),
        )

    def test_confirmation_is_stronger_for_unbounded_delete(self) -> None:
        self.assertEqual(
            bot._required_confirmation(None, None),
            bot.DELETE_ALL_CONFIRMATION,
        )
        self.assertEqual(
            bot._required_confirmation(
                datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc),
                None,
            ),
            bot.DELETE_RANGE_CONFIRMATION,
        )

    def test_daily_usage_store_limits_delete_runs_per_user_per_day(self) -> None:
        with TemporaryDirectory() as directory:
            store = bot.DailyUsageStore(Path(directory) / "usage.json")
            today = date(2026, 6, 30)

            self.assertEqual(store.remaining(10, today), 3)
            self.assertEqual(store.increment(10, today), 1)
            self.assertEqual(store.increment(10, today), 2)
            self.assertEqual(store.increment(10, today), 3)
            self.assertEqual(store.remaining(10, today), 0)
            self.assertEqual(store.remaining(20, today), 3)

    async def test_final_delete_guard_skips_other_users_messages(self) -> None:
        own_message = FakeMessage(1, 10)
        other_message = FakeMessage(2, 20)

        deleted, failed = await bot._delete_messages_safely(
            [own_message, other_message],
            user_id=10,
        )

        self.assertEqual(deleted, 1)
        self.assertEqual(failed, 1)
        self.assertTrue(own_message.deleted)
        self.assertFalse(other_message.deleted)


if __name__ == "__main__":
    unittest.main()
