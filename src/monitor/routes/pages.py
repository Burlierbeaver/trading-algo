from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from monitor.deps import get_snapshot
from monitor.services.snapshot import SnapshotBuilder

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    snap: SnapshotBuilder = Depends(get_snapshot),
) -> HTMLResponse:
    snapshot = await snap.build()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "snapshot": snapshot},
    )
