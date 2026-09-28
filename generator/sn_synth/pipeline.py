"""Runs every generator module in the right order and returns the complete dataset."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .changes import ChangeDraft, generate_changes, induced_incident_specs
from .incidents import IncidentDraft, generate_arrivals, generate_induced
from .lifecycle import apply_lifecycle
from .reference import ReferenceData, build_reference
from .sla import build_sla_rows


@dataclass
class Dataset:
    reference: ReferenceData
    changes: list[ChangeDraft]
    incidents: list[IncidentDraft]
    sla_rows: list[dict[str, Any]]


def generate_all(cfg: dict) -> Dataset:
    ref = build_reference(cfg)
    changes = generate_changes(cfg, ref)                     # changes first: failures cause incidents
    incidents = generate_arrivals(cfg, ref) + generate_induced(cfg, ref, induced_incident_specs(cfg, changes))
    incidents.sort(key=lambda d: (d.opened_local, d.key))
    apply_lifecycle(cfg, ref, incidents)
    return Dataset(reference=ref, changes=changes, incidents=incidents, sla_rows=build_sla_rows(cfg, incidents))
