"""Command line.

    python -m sn_synth reference   -> reference data batch files
    python -m sn_synth preview     -> full dataset preview: changes, incidents, SLAs (not loadable yet)
    python -m sn_synth incidents   -> same as preview (kept for compatibility)
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .config import DEFAULT_CONFIG, REPO_ROOT, load_config
from .export import REFERENCE_OPTIONS, write_batches
from collections import Counter

from .incidents import monthly_counts
from .pipeline import generate_all
from .sla import attainment_by_quarter
from .reference import build_reference

PREVIEW_FIELDS = ["opened_at", "priority", "category", "subcategory", "short_description",
                  "state", "reassignment_count", "resolved_at", "close_code", "caused_by"]
STATE_LABELS = {"1": "New", "2": "In Progress", "3": "On Hold", "6": "Resolved", "7": "Closed", "8": "Canceled"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="sn_synth", description="NGI synthetic ITSM data generator")
    parser.add_argument("command", choices=["reference", "preview", "incidents"], help="what to generate")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out", default=None, help="output directory (default: output/ in the repo)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    out = Path(args.out) if args.out else REPO_ROOT / cfg["output"]["directory"]
    ref = build_reference(cfg)

    if args.command == "reference":
        run_tag = cfg["meta"]["load_tag_prefix"] + "REF-01"
        files = write_batches(ref.tables, out / "reference", cfg["output"]["batch_size"], run_tag, REFERENCE_OPTIONS)
        print(f"Run tag: {run_tag}")
        for table, rows in ref.tables.items():
            print(f"  {table:20s} {len(rows):6d}")
        print(f"{len(files)} batch files + manifest.json written to {out / 'reference'}")

    else:
        ds = generate_all(cfg)
        drafts = ds.incidents
        group_name = {v: k for k, v in ref.group_id_by_name.items()}
        print(f"History window: {cfg['time']['start_date']} to {cfg['time']['end_date']} (exclusive)")
        print("Incidents opened per month:")
        for month, n in monthly_counts(drafts).items():
            print(f"  {month}  {n:5d}  {'#' * (n // 50)}")
        print(f"Total: {len(drafts)}  (ERP wave: {sum(d.story == 'erp_wave' for d in drafts)}, "
              f"change-induced: {sum(d.story == 'change_induced' for d in drafts)})")
        states = Counter(d.record["state"] for d in drafts)
        print("State at history cut-off: " + ", ".join(f"{STATE_LABELS[k]} {v}" for k, v in sorted(states.items())))
        preview = out / "preview"
        preview.mkdir(parents=True, exist_ok=True)
        path = preview / "incidents.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: opens cleanly in Excel
            w = csv.writer(f)
            w.writerow(["site", "opened_local", "assignment_group", "business_hours_to_resolve"] + PREVIEW_FIELDS)
            for d in drafts:
                bstc = d.record.get("business_stc")
                w.writerow([d.site, d.opened_local.strftime("%Y-%m-%d %H:%M"),
                            group_name[d.record["assignment_group"]],
                            round(int(bstc) / 3600, 1) if bstc else ""] +
                           [d.record.get(k, "") for k in PREVIEW_FIELDS])
        print(f"Preview written to {path}")

        sla_rows = ds.sla_rows
        print(f"SLA records: {len(sla_rows)}")
        print("SLA attainment by quarter of completion (response | resolution):")
        response, resolution = attainment_by_quarter(sla_rows, "response"), attainment_by_quarter(sla_rows, "resolution")
        for q in resolution:
            print(f"  {q}   {response.get(q, 0):6.1%} | {resolution[q]:6.1%}")
        sla_path = preview / "task_sla.csv"
        fields = ["sla_name", "stage", "has_breached", "start_time", "end_time", "business_percentage",
                  "business_duration", "business_pause_duration"]
        with sla_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(fields)
            for r in sla_rows:
                w.writerow([r.get(k, "") for k in fields])
        print(f"SLA preview written to {sla_path}")

        changes = ds.changes
        closed = [c for c in changes if c.record["state"] == "3"]
        ok = sum(c.close_code != "unsuccessful" for c in closed)
        print(f"Changes: {len(changes)}  types: " + ", ".join(f"{t} {n}" for t, n in Counter(c.type for c in changes).items()))
        print(f"Change success rate (closed, incl. 'successful with issues'): {ok / len(closed):.1%}")
        chg_path = preview / "changes.csv"
        with chg_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["type", "group", "start_local", "state", "close_code", "short_description"])
            for c in changes:
                w.writerow([c.type, c.group, c.start_local.strftime("%Y-%m-%d %H:%M"), c.record["state"],
                            c.record.get("close_code", ""), c.record["short_description"]])
        print(f"Change preview written to {chg_path}")


if __name__ == "__main__":
    main()
