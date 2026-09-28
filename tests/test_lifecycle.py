import datetime as dt
import statistics
from collections import Counter

import pytest

from sn_synth.calendar import SN_FORMAT
from sn_synth.config import load_config
from sn_synth.incidents import generate_arrivals
from sn_synth.lifecycle import apply_lifecycle
from sn_synth.reference import build_reference

TODAY = dt.date(2026, 9, 27)
CUTOFF = "2026-09-26 22:00:00"   # 27 Sep 00:00 Paris (CEST) in UTC


def ts(text):
    return dt.datetime.strptime(text, SN_FORMAT)


@pytest.fixture(scope="module")
def cfg():
    return load_config(today=TODAY)


@pytest.fixture(scope="module")
def ref(cfg):
    return build_reference(cfg)


@pytest.fixture(scope="module")
def drafts(cfg, ref):
    return apply_lifecycle(cfg, ref, generate_arrivals(cfg, ref))


@pytest.fixture(scope="module")
def recs(drafts):
    return [d.record for d in drafts]


def in_period(drafts, start, end):
    return [d for d in drafts if start <= d.opened_local.date() < end and not d.story]


def test_deterministic(cfg, ref, recs):
    again = apply_lifecycle(cfg, ref, generate_arrivals(cfg, ref))
    assert [d.record for d in again] == recs


def test_valid_states_and_active_flag(recs):
    for r in recs:
        assert r["state"] in {"1", "2", "3", "6", "7", "8"}
        assert r["incident_state"] == r["state"]
        assert r["active"] == ("false" if r["state"] in {"7", "8"} else "true")


def test_data_policy_close_info(cfg, recs):
    codes = set(cfg["instance_facts"]["incident_close_codes"])
    for r in recs:
        if r["state"] in {"6", "7"}:
            assert r["close_code"] in codes and r["close_notes"]


def test_date_order_and_cutoff(cfg, recs):
    autoclose = dt.timedelta(days=cfg["time"]["autoclose_days"])
    for r in recs:
        opened = ts(r["opened_at"])
        assert r["sys_created_on"] == r["opened_at"]
        assert opened <= ts(r["sys_updated_on"]) <= ts(CUTOFF)
        if "resolved_at" in r:
            assert opened <= ts(r["resolved_at"]) <= ts(CUTOFF)
        if r["state"] == "7":
            assert ts(r["closed_at"]) - ts(r["resolved_at"]) == autoclose
        if r["state"] == "6":
            assert ts(CUTOFF) - ts(r["resolved_at"]) < autoclose


def test_open_incidents_have_no_resolution(recs):
    for r in recs:
        if r["state"] in {"1", "2", "3"}:
            assert "resolved_at" not in r and "close_code" not in r
        if r["state"] == "3":
            assert r["hold_reason"]


def test_canceled_have_no_resolution(recs):
    canceled = [r for r in recs if r["state"] == "8"]
    assert canceled and all("resolved_at" not in r and r["closed_at"] for r in canceled)


def test_resolve_times(recs):
    for r in recs:
        if "resolved_at" in r:
            calendar = int(r["calendar_stc"])
            assert calendar == int((ts(r["resolved_at"]) - ts(r["opened_at"])).total_seconds())
            assert 0 <= int(r["business_stc"]) <= calendar


def test_assignee_belongs_to_group(ref, recs):
    members = {(m["user"], m["group"]) for m in ref.tables["sys_user_grmember"]}
    for r in recs:
        if r.get("assigned_to"):
            assert (r["assigned_to"], r["assignment_group"]) in members


def test_fcr_improves(cfg, ref, drafts):
    desk = ref.group_id_by_name["NGI Service Desk"]

    def fcr(ds):
        done = [d.record for d in ds if d.record["state"] in {"6", "7"}]
        return sum(r["assignment_group"] == desk and r["reassignment_count"] == "0" for r in done) / len(done)

    before = fcr(in_period(drafts, dt.date(2025, 7, 1), dt.date(2026, 1, 1)))
    after = fcr(in_period(drafts, dt.date(2026, 7, 1), dt.date(2026, 9, 1)))
    assert before == pytest.approx(0.60, abs=0.03)
    assert after == pytest.approx(0.68, abs=0.03)


def test_mttr_improves(drafts):
    def median_p3(ds):
        return statistics.median(int(d.record["business_stc"]) for d in ds
                                 if d.record["priority"] == "3" and "business_stc" in d.record
                                 and d.record["reopen_count"] == "0" and not d.timeline.get("hold"))

    before = median_p3(in_period(drafts, dt.date(2025, 7, 1), dt.date(2026, 1, 1)))
    after = median_p3(in_period(drafts, dt.date(2026, 7, 1), dt.date(2026, 9, 1)))
    assert after / before == pytest.approx(0.75, abs=0.08)


def test_retired_group_only_early(cfg, ref, drafts):
    retired = ref.group_id_by_name[cfg["data_quality_defects"]["retired_group"]["name"]]
    used = [d for d in drafts if d.record["assignment_group"] == retired]
    assert used and max(d.opened_local.date() for d in used) < cfg["data_quality_defects"]["retired_group"]["only_before"]
    assert all(not d.record.get("assigned_to") for d in used)


def test_erp_wave_handled_by_sap_group(ref, drafts):
    sap = ref.group_id_by_name["NGI SAP ERP Support"]
    wave = [d.record for d in drafts if d.story == "erp_wave"]
    assert all(r["assignment_group"] == sap and r["reassignment_count"] == "1" for r in wave)


def test_open_backlog_exists_and_some_stale(recs):
    open_recs = [r for r in recs if r["state"] in {"1", "2", "3"}]
    assert len(open_recs) >= 50
    stale = [r for r in open_recs if ts(CUTOFF) - ts(r["sys_updated_on"]) > dt.timedelta(days=5)]
    assert stale


def test_state_distribution_plausible(recs):
    counts = Counter(r["state"] for r in recs)
    assert counts["7"] / len(recs) > 0.9
    assert 0.01 <= counts["8"] / len(recs) <= 0.03
