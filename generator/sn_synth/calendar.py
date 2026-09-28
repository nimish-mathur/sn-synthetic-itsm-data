"""Local-time helpers: Europe/Paris clock, French public holidays, UTC conversion."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import holidays

UTC = ZoneInfo("UTC")
SN_FORMAT = "%Y-%m-%d %H:%M:%S"     # ServiceNow internal date-time format (always UTC)


class NGICalendar:
    def __init__(self, cfg: dict) -> None:
        self.tz = ZoneInfo(cfg["time"]["local_timezone"])
        start, end = cfg["time"]["start_date"], cfg["time"]["end_date"]
        country = cfg["sla"]["schedule"]["holidays"]
        self.holidays = holidays.country_holidays(country, years=range(start.year, end.year + 2))

    def is_holiday(self, day: dt.date) -> bool:
        return day in self.holidays

    def is_business_day(self, day: dt.date) -> bool:
        return day.weekday() < 5 and not self.is_holiday(day)

    def local(self, day: dt.date, seconds_after_midnight: float) -> dt.datetime:
        """Aware local datetime for a day plus an offset in seconds."""
        # Whole seconds only: ServiceNow stores seconds, so durations must match the stored values.
        naive = dt.datetime.combine(day, dt.time()) + dt.timedelta(seconds=round(seconds_after_midnight))
        return naive.replace(tzinfo=self.tz)


def to_sn(value: dt.datetime) -> str:
    """Aware datetime -> ServiceNow UTC string 'YYYY-MM-DD HH:MM:SS'."""
    return value.astimezone(UTC).strftime(SN_FORMAT)


def hhmm_to_seconds(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 3600 + int(m) * 60


# --- Time arithmetic ----------------------------------------------------------
# Calendar time is measured in real elapsed seconds (via UTC, so the clock changes
# in March/October are handled correctly). Business time counts only NGI working
# hours: Mon–Fri 08:00–18:00 Europe/Paris, excluding French public holidays.

def elapsed_seconds(a: dt.datetime, b: dt.datetime) -> int:
    """Real seconds from a to b. (Subtracting two aware datetimes that share a tzinfo
    object ignores DST offsets in Python, so we always go through UTC.)"""
    return int((b.astimezone(UTC) - a.astimezone(UTC)).total_seconds())


def add_calendar(start: dt.datetime, seconds: float) -> dt.datetime:
    return (start.astimezone(UTC) + dt.timedelta(seconds=round(seconds))).astimezone(start.tzinfo)


class BusinessClock:
    def __init__(self, cal: NGICalendar, schedule: dict) -> None:
        self.cal = cal
        self.open_s = hhmm_to_seconds(schedule["start"])
        self.close_s = hhmm_to_seconds(schedule["end"])

    def _window(self, day: dt.date) -> tuple[dt.datetime, dt.datetime] | None:
        if not self.cal.is_business_day(day):
            return None
        return self.cal.local(day, self.open_s), self.cal.local(day, self.close_s)

    def add(self, start: dt.datetime, seconds: float) -> dt.datetime:
        """Moment when `seconds` of business time have elapsed after `start`."""
        current, remaining = start.astimezone(self.cal.tz), float(seconds)
        day = current.date()
        while True:
            window = self._window(day)
            if window:
                w_open, w_close = window
                if current < w_open:
                    current = w_open
                if current < w_close:
                    available = elapsed_seconds(current, w_close)
                    if remaining <= available:
                        return add_calendar(current, remaining)
                    remaining -= available
            day += dt.timedelta(days=1)
            current = self.cal.local(day, 0)

    def between(self, a: dt.datetime, b: dt.datetime) -> int:
        """Business seconds between a and b (0 if b <= a)."""
        if b <= a:
            return 0
        total, day = 0, a.astimezone(self.cal.tz).date()
        last = b.astimezone(self.cal.tz).date()
        while day <= last:
            window = self._window(day)
            if window:
                lo, hi = max(window[0], a), min(window[1], b)
                if hi > lo:
                    total += elapsed_seconds(lo, hi)
            day += dt.timedelta(days=1)
        return total

    def add_in_clock(self, start: dt.datetime, seconds: float, clock: str) -> dt.datetime:
        return add_calendar(start, seconds) if clock == "24x7" else self.add(start, seconds)
