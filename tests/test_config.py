from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parents[1] / "config" / "ngi.yaml"


@pytest.fixture(scope="module")
def cfg():
    with CONFIG.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_shares_sum_to_one(cfg):
    inc = cfg["incidents"]
    assert sum(inc["priority_mix"].values()) == pytest.approx(1.0)
    assert sum(inc["category_mix"].values()) == pytest.approx(1.0)
    assert sum(inc["reassignments_when_escalated"].values()) == pytest.approx(1.0)
    assert sum(s["employee_share"] for s in cfg["organisation"]["sites"]) == pytest.approx(1.0)
    assert sum(cfg["changes"]["type_mix"].values()) == pytest.approx(1.0)
    for mix in cfg["changes"]["close_code_mix"].values():
        assert sum(mix.values()) == pytest.approx(1.0)


def test_categories_match_instance(cfg):
    known = set(cfg["instance_facts"]["incident_categories"])
    assert set(cfg["incidents"]["category_mix"]) == known


def test_eight_sla_definitions(cfg):
    defs = cfg["sla"]["definitions"]
    expected = {(p, t) for p in (1, 2, 3, 4) for t in ("response", "resolution")}
    assert {(d["priority"], d["target"]) for d in defs} == expected


def test_legacy_category_is_not_active(cfg):
    legacy = cfg["data_quality_defects"]["legacy_category"]["value"]
    assert legacy not in cfg["instance_facts"]["incident_categories"]


def test_close_codes_exist_on_instance(cfg):
    known = set(cfg["instance_facts"]["incident_close_codes"])
    assert set(cfg["incidents"]["close_code_mix"]) <= known
    assert sum(cfg["incidents"]["close_code_mix"].values()) == pytest.approx(1.0)


def test_hold_reasons_exist_on_instance(cfg):
    known = set(cfg["instance_facts"]["incident_hold_reasons"])
    assert set(cfg["incidents"]["hold_reason_mix"]) <= known
    assert sum(cfg["incidents"]["hold_reason_mix"].values()) == pytest.approx(1.0)


def test_subcategory_parents_are_categories(cfg):
    categories = set(cfg["instance_facts"]["incident_categories"])
    assert set(cfg["instance_facts"]["incident_subcategories"]) <= categories
    for add in cfg["ngi_choice_additions"]["incident_subcategory"]:
        assert add["dependent_value"] in categories


def test_departments_sum_to_one(cfg):
    assert sum(cfg["organisation"]["departments"].values()) == pytest.approx(1.0)
