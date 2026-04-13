from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from monitor.repositories.alerts import AlertsRepo  # for isinstance if needed
from monitor.routes import api_router
from monitor.services.kill_switch import KillSwitch
from monitor.services.snapshot import SnapshotBuilder


def _make_app(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo) -> FastAPI:
    app = FastAPI()
    app.state.kill_switch = KillSwitch(redis=redis, audit=kill_audit_repo)
    app.state.snapshot = SnapshotBuilder(
        redis=redis,
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        alerts_repo=alerts_repo,
        heartbeat_stale_seconds=15,
    )
    app.state.alerts_repo = alerts_repo
    app.include_router(api_router)
    return app


@pytest.mark.asyncio
async def test_kill_endpoint_flips_flag(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo):
    app = _make_app(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo)
    with TestClient(app) as client:
        r = client.post("/api/kill", json={"note": "test"})
        assert r.status_code == 200
        assert r.json() == {"halted": True}
    assert await redis.get("engine:halted") == "1"
    assert kill_audit_repo.records[0][0] == "halt"


@pytest.mark.asyncio
async def test_resume_endpoint_clears_flag(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo):
    app = _make_app(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo)
    await redis.set("engine:halted", "1")
    with TestClient(app) as client:
        r = client.post("/api/resume", json={"note": "back"})
        assert r.status_code == 200
        assert r.json() == {"halted": False}
    assert await redis.get("engine:halted") == "0"


@pytest.mark.asyncio
async def test_snapshot_endpoint_returns_shape(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo):
    app = _make_app(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo)
    with TestClient(app) as client:
        r = client.get("/api/snapshot")
        assert r.status_code == 200
        data = r.json()
        assert "engine" in data
        assert "positions" in data
        assert "recent_alerts" in data
        assert "server_time" in data


def test_healthz(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo):
    app = _make_app(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo)
    with TestClient(app) as client:
        r = client.get("/api/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_alerts_list_and_ack(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo):
    from monitor.models import Alert

    # Insert a couple alerts through the fake repo
    a1 = await alerts_repo.insert(Alert(severity="info", source="test", title="one"))
    await alerts_repo.insert(Alert(severity="warning", source="test", title="two"))

    app = _make_app(redis, alerts_repo, positions_repo, trades_repo, kill_audit_repo)
    with TestClient(app) as client:
        r = client.get("/api/alerts")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 2

        r = client.post(f"/api/alerts/{a1.id}/ack")
        assert r.status_code == 200
        assert r.json()["acknowledged_at"] is not None
