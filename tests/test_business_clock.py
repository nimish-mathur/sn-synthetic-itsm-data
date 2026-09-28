import datetime as dt

import pytest

from sn_synth.calendar import BusinessClock, NGICalendar, add_calendar, elapsed_seconds, to_sn
from sn_synth.config import load_config


@pytest.fixture(scope="module")
def cal():
    return NGICalendar(load_config(today=dt.date(2026, 9, 27)))


@pytest.fixture(scope="module")
def clock(cal):
    return BusinessClock(cal, {"start": "08:00", "end": "18:00"})


def at(cal, y, m, d, h, mi=0):
    return cal.local(dt.date(y, m, d), h * 3600 + mi * 60)


def test_friday_evening_rolls_to_monday(cal, clock):
    # Fri 2025-10-10 17:00 + 2 business hours -> Mon 2025-10-13 09:00
    assert clock.add(at(cal, 2025, 10, 10, 17), 7200) == at(cal, 2025, 10, 13, 9)


def test_public_holiday_is_skipped(cal, clock):
    # Fri 2025-07-11 17:00 + 2 h; Mon 14 July is Bastille Day -> Tue 15 July 09:00
    assert clock.add(at(cal, 2025, 7, 11, 17), 7200) == at(cal, 2025, 7, 15, 9)


def test_start_outside_hours(cal, clock):
    # Tue 2025-09-02 20:00 + 1 h -> Wed 09:00
    assert clock.add(at(cal, 2025, 9, 2, 20), 3600) == at(cal, 2025, 9, 3, 9)


def test_between_matches_add(cal, clock):
    start = at(cal, 2025, 12, 23, 15, 30)
    end = clock.add(start, 5 * 3600)
    assert clock.between(start, end) == 5 * 3600


def test_calendar_add_across_clock_change(cal):
    # 26 Oct 2025: clocks go back one hour. 24 real hours after Sat 12:00 is Sun 11:00 local.
    start = at(cal, 2025, 10, 25, 12)
    assert add_calendar(start, 86400) == at(cal, 2025, 10, 26, 11)
    assert elapsed_seconds(start, at(cal, 2025, 10, 26, 12)) == 90000


def test_to_sn_is_utc(cal):
    assert to_sn(at(cal, 2026, 3, 9, 9)) == "2026-03-09 08:00:00"
