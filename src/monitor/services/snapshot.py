from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis

from monitor.models import DashboardSnapshot, EngineState, LivePnL
from monitor.redis_client import KEY_ENGINE_HALTED, KEY_ENGINE_HEARTBEAT, KEY_PNL_LIVE
from monitor.repositories.alerts import AlertsRepo
from monitor.repositories.positions import PositionsRepo
from monitor.repositories.trades import TradesRepo

log = logging.getLogger(__name__)


class SnapshotBuilder:
    """Aggregates the full dashboard view from Redis + Postgres in one call."""

    def __init__(
        self,
        redis: aioredis.Redis,
        positions_repo: PositionsRepo,
        trades_repo: TradesRepo,
        alerts_repo: AlertsRepo,
        *,
        heartbeat_stale_seconds: float,
    ) -> None:
        self._redis = redis
        self._positions = positions_repo
        self._trades = trades_repo
        self._alerts = alerts_repo
        self._stale_after = heartbeat_stale_seconds

    async def build(self) -> DashboardSnapshot:
        engine = await self._engine_state()
        live = await self._live_pnl()

        positions = []
        trades = []
        alerts = []
        try:
            positions = await self._positions.list_open()
        except Exception:
            log.exception("positions fetch failed")
        try:
            trades = await self._trades.recent(limit=15)
        except Exception:
            log.exception("trades fetch failed")
        try:
            alerts = await self._alerts.recent(limit=15)
        except Exception:
            log.exception("alerts fetch failed")

        return DashboardSnapshot(
            engine=engine,
            live_pnl=live,
            positions=positions,
            recent_trades=trades,
            recent_alerts=alerts,
            server_time=datetime.now(tz=timezone.utc),
        )

    async def _engine_state(self) -> EngineState:
        try:
            halted_raw = await self._redis.get(KEY_ENGINE_HALTED)
            heartbeat_raw = await self._redis.get(KEY_ENGINE_HEARTBEAT)
        except Exception:
            log.exception("redis read failed for engine state")
            return EngineState(halted=False, last_heartbeat=None, heartbeat_age_seconds=None, stale=True)

        last_heartbeat = None
        age: float | None = None
        if heartbeat_raw is not None:
            try:
                ts = float(heartbeat_raw)
                last_heartbeat = datetime.fromtimestamp(ts, tz=timezone.utc)
                age = time.time() - ts
            except ValueError:
                pass

        stale = age is None or age > self._stale_after
        return EngineState(
            halted=(halted_raw == "1"),
            last_heartbeat=last_heartbeat,
            heartbeat_age_seconds=age,
            stale=stale,
        )

    async def _live_pnl(self) -> LivePnL | None:
        try:
            raw = await self._redis.get(KEY_PNL_LIVE)
        except Exception:
            log.exception("redis read failed for live pnl")
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return LivePnL(**data)
        except Exception:
            log.warning("pnl:live payload malformed: %r", raw)
            return None
