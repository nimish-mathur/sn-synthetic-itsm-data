"""Command line.

    python -m sn_synth reference   -> reference data batch files
    python -m sn_synth export      -> loadable batch files for every table + manifest + ground truth
    python -m sn_synth bundle      -> files to attach to the "NGI Synthetic Load" Fix Script (browser route)
    python -m sn_synth preview     -> full dataset preview: changes, incidents, SLAs (CSV for Excel)
    python -m sn_synth load --smoke                 -> end-to-end transport check (2 test incidents, rolled back)
    python -m sn_synth load [--tables a,b] [--max-batches N] [--continue-on-error]
    python -m sn_synth rollback --yes [--tables a,b] -> delete everything listed in output/load/manifest.json
    python -m sn_synth credentials --set [--show] | --check | --delete  -> password in Windows Credential Manager
    python -m sn_synth incidents   -> same as preview (kept for compatibility)
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .config import DEFAULT_CONFIG, REPO_ROOT, load_config
from .export import REFERENCE_OPTIONS, export_dataset, write_batches, write_upload_bundle
from collections import Counter

from .incidents import monthly_counts
from .pipeline import generate_all
from .sla import attainment_by_quarter
from .reference import build_reference

PREVIEW_FIELDS = ["opened_at", "priority", "category", "subcategory", "short_description",
                  "state", "reassignment_count", "resolved_at", "close_code", "caused_by"]
STATE_LABELS = {"1": "New", "2": "In Progress", "3": "On Hold", "6": "Resolved", "7": "Closed", "8": "Canceled"}


def _transport(args, cfg, out, tables, client_from_config, run_load, run_rollback, run_smoke) -> None:
    client = client_from_config(cfg)
    if args.command == "load" and args.smoke:
        print("Transport smoke test:")
        print("RESULT: " + ("PASS" if run_smoke(client) else "FAIL"))
    elif args.command == "load":
        totals = run_load(client, out / "load", tables, args.max_batches, not args.continue_on_error)
        print(f"Batches {totals['batches']} | inserted {totals['inserted']} | skipped {totals['skipped']} | "
              f"errors {len(totals['errors'])}" + ("  (STOPPED)" if totals["stopped"] else ""))
    else:
        run_rollback(client, out / "load" / "manifest.json", tables)


def main() -> None:
    parser = argparse.ArgumentParser(prog="sn_synth", description="NGI synthetic ITSM data generator")
    parser.add_argument("command", choices=["reference", "export", "bundle", "preview", "incidents", "load", "rollback", "credentials"], help="what to generate")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out", default=None, help="output directory (default: output/ in the repo)")
    parser.add_argument("--smoke", action="store_true", help="load: transport smoke test only")
    parser.add_argument("--tables", default=None, help="load/rollback: comma-separated table names")
    parser.add_argument("--max-batches", type=int, default=None, help="load: send at most N batch files")
    parser.add_argument("--continue-on-error", action="store_true", help="load: do not stop at the first error")
    parser.add_argument("--yes", action="store_true", help="rollback: confirm deletion")
    parser.add_argument("--set", action="store_true", help="credentials: verify and store the password")
    parser.add_argument("--check", action="store_true", help="credentials: test the stored password")
    parser.add_argument("--delete", action="store_true", help="credentials: remove the stored password")
    parser.add_argument("--show", action="store_true", help="credentials --set: show the password while typing")
    args = parser.parse_args()

    cfg = load_config(args.config)
    out = Path(args.out) if args.out else REPO_ROOT / cfg["output"]["directory"]
    tables = args.tables.split(",") if args.tables else None

    if args.command == "credentials":
        from . import credentials
        instance, user = cfg["loader"]["instance"], cfg["loader"]["user"]
        if args.set:
            credentials.set_password(instance, user, show=args.show)
        elif args.delete:
            credentials.delete(instance, user)
        else:
            credentials.check(instance, user)
        return

    if args.command in ("load", "rollback"):
        from .transport import LoaderError, client_from_config, run_load, run_rollback, run_smoke
        if args.command == "rollback" and not args.yes:
            print("Rollback deletes every record in output/load/manifest.json. Re-run with --yes to confirm.")
            return
        try:
            _transport(args, cfg, out, tables, client_from_config, run_load, run_rollback, run_smoke)
        except LoaderError as exc:
            raise SystemExit(f"ERROR: {exc}")
        return

    ref = build_reference(cfg)

    if args.command == "reference":
        run_tag = cfg["meta"]["load_tag_prefix"] + "REF-01"
        files = write_batches(ref.tables, out / "reference", cfg["output"]["batch_size"], run_tag, REFERENCE_OPTIONS)
        print(f"Run tag: {run_tag}")
        for table, rows in ref.tables.items():
            print(f"  {table:20s} {len(rows):6d}")
        print(f"{len(files)} batch files + manifest.json written to {out / 'reference'}")

    elif args.command == "bundle":
        from .transport import smoke_payload
        ds = generate_all(cfg)
        files = write_upload_bundle(ds, out / "upload", cfg["meta"]["load_tag_prefix"], smoke_payload())
        size = sum(p.stat().st_size for p in files) / 1e6
        print(f"{len(files)} files + manifest.json in {out / 'upload'}  ({size:.0f} MB)")
        print("  00-smoke-incident.json  -> attach alone for the smoke test (MODE = 'smoke')")
        print("  01-... to 09-...        -> attach all + manifest.json for the load (MODE = 'load')")

    elif args.command == "export":
        ds = generate_all(cfg)
        files, gt_path = export_dataset(ds, out, cfg["output"]["batch_size"], cfg["meta"]["load_tag_prefix"])
        per_table = Counter(p.name.split("-", 1)[1].rsplit("-", 1)[0] for p in files)
        print(f"History window: {cfg['time']['start_date']} to {cfg['time']['end_date']} (exclusive)")
        for table, n in per_table.items():
            rows = len(json.loads((out / "load" / "manifest.json").read_text(encoding="utf-8"))["tables"][table])
            print(f"  {table:20s} {rows:6d} records in {n:3d} batch files")
        print(f"{len(files)} batch files + manifest.json in {out / 'load'}")
        print(f"Ground truth: {gt_path}")

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
