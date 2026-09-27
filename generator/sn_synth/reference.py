"""Reference data: company, locations, departments, users, groups, memberships.

Everything is deterministic: the same config (seed included) produces the same
records and the same sys_ids on every run.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .ids import rng, sys_id
from .names import NAME_POOLS

Record = dict[str, Any]

COUNTRY_NAMES = {"FR": "France", "DE": "Germany", "IT": "Italy",
                 "PL": "Poland", "NL": "Netherlands", "ES": "Spain"}


@dataclass
class ReferenceData:
    tables: dict[str, list[Record]]
    company_id: str
    location_by_site: dict[str, str]
    department_by_name: dict[str, str]
    users_by_site: dict[str, list[str]]
    group_id_by_name: dict[str, str]
    agents_by_group: dict[str, list[str]] = field(default_factory=dict)


def allocate(total: int, shares: dict[str, float]) -> dict[str, int]:
    """Split `total` by `shares` into integers that add up exactly (largest remainder)."""
    raw = {k: total * v for k, v in shares.items()}
    counts = {k: int(v) for k, v in raw.items()}
    remainder = total - sum(counts.values())
    for k in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[:remainder]:
        counts[k] += 1
    return counts


def slug(text: str) -> str:
    """'Wiśniewski' -> 'wisniewski', 'de Jong' -> 'dejong'."""
    text = text.replace("ł", "l").replace("Ł", "L")      # not decomposable by NFKD
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def _sys_fields(created_on: str, user: str) -> Record:
    return {"sys_created_on": created_on, "sys_updated_on": created_on,
            "sys_created_by": user, "sys_updated_by": user}


def build_reference(cfg: dict[str, Any]) -> ReferenceData:
    meta, org = cfg["meta"], cfg["organisation"]
    r = rng(meta["seed"], "reference")
    domain = org["email_domain"]
    # Reference data predates the history window by 30 days (06:00 UTC).
    created_on = (cfg["time"]["start_date"] - dt.timedelta(days=30)).strftime("%Y-%m-%d 06:00:00")
    sysf = _sys_fields(created_on, meta["generator_user"])

    # Company
    company_id = sys_id("core_company", meta["client_code"])
    companies = [{"sys_id": company_id, "name": meta["client_name"], "city": "Lyon",
                  "country": "France", **sysf}]

    # Locations
    locations, location_by_site = [], {}
    for s in org["sites"]:
        loc_id = sys_id("cmn_location", s["code"])
        location_by_site[s["code"]] = loc_id
        suffix = " (HQ)" if s["role"] == "HQ" else ""
        locations.append({"sys_id": loc_id, "name": f"NGI {s['name']}{suffix}", "city": s["name"],
                          "country": COUNTRY_NAMES[s["country"]], "company": company_id, **sysf})

    # Departments
    departments, department_by_name = [], {}
    for name in org["departments"]:
        dep_id = sys_id("cmn_department", name)
        department_by_name[name] = dep_id
        departments.append({"sys_id": dep_id, "name": f"NGI {name}", "company": company_id, **sysf})

    # Users: per site, per department
    users, users_by_site = [], {}
    it_staff_by_site: dict[str, list[str]] = {}
    taken: set[str] = set()
    site_counts = allocate(org["employees"], {s["code"]: s["employee_share"] for s in org["sites"]})
    for s in org["sites"]:
        pool = NAME_POOLS[s["country"]]
        users_by_site[s["code"]] = []
        it_staff_by_site[s["code"]] = []
        dept_counts = allocate(site_counts[s["code"]], org["departments"])
        for dept, n in dept_counts.items():
            for _ in range(n):
                first = pool["first"][r.integers(len(pool["first"]))]
                last = pool["last"][r.integers(len(pool["last"]))]
                base = f"{slug(first)}.{slug(last)}"
                user_name, i = base, 1
                while user_name in taken:
                    i += 1
                    user_name = f"{base}{i}"
                taken.add(user_name)
                uid = sys_id("sys_user", user_name)
                users.append({"sys_id": uid, "user_name": user_name, "first_name": first, "last_name": last,
                              "email": f"{user_name}@{domain}", "company": company_id,
                              "location": location_by_site[s["code"]],
                              "department": department_by_name[dept], "active": "true",
                              "source": meta["load_tag_prefix"] + "REF", **sysf})
                users_by_site[s["code"]].append(uid)
                if dept == org["agent_department"]:
                    it_staff_by_site[s["code"]].append(uid)

    # Groups and memberships: each agent belongs to exactly one group.
    groups, members, group_id_by_name, agents_by_group = [], [], {}, {}
    available = {site: list(ids) for site, ids in it_staff_by_site.items()}
    for g in org["assignment_groups"]:
        gid = sys_id("sys_user_group", g["name"])
        group_id_by_name[g["name"]] = gid
        sites = g.get("sites") or [s["code"] for s in org["sites"]]
        candidates = [u for site in sites for u in available[site]]
        if len(candidates) < g["agents"]:
            raise ValueError(f"Not enough IT staff at {sites} for group {g['name']}")
        chosen = [candidates[i] for i in r.choice(len(candidates), size=g["agents"], replace=False)]
        for site in sites:
            available[site] = [u for u in available[site] if u not in chosen]
        agents_by_group[g["name"]] = chosen
        active = g.get("active", True)
        record = {"sys_id": gid, "name": g["name"], "active": str(active).lower(),
                  "description": f"Tier {g['tier']} assignment group (synthetic)",
                  "email": f"{slug(g['name'])}@{domain}", **sysf}
        if chosen:
            record["manager"] = chosen[0]
        groups.append(record)
        for uid in chosen:
            members.append({"sys_id": sys_id("sys_user_grmember", f"{g['name']}:{uid}"),
                            "user": uid, "group": gid, **sysf})

    return ReferenceData(
        tables={"core_company": companies, "cmn_location": locations, "cmn_department": departments,
                "sys_user": users, "sys_user_group": groups, "sys_user_grmember": members},
        company_id=company_id, location_by_site=location_by_site, department_by_name=department_by_name,
        users_by_site=users_by_site, group_id_by_name=group_id_by_name, agents_by_group=agents_by_group,
    )
