"""Application events, structured logging and an in-process pub/sub bus.

Events are persisted to ``app_events`` and pushed to connected dashboard
websockets, which turn notification-worthy categories into browser/desktop
notifications (each category can be disabled in Settings).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import Any

from ..db import now_ms, session_scope
from ..models import AppEvent

log = logging.getLogger("reversal.events")

NOTIFY_CATEGORIES = {
    "market_discovered": "A new market is discovered",
    "opportunity": "A reversal opportunity appears",
    "order_simulated": "An order is simulated",
    "trade_settled": "A trade settles",
    "loss_limit": "A strategy reaches a loss limit",
    "connection_failed": "An asset connection fails",
    "collector_stopped": "The data collector stops",
    "experiment_completed": "An experiment completes",
}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self.recent: deque[dict] = deque(maxlen=300)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, payload: dict) -> None:
        self.recent.append(payload)
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:  # slow consumer: drop oldest
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass


bus = EventBus()


def record_event(category: str, message: str, level: str = "INFO", data: dict[str, Any] | None = None,
                 persist: bool = True) -> dict:
    ts = now_ms()
    payload = {"type": "event", "ts": ts, "level": level, "category": category, "message": message,
               "data": data or {}, "notify": category in NOTIFY_CATEGORIES}
    getattr(log, level.lower(), log.info)("[%s] %s", category, message)
    if persist:
        try:
            with session_scope() as s:
                s.add(AppEvent(ts=ts, level=level, category=category, message=message,
                               data_json=json.dumps(data, default=str) if data else None))
        except Exception as e:  # never let event logging kill a caller
            log.error("failed to persist event: %s", e)
    bus.publish(payload)
    return payload
