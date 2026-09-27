import datetime as dt
from collections import Counter

import pytest

from sn_synth.calendar import NGICalendar, to_sn
from sn_synth.config import load_config
from sn_synth.ids import sys_id
from sn_synth.incidents import ERP_CHANGE_KEY, generate_arrivals, monthly_counts
from sn_synth.reference import build_reference

TODAY = dt.date(2026, 9, 27)


@pytest.fixture(scope="module")
def cfg():
    return load_config(today=TODAY)


@pytest.fixture(scope="module")
def drafts(cfg):
    return generate_arrivals(cfg, build_reference(cfg))


@pytest.fixture(scope="module")
def base(drafts):
    return [d for d in drafts if not d.story]


def test_utc_conversion_summer_and_winter(cfg):
    cal = NGICalendar(cfg)
    assert to_sn(cal.local(dt.date(2025, 7, 1), 9 * 3600)) == "2025-07-01 07:00:00"   # CEST = UTC+2
    assert to_sn(cal.local(dt.date(2026, 1, 15), 9 * 3600)) == "2026-01-15 08:00:00"  # CET = UTC+1


def test_window_and_order(cfg, drafts):
    assert all(cfg["time"]["start_date"] <= d.opened_local.date() < TODAY for d in drafts)
    assert [d.opened_local for d in drafts] == sorted(d.opened_local for d in drafts)


def test_deterministic(cfg, drafts):
    again = generate_arrivals(cfg, build_reference(cfg))
    assert [d.record for d in again] == [d.record for d in drafts]


def test_sys_ids_unique(drafts):
    ids = [d.record["sys_id"] for d in drafts]
    assert len(ids) == len(set(ids))


def test_typical_month_near_target(drafts):
    counts = monthly_counts(drafts)
    for month in ["2025-07", "2025-10", "2026-04", "2026-07"]:
        assert 1250 <= counts[month] <= 1550, month


def test_august_dip(drafts):
    counts = monthly_counts(drafts)
    ratio = counts["2025-08"] / ((counts["2025-07"] + counts["2025-09"]) / 2)
    assert 0.60 <= ratio <= 0.80


def test_weekdays_busier_than_weekends(base):
    by_day = Counter(d.opened_local.weekday() for d in base)
    assert min(by_day[i] for i in range(5)) > 2 * max(by_day[5], by_day[6])


def test_business_hours_share(cfg, base):
    cal = NGICalendar(cfg)
    working = [d for d in base if cal.is_business_day(d.opened_local.date())]
    in_hours = sum(8 <= d.opened_local.hour < 18 for d in working) / len(working)
    assert in_hours == pytest.approx(cfg["incidents"]["business_hours_share"], abs=0.02)


def test_priority_mix(cfg, base):
    counts = Counter(d.record["priority"] for d in base)
    for prio, share in cfg["incidents"]["priority_mix"].items():
        assert counts[str(prio)] / len(base) == pytest.approx(share, abs=0.01)


def test_impact_urgency_consistent_with_priority(cfg, drafts):
    matrix = cfg["incidents"]["priority_matrix"]
    for d in drafts:
        rec = d.record
        assert str(matrix[f"{rec['impact']},{rec['urgency']}"]) == rec["priority"]


def test_categories_valid(cfg, drafts):
    allowed = set(cfg["instance_facts"]["incident_categories"]) | {"", cfg["data_quality_defects"]["legacy_category"]["value"]}
    assert {d.record["category"] for d in drafts} <= allowed


def test_legacy_category_only_before_cutoff(cfg, drafts):
    legacy = cfg["data_quality_defects"]["legacy_category"]
    dates = [d.opened_local.date() for d in drafts if d.record["category"] == legacy["value"]]
    assert dates and max(dates) < legacy["only_before"]


def test_missing_category_rate(cfg, base):
    rate = sum(d.record["category"] == "" for d in base) / len(base)
    assert rate == pytest.approx(cfg["data_quality_defects"]["missing_category_rate"], abs=0.005)


def test_subcategory_belongs_to_category(cfg, drafts):
    allowed = {k: set(v) for k, v in cfg["instance_facts"]["incident_subcategories"].items()}
    for add in cfg["ngi_choice_additions"]["incident_subcategory"]:
        allowed[add["dependent_value"]].add(add["value"])
    for d in drafts:
        cat, sub = d.record["category"], d.record["subcategory"]
        if cat in allowed:
            assert sub == "" or sub in allowed[cat]
        else:
            assert sub == ""


def test_caller_location_matches_site(drafts):
    for d in drafts[:500]:
        assert d.record["location"] == sys_id("cmn_location", d.site)


def test_erp_wave(cfg, drafts):
    wave = [d for d in drafts if d.story == "erp_wave"]
    ev = cfg["story_events"]["erp_failed_change"]
    assert len(wave) == ev["extra_incidents"]
    assert {d.opened_local.date() for d in wave} <= {dt.date(2026, 3, 9) + dt.timedelta(days=i) for i in range(5)}
    assert all(d.record["caused_by"] == sys_id("change_request", ERP_CHANGE_KEY) for d in wave)
    assert all(d.record["category"] == "software" and d.record["subcategory"] == "erp" for d in wave)
    assert not any("caused_by" in d.record for d in drafts if not d.story)


def test_every_record_tagged(cfg, drafts):
    assert all(d.record["correlation_id"] == cfg["meta"]["load_tag_prefix"] + "INC-01" for d in drafts)
