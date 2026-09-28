"""Password storage in the operating system's secure store.

On Windows this is Windows Credential Manager (encrypted, tied to your Windows login).
The password is never written to a file in the repo, a log, or the console.

Lookup order used by the loader:
    SN_PASSWORD env var  ->  .env file in the repo root (only if git-ignored)  ->  secure store  ->  prompt.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Callable

import keyring
import requests

SERVICE = "sn-synthetic-itsm-data"
REPO_ROOT = Path(__file__).resolve().parents[2]


class CredentialError(RuntimeError):
    pass


def env_file_is_ignored(root: Path = REPO_ROOT) -> bool:
    """True if .gitignore excludes .env (GitHub's Python template does)."""
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return False
    lines = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
    return bool(lines & {".env", "/.env", "*.env", ".env*"})


def read_env_file(root: Path = REPO_ROOT) -> str | None:
    """SN_PASSWORD from <repo>/.env, refusing to use it if git would track the file."""
    path = root / ".env"
    if not path.exists():
        return None
    if not env_file_is_ignored(root):
        raise CredentialError(".env exists but is NOT in .gitignore – add a line '.env' before using it")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "SN_PASSWORD":
            return value.strip().strip('"').strip("'") or None
    return None


def account(instance: str, user: str) -> str:
    return f"{user}@{instance}"


def verify(instance: str, user: str, password: str, get: Callable | None = None) -> tuple[bool, str]:
    """One authenticated read of the user's own record. One attempt only, to avoid lock-outs."""
    get = get or requests.get
    url = f"https://{instance}.service-now.com/api/now/table/sys_user"
    try:
        resp = get(url, params={"sysparm_query": f"user_name={user}", "sysparm_fields": "user_name",
                                "sysparm_limit": "1"},
                   auth=(user, password), headers={"Accept": "application/json"}, timeout=30)
    except requests.RequestException as exc:
        return False, f"no response from instance ({exc.__class__.__name__}); is the PDI awake?"
    if resp.status_code == 401:
        return False, "401 Unauthorized: wrong password (nothing saved)"
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    return True, "password accepted by the instance"


def set_password(instance: str, user: str, ask: Callable[[str], str] | None = None,
                 get: Callable | None = None, printer: Callable[[str], None] = print, show: bool = False) -> bool:
    """show=True: typed/pasted text is visible (clear the screen afterwards with `cls`)."""
    ask = ask or (input if show else getpass.getpass)
    first = ask(f"Password for {account(instance, user)}: ")
    second = first if show else ask("Same password again: ")
    if not first or first != second:
        printer("The two entries differ or are empty. Nothing saved.")
        return False
    ok, message = verify(instance, user, first, get)
    printer(message)
    if ok:
        keyring.set_password(SERVICE, account(instance, user), first)
        printer(f"Saved in the secure store ({keyring.get_keyring().__class__.__name__}).")
    return ok


def check(instance: str, user: str, get: Callable | None = None, printer: Callable[[str], None] = print) -> bool:
    stored = keyring.get_password(SERVICE, account(instance, user))
    if not stored:
        printer("No password stored. Run: python -m sn_synth credentials --set")
        return False
    ok, message = verify(instance, user, stored, get)
    printer(f"Stored password: {message}")
    return ok


def delete(instance: str, user: str, printer: Callable[[str], None] = print) -> None:
    try:
        keyring.delete_password(SERVICE, account(instance, user))
        printer("Stored password deleted.")
    except keyring.errors.PasswordDeleteError:
        printer("No stored password to delete.")


def get_password(instance: str, user: str, ask: Callable[[str], str] = getpass.getpass,
                 root: Path = REPO_ROOT) -> str:
    return (os.environ.get("SN_PASSWORD")
            or read_env_file(root)
            or keyring.get_password(SERVICE, account(instance, user))
            or ask(f"Password for {account(instance, user)}: "))
