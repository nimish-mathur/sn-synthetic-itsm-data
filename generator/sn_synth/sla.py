"""SLA records (task_sla) computed from each incident's timeline.

ServiceNow's SLA engine only runs in real time, so for backdated history the
generator computes what the engine would have recorded: start, stop, pauses,
breach flag, durations and percentages. Two rows per incident: response and
resolution, using the 8 NGI SLA definitions (D4).

References to the SLA definition and schedule are kept as names (`sla_name`,
`schedule_name`); the export step (T8.7) replaces them with the sys_ids read
from the instance after the definitions are created (T8.9).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from .calendar import BusinessClock, NGICalendar, add_calendar, elapsed_seconds, to_sn
from .ids import sys_id
from .incidents import IncidentDraft

EPOCH = dt.datetime(1970, 1, 1)


def sn_duration(seconds: float) -> str:
    """ServiceNow stores durations as a date-time offset from 1970-01-01 00:00:00."""
    return (EPOCH + dt.timedelta(seconds=max(0, int(seconds)))).strftime("%Y-%m-%d %H:%M:%S")


class SlaBuilder:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.cal = NGICalendar(cfg)
        self.clock = BusinessClock(self.cal, cfg["sla"]["schedule"])
        self.cutoff = self.cal.local(cfg["time"]["end_date"], 0)
        self.defs = {(d["priority"], d["target"]): d for d in cfg["sla"]["definitions"]}
        self.stage = cfg["instance_facts"]["task_sla_stages"]
        self.schedule_name = cfg["sla"]["schedule"]["name"]
        self.timezone = cfg["time"]["local_timezone"]
        self.user = cfg["meta"]["generator_user"]

    def _elapsed(self, a: dt.datetime, b: dt.datetime, clock: str) -> int:
        if b <= a:
            return 0
        return elapsed_seconds(a, b) if clock == "24x7" else self.clock.between(a, b)

    def _row(self, draft: IncidentDraft, target: str) -> dict[str, Any]:
        tl, rec = draft.timeline, draft.record
        d = self.defs[(int(rec["priority"]), target)]
        clock, target_s = d["clock"], d["minutes"] * 60
        start, cutoff = draft.opened_local, self.cutoff

        # Stop moment and stage. The resolution SLA pauses while On Hold and while an
        # incident sits Resolved before being reopened; it stops at the final resolution.
        pause_windows: list[tuple[dt.datetime, dt.datetime]] = []
        if "canceled" in tl:
            end = tl["canceled"] if tl["canceled"] <= cutoff else None
            stage = "cancelled" if end else "in_progress"
            if target == "response" and end is None:
                stage = "in_progress"
        elif target == "response":
            end = tl["response"] if tl["response"] <= cutoff else None
            stage = "completed" if end else "in_progress"
        else:
            end = tl["resolved"] if tl["resolved"] <= cutoff else None
            stage = "completed" if end else "in_progress"
            hold = tl.get("hold")
            if hold:
                pause_windows.append(hold)
            if "reopened" in tl:
                pause_windows.append((tl["first_resolved"], tl["reopened"]))
            if end is None and any(lo <= cutoff < hi for lo, hi in pause_windows):
                stage = "paused"
        measured_to = end or cutoff

        # Pauses, clipped to the measured period
        pause_cal = pause_clock = 0
        for window in pause_windows:
            lo, hi = max(window[0], start), min(window[1], measured_to)
            if hi > lo:
                pause_cal += elapsed_seconds(lo, hi)
                pause_clock += self._elapsed(lo, hi, clock)

        cal_elapsed = max(0, elapsed_seconds(start, measured_to) - pause_cal)
        clock_elapsed = max(0, self._elapsed(start, measured_to, clock) - pause_clock)
        original_breach = self.clock.add_in_clock(start, target_s, clock)
        planned_end = self.clock.add_in_clock(start, target_s + pause_clock, clock)
        target_cal_span = max(1, elapsed_seconds(start, original_breach))

        row = {
            "sys_id": sys_id("task_sla", f"{draft.key}:{target}"),
            "task": rec["sys_id"],
            "sla_name": d["name"],
            "stage": self.stage[stage],
            "active": "true" if stage in ("in_progress", "paused") else "false",
            "has_breached": "true" if clock_elapsed > target_s else "false",
            "start_time": to_sn(start),
            "planned_end_time": to_sn(planned_end),
            "original_breach_time": to_sn(original_breach),
            "duration": sn_duration(cal_elapsed),
            "business_duration": sn_duration(clock_elapsed),
            "pause_duration": sn_duration(pause_cal),
            "business_pause_duration": sn_duration(pause_clock),
            "percentage": f"{100 * cal_elapsed / target_cal_span:.2f}",
            "business_percentage": f"{100 * clock_elapsed / target_s:.2f}",
            "time_left": sn_duration(elapsed_seconds(measured_to, planned_end)),
            "business_time_left": sn_duration(target_s - clock_elapsed),
            "timezone": self.timezone,
            "sys_created_on": to_sn(start),
            "sys_updated_on": to_sn(measured_to),
            "sys_created_by": self.user,
            "sys_updated_by": self.user,
        }
        if clock != "24x7":
            row["schedule_name"] = self.schedule_name
        if end is not None:
            row["end_time"] = to_sn(end)
        return row

    def rows(self, draft: IncidentDraft) -> list[dict[str, Any]]:
        return [self._row(draft, "response"), self._row(draft, "resolution")]


def build_sla_rows(cfg: dict, drafts: list[IncidentDraft]) -> list[dict[str, Any]]:
    builder = SlaBuilder(cfg)
    return [row for d in drafts for row in builder.rows(d)]


def attainment_by_quarter(rows: list[dict[str, Any]], target: str) -> dict[str, float]:
    """Share of completed SLAs of the given target that did not breach, by quarter of completion."""
    done: dict[str, list[bool]] = {}
    for r in rows:
        if r["stage"] == "completed" and (" response " in f" {r['sla_name']} ") == (target == "response"):
            year, month = int(r["end_time"][:4]), int(r["end_time"][5:7])
            quarter = f"{year}-Q{(month - 1) // 3 + 1}"
            done.setdefault(quarter, []).append(r["has_breached"] == "false")
    return {q: sum(v) / len(v) for q, v in sorted(done.items())}
