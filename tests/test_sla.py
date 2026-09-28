import datetime as dt
import re

import pytest

from sn_synth.calendar import SN_FORMAT
from sn_synth.config import load_config
from sn_synth.incidents import generate_arrivals
from sn_synth.lifecycle import apply_lifecycle
from sn_synth.reference import build_reference
from sn_synth.sla import attainment_by_quarter, build_sla_rows, sn_duration

TODAY = dt.date(2026, 9, 27)
DURATION = re.compile(r"^1970-01-\d{2} \d{2}:\d{2}:\d{2}$|^19[7-9]\d-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def ts(text):
    return dt.datetime.strptime(text, SN_FORMAT)


def dur(text):
    return int((ts(text) - dt.datetime(1970, 1, 1)).total_seconds())


@pytest.fixture(scope="module")
def cfg():
    return load_config(today=TODAY)


@pytest.fixture(scope="module")
def drafts(cfg):
    ref = build_reference(cfg)
    return apply_lifecycle(cfg, ref, generate_arrivals(cfg, ref))


@pytest.fixture(scope="module")
def rows(cfg, drafts):
    return build_sla_rows(cfg, drafts)


def test_duration_format():
    assert sn_duration(90061) == "1970-01-02 01:01:01"
    assert sn_duration(-5) == "1970-01-01 00:00:00"


def test_two_rows_per_incident(drafts, rows):
    assert len(rows) == 2 * len(drafts)
    assert len({r["sys_id"] for r in rows}) == len(rows)
    incident_ids = {d.record["sys_id"] for d in drafts}
    assert {r["task"] for r in rows} == incident_ids


def test_sla_names_match_definitions(cfg, drafts, rows):
    names = {d["name"] for d in cfg["sla"]["definitions"]}
    assert {r["sla_name"] for r in rows} <= names
    prio = {d.record["sys_id"]: d.record["priority"] for d in drafts}
    for r in rows:
        assert f"P{prio[r['task']]} " in r["sla_name"]


def test_stage_active_and_end_time_consistent(cfg, rows):
    stages = set(cfg["instance_facts"]["task_sla_stages"].values())
    for r in rows:
        assert r["stage"] in stages
        assert r["active"] == ("true" if r["stage"] in ("in_progress", "paused") else "false")
        assert ("end_time" in r) == (r["stage"] in ("completed", "cancelled"))


def test_breach_flag_matches_percentage(rows):
    for r in rows:
        assert (r["has_breached"] == "true") == (float(r["business_percentage"]) > 100)


def test_time_order(rows):
    for r in rows:
        assert ts(r["start_time"]) <= ts(r["original_breach_time"]) <= ts(r["planned_end_time"])
        if "end_time" in r:
            assert ts(r["start_time"]) <= ts(r["end_time"])


def test_durations_valid(rows):
    for r in rows:
        for f in ("duration", "business_duration", "pause_duration", "business_pause_duration"):
            assert DURATION.match(r[f]), (f, r[f])
        if "schedule_name" in r:
            assert dur(r["business_duration"]) <= dur(r["duration"]) + 1
        else:                                        # 24x7 SLA: business time == real time
            assert r["business_duration"] == r["duration"]


def test_response_stops_before_resolution(rows):
    by_task = {}
    for r in rows:
        by_task.setdefault(r["task"], {})["response" if "response" in r["sla_name"] else "resolution"] = r
    for pair in by_task.values():
        a, b = pair["response"], pair["resolution"]
        if "end_time" in a and "end_time" in b and b["stage"] == "completed":
            assert ts(a["end_time"]) <= ts(b["end_time"])


def test_open_incidents_have_active_resolution_sla(drafts, rows):
    open_ids = {d.record["sys_id"] for d in drafts if d.record["state"] in {"1", "2", "3"}}
    res = {r["task"]: r for r in rows if "resolution" in r["sla_name"]}
    for tid in open_ids:
        assert res[tid]["active"] == "true"
    on_hold = {d.record["sys_id"] for d in drafts if d.record["state"] == "3"}
    assert all(res[tid]["stage"] == "paused" for tid in on_hold)


def test_resolution_sla_stops_at_final_resolution(drafts, rows):
    res = {r["task"]: r for r in rows if "resolution" in r["sla_name"]}
    for d in drafts:
        if d.record["state"] in {"6", "7"}:
            assert res[d.record["sys_id"]]["end_time"] == d.record["resolved_at"]


def test_business_sla_has_schedule_p1_does_not(rows):
    for r in rows:
        assert ("schedule_name" in r) == (" P1 " not in f" {r['sla_name']} ")


def test_attainment_story(rows):
    resolution = attainment_by_quarter(rows, "resolution")
    response = attainment_by_quarter(rows, "response")
    assert 0.72 <= resolution["2025-Q3"] <= 0.84
    assert 0.82 <= resolution["2026-Q3"] <= 0.92
    assert resolution["2026-Q3"] - resolution["2025-Q3"] >= 0.05
    assert all(v >= 0.85 for v in response.values())
