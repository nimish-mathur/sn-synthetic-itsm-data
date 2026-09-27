"""Command line: python -m sn_synth reference"""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import DEFAULT_CONFIG, REPO_ROOT, load_config
from .export import REFERENCE_OPTIONS, write_batches
from .reference import build_reference


def main() -> None:
    parser = argparse.ArgumentParser(prog="sn_synth", description="NGI synthetic ITSM data generator")
    parser.add_argument("command", choices=["reference"], help="what to generate")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out", default=None, help="output directory (default: output/ in the repo)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    out = Path(args.out) if args.out else REPO_ROOT / cfg["output"]["directory"]
    ref = build_reference(cfg)
    run_tag = cfg["meta"]["load_tag_prefix"] + "REF-01"
    files = write_batches(ref.tables, out / "reference", cfg["output"]["batch_size"], run_tag, REFERENCE_OPTIONS)

    print(f"Run tag: {run_tag}")
    for table, rows in ref.tables.items():
        print(f"  {table:20s} {len(rows):6d}")
    print(f"{len(files)} batch files + manifest.json written to {out / 'reference'}")


if __name__ == "__main__":
    main()
