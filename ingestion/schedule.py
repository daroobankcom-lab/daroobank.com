"""Offline schedule inspection. This module never dispatches or authorizes work."""
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_START = '23:00'
DEFAULT_END = '01:00'
DEFAULT_ZONE = 'Asia/Tehran'
_TIME = re.compile(r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
_ZONE = re.compile(r'^[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*$')


class ScheduleError(ValueError):
    """Invalid or unresolvable local schedule, never permission to run."""


def parse_time(value):
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise ScheduleError('ساعت باید با قالب HH:MM و ارقام انگلیسی باشد.')
    return time(int(value[:2]), int(value[3:]))


def parse_zone(value):
    if not isinstance(value, str) or len(value) > 80 or not _ZONE.fullmatch(value):
        raise ScheduleError('نام منطقه زمانی IANA معتبر نیست.')
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ScheduleError('منطقه زمانی در پایگاه زمانی این سیستم موجود نیست.') from exc


def _resolve(day, wall_time, zone):
    """Resolve exactly one UTC instant; reject both DST gaps and folds."""
    naive = datetime.combine(day, wall_time)
    instants = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        utc = candidate.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            instants.add(utc)
    if len(instants) != 1:
        raise ScheduleError('مرز پنجره در این تاریخ محلی مبهم یا ناموجود است؛ محاسبه متوقف شد.')
    return instants.pop()


@dataclass(frozen=True)
class WindowPlan:
    zone: str
    start_time: str
    end_time: str
    checked_at_utc: datetime
    start_utc: datetime
    end_utc: datetime
    is_open: bool
    crosses_midnight: bool

    def as_dict(self):
        zone = parse_zone(self.zone)
        return {
            'mode': 'inspection_only', 'dispatch_enabled': False,
            'zone': self.zone, 'start_time': self.start_time, 'end_time': self.end_time,
            'crosses_midnight': self.crosses_midnight, 'is_open': self.is_open,
            'checked_at_utc': self.checked_at_utc.isoformat(),
            'start_utc': self.start_utc.isoformat(), 'end_utc': self.end_utc.isoformat(),
            'start_local': self.start_utc.astimezone(zone).isoformat(),
            'end_local': self.end_utc.astimezone(zone).isoformat(),
        }


def inspect_window(*, at, start=DEFAULT_START, end=DEFAULT_END, zone=DEFAULT_ZONE):
    """Return the containing or next daily window, inclusive start / exclusive end.

    A window's end is on its start date for start < end, otherwise next date.
    Equal boundaries are rejected rather than interpreted as a 24-hour window.
    A timezone-aware instant is required. No database, network or scheduler access.
    """
    begin, finish, tz = parse_time(start), parse_time(end), parse_zone(zone)
    if begin == finish:
        raise ScheduleError('ساعت شروع و پایان نباید برابر باشند.')
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise ScheduleError('زمان بررسی باید دارای منطقه یا اختلاف ساعت باشد.')
    try:
        instant = at.astimezone(timezone.utc)
        local = instant.astimezone(tz)
        clock = local.timetz().replace(tzinfo=None)
        overnight = begin > finish
        if overnight:
            if clock < finish:
                day = local.date() - timedelta(days=1)
            else:
                day = local.date()
        else:
            day = local.date() + timedelta(days=1 if clock >= finish else 0)
        end_day = day + timedelta(days=1 if overnight else 0)
        start_utc, end_utc = _resolve(day, begin, tz), _resolve(end_day, finish, tz)
        if end_utc <= start_utc:
            raise ScheduleError('مرزهای پنجره ترتیب زمانی معتبر ندارند.')
        is_open = start_utc <= instant < end_utc
        if not is_open and instant >= start_utc:
            # An unexpected timezone transition must not yield an incorrect next window.
            raise ScheduleError('تطبیق زمان محلی و UTC نامعتبر است؛ محاسبه متوقف شد.')
        return WindowPlan(zone, start, end, instant, start_utc, end_utc, is_open, overnight)
    except (OverflowError, ValueError) as exc:
        if isinstance(exc, ScheduleError):
            raise
        raise ScheduleError('محاسبه تاریخ یا منطقه زمانی ممکن نیست.') from exc
