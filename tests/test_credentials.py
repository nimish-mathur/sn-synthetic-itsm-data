import keyring
import pytest
from keyring.backend import KeyringBackend

from sn_synth import credentials


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError()
        del self.store[(service, username)]


class Resp:
    def __init__(self, status):
        self.status_code = status


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    monkeypatch.delenv("SN_PASSWORD", raising=False)
    return kr


def asker(*answers):
    it = iter(answers)
    return lambda prompt: next(it)


def test_set_saves_only_a_verified_password(memory_keyring):
    ok = credentials.set_password("dev0", "admin", ask=asker("pw", "pw"), get=lambda *a, **k: Resp(200),
                                  printer=lambda s: None)
    assert ok and memory_keyring.store[(credentials.SERVICE, "admin@dev0")] == "pw"


def test_wrong_password_is_not_saved(memory_keyring):
    ok = credentials.set_password("dev0", "admin", ask=asker("bad", "bad"), get=lambda *a, **k: Resp(401),
                                  printer=lambda s: None)
    assert not ok and not memory_keyring.store


def test_mismatched_entries_not_verified_or_saved(memory_keyring):
    calls = []
    ok = credentials.set_password("dev0", "admin", ask=asker("a", "b"),
                                  get=lambda *a, **k: calls.append(1) or Resp(200), printer=lambda s: None)
    assert not ok and not calls and not memory_keyring.store


def test_lookup_order(monkeypatch, memory_keyring, tmp_path):
    prompted = lambda prompt: "typed"
    assert credentials.get_password("dev0", "admin", ask=prompted, root=tmp_path) == "typed"
    memory_keyring.set_password(credentials.SERVICE, "admin@dev0", "stored")
    assert credentials.get_password("dev0", "admin", ask=prompted, root=tmp_path) == "stored"
    (tmp_path / ".gitignore").write_text("output/\n.env\n", encoding="utf-8")
    (tmp_path / ".env").write_text('SN_PASSWORD="from-file"\n', encoding="utf-8")
    assert credentials.get_password("dev0", "admin", ask=prompted, root=tmp_path) == "from-file"
    monkeypatch.setenv("SN_PASSWORD", "env")
    assert credentials.get_password("dev0", "admin", ask=prompted, root=tmp_path) == "env"


def test_env_file_refused_if_not_git_ignored(tmp_path):
    (tmp_path / ".gitignore").write_text("output/\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SN_PASSWORD=x\n", encoding="utf-8")
    with pytest.raises(credentials.CredentialError, match="gitignore"):
        credentials.read_env_file(tmp_path)


def test_real_repo_ignores_env_file():
    assert credentials.env_file_is_ignored()


def test_show_mode_asks_once(memory_keyring):
    asked = []
    ok = credentials.set_password("dev0", "admin", ask=lambda p: asked.append(p) or "pw",
                                  get=lambda *a, **k: Resp(200), printer=lambda s: None, show=True)
    assert ok and len(asked) == 1


def test_delete(memory_keyring):
    memory_keyring.set_password(credentials.SERVICE, "admin@dev0", "x")
    credentials.delete("dev0", "admin", printer=lambda s: None)
    assert not memory_keyring.store
    credentials.delete("dev0", "admin", printer=lambda s: None)     # no error when already gone


def test_verify_single_attempt():
    calls = []
    ok, msg = credentials.verify("dev0", "admin", "x", get=lambda *a, **k: calls.append(1) or Resp(401))
    assert not ok and "401" in msg and len(calls) == 1
