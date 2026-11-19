"""Saved Strategy Builder strategies: create / rename / delete / share codes."""
from __future__ import annotations

import base64
import json
import zlib

from sqlalchemy import select

from ..db import now_ms, session_scope
from ..models import CustomStrategy
from ..strategies.custom import DEFAULTS, merged

PRESETS = [
    {"name": "Late favourite 92–97¢, 60–90s, z4 (best tested)", "params": {**DEFAULTS, "side": "favourite", "min_price": 0.92,
                                                                       "max_price": 0.97, "entry_min_secs": 60, "entry_max_secs": 90,
                                                                       "z_min": 4.0, "momentum_filter": False, "stake_value": 5.0,
                                                                       "max_loss_pct": 5.0, "max_losses_per_day": 2}},
    {"name": "Late favourite 95–97¢ (safest tested)", "params": {**DEFAULTS, "side": "favourite", "min_price": 0.95, "max_price": 0.97,
                                                             "entry_min_secs": 40, "entry_max_secs": 75, "z_min": 4.0}},
    {"name": "Late favourite 90–97¢ (more trades)", "params": {**DEFAULTS, "side": "favourite", "min_price": 0.90, "max_price": 0.97,
                                                            "entry_min_secs": 30, "entry_max_secs": 90, "z_min": 4.0}},
]
CODE_PREFIX = "RTS1-"


def _clean(params: dict) -> dict:
    p = merged(params)
    return {k: p[k] for k in DEFAULTS}          # only known settings; unknown keys are dropped


def to_code(name: str, params: dict) -> str:
    raw = json.dumps({"n": name, "p": _clean(params)}, separators=(",", ":")).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode().rstrip("=")


def from_code(code: str) -> dict:
    code = (code or "").strip()
    if "code=" in code:                          # a full share link was pasted
        code = code.split("code=", 1)[1].split("&")[0]
    if not code.startswith(CODE_PREFIX):
        raise ValueError("not a strategy code (should start with RTS1-)")
    body = code[len(CODE_PREFIX):]
    body += "=" * (-len(body) % 4)
    d = json.loads(zlib.decompress(base64.urlsafe_b64decode(body)))
    return {"name": str(d.get("n") or "Shared strategy")[:60], "params": _clean(d.get("p") or {})}


def _row(r: CustomStrategy) -> dict:
    p = json.loads(r.params_json or "{}")
    return {"id": r.id, "name": r.name, "params": p, "code": to_code(r.name, p),
            "created_ts": r.created_ts, "updated_ts": r.updated_ts}


def seed() -> None:
    """Add any built-in preset that has never been added before (deleted ones stay deleted)."""
    with session_scope() as s:
        known = set(s.scalars(select(CustomStrategy.name)).all())
        for pr in PRESETS:
            if pr["name"] not in known:
                s.add(CustomStrategy(name=pr["name"], params_json=json.dumps(_clean(pr["params"])), created_ts=now_ms(), updated_ts=now_ms()))


def list_all() -> list[dict]:
    seed()
    with session_scope() as s:
        return [_row(r) for r in s.scalars(select(CustomStrategy).where(CustomStrategy.deleted.is_(False))
                                           .order_by(CustomStrategy.id)).all()]


def create(name: str, params: dict) -> dict:
    name = (name or "").strip()[:60] or "My strategy"
    with session_scope() as s:
        r = CustomStrategy(name=name, params_json=json.dumps(_clean(params)), created_ts=now_ms(), updated_ts=now_ms())
        s.add(r)
        s.flush()
        return _row(r)


def update(sid: int, name: str | None = None, params: dict | None = None) -> dict:
    with session_scope() as s:
        r = s.get(CustomStrategy, sid)
        if r is None or r.deleted:
            raise KeyError("strategy not found")
        if name is not None and name.strip():
            r.name = name.strip()[:60]
        if params is not None:
            r.params_json = json.dumps(_clean(params))
        r.updated_ts = now_ms()
        return _row(r)


def delete(sid: int) -> None:
    with session_scope() as s:
        r = s.get(CustomStrategy, sid)
        if r is None:
            raise KeyError("strategy not found")
        r.deleted = True
