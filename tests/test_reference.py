import datetime as dt
import re

import pytest

from sn_synth.config import load_config
from sn_synth.reference import allocate, build_reference, slug

HEX32 = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture(scope="module")
def cfg():
    return load_config(today=dt.date(2026, 9, 27))


@pytest.fixture(scope="module")
def ref(cfg):
    return build_reference(cfg)


def test_allocate_adds_up_exactly():
    assert sum(allocate(3500, {"a": 0.333, "b": 0.333, "c": 0.334}).values()) == 3500


def test_slug_handles_accents_and_spaces():
    assert slug("Wiśniewski") == "wisniewski"
    assert slug("Łukasz") == "lukasz"
    assert slug("de Jong") == "dejong"


def test_counts(cfg, ref):
    t = ref.tables
    assert len(t["core_company"]) == 1
    assert len(t["cmn_location"]) == 6
    assert len(t["cmn_department"]) == len(cfg["organisation"]["departments"])
    assert len(t["sys_user"]) == 3500
    assert len(t["sys_user_group"]) == 12
    assert len(t["sys_user_grmember"]) == sum(g["agents"] for g in cfg["organisation"]["assignment_groups"])


def test_sys_ids_valid_and_unique(ref):
    all_ids = [row["sys_id"] for rows in ref.tables.values() for row in rows]
    assert all(HEX32.match(i) for i in all_ids)
    assert len(all_ids) == len(set(all_ids))


def test_deterministic(cfg, ref):
    again = build_reference(cfg)
    assert again.tables == ref.tables


def test_user_names_unique_and_emails_on_example_domain(ref):
    users = ref.tables["sys_user"]
    assert len({u["user_name"] for u in users}) == len(users)
    assert all(u["email"].endswith("@northgate-industrial.example") for u in users)


def test_site_sizes_follow_shares(cfg, ref):
    for s in cfg["organisation"]["sites"]:
        assert len(ref.users_by_site[s["code"]]) == round(3500 * s["employee_share"])


def test_references_resolve(ref):
    t = ref.tables
    locations = {r["sys_id"] for r in t["cmn_location"]}
    departments = {r["sys_id"] for r in t["cmn_department"]}
    users = {r["sys_id"] for r in t["sys_user"]}
    groups = {r["sys_id"] for r in t["sys_user_group"]}
    assert all(u["location"] in locations and u["department"] in departments for u in t["sys_user"])
    assert all(m["user"] in users and m["group"] in groups for m in t["sys_user_grmember"])
    assert all(g["manager"] in users for g in t["sys_user_group"] if "manager" in g)


def test_each_agent_in_one_group_and_it_department(ref):
    it_dept = ref.department_by_name["IT"]
    dept_of = {u["sys_id"]: u["department"] for u in ref.tables["sys_user"]}
    agents = [m["user"] for m in ref.tables["sys_user_grmember"]]
    assert len(agents) == len(set(agents))
    assert all(dept_of[a] == it_dept for a in agents)


def test_site_restricted_groups_use_local_staff(cfg, ref):
    site_of = {uid: site for site, ids in ref.users_by_site.items() for uid in ids}
    for g in cfg["organisation"]["assignment_groups"]:
        if g.get("sites"):
            assert all(site_of[a] in g["sites"] for a in ref.agents_by_group[g["name"]])


def test_retired_group_inactive_and_empty(ref):
    retired = next(g for g in ref.tables["sys_user_group"] if "retired" in g["name"])
    assert retired["active"] == "false"
    assert ref.agents_by_group[retired["name"]] == []


def test_reference_data_predates_history(cfg, ref):
    start = cfg["time"]["start_date"].strftime("%Y-%m-%d")
    assert all(r["sys_created_on"] < start for rows in ref.tables.values() for r in rows)
