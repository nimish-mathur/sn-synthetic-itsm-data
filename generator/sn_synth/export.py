"""Write generated records as JSON batch files for the ServiceNow loader."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Parents before children, so every reference points to a record that already exists.
LOAD_ORDER = ["core_company", "cmn_location", "cmn_department",
              "sys_user", "sys_user_group", "sys_user_grmember"]

# Reference data: keep our dates, but let business rules run (e.g. role inheritance).
REFERENCE_OPTIONS = {"keepSysFields": True, "runBusinessRules": True}


def write_batches(tables: dict[str, list[dict[str, Any]]], out_dir: Path, batch_size: int,
                  run_tag: str, options: dict[str, Any]) -> list[Path]:
    """Write one JSON file per batch plus manifest.json (sys_ids per table, used for rollback)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files, manifest = [], {"run_tag": run_tag, "tables": {}}
    for order, table in enumerate(LOAD_ORDER, start=1):
        rows = tables.get(table, [])
        manifest["tables"][table] = [row["sys_id"] for row in rows]
        for n, start in enumerate(range(0, len(rows), batch_size), start=1):
            path = out_dir / f"{order:02d}-{table}-{n:04d}.json"
            payload = {"run_tag": run_tag, "table": table, "options": options,
                       "records": rows[start:start + batch_size]}
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            files.append(path)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return files
