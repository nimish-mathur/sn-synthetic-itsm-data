import datetime as dt
import json

import pytest

from sn_synth.config import load_config
from sn_synth.export import LOAD_ORDER, UPLOAD_CHUNK, write_upload_bundle
from sn_synth.pipeline import generate_all
from sn_synth.transport import smoke_payload


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    cfg = load_config(today=dt.date(2026, 9, 27))
    ds = generate_all(cfg)
    out = tmp_path_factory.mktemp("upload")
    files = write_upload_bundle(ds, out, cfg["meta"]["load_tag_prefix"], smoke_payload())
    return ds, out, files


def test_smoke_file_first_and_names_sort_in_load_order(bundle):
    _, _, files = bundle
    assert files[0].name == "00-smoke-incident.json"
    names = [p.name for p in files]
    assert names == sorted(names)
    tables = [json.loads(p.read_text())["table"] for p in files[1:]]
    assert [LOAD_ORDER.index(t) for t in tables] == sorted(LOAD_ORDER.index(t) for t in tables)


def test_files_are_ascii_and_small(bundle):
    _, _, files = bundle
    for p in files:
        p.read_bytes().decode("ascii")                  # raises if any non-ASCII byte
        assert p.stat().st_size < 2_000_000
        assert len(json.loads(p.read_text())["records"]) <= UPLOAD_CHUNK


def test_accents_survive_round_trip(bundle):
    ds, out, _ = bundle
    names = {u["last_name"] for u in ds.reference.tables["sys_user"]}
    loaded = set()
    for p in sorted(out.glob("04-sys_user-*.json")):
        loaded |= {r["last_name"] for r in json.loads(p.read_text())["records"]}
    assert loaded == names and any(ch > "\x7f" for n in names for ch in n)


def test_manifest_covers_every_record(bundle):
    ds, out, files = bundle
    manifest = json.loads((out / "manifest.json").read_text())
    counted = {}
    for p in files[1:]:
        b = json.loads(p.read_text())
        counted[b["table"]] = counted.get(b["table"], 0) + len(b["records"])
    assert counted == {t: len(ids) for t, ids in manifest["tables"].items()}
    assert counted["task_sla"] == len(ds.sla_rows)
