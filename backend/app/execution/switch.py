"""Effective live-trading master switch: server env OR the in-app switch (password protected)."""
from __future__ import annotations

from ..config import get_settings


def live_enabled() -> bool:
    if get_settings().live_trading_enabled:
        return True
    from ..services import app_settings
    return bool(app_settings.get_all().get("live_enabled"))
