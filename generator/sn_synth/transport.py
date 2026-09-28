"""Send batch files to the ServiceNow loader endpoint, and roll back by manifest.

Credentials: the password comes from the SN_PASSWORD environment variable or is asked
for at run time. It is never written to a file or a log.
"""
from __future__ import annotations

import getpass
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import requests

from .export import LOAD_ORDER
from .ids import sys_id


class LoaderError(RuntimeError):
    pass


class LoaderClient:
    def __init__(self, instance: str, base_path: str, user: str, password: str,
                 timeout: int = 120, retries: int = 3, post: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if "CHANGE_ME" in base_path:
            raise LoaderError("loader.base_path in config/ngi.yaml still says CHANGE_ME – "
                              "copy the Base API path from the Scripted REST API record")
        self.base_url = f"https://{instance}.service-now.com{base_path.rstrip('/')}"
        self.timeout, self.retries, self._sleep = timeout, retries, sleep
        session = requests.Session()
        session.auth = (user, password)
        session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        self._post = post or session.post

    def __repr__(self) -> str:                       # never show credentials
        return f"LoaderClient({self.base_url})"

    def _call(self, resource: str, body: dict) -> dict:
        url = f"{self.base_url}/{resource}"
        for attempt in range(1, self.retries + 1):
            try:
                resp = self._post(url, data=json.dumps(body), timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == self.retries:
                    raise LoaderError(f"{resource}: no response after {attempt} attempts ({exc})") from exc
                self._sleep(2 ** attempt)
                continue
            if resp.status_code >= 500 and attempt < self.retries:
                self._sleep(2 ** attempt)
                continue
            if resp.status_code == 401:
                raise LoaderError("401 Unauthorized – check user and password")
            if resp.status_code == 404:
                raise LoaderError(f"404 Not Found – check loader.base_path ({url}) and that the API is active")
            if resp.status_code != 200:
                raise LoaderError(f"{resource}: HTTP {resp.status_code} {resp.text[:300]}")
            data = resp.json()
            return data.get("result", data)          # Scripted REST wraps bodies in "result"
        raise LoaderError(f"{resource}: failed after {self.retries} attempts")

    def send_batch(self, payload: dict) -> dict:
        return self._call("batch", payload)

    def rollback(self, table: str, ids: list[str]) -> int:
        return int(self._call("rollback", {"table": table, "ids": ids})["deleted"])


def client_from_config(cfg: dict) -> LoaderClient:
    lc = cfg["loader"]
    password = os.environ.get("SN_PASSWORD") or getpass.getpass(f"Password for {lc['user']}@{lc['instance']}: ")
    return LoaderClient(lc["instance"], lc["base_path"], lc["user"], password,
                        timeout=lc["timeout_seconds"], retries=lc["retries"])


def run_load(client, load_dir: Path, tables: list[str] | None = None, max_batches: int | None = None,
             stop_on_error: bool = True, printer: Callable[[str], None] = print) -> dict[str, Any]:
    """Send batch files in load order. Safe to re-run: existing records are skipped."""
    files = sorted(p for p in load_dir.glob("*.json") if p.name != "manifest.json")
    if tables:
        files = [p for p in files if p.name.split("-", 1)[1].rsplit("-", 1)[0] in tables]
    if max_batches is not None:
        files = files[:max_batches]
    totals: dict[str, Any] = {"batches": 0, "inserted": 0, "skipped": 0, "errors": [], "stopped": False}
    log_path = load_dir / "load-log.jsonl"
    with log_path.open("a", encoding="utf-8") as log:
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            result = client.send_batch(payload)
            totals["batches"] += 1
            totals["inserted"] += result.get("inserted", 0)
            totals["skipped"] += result.get("skipped", 0)
            errors = result.get("errors", [])
            log.write(json.dumps({"file": path.name, **result}, ensure_ascii=False) + "\n")
            printer(f"{path.name:32s} inserted {result.get('inserted', 0):4d}  skipped {result.get('skipped', 0):4d}"
                    f"  errors {len(errors)}")
            if errors:
                totals["errors"].extend(f"{path.name}: {e}" for e in errors)
                if stop_on_error:
                    totals["stopped"] = True
                    printer(f"STOPPED on errors in {path.name}. First error: {errors[0]}")
                    break
    return totals


def run_rollback(client, manifest_path: Path, tables: list[str] | None = None, chunk: int = 200,
                 printer: Callable[[str], None] = print) -> dict[str, int]:
    """Delete everything in the manifest, children before parents."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    deleted: dict[str, int] = {}
    for table in reversed(LOAD_ORDER):
        ids = manifest["tables"].get(table, [])
        if not ids or (tables and table not in tables):
            continue
        deleted[table] = sum(client.rollback(table, ids[i:i + chunk]) for i in range(0, len(ids), chunk))
        printer(f"  {table:20s} deleted {deleted[table]:6d} of {len(ids)}")
    return deleted


SMOKE_TAG = "NGI-SYNTH-SMOKE-02"


def smoke_payload() -> dict:
    """Two closed incidents dated 2025, for an end-to-end check of the transport."""
    records = []
    for n, opened in enumerate(["2025-07-03 07:15:00", "2025-10-14 06:50:00"], start=1):
        records.append({
            "sys_id": sys_id("incident", f"SMOKE-02-{n}"),
            "short_description": f"[SMOKE] NGI transport test {n}",
            "category": "software", "impact": "2", "urgency": "2", "priority": "3",
            "state": "7", "incident_state": "7", "active": "false",
            "opened_at": opened, "resolved_at": opened, "closed_at": opened,
            "close_code": "Solution provided", "close_notes": "Transport smoke test",
            "sys_created_on": opened, "sys_updated_on": opened,
            "sys_created_by": "ngi.synth.loader", "sys_updated_by": "ngi.synth.loader",
            "correlation_id": SMOKE_TAG,
        })
    return {"run_tag": SMOKE_TAG, "table": "incident",
            "options": {"keepSysFields": True, "runBusinessRules": False}, "resolve": {}, "records": records}


def run_smoke(client, printer: Callable[[str], None] = print) -> bool:
    """Insert 2 incidents, re-send (must skip), roll back (must delete 2)."""
    payload = smoke_payload()
    ids = [r["sys_id"] for r in payload["records"]]
    first = client.send_batch(json.loads(json.dumps(payload)))
    second = client.send_batch(json.loads(json.dumps(payload)))
    deleted = client.rollback("incident", ids)
    checks = {
        "insert 2": first.get("inserted") == 2 and not first.get("errors"),
        "re-send skips 2": second.get("skipped") == 2 and second.get("inserted") == 0,
        "rollback deletes 2": deleted == 2,
    }
    for name, ok in checks.items():
        printer(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if first.get("errors"):
        printer(f"  first error: {first['errors'][0]}")
    return all(checks.values())
