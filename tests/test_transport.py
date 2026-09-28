import json

import pytest
import requests

from sn_synth.export import LOAD_ORDER
from sn_synth.transport import LoaderClient, LoaderError, run_load, run_rollback, run_smoke, smoke_payload


class FakeResponse:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body or {}, text

    def json(self):
        return self._body


class FakeClient:
    """Stands in for the instance: remembers inserted sys_ids."""

    def __init__(self, fail_on=None):
        self.store, self.sent, self.fail_on = {}, [], fail_on

    def send_batch(self, payload):
        self.sent.append(payload["table"])
        res = {"table": payload["table"], "inserted": 0, "skipped": 0, "errors": []}
        for r in payload["records"]:
            if payload["table"] == self.fail_on:
                res["errors"].append("boom")
            elif r["sys_id"] in self.store:
                res["skipped"] += 1
            else:
                self.store[r["sys_id"]] = payload["table"]
                res["inserted"] += 1
        return res

    def rollback(self, table, ids):
        gone = [i for i in ids if self.store.get(i) == table]
        for i in gone:
            del self.store[i]
        return len(gone)


@pytest.fixture
def load_dir(tmp_path):
    manifest = {"tables": {}}
    for order, table in enumerate(["sys_user", "incident", "task_sla"], start=1):
        ids = [f"{order:02d}{n:030x}" for n in range(3)]
        manifest["tables"][table] = ids
        payload = {"table": table, "options": {}, "resolve": {}, "records": [{"sys_id": i} for i in ids]}
        (tmp_path / f"{order:02d}-{table}-0001.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def client_with(responses):
    calls = []

    def post(url, data, timeout):
        calls.append(url)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return LoaderClient("dev0", "/api/x/ngi_synth", "admin", "secret", post=post, sleep=lambda s: None), calls


def test_load_in_order_and_idempotent(load_dir):
    fake = FakeClient()
    first = run_load(fake, load_dir, printer=lambda s: None)
    assert fake.sent == ["sys_user", "incident", "task_sla"]
    assert first["inserted"] == 9
    again = run_load(fake, load_dir, printer=lambda s: None)
    assert again["inserted"] == 0 and again["skipped"] == 9


def test_load_stops_on_first_error(load_dir):
    fake = FakeClient(fail_on="incident")
    totals = run_load(fake, load_dir, printer=lambda s: None)
    assert totals["stopped"] and fake.sent == ["sys_user", "incident"]


def test_load_filters_and_limits(load_dir):
    fake = FakeClient()
    run_load(fake, load_dir, tables=["incident", "task_sla"], max_batches=1, printer=lambda s: None)
    assert fake.sent == ["incident"]


def test_load_writes_log(load_dir):
    run_load(FakeClient(), load_dir, printer=lambda s: None)
    lines = (load_dir / "load-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["file"].startswith("01-sys_user")


def test_rollback_children_first(load_dir):
    fake = FakeClient()
    run_load(fake, load_dir, printer=lambda s: None)
    order = []
    original = fake.rollback
    fake.rollback = lambda t, ids: order.append(t) or original(t, ids)
    deleted = run_rollback(fake, load_dir / "manifest.json", printer=lambda s: None)
    assert order == [t for t in reversed(LOAD_ORDER) if t in {"sys_user", "incident", "task_sla"}]
    assert deleted == {"task_sla": 3, "incident": 3, "sys_user": 3} and not fake.store


def test_smoke_passes_against_fake():
    assert run_smoke(FakeClient(), printer=lambda s: None)


def test_smoke_payload_satisfies_data_policy():
    for r in smoke_payload()["records"]:
        assert r["state"] == "7" and r["close_code"] and r["close_notes"]


def test_client_retries_server_errors():
    client, calls = client_with([FakeResponse(503), FakeResponse(200, {"result": {"inserted": 1}})])
    assert client.send_batch({"records": []}) == {"inserted": 1}
    assert calls == ["https://dev0.service-now.com/api/x/ngi_synth/batch"] * 2


def test_client_retries_timeouts_then_gives_up():
    client, _ = client_with([requests.Timeout(), requests.Timeout(), requests.Timeout()])
    with pytest.raises(LoaderError, match="no response"):
        client.send_batch({})


def test_client_clear_messages():
    client, _ = client_with([FakeResponse(401)])
    with pytest.raises(LoaderError, match="401"):
        client.send_batch({})
    client, _ = client_with([FakeResponse(404)])
    with pytest.raises(LoaderError, match="base_path"):
        client.send_batch({})


def test_unconfigured_base_path_refused():
    with pytest.raises(LoaderError, match="CHANGE_ME"):
        LoaderClient("dev0", "/api/CHANGE_ME/ngi_synth", "admin", "secret")


def test_password_never_in_repr():
    client, _ = client_with([])
    assert "secret" not in repr(client)
