"""Load and resolve the generator configuration (config/ngi.yaml)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "ngi.yaml"


def load_config(path: Path | str = DEFAULT_CONFIG, today: dt.date | None = None) -> dict[str, Any]:
    """Read the YAML config and resolve run-time values such as end_date: today."""
    with Path(path).open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if cfg["time"]["end_date"] == "today":
        cfg["time"]["end_date"] = today or dt.date.today()
    return cfg
