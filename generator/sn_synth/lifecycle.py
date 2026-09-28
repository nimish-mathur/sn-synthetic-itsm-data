"""Incident generator – part 2: lifecycle.

For each incident: who handles it, how long response and resolution take (in the
SLA clock of its priority), on-hold periods, reopen, cancel, and the state it is in
at the history cut-off. Timestamps the SLA module needs are kept in draft.timeline.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np

from .calendar import BusinessClock, NGICalendar, add_calendar, elapsed_seconds, to_sn
from .descriptions import CLOSE_NOTES
from .ids import rng
from .incidents import IncidentDraft, _pick
from .reference import ReferenceData

STATE = {"new": "1", "in_progress": "2", "on_hold": "3", "resolved": "6", "closed": "7", "canceled": "8"}


def _lognormal(r: np.random.Generator, median: float, sigma: float) -> float:
    return float(median * np.exp(sigma * r.standard_normal()))


def improvement(cfg: dict, day: dt.date) -> float:
    """0 before governance starts, rising linearly to 1 at the end of the ramp (D7c)."""
    ev = cfg["story_events"]["governance_improvement"]
    start = ev["start"]
    if day < start:
        return 0.0
    months = (day.year - start.year) * 12 + (day.month - start.month) + (day.day - 1) / 31
    return min(1.0, months / ev["ramp_months"])


class Lifecycle:
    def __init__(self, cfg: dict, ref: ReferenceData) -> None:
        self.cfg, self.ref = cfg, ref
        self.inc = cfg["incidents"]
        self.cal = NGICalendar(cfg)
        self.clock = BusinessClock(self.cal, cfg["sla"]["schedule"])
        self.cutoff = self.cal.local(cfg["time"]["end_date"], 0)
        self.autoclose = dt.timedelta(days=cfg["time"]["autoclose_days"])
        self.sla_clock = {d["priority"]: d["clock"] for d in cfg["sla"]["definitions"]}
        self.region_group = {site: g["name"] for g in cfg["organisation"]["assignment_groups"]
                             if g["name"].startswith("NGI Workplace Support") for site in g["sites"]}
        mix, weights = self.inc["category_mix"], self.inc["fcr_category_weights"]
        self.mean_fcr_weight = sum(mix[c] * weights[c] for c in mix)
        self.user_name = {u["sys_id"]: u["user_name"] for u in ref.tables["sys_user"]}

    # --- routing ---------------------------------------------------------
    def _fcr_probability(self, rec: dict, day: dt.date) -> float:
        ev = self.cfg["story_events"]["governance_improvement"]
        base = self.inc["first_contact_resolution_rate"]
        rate = base + (ev["fcr_rate_at_end"] - base) * improvement(self.cfg, day)
        category = rec["category"] if rec["category"] in self.inc["fcr_category_weights"] else self.inc["routing_fallback"]
        p = rate * self.inc["fcr_category_weights"][category] / self.mean_fcr_weight
        if rec["priority"] == "1":
            p *= self.inc["p1_fcr_factor"]
        return min(p, 0.97)

    def _escalation_group(self, r: np.random.Generator, draft: IncidentDraft) -> str:
        rec = draft.record
        if rec["subcategory"] in self.inc["subcategory_routing"]:
            return self.inc["subcategory_routing"][rec["subcategory"]]
        category = rec["category"] if rec["category"] in self.inc["escalation_routing"] else self.inc["routing_fallback"]
        group = _pick(r, self.inc["escalation_routing"][category])
        return group.replace("NGI Workplace Support - <region>", self.region_group[draft.site])

    def _route(self, r: np.random.Generator, draft: IncidentDraft) -> tuple[str, int]:
        day = draft.opened_local.date()
        if draft.forced_group:                              # story incidents (ERP wave, change-induced)
            return draft.forced_group, 1
        dq = self.cfg["data_quality_defects"]
        if dq["enabled"] and day < dq["retired_group"]["only_before"] and r.random() < dq["retired_group"]["rate"]:
            return dq["retired_group"]["name"], int(_pick(r, self.inc["reassignments_when_escalated"]))
        if r.random() < self._fcr_probability(draft.record, day):
            return "NGI Service Desk", 0
        return self._escalation_group(r, draft), int(_pick(r, self.inc["reassignments_when_escalated"]))

    # --- one incident ------------------------------------------------------
    def apply(self, r: np.random.Generator, draft: IncidentDraft) -> None:
        rec, tl = draft.record, draft.timeline
        opened = draft.opened_local
        prio = int(rec["priority"])
        clock = self.sla_clock[prio]
        factor = 1 - (1 - self.cfg["story_events"]["governance_improvement"]["resolution_time_factor_at_end"]) \
            * improvement(self.cfg, opened.date())

        group, reassignments = self._route(r, draft)
        agents = self.ref.agents_by_group.get(group, [])
        agent = agents[r.integers(len(agents))] if agents else ""

        # Cancelled incidents: short life, no resolution
        if r.random() < self.inc["cancel_rate"]:
            ended = add_calendar(opened, 3600 * _lognormal(r, **self.inc["cancel_after_hours"]))
            tl.update(canceled=ended)
            self._finish(rec, tl, opened, group, agent, reassignments, state="canceled" if ended <= self.cutoff else None, r=r)
            return

        # Response (first assignment / work start) in the SLA clock
        resp = self.inc["response_time_minutes"][prio]
        response = self.clock.add_in_clock(opened, 60 * _lognormal(r, resp["median"], resp["sigma"]), clock)

        # Resolution effort in the SLA clock, faster once governance improves
        if r.random() < self.inc["long_running_share"]:
            lo, hi = self.inc["long_running_days"]
            resolved = add_calendar(opened, 86400 * r.uniform(lo, hi))
            hold = (add_calendar(response, 3600 * r.uniform(1, 8)), None)          # vendor wait until resolved
            hold_reason = "4"
        else:
            res = self.inc["resolution_time_hours"][prio]
            effort = 3600 * _lognormal(r, res["median"], res["sigma"]) * factor
            resolved = self.clock.add_in_clock(opened, effort, clock)
            hold, hold_reason = None, ""
            if r.random() < self.inc["on_hold"]["rate"]:
                oh = self.inc["on_hold"]
                duration = 3600 * _lognormal(r, oh["median_hours"], oh["sigma"])
                hold_start = add_calendar(response, elapsed_seconds(response, resolved) / 2) if resolved > response else response
                hold = (hold_start, add_calendar(hold_start, duration))
                resolved = add_calendar(resolved, duration)
                hold_reason = _pick(r, self.inc["hold_reason_mix"])
        if resolved < response:
            resolved = response
        if hold and hold[1] is None:
            hold = (hold[0], resolved)

        # Reopen: resolved, reopened after 1–3 days, resolved again
        first_resolved, reopened = resolved, False
        if r.random() < self.inc["reopen_rate"]:
            gap_lo, gap_hi = self.inc["reopen"]["gap_days"]
            reopen_at = add_calendar(first_resolved, 86400 * r.uniform(gap_lo, gap_hi))
            extra = self.inc["reopen"]["extra_business_hours"]
            resolved = self.clock.add(reopen_at, 3600 * _lognormal(r, extra["median"], extra["sigma"]))
            reopened = True
            tl["reopened"] = reopen_at

        tl.update(response=response, resolved=resolved, first_resolved=first_resolved, hold=hold,
                  hold_reason=hold_reason, clock=clock)
        rec["reopen_count"] = "1" if reopened and tl["reopened"] <= self.cutoff else "0"
        self._finish(rec, tl, opened, group, agent, reassignments, state=None, r=r)

    # --- state at the cut-off and final fields -------------------------------
    def _finish(self, rec: dict, tl: dict, opened: dt.datetime, group: str, agent: str,
                reassignments: int, state: str | None, r: np.random.Generator) -> None:
        cutoff = self.cutoff
        rec["assignment_group"] = self.ref.group_id_by_name[group]
        rec["reassignment_count"] = str(reassignments)
        rec.setdefault("reopen_count", "0")
        last_update = opened

        if "canceled" in tl:
            if state == "canceled":
                rec.update(state=STATE["canceled"], active="false", closed_at=to_sn(tl["canceled"]))
                last_update = tl["canceled"]
            else:
                state = "new"
        else:
            resolved = tl["resolved"]
            hold = tl["hold"]
            if resolved <= cutoff:
                rec["resolved_at"] = to_sn(resolved)
                rec["resolved_by"] = agent
                code = _pick(r, self.inc["close_code_mix"])
                notes = CLOSE_NOTES[code]
                rec["close_code"], rec["close_notes"] = code, notes[r.integers(len(notes))]
                rec["calendar_stc"] = str(elapsed_seconds(opened, resolved))
                rec["business_stc"] = str(self.clock.between(opened, resolved))
                if resolved + self.autoclose <= cutoff:
                    closed = add_calendar(resolved, self.autoclose.total_seconds())
                    rec.update(state=STATE["closed"], active="false", closed_at=to_sn(closed))
                    last_update = closed
                else:
                    rec.update(state=STATE["resolved"], active="true")
                    last_update = resolved
            elif "reopened" in tl and tl["reopened"] <= cutoff:
                state = "in_progress"
                last_update = tl["reopened"]
            elif hold and hold[0] <= cutoff < hold[1]:
                state = "on_hold"
                rec["hold_reason"] = tl["hold_reason"]
                last_update = hold[0]
            elif tl["response"] <= cutoff:
                state = "in_progress"
                last_update = tl["response"]
            else:
                state = "new"

        if "state" not in rec:                                 # still open at the cut-off
            rec.update(state=STATE[state], active="true")
            if state != "new":
                rec["assigned_to"] = agent
            stale_before = add_calendar(cutoff, -5 * 86400)
            if state != "new" and last_update < stale_before:
                pass                                           # already inactive > 5 days
            elif state != "new" and opened < add_calendar(cutoff, -6 * 86400) \
                    and r.random() < self.inc["stale_open_share"]:
                last_update = add_calendar(opened, elapsed_seconds(opened, stale_before) * r.uniform(0.3, 1.0))
        else:
            rec["assigned_to"] = agent

        rec["incident_state"] = rec["state"]
        user = self.cfg["meta"]["generator_user"]
        rec.update(sys_created_on=rec["opened_at"], sys_updated_on=to_sn(max(last_update, opened)),
                   sys_created_by=user, sys_updated_by=user)
        rec.setdefault("hold_reason", "")


def apply_lifecycle(cfg: dict, ref: ReferenceData, drafts: list[IncidentDraft]) -> list[IncidentDraft]:
    """Complete every draft in place (in time order, one random stream) and return them."""
    life = Lifecycle(cfg, ref)
    r = rng(cfg["meta"]["seed"], "incidents.lifecycle")
    for draft in drafts:
        life.apply(r, draft)
    return drafts
