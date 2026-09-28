"""Change requests: planned work by the implementing groups, including the failed
ERP change (D7b) and changes whose failure causes incidents."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .calendar import NGICalendar, add_calendar, to_sn
from .descriptions import CHANGE_CLOSE_NOTES, CHANGE_TEMPLATES
from .ids import rng, sys_id
from .incidents import ERP_CHANGE_KEY, _pick
from .reference import ReferenceData


@dataclass
class ChangeDraft:
    key: str
    start_local: dt.datetime
    end_local: dt.datetime
    type: str
    group: str
    record: dict[str, Any] = field(default_factory=dict)
    close_code: str = ""


def _window_start(r: np.random.Generator, cfg: dict, cal: NGICalendar, day: dt.date, ctype: str) -> dt.datetime:
    """Planned start: emergency any time; others weekday evenings or weekends."""
    if ctype == "emergency":
        return cal.local(day, r.uniform(0, 86400))
    if day.weekday() >= 5:
        return cal.local(day, r.uniform(6 * 3600, 20 * 3600))
    lo, hi = (int(t[:2]) for t in cfg["changes"]["implementation_window"]["weekday_evening"].split("-"))
    return cal.local(day, r.uniform(lo * 3600, (hi - 1) * 3600))


def _planned_day(r: np.random.Generator, cfg: dict, month_start: dt.date, days_in_month: int, ctype: str) -> dt.date:
    """Weekend share for non-emergency changes follows implementation_window.weekend_share."""
    days = [month_start + dt.timedelta(days=i) for i in range(days_in_month)]
    if ctype != "emergency":
        weekend = [d for d in days if d.weekday() >= 5]
        weekday = [d for d in days if d.weekday() < 5]
        pool = weekend if r.random() < cfg["changes"]["implementation_window"]["weekend_share"] else weekday
        return pool[r.integers(len(pool))]
    return days[r.integers(len(days))]


class ChangeGenerator:
    def __init__(self, cfg: dict, ref: ReferenceData) -> None:
        self.cfg, self.ref = cfg, ref
        self.chg = cfg["changes"]
        self.cal = NGICalendar(cfg)
        self.cutoff = self.cal.local(cfg["time"]["end_date"], 0)
        self.state = {k: str(v) for k, v in cfg["instance_facts"]["change_states"].items()}
        self.tag = cfg["meta"]["load_tag_prefix"] + "CHG-01"
        self.site_names = [s["name"] for s in cfg["organisation"]["sites"]]

    def _record(self, r, draft: ChangeDraft, description: str, opened: dt.datetime, canceled: bool) -> None:
        chg, cutoff = self.chg, self.cutoff
        agents = self.ref.agents_by_group[draft.group]
        agent = agents[r.integers(len(agents))]
        rec = {
            "sys_id": sys_id("change_request", draft.key),
            "short_description": description,
            "type": draft.type,
            "assignment_group": self.ref.group_id_by_name[draft.group],
            "assigned_to": agent,
            "requested_by": agent,
            "company": self.ref.company_id,
            "opened_at": to_sn(opened),
            "start_date": to_sn(draft.start_local),
            "end_date": to_sn(draft.end_local),
            "correlation_id": self.tag,
        }
        review = dt.timedelta(days=chg["review_days"][draft.type])
        closed_at = draft.end_local + (review if review else dt.timedelta(hours=1))
        last = opened

        if canceled:
            cancel_at = min(add_calendar(opened, 86400 * r.uniform(0.2, 3)), draft.start_local)
            if cancel_at <= cutoff:
                rec.update(state=self.state["canceled"], active="false", closed_at=to_sn(cancel_at))
                last = cancel_at
            else:
                canceled = False
        if not canceled:
            if closed_at <= cutoff:
                code = draft.close_code or _pick(r, chg["close_code_mix"][draft.type])
                draft.close_code = code
                notes = CHANGE_CLOSE_NOTES[code]
                rec.update(state=self.state["closed"], active="false", closed_at=to_sn(closed_at),
                           work_start=to_sn(draft.start_local), work_end=to_sn(draft.end_local),
                           close_code=code, close_notes=notes[r.integers(len(notes))])
                last = closed_at
            elif draft.end_local <= cutoff:
                rec.update(state=self.state["review"], active="true",
                           work_start=to_sn(draft.start_local), work_end=to_sn(draft.end_local))
                last = draft.end_local
            elif draft.start_local <= cutoff:
                rec.update(state=self.state["implement"], active="true", work_start=to_sn(draft.start_local))
                last = draft.start_local
            elif draft.type == "normal" and opened > add_calendar(cutoff, -86400 * chg["assess_days_normal"]):
                rec.update(state=self.state["assess"], active="true")
            else:
                rec.update(state=self.state["scheduled"], active="true")

        user = self.cfg["meta"]["generator_user"]
        rec.update(sys_created_on=rec["opened_at"], sys_updated_on=to_sn(last),
                   sys_created_by=user, sys_updated_by=user)
        draft.record = rec

    def generate(self) -> list[ChangeDraft]:
        chg, cfg = self.chg, self.cfg
        r = rng(cfg["meta"]["seed"], "changes")
        drafts: list[ChangeDraft] = []
        start = cfg["time"]["start_date"]
        horizon = cfg["time"]["end_date"] + dt.timedelta(days=chg["scheduled_horizon_days"])
        month = start.replace(day=1)
        seq = 0
        while month < horizon:
            nxt = (month + dt.timedelta(days=32)).replace(day=1)
            days_in_month = (nxt - month).days
            for _ in range(r.poisson(chg["monthly_volume"])):
                ctype = _pick(r, chg["type_mix"])
                day = _planned_day(r, cfg, month, days_in_month, ctype)
                if not (start <= day < horizon):
                    continue
                begin = _window_start(r, cfg, self.cal, day, ctype)
                end = add_calendar(begin, 3600 * float(chg["duration_hours"]["median"] *
                                                       np.exp(chg["duration_hours"]["sigma"] * r.standard_normal())))
                lead = chg["lead_time_days"][ctype]
                opened = add_calendar(begin, -3600 * r.uniform(2, 12) - 86400 * lead * r.uniform(0.6, 1.4))
                if opened >= self.cutoff:
                    continue
                group = chg["implementing_groups"][r.integers(len(chg["implementing_groups"]))]
                template = CHANGE_TEMPLATES[group][r.integers(len(CHANGE_TEMPLATES[group]))]
                seq += 1
                draft = ChangeDraft(key=f"{day:%Y%m%d}-c{seq:05d}", start_local=begin, end_local=end,
                                    type=ctype, group=group)
                self._record(r, draft, template.format(site=self.site_names[r.integers(len(self.site_names))]),
                             opened, canceled=r.random() < chg["cancel_rate"])
                drafts.append(draft)
            month = nxt

        # Story event: the failed ERP change (D7b)
        ev = cfg["story_events"]["erp_failed_change"]
        begin = dt.datetime.strptime(ev["change_start_local"], "%Y-%m-%d %H:%M").replace(tzinfo=self.cal.tz)
        if begin < self.cutoff:
            erp = ChangeDraft(key=ERP_CHANGE_KEY, start_local=begin,
                              end_local=add_calendar(begin, 3600 * ev["duration_hours"]),
                              type=ev["change_type"], group=ev["implementing_group"], close_code=ev["close_code"])
            self._record(rng(cfg["meta"]["seed"], "changes.erp"), erp, ev["short_description"],
                         add_calendar(begin, -86400 * chg["lead_time_days"][ev["change_type"]]), canceled=False)
            drafts.append(erp)

        drafts.sort(key=lambda d: (d.record["opened_at"], d.key))
        return drafts


def generate_changes(cfg: dict, ref: ReferenceData) -> list[ChangeDraft]:
    return ChangeGenerator(cfg, ref).generate()


def induced_incident_specs(cfg: dict, changes: list[ChangeDraft]) -> list[dict]:
    """Which unsuccessful changes cause incidents, and how many (the ERP wave is handled separately)."""
    ind = cfg["changes"]["induced_incidents"]
    r = rng(cfg["meta"]["seed"], "changes.induced")
    lo, hi = ind["incidents_per_event"]
    specs = []
    for c in changes:
        if c.close_code == "unsuccessful" and c.key != ERP_CHANGE_KEY and r.random() < ind["probability_if_unsuccessful"]:
            specs.append({"change_key": c.key, "change_id": c.record["sys_id"], "group": c.group,
                          "after": c.end_local, "count": int(r.integers(lo, hi + 1))})
    return specs
