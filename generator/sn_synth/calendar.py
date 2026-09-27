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
        naive = dt.datetime.combine(day, dt.time()) + dt.timedelta(seconds=seconds_after_midnight)
        return naive.replace(tzinfo=self.tz)


def to_sn(value: dt.datetime) -> str:
    """Aware datetime -> ServiceNow UTC string 'YYYY-MM-DD HH:MM:SS'."""
    return value.astimezone(UTC).strftime(SN_FORMAT)


def hhmm_to_seconds(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 3600 + int(m) * 60
