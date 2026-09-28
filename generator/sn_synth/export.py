"""Write generated records as JSON batch files for the ServiceNow loader, plus the
manifest (sys_ids per table, for rollback) and the ground truth (expected counts)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

# Parents before children, so every reference points to a record that already exists:
# users -> groups -> changes -> incidents (caused_by -> change) -> SLAs (task -> incident).
LOAD_ORDER = ["core_company", "cmn_location", "cmn_department", "sys_user", "sys_user_group",
              "sys_user_grmember", "change_request", "incident", "task_sla"]

# Reference data: keep our dates, let business rules run (e.g. group membership logic).
REFERENCE_OPTIONS = {"keepSysFields": True, "runBusinessRules": True}
# History: keep our dates, no business rules (no SLA engine, no notifications) – tested in T7.
HISTORY_OPTIONS = {"keepSysFields": True, "runBusinessRules": False}

OPTIONS = {t: REFERENCE_OPTIONS for t in LOAD_ORDER[:6]} | {t: HISTORY_OPTIONS for t in LOAD_ORDER[6:]}

# Name -> sys_id lookups the loader performs on the instance (the SLA definitions and the
# schedule are created in ServiceNow in T8.9, so their sys_ids are only known there).
RESOLVE = {
    "task_sla": {
        "sla": {"table": "contract_sla", "match_field": "name", "source_key": "sla_name"},
        "schedule": {"table": "cmn_schedule", "match_field": "name", "source_key": "schedule_name"},
    }
}


def write_batches(tables: dict[str, list[dict[str, Any]]], out_dir: Path, batch_size: int,
                  run_tag: str, options: dict[str, Any] | None = None) -> list[Path]:
    """One JSON file per batch plus manifest.json. `options` overrides the per-table defaults."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files, manifest = [], {"run_tag": run_tag, "tables": {}}
    for order, table in enumerate(LOAD_ORDER, start=1):
        rows = tables.get(table, [])
        if not rows:
            continue
        manifest["tables"][table] = [row["sys_id"] for row in rows]
        for n, start in enumerate(range(0, len(rows), batch_size), start=1):
            path = out_dir / f"{order:02d}-{table}-{n:04d}.json"
            payload = {"run_tag": run_tag, "table": table, "options": options or OPTIONS[table],
                       "resolve": RESOLVE.get(table, {}), "records": rows[start:start + batch_size]}
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            files.append(path)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return files


def dataset_tables(ds) -> dict[str, list[dict[str, Any]]]:
    return {**ds.reference.tables,
            "change_request": [c.record for c in ds.changes],
            "incident": [d.record for d in ds.incidents],
            "task_sla": ds.sla_rows}


def ground_truth(ds) -> dict[str, Any]:
    """Expected counts after loading. T9 compares the instance against these numbers."""
    inc = [d.record for d in ds.incidents]
    chg = [c.record for c in ds.changes]
    sla = ds.sla_rows

    def by(rows, *keys):
        return dict(sorted(Counter("|".join(str(r.get(k, "")) for k in keys) for r in rows).items()))

    return {
        "record_counts": {t: len(rows) for t, rows in dataset_tables(ds).items()},
        "incident": {
            "by_opened_month": dict(sorted(Counter(r["opened_at"][:7] for r in inc).items())),
            "by_state": by(inc, "state"),
            "by_priority": by(inc, "priority"),
            "by_category": by(inc, "category"),
            "with_caused_by": sum("caused_by" in r for r in inc),
        },
        "change_request": {
            "by_state": by(chg, "state"),
            "by_type": by(chg, "type"),
            "by_close_code": by(chg, "close_code"),
        },
        "task_sla": {
            "by_definition_stage": by(sla, "sla_name", "stage"),
            "breached_by_definition": dict(sorted(Counter(r["sla_name"] for r in sla
                                                          if r["has_breached"] == "true").items())),
        },
        "note": "Months are UTC (as stored in ServiceNow). Counts only; KPI values follow in P4.",
    }


def export_dataset(ds, out_dir: Path, batch_size: int, tag_prefix: str) -> tuple[list[Path], Path]:
    files = write_batches(dataset_tables(ds), out_dir / "load", batch_size, tag_prefix + "LOAD-01")
    gt_dir = out_dir / "ground_truth"
    gt_dir.mkdir(parents=True, exist_ok=True)
    gt_path = gt_dir / "counts.json"
    gt_path.write_text(json.dumps(ground_truth(ds), indent=1, ensure_ascii=False), encoding="utf-8")
    return files, gt_path
