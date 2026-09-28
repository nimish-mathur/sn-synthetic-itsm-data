import datetime as dt
from collections import Counter

import pytest

from sn_synth.calendar import SN_FORMAT
from sn_synth.config import load_config
from sn_synth.ids import sys_id
from sn_synth.incidents import ERP_CHANGE_KEY
from sn_synth.pipeline import generate_all

TODAY = dt.date(2026, 9, 27)
CUTOFF = dt.datetime(2026, 9, 26, 22, 0, 0)      # 27 Sep 00:00 Paris in UTC


def ts(text):
    return dt.datetime.strptime(text, SN_FORMAT)


@pytest.fixture(scope="module")
def cfg():
    return load_config(today=TODAY)


@pytest.fixture(scope="module")
def ds(cfg):
    return generate_all(cfg)


@pytest.fixture(scope="module")
def changes(ds):
    return ds.changes


def test_deterministic(cfg, ds):
    again = generate_all(cfg)
    assert [c.record for c in again.changes] == [c.record for c in ds.changes]
    assert [d.record for d in again.incidents] == [d.record for d in ds.incidents]


def test_volume_and_type_mix(cfg, changes):
    months = Counter(c.start_local.strftime("%Y-%m") for c in changes)
    for m in ["2025-08", "2025-11", "2026-02", "2026-06"]:
        assert 140 <= months[m] <= 220, m
    types = Counter(c.type for c in changes)
    for t, share in cfg["changes"]["type_mix"].items():
        assert types[t] / len(changes) == pytest.approx(share, abs=0.03)


def test_states_valid(cfg, changes):
    valid = {str(v) for v in cfg["instance_facts"]["change_states"].values()}
    assert {c.record["state"] for c in changes} <= valid


def test_closed_changes_have_close_info(cfg, changes):
    codes = set(cfg["instance_facts"]["change_close_codes"])
    for c in changes:
        rec = c.record
        if rec["state"] == "3":
            assert rec["close_code"] in codes and rec["close_notes"]
            assert ts(rec["work_end"]) <= ts(rec["closed_at"]) <= CUTOFF
        else:
            assert "close_code" not in rec


def test_dates_ordered_and_opened_before_cutoff(changes):
    for c in changes:
        rec = c.record
        assert ts(rec["opened_at"]) < ts(rec["start_date"]) < ts(rec["end_date"])
        assert ts(rec["opened_at"]) <= CUTOFF


def test_future_scheduled_changes_exist(changes):
    future = [c for c in changes if ts(c.record["start_date"]) > CUTOFF]
    assert future and all(c.record["state"] in {"-2", "-4", "4"} for c in future)


def test_implementation_windows(changes):
    planned = [c for c in changes if c.type != "emergency" and c.key != ERP_CHANGE_KEY]
    weekend = sum(c.start_local.weekday() >= 5 for c in planned) / len(planned)
    assert weekend == pytest.approx(0.35, abs=0.04)
    for c in planned:
        if c.start_local.weekday() < 5:
            assert 18 <= c.start_local.hour < 22


def test_success_rate_by_type(cfg, changes):
    for t, mix in cfg["changes"]["close_code_mix"].items():
        closed = [c for c in changes if c.type == t and c.record["state"] == "3" and c.key != ERP_CHANGE_KEY]
        if len(closed) > 500:
            fail = sum(c.close_code == "unsuccessful" for c in closed) / len(closed)
            assert fail == pytest.approx(mix["unsuccessful"], abs=0.02)


def test_assignee_in_implementing_group(ds, changes):
    members = {(m["user"], m["group"]) for m in ds.reference.tables["sys_user_grmember"]}
    assert all((c.record["assigned_to"], c.record["assignment_group"]) in members for c in changes)


def test_erp_change_exists_and_failed(changes):
    erp = [c for c in changes if c.key == ERP_CHANGE_KEY]
    assert len(erp) == 1
    rec = erp[0].record
    assert rec["sys_id"] == sys_id("change_request", ERP_CHANGE_KEY)
    assert rec["start_date"] == "2026-03-07 21:00:00"      # 22:00 Paris (CET)
    assert rec["close_code"] == "unsuccessful" and rec["state"] == "3"


def test_every_caused_by_points_to_a_failed_change(ds, changes):
    failed = {c.record["sys_id"]: c for c in changes if c.close_code == "unsuccessful"}
    caused = [d for d in ds.incidents if "caused_by" in d.record]
    assert caused and all(d.record["caused_by"] in failed for d in caused)


def test_induced_incidents_follow_their_change(cfg, ds, changes):
    by_id = {c.record["sys_id"]: c for c in changes}
    window = dt.timedelta(hours=cfg["changes"]["induced_incidents"]["window_hours"])
    induced = [d for d in ds.incidents if d.story == "change_induced"]
    assert induced
    for d in induced:
        change = by_id[d.record["caused_by"]]
        assert change.end_local <= d.opened_local <= change.end_local + window
        assert d.record["assignment_group"] == ds.reference.group_id_by_name[change.group]


def test_every_record_tagged(cfg, changes):
    assert all(c.record["correlation_id"] == cfg["meta"]["load_tag_prefix"] + "CHG-01" for c in changes)
