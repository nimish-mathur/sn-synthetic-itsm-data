"""Deterministic identifiers: the same input always gives the same sys_id."""
from __future__ import annotations

import uuid

import numpy as np

# Fixed namespace for this project. Changing it changes every sys_id.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "sn-synthetic-itsm-data/ngi")


def sys_id(table: str, key: str) -> str:
    """Return a 32-character lowercase hex sys_id for (table, natural key)."""
    return uuid.uuid5(NAMESPACE, f"{table}:{key}").hex


def rng(seed: int, stream: str) -> np.random.Generator:
    """Independent random stream per module, so changing one module
    does not reshuffle the data produced by another."""
    stream_key = int(uuid.uuid5(NAMESPACE, stream).hex[:8], 16)
    return np.random.default_rng([seed, stream_key])
