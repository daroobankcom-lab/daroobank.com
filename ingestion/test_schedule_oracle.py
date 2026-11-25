"""Seeded UTC-window oracle over synthetic dates; not a dispatch authorization."""
import random
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from .schedule import ScheduleError, inspect_window

UTC = timezone.utc
ZONES = ('UTC', 'Asia/Tehran', 'America/New_York', 'Europe/Amsterdam', 'Australia/Lord_Howe',
         'Pacific/Apia', 'Pacific/Kwajalein', 'Pacific/Chatham', 'Africa/Casablanca', 'Asia/Kathmandu')
DATES = (datetime(2024, 3, 10, tzinfo=UTC), datetime(2024, 11, 3, tzinfo=UTC),
         datetime(2024, 4, 7, tzinfo=UTC), datetime(2024, 10, 6, tzinfo=UTC),
         datetime(2022, 3, 21, tzinfo=UTC), datetime(2022, 9, 21, tzinfo=UTC),
         datetime(2011, 12, 30, tzinfo=UTC))


def unique_instant(day, minute, zone):
    """Independently enumerate distinct round-tripping instants for a wall boundary."""
    wall = datetime.combine(day, time(minute // 60, minute % 60))
    possible = set()
    for fold in (0, 1):
        point = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if point.astimezone(zone).replace(tzinfo=None) == wall:
            possible.add(point)
    return possible.pop() if len(possible) == 1 else None


class WindowOracleTests(SimpleTestCase):
    def test_seeded_returned_plans_are_the_earliest_eligible_utc_window(self):
        rng = random.Random(2359)
        returned = 0
        for _ in range(6000):
            zone_name = rng.choice(ZONES)
            zone = ZoneInfo(zone_name)
            instant = rng.choice(DATES) + timedelta(minutes=rng.randrange(-4320, 4321))
            start, end = rng.randrange(0, 1440, 30), rng.randrange(0, 1440, 30)
            if start == end:
                continue
            try:
                plan = inspect_window(at=instant, zone=zone_name,
                                      start=f'{start // 60:02}:{start % 60:02}',
                                      end=f'{end // 60:02}:{end % 60:02}')
            except ScheduleError:
                # A boundary may be ambiguous or nonexistent. Existing targeted
                # tests verify rejection; this oracle only checks returned plans.
                continue
            local_day = instant.astimezone(zone).date()
            eligible = []
            for delta in range(-3, 4):
                day = local_day + timedelta(days=delta)
                first = unique_instant(day, start, zone)
                last = unique_instant(day + timedelta(days=end < start), end, zone)
                if first is not None and last is not None and first < last and last > instant:
                    eligible.append((first, last))
            self.assertTrue(eligible, (zone_name, instant, start, end))
            self.assertEqual((plan.start_utc, plan.end_utc), min(eligible), (zone_name, instant, start, end))
            self.assertEqual(plan.is_open, plan.start_utc <= instant < plan.end_utc)
            self.assertFalse(plan.as_dict()['dispatch_enabled'])
            returned += 1
        # Avoid a vacuous pass if a regression starts rejecting every input.
        self.assertGreater(returned, 5500)
