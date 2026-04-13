"""FastAPI dependency accessors.

All shared services live on `app.state`; these helpers are a single place to
pull them out in a type-safe-ish way.
"""

from __future__ import annotations

from fastapi import Request

from monitor.services.alert_dispatcher import AlertDispatcher
from monitor.services.kill_switch import KillSwitch
from monitor.services.snapshot import SnapshotBuilder
from monitor.repositories.alerts import AlertsRepo


def get_kill_switch(request: Request) -> KillSwitch:
    return request.app.state.kill_switch


def get_snapshot(request: Request) -> SnapshotBuilder:
    return request.app.state.snapshot


def get_dispatcher(request: Request) -> AlertDispatcher:
    return request.app.state.dispatcher


def get_alerts_repo(request: Request) -> AlertsRepo:
    return request.app.state.alerts_repo
