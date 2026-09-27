"""Command line.

    python -m sn_synth reference   -> reference data batch files
    python -m sn_synth incidents   -> incident arrivals preview (part 1, not loadable yet)
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .config import DEFAULT_CONFIG, REPO_ROOT, load_config
from .export import REFERENCE_OPTIONS, write_batches
from .incidents import generate_arrivals, monthly_counts
from .reference import build_reference

PREVIEW_FIELDS = ["opened_at", "priority", "impact", "urgency", "category", "subcategory",
                  "short_description", "caused_by"]


def main() -> None:
    parser = argparse.ArgumentParser(prog="sn_synth", description="NGI synthetic ITSM data generator")
    parser.add_argument("command", choices=["reference", "incidents"], help="what to generate")
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

    elif args.command == "incidents":
        drafts = generate_arrivals(cfg, ref)
        print(f"History window: {cfg['time']['start_date']} to {cfg['time']['end_date']} (exclusive)")
        print("Incidents opened per month:")
        for month, n in monthly_counts(drafts).items():
            print(f"  {month}  {n:5d}  {'#' * (n // 50)}")
        print(f"Total: {len(drafts)}  (of which ERP wave: {sum(d.story == 'erp_wave' for d in drafts)})")
        preview = out / "preview"
        preview.mkdir(parents=True, exist_ok=True)
        path = preview / "incident_arrivals.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: opens cleanly in Excel
            w = csv.writer(f)
            w.writerow(["site", "opened_local"] + PREVIEW_FIELDS)
            for d in drafts:
                w.writerow([d.site, d.opened_local.strftime("%Y-%m-%d %H:%M")] +
                           [d.record.get(k, "") for k in PREVIEW_FIELDS])
        print(f"Preview written to {path}")


if __name__ == "__main__":
    main()
