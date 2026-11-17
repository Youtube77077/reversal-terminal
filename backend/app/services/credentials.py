"""Encrypted storage for Polymarket live-trading credentials entered in the app/website.

* Stored at  <data_dir>/live_credentials.enc  (AES-256-GCM, file mode 600), never in the
  database, backups, exports or Git.
* The encryption key is derived from SESSION_SECRET (or the generated session.key file).
* The browser can WRITE credentials but only ever reads back a masked summary.
* On save (and on every backend start) they are handed to the local executor process
  over the token-protected localhost API; the executor keeps them in memory only.

Environment variables (POLYMARKET_PRIVATE_KEY, ...) still work and take precedence in
the executor when present.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import get_settings

FIELDS = ("private_key", "wallet_address", "relayer_key", "relayer_address", "builder_key", "builder_secret",
          "builder_passphrase")


def _path() -> Path:
    return Path(get_settings().data_dir) / "live_credentials.enc"


def _key() -> bytes:
    s = get_settings()
    base = s.session_secret.encode() if s.session_secret else None
    if base is None:
        f = Path(s.data_dir) / "session.key"
        if not f.exists():
            f.write_text(secrets.token_hex(32), encoding="utf-8")
        base = f.read_text(encoding="utf-8").encode()
    return hashlib.sha256(b"reversal-live-credentials|" + base).digest()


def validate(c: dict) -> dict:
    out = {k: (str(c.get(k) or "").strip()) for k in FIELDS}
    pk = out["private_key"]
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk
        out["private_key"] = pk
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", pk or ""):
        raise ValueError("Private key must be 64 hex characters (optionally starting with 0x).")
    for f in ("wallet_address", "relayer_address"):
        if out[f] and not re.fullmatch(r"0x[0-9a-fA-F]{40}", out[f]):
            raise ValueError(f"{f.replace('_', ' ')} must be a 0x… address with 40 hex characters.")
    b = [out["builder_key"], out["builder_secret"], out["builder_passphrase"]]
    if any(b) and not all(b):
        raise ValueError("Builder credentials need all three: key, secret and passphrase.")
    return out


def save(c: dict) -> None:
    data = json.dumps(validate(c)).encode()
    nonce = os.urandom(12)
    blob = nonce + AESGCM(_key()).encrypt(nonce, data, b"v1")
    p = _path()
    p.write_bytes(base64.b64encode(blob))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def load() -> dict | None:
    p = _path()
    if not p.exists():
        return None
    try:
        raw = base64.b64decode(p.read_bytes())
        return json.loads(AESGCM(_key()).decrypt(raw[:12], raw[12:], b"v1"))
    except Exception:
        return None


def delete() -> None:
    p = _path()
    if p.exists():
        p.write_bytes(os.urandom(len(p.read_bytes())))  # overwrite before unlinking
        p.unlink()


def masked() -> dict:
    c = load()
    if not c:
        return {"configured": False}
    pk = c.get("private_key", "")
    return {
        "configured": True,
        "private_key": f"{pk[:6]}…{pk[-4:]}" if pk else None,
        "wallet_address": c.get("wallet_address") or None,
        "relayer_key": bool(c.get("relayer_key")),
        "builder_key": bool(c.get("builder_key")),
        "gasless": bool(c.get("relayer_key") or c.get("builder_key")),
    }


async def push_to_executor(live_enabled: bool) -> dict:
    """Send stored credentials + the live switch to the executor (localhost, token-protected)."""
    s = get_settings()
    c = load() or {}
    body = {"liveEnabled": bool(live_enabled), "credentials": c or None}
    try:
        async with httpx.AsyncClient(timeout=60) as cl:
            r = await cl.post(f"{s.executor_url}/configure", json=body,
                              headers={"Authorization": f"Bearer {s.executor_token}"})
            return r.json()
    except Exception as e:
        return {"ok": False, "error": f"executor unreachable: {e!r}"}
