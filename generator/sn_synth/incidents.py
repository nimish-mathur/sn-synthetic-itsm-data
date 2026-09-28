"""Incident generator – part 1: arrivals and initial attributes.

Decides WHEN each incident is opened, WHO raises it and WHAT it is about.
The lifecycle (assignment, response, resolution, closure) is added in part 2.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .calendar import NGICalendar, hhmm_to_seconds, to_sn
from .descriptions import ERP_WAVE_TEMPLATES, SUBCATEGORY_LABELS, TEMPLATES
from .ids import rng, sys_id
from .reference import ReferenceData

ERP_CHANGE_KEY = "NGI-ERP-FAILED-CHANGE-2026-03"   # the change module creates this exact record


@dataclass
class IncidentDraft:
    """One incident in progress. `record` holds ServiceNow fields; the rest is generator context."""
    key: str
    opened_local: dt.datetime
    site: str
    record: dict[str, Any] = field(default_factory=dict)
    story: str = ""                     # e.g. "erp_wave", "change_induced"
    forced_group: str = ""              # story incidents go straight to this group
    timeline: dict[str, Any] = field(default_factory=dict)   # filled by the lifecycle (part 2)


def _pick(r: np.random.Generator, weights: dict[Any, float]) -> Any:
    keys = list(weights)
    p = np.array([weights[k] for k in keys], dtype=float)
    return keys[r.choice(len(keys), p=p / p.sum())]


def _impact_urgency_by_priority(cfg: dict) -> dict[int, list[tuple[str, str]]]:
    pairs: dict[int, list[tuple[str, str]]] = {}
    for iu, prio in cfg["incidents"]["priority_matrix"].items():
        impact, urgency = iu.split(",")
        pairs.setdefault(int(prio), []).append((impact, urgency))
    return pairs


def daily_factor(cfg: dict, cal: NGICalendar, day: dt.date) -> float:
    """Relative volume for one day (1.0 = an average day)."""
    inc = cfg["incidents"]
    weights = inc["weekday_weights"]
    mean = sum(weights) / 7
    weekday = 5 if cal.is_holiday(day) and inc["holiday_behaviour"] == "saturday" else day.weekday()
    factor = weights[weekday] / mean
    factor *= inc["month_factors"].get(day.month, 1.0)
    dip = cfg["story_events"]["august_dip"]
    if day.month == dip["month"]:
        factor *= dip["volume_factor"]
    return factor


def _open_time(r: np.random.Generator, cfg: dict, cal: NGICalendar, day: dt.date) -> dt.datetime:
    inc = cfg["incidents"]
    if cal.is_business_day(day):
        if r.random() < inc["business_hours_share"]:
            seconds = r.uniform(8 * 3600, 18 * 3600)
        else:                                              # 00:00–08:00 or 18:00–24:00 (14 h)
            s = r.uniform(0, 14 * 3600)
            seconds = s if s < 8 * 3600 else s + 10 * 3600
    else:
        lo, hi = (hhmm_to_seconds(t) for t in inc["weekend_hours"])
        seconds = r.uniform(lo, hi)
    return cal.local(day, seconds)


class _AttributePicker:
    """Draws caller, category, subcategory, priority and description for one incident."""

    def __init__(self, cfg: dict, ref: ReferenceData) -> None:
        self.cfg, self.ref = cfg, ref
        self.inc = cfg["incidents"]
        self.facts = cfg["instance_facts"]
        self.pairs = _impact_urgency_by_priority(cfg)
        self.dq = cfg["data_quality_defects"]
        self.site_of = {uid: site for site, ids in ref.users_by_site.items() for uid in ids}
        self.all_users = [uid for ids in ref.users_by_site.values() for uid in ids]
        self.site_names = {s["code"]: s["name"] for s in cfg["organisation"]["sites"]}
        additions = [a["value"] for a in cfg.get("ngi_choice_additions", {}).get("incident_subcategory", [])]
        self.d9_enabled = {"erp", "mes"} <= set(additions)

    def caller(self, r: np.random.Generator) -> str:
        return self.all_users[r.integers(len(self.all_users))]

    def category(self, r: np.random.Generator, day: dt.date) -> str:
        cat = _pick(r, self.inc["category_mix"])
        if self.dq["enabled"]:
            legacy = self.dq["legacy_category"]
            if day < legacy["only_before"] and r.random() < legacy["rate"]:
                return legacy["value"]
            if r.random() < self.dq["missing_category_rate"]:
                return ""
        return cat

    def subcategory(self, r: np.random.Generator, category: str) -> str:
        if category == "software":
            weights = dict(self.inc["software_subcategory_weights"])
            if not self.d9_enabled:
                weights = {k: v for k, v in weights.items() if k in self.facts["incident_subcategories"]["software"]}
            return _pick(r, weights)
        options = self.facts["incident_subcategories"].get(category, [])
        return options[r.integers(len(options))] if options else ""

    def priority(self, r: np.random.Generator, mix: dict[int, float]) -> tuple[str, str, str]:
        prio = _pick(r, mix)
        impact, urgency = self.pairs[prio][r.integers(len(self.pairs[prio]))]
        return impact, urgency, str(prio)

    def description(self, r: np.random.Generator, category: str, subcategory: str, site: str) -> str:
        templates = TEMPLATES.get(category, TEMPLATES[""])
        text = templates[r.integers(len(templates))]
        return text.format(sub=SUBCATEGORY_LABELS.get(subcategory, subcategory), site=self.site_names[site])


def _build(pick: _AttributePicker, ref: ReferenceData, r: np.random.Generator, opened: dt.datetime, key: str,
           prio_mix: dict, tag: str, story: str = "", category: str | None = None, subcategory: str | None = None,
           description: str | None = None, extra: dict | None = None, forced_group: str = "") -> IncidentDraft:
    caller = pick.caller(r)
    site = pick.site_of[caller]
    cat = pick.category(r, opened.date()) if category is None else category
    sub = pick.subcategory(r, cat) if subcategory is None else subcategory
    impact, urgency, prio = pick.priority(r, prio_mix)
    rec = {
        "sys_id": sys_id("incident", key),
        "opened_at": to_sn(opened),
        "caller_id": caller,
        "location": ref.location_by_site[site],
        "company": ref.company_id,
        "category": cat,
        "subcategory": sub,
        "impact": impact, "urgency": urgency, "priority": prio,
        "short_description": description or pick.description(r, cat, sub, site),
        "correlation_id": tag,
        **(extra or {}),
    }
    return IncidentDraft(key=key, opened_local=opened, site=site, record=rec, story=story, forced_group=forced_group)


def generate_arrivals(cfg: dict, ref: ReferenceData) -> list[IncidentDraft]:
    """All incidents opened from start_date up to (not including) end_date, sorted by open time."""
    cal = NGICalendar(cfg)
    pick = _AttributePicker(cfg, ref)
    tag = cfg["meta"]["load_tag_prefix"] + "INC-01"
    base_daily = cfg["incidents"]["monthly_volume"] * 12 / 365
    drafts: list[IncidentDraft] = []

    def make(r, day, key, prio_mix, **kwargs):
        opened = _open_time(r, cfg, cal, day)
        drafts.append(_build(pick, ref, r, opened, key, prio_mix, tag, **kwargs))

    # Base volume
    r = rng(cfg["meta"]["seed"], "incidents.arrivals")
    day, end = cfg["time"]["start_date"], cfg["time"]["end_date"]
    while day < end:
        for k in range(r.poisson(base_daily * daily_factor(cfg, cal, day))):
            make(r, day, f"{day:%Y%m%d}-b{k:03d}", cfg["incidents"]["priority_mix"])
        day += dt.timedelta(days=1)

    # Story event: incident wave after the failed ERP change (own random stream)
    ev = cfg["story_events"]["erp_failed_change"]
    first = ev["first_day_local"]
    if first < end:
        rw = rng(cfg["meta"]["seed"], "incidents.erp_wave")
        counts = np.round(np.array(ev["daily_profile"]) * ev["extra_incidents"]).astype(int)
        change_id = sys_id("change_request", ERP_CHANGE_KEY)
        sub = "erp" if pick.d9_enabled else "os"
        for offset, n in enumerate(counts):
            wave_day = first + dt.timedelta(days=offset)
            if wave_day >= end:
                break
            for k in range(n):
                make(rw, wave_day, f"{wave_day:%Y%m%d}-w{k:03d}", ev["priority_mix"], story="erp_wave",
                     category=ev["category"], subcategory=sub,
                     description=ERP_WAVE_TEMPLATES[rw.integers(len(ERP_WAVE_TEMPLATES))],
                     extra={"caused_by": change_id}, forced_group=ev["implementing_group"])

    drafts.sort(key=lambda d: (d.opened_local, d.key))   # load order = number order = time order
    return drafts


def monthly_counts(drafts: list[IncidentDraft]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in drafts:
        month = d.opened_local.strftime("%Y-%m")
        counts[month] = counts.get(month, 0) + 1
    return counts


def generate_induced(cfg: dict, ref: ReferenceData, specs: list[dict]) -> list[IncidentDraft]:
    """Incidents caused by unsuccessful changes (incident.caused_by -> change)."""
    pick = _AttributePicker(cfg, ref)
    tag = cfg["meta"]["load_tag_prefix"] + "INC-01"
    ind = cfg["changes"]["induced_incidents"]
    r = rng(cfg["meta"]["seed"], "incidents.change_induced")
    cutoff = NGICalendar(cfg).local(cfg["time"]["end_date"], 0)
    drafts = []
    for spec in specs:
        mapping = ind["category_by_group"][spec["group"]]
        for k in range(spec["count"]):
            opened = spec["after"] + dt.timedelta(seconds=round(r.uniform(0, ind["window_hours"] * 3600)))
            if opened >= cutoff:
                continue
            drafts.append(_build(pick, ref, r, opened, f"{spec['change_key']}-i{k}", ind["priority_mix"], tag,
                                 story="change_induced", category=mapping["category"],
                                 subcategory=mapping.get("subcategory"),
                                 extra={"caused_by": spec["change_id"]}, forced_group=spec["group"]))
    return drafts
