import datetime as dt
import json

import pytest

from sn_synth.config import load_config
from sn_synth.export import LOAD_ORDER, RESOLVE, export_dataset
from sn_synth.pipeline import generate_all


@pytest.fixture(scope="module")
def cfg():
    return load_config(today=dt.date(2026, 9, 27))


@pytest.fixture(scope="module")
def exported(cfg, tmp_path_factory):
    out = tmp_path_factory.mktemp("export")
    ds = generate_all(cfg)
    files, gt_path = export_dataset(ds, out, cfg["output"]["batch_size"], cfg["meta"]["load_tag_prefix"])
    manifest = json.loads((out / "load" / "manifest.json").read_text(encoding="utf-8"))
    return ds, files, manifest, json.loads(gt_path.read_text(encoding="utf-8"))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_files_follow_load_order(exported):
    _, files, _, _ = exported
    tables = [load(p)["table"] for p in files]
    order = [LOAD_ORDER.index(t) for t in tables]
    assert order == sorted(order)


def test_batches_within_size(cfg, exported):
    _, files, _, _ = exported
    assert all(0 < len(load(p)["records"]) <= cfg["output"]["batch_size"] for p in files)


def test_manifest_matches_records(exported):
    _, files, manifest, gt = exported
    ids = {}
    for p in files:
        b = load(p)
        ids.setdefault(b["table"], []).extend(r["sys_id"] for r in b["records"])
    assert ids == manifest["tables"]
    assert {t: len(v) for t, v in ids.items()} == gt["record_counts"]


def test_history_without_business_rules_reference_with(exported):
    _, files, _, _ = exported
    for p in files:
        b = load(p)
        history = b["table"] in {"change_request", "incident", "task_sla"}
        assert b["options"]["runBusinessRules"] is (not history)
        assert b["options"]["keepSysFields"] is True


def test_references_point_to_earlier_batches(exported):
    _, _, manifest, _ = exported
    changes = set(manifest["tables"]["change_request"])
    incidents = set(manifest["tables"]["incident"])
    ds = exported[0]
    assert all(d.record["caused_by"] in changes for d in ds.incidents if "caused_by" in d.record)
    assert all(r["task"] in incidents for r in ds.sla_rows)


def test_task_sla_fields_exist_on_instance(cfg, exported):
    ds = exported[0]
    allowed = set(cfg["instance_facts"]["task_sla_fields"]) | {
        rule["source_key"] for rule in RESOLVE["task_sla"].values()}
    for r in ds.sla_rows[:2000]:
        assert set(r) <= allowed


def test_task_sla_batches_carry_resolve_rules(exported):
    _, files, _, _ = exported
    for p in files:
        b = load(p)
        assert b["resolve"] == RESOLVE.get(b["table"], {})


def test_ground_truth_totals(exported):
    ds, _, _, gt = exported
    assert sum(gt["incident"]["by_state"].values()) == len(ds.incidents)
    assert sum(gt["incident"]["by_opened_month"].values()) == len(ds.incidents)
    assert gt["incident"]["with_caused_by"] == sum("caused_by" in d.record for d in ds.incidents)
