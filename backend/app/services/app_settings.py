"""User-editable settings persisted in the ``settings`` table."""
from __future__ import annotations

import json

from ..db import session_scope
from ..models import Setting
from .events import NOTIFY_CATEGORIES

DEFAULTS = {
    "notifications": {k: True for k in NOTIFY_CATEGORIES},
    "notifications_enabled": True,
    "operating_mode": "paper",
    "display_timezone": "local",
    "live_armed": False,
    "theme": "dark",
}


def get_all() -> dict:
    out = json.loads(json.dumps(DEFAULTS))
    with session_scope() as s:
        for row in s.query(Setting).all():
            try:
                out[row.key] = json.loads(row.value_json)
            except ValueError:
                pass
    out["operating_mode"] = "paper"  # live mode can never be persisted on (eligibility gate)
    for k in NOTIFY_CATEGORIES:
        out["notifications"].setdefault(k, True)
    return out


def update(values: dict) -> dict:
    with session_scope() as s:
        for k, v in values.items():
            if k not in DEFAULTS or k == "operating_mode":
                continue
            row = s.get(Setting, k) or Setting(key=k, value_json="null")
            row.value_json = json.dumps(v)
            s.add(row)
    return get_all()
