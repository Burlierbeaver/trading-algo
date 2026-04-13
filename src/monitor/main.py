from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from monitor.config import Settings, get_settings
from monitor.db import Database
from monitor.notifiers.base import NullNotifier, Notifier
from monitor.notifiers.email import EmailNotifier
from monitor.notifiers.slack import SlackNotifier
from monitor.redis_client import make_redis
from monitor.repositories.alerts import AlertsRepo
from monitor.repositories.kill_audit import KillAuditRepo
from monitor.repositories.pnl import PnLRepo
from monitor.repositories.positions import PositionsRepo
from monitor.repositories.trades import TradesRepo
from monitor.routes import api_router, events_router, pages_router
from monitor.services.alert_dispatcher import AlertDispatcher
from monitor.services.heartbeat import HeartbeatMonitor
from monitor.services.kill_switch import KillSwitch
from monitor.services.snapshot import SnapshotBuilder

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def _build_notifiers(settings: Settings) -> list[Notifier]:
    notifiers: list[Notifier] = []
    if settings.slack_enabled:
        notifiers.append(SlackNotifier(webhook_url=settings.slack_webhook_url))  # type: ignore[arg-type]
    if settings.email_enabled:
        notifiers.append(
            EmailNotifier(
                host=settings.smtp_host,  # type: ignore[arg-type]
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                sender=settings.smtp_from,  # type: ignore[arg-type]
                recipient=settings.smtp_to,  # type: ignore[arg-type]
                use_tls=settings.smtp_use_tls,
            )
        )
    if not notifiers:
        notifiers.append(NullNotifier())
    return notifiers


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db = Database(settings.database_url)
    redis = make_redis(settings.redis_url)

    try:
        await db.connect()
    except Exception:
        log.exception("postgres connect failed (app continues, endpoints may 503)")

    alerts_repo = AlertsRepo(db)
    positions_repo = PositionsRepo(db)
    trades_repo = TradesRepo(db)
    pnl_repo = PnLRepo(db)
    kill_audit_repo = KillAuditRepo(db)

    kill_switch = KillSwitch(redis=redis, audit=kill_audit_repo)
    snapshot = SnapshotBuilder(
        redis=redis,
        positions_repo=positions_repo,
        trades_repo=trades_repo,
        alerts_repo=alerts_repo,
        heartbeat_stale_seconds=settings.heartbeat_stale_seconds,
    )

    notifiers = _build_notifiers(settings)
    dispatcher = AlertDispatcher(redis=redis, alerts_repo=alerts_repo, notifiers=notifiers)
    heartbeat = HeartbeatMonitor(
        redis=redis,
        poll_interval=settings.heartbeat_poll_seconds,
        stale_after=settings.heartbeat_stale_seconds,
        repeat_suppress=settings.heartbeat_repeat_suppress_seconds,
    )

    app.state.db = db
    app.state.redis = redis
    app.state.alerts_repo = alerts_repo
    app.state.pnl_repo = pnl_repo
    app.state.kill_switch = kill_switch
    app.state.snapshot = snapshot
    app.state.dispatcher = dispatcher
    app.state.heartbeat = heartbeat

    dispatcher.start()
    heartbeat.start()
    log.info("dashboard ready")
    try:
        yield
    finally:
        await heartbeat.stop()
        await dispatcher.stop()
        await db.close()
        try:
            await redis.aclose()
        except Exception:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="Trading Monitor", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(pages_router)
    app.include_router(api_router)
    app.include_router(events_router)
    return app


app = create_app()
