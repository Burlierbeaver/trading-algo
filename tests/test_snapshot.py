from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from monitor.models import Position
from monitor.redis_client import KEY_ENGINE_HALTED, KEY_ENGINE_HEARTBEAT, KEY_PNL_LIVE
from monitor.services.snapshot import SnapshotBuilder


@pytest.mark.asyncio
async def test_snapshot_running_when_heartbeat_fresh_and_not_halted(
    redis, positions_repo, trades_repo, alerts_repo
):
    snap = SnapshotBuilder(
        redis=redis,
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        alerts_repo=alerts_repo,
        heartbeat_stale_seconds=15,
    )
    import time
    await redis.set(KEY_ENGINE_HEARTBEAT, str(time.time()))
    result = await snap.build()
    assert result.engine.halted is False
    assert result.engine.stale is False
    assert result.engine.last_heartbeat is not None


@pytest.mark.asyncio
async def test_snapshot_halted(redis, positions_repo, trades_repo, alerts_repo):
    snap = SnapshotBuilder(
        redis=redis,
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        alerts_repo=alerts_repo,
        heartbeat_stale_seconds=15,
    )
    await redis.set(KEY_ENGINE_HALTED, "1")
    result = await snap.build()
    assert result.engine.halted is True


@pytest.mark.asyncio
async def test_snapshot_stale_when_heartbeat_missing(
    redis, positions_repo, trades_repo, alerts_repo
):
    snap = SnapshotBuilder(
        redis=redis,
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        alerts_repo=alerts_repo,
        heartbeat_stale_seconds=15,
    )
    result = await snap.build()
    assert result.engine.stale is True


@pytest.mark.asyncio
async def test_snapshot_live_pnl_parsed(
    redis, positions_repo, trades_repo, alerts_repo
):
    snap = SnapshotBuilder(
        redis=redis,
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        alerts_repo=alerts_repo,
        heartbeat_stale_seconds=15,
    )
    await redis.set(
        KEY_PNL_LIVE,
        json.dumps(
            {
                "equity": "10100.50",
                "cash": "5000.00",
                "realized_pnl": "50.00",
                "unrealized_pnl": "50.50",
                "daily_pnl": "100.50",
                "as_of": "2026-04-12T12:00:00+00:00",
            }
        ),
    )
    result = await snap.build()
    assert result.live_pnl is not None
    assert result.live_pnl.daily_pnl == Decimal("100.50")


@pytest.mark.asyncio
async def test_snapshot_positions_passthrough(redis, trades_repo, alerts_repo):
    from tests.conftest import FakePositionsRepo

    positions = [
        Position(
            symbol="AAPL",
            quantity=Decimal("10"),
            avg_price=Decimal("150.00"),
            market_value=Decimal("1550.00"),
            unrealized_pnl=Decimal("50.00"),
            realized_pnl=Decimal("0"),
            updated_at=datetime.now(tz=timezone.utc),
        )
    ]
    snap = SnapshotBuilder(
        redis=redis,
        positions_repo=FakePositionsRepo(positions),
        trades_repo=trades_repo,
        alerts_repo=alerts_repo,
        heartbeat_stale_seconds=15,
    )
    result = await snap.build()
    assert len(result.positions) == 1
    assert result.positions[0].symbol == "AAPL"
