from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from monitor.deps import get_alerts_repo, get_kill_switch, get_snapshot
from monitor.models import Alert, DashboardSnapshot
from monitor.repositories.alerts import AlertsRepo
from monitor.services.kill_switch import KillSwitch
from monitor.services.snapshot import SnapshotBuilder

router = APIRouter(prefix="/api", tags=["api"])


class KillRequest(BaseModel):
    note: str | None = Field(default=None, max_length=200)


@router.post("/kill", response_model=dict)
async def kill(
    body: KillRequest | None = None,
    ks: KillSwitch = Depends(get_kill_switch),
) -> dict:
    note = body.note if body else None
    await ks.halt(note=note)
    return {"halted": True}


@router.post("/resume", response_model=dict)
async def resume(
    body: KillRequest | None = None,
    ks: KillSwitch = Depends(get_kill_switch),
) -> dict:
    note = body.note if body else None
    await ks.resume(note=note)
    return {"halted": False}


@router.get("/snapshot", response_model=DashboardSnapshot)
async def snapshot(
    snap: SnapshotBuilder = Depends(get_snapshot),
) -> DashboardSnapshot:
    return await snap.build()


@router.get("/alerts", response_model=list[Alert])
async def list_alerts(
    limit: int = 50,
    repo: AlertsRepo = Depends(get_alerts_repo),
) -> list[Alert]:
    return await repo.recent(limit=min(max(limit, 1), 500))


@router.post("/alerts/{alert_id}/ack", response_model=Alert)
async def ack_alert(
    alert_id: int,
    repo: AlertsRepo = Depends(get_alerts_repo),
) -> Alert:
    ack = await repo.acknowledge(alert_id)
    if ack is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return ack


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
