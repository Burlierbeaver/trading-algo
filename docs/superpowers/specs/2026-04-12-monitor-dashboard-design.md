# Monitor / Dashboard — Design

**Date:** 2026-04-12
**Component branch:** `fastapi-dashboard-for-live-trading-monitoring-and`

## Purpose

Human-in-the-loop control surface for a live trading algorithm. One operator
watches live P&L and positions, receives alerts when something goes wrong, and
can halt the strategy engine from a browser on their tailnet.

## Decisions (captured inline — no Q&A review loop)

| # | Decision | Rationale |
|---|---|---|
| D1 | Solo user on tailnet, **no auth** | User directive (Q1=b). Tailnet provides network-level access control. |
| D2 | Kill button = **halt only** | User directive (Q2=a). Flip a Redis flag; existing positions untouched. Operator unwinds manually. |
| D3 | **Hybrid alerts**: dashboard owns infra (heartbeat, stale data, DB/Redis connectivity); engine/risk components publish domain alerts to a Redis channel that the dashboard relays | Keeps trading logic out of the dashboard; dashboard is still the only component watching plumbing. |
| D4 | **Stack:** FastAPI + Jinja2 + HTMX + SSE for push. asyncpg + redis-py (async). Slack via incoming webhook; email via SMTP (aiosmtplib). | "Simple web UI" per spec. HTMX+SSE avoids an SPA build. No websockets needed for a one-operator dashboard. |
| D5 | **Pub/sub channel = integration contract** | Sibling components (strategy engine, risk, broker) publish to `alerts:events` and heartbeat to `engine:heartbeat`. Dashboard only reads Postgres + Redis — never imports from siblings. |
| D6 | Tests: pytest + pytest-asyncio + fakeredis for Redis; async Postgres tests hit a real DB when `TEST_DATABASE_URL` is set, otherwise skip | Fake Postgres (pg_mock libraries) is low-value for the small set of SQL we run. |
| D7 | YAGNI: no login, no RBAC, no audit beyond the kill_audit table, no historical charting (equity curve shown as a table of recent snapshots) | "Simple" UI per spec. Can add later. |

## Architecture

```
┌──────────────────────┐        ┌──────────────────────┐
│  Strategy Engine     │        │  Risk / Broker / NLP │
│  (sibling component) │        │  (sibling components)│
└────────┬─────────────┘        └──────────┬───────────┘
         │                                  │
         │ writes                           │ publishes alerts
         ▼                                  ▼
  ┌────────────────────┐          ┌─────────────────────┐
  │     Postgres       │          │       Redis         │
  │  positions, trades │          │ engine:halted       │
  │  pnl_snapshots     │          │ engine:heartbeat    │
  │  alerts, kill_audit│◀─────────│ pnl:live (JSON)     │
  └──────────┬─────────┘ persist  │ alerts:events (ch)  │
             │          alerts    └──────────┬──────────┘
             │                               │
             └────────────┐   ┌──────────────┘
                          ▼   ▼
                 ┌────────────────────┐
                 │   Dashboard App    │
                 │  (FastAPI, this)   │
                 │ ┌────────────────┐ │
                 │ │ HTTP + SSE     │ │──▶ Browser (operator)
                 │ │ Heartbeat task │ │
                 │ │ Alert subscriber│──▶ Slack webhook
                 │ │ Kill switch    │ │──▶ Email (SMTP)
                 │ └────────────────┘ │
                 └────────────────────┘
```

## Data contract (shared interface)

### Postgres tables (see `src/monitor/schema.sql`)

| Table | Writer | Dashboard use |
|---|---|---|
| `positions` | strategy/broker | read — display live positions |
| `trades` | broker/execution | read — recent fills |
| `pnl_snapshots` | strategy or a separate snapshotter | read — PnL history |
| `alerts` | dashboard (persist all dispatched) | read + write |
| `kill_audit` | dashboard | write |

### Redis keys & channels

| Key / Channel | Direction | Meaning |
|---|---|---|
| `engine:halted` (str) | dashboard writes `"1"`/`"0"`; engine reads | If `"1"`, engine must stop placing NEW orders. |
| `engine:heartbeat` (str: epoch seconds) | engine writes every ≤5s; dashboard reads | Staleness >15s triggers critical infra alert. |
| `pnl:live` (str: JSON) | engine writes; dashboard reads | Latest live PnL snapshot for ticker display. |
| `alerts:events` (pub/sub channel) | anyone publishes JSON `{severity, source, title, detail}`; dashboard subscribes | Dispatches to Slack/email and persists to `alerts`. |

## Components

- **`config.py`** — pydantic-settings. Env-driven.
- **`db.py`** — asyncpg pool wrapper.
- **`redis_client.py`** — redis async client wrapper.
- **`models.py`** — Pydantic models for Position, Trade, PnLSnapshot, Alert, EngineState.
- **`repositories/`** — one module per table.
- **`services/kill_switch.py`** — halt()/resume(), writes kill_audit row.
- **`services/heartbeat.py`** — async task checks `engine:heartbeat`, emits infra alerts.
- **`services/alert_dispatcher.py`** — subscribes to `alerts:events`, persists, fans out to notifiers.
- **`notifiers/slack.py`**, **`notifiers/email.py`** — thin clients with the same interface.
- **`routes/pages.py`** — `/` HTML dashboard.
- **`routes/api.py`** — `POST /api/kill`, `POST /api/resume`, `GET /api/alerts`, `POST /api/alerts/{id}/ack`.
- **`routes/events.py`** — `GET /sse` Server-Sent Events stream with combined state.

## Flow: operator clicks "Halt"

1. Browser POSTs `/api/kill` (HTMX request, CSRF not needed on tailnet per D1).
2. `kill_switch.halt()` sets `engine:halted` = `"1"` in Redis, inserts a `kill_audit` row, publishes an `alerts:events` info message (`source=dashboard.kill`).
3. Alert dispatcher fans out to Slack + email.
4. SSE stream broadcasts new state; all open dashboards update instantly.
5. Strategy engine (sibling) sees `engine:halted=1` on next check and stops issuing new orders.

## Flow: engine goes silent

1. Heartbeat task polls `engine:heartbeat` every 5s.
2. If the timestamp is >15s old (and wasn't already flagged), publish critical alert `source=dashboard.heartbeat`, then *suppress* repeat alerts for 60s to avoid spam.
3. Dispatcher persists + notifies Slack + email.
4. Dashboard shows red banner.

## Error handling

- **DB or Redis unavailable at startup:** app still boots; endpoints return 503 for affected pages. Heartbeat task retries with exponential backoff.
- **Slack/email notifier failure:** logged at error level, does NOT fail the pub/sub subscriber; persistence to Postgres still happens so the alert is not lost.
- **Kill switch failure:** returned as 500 with explicit error; operator must retry. No silent success.

## Testing

- Unit: kill switch, heartbeat detector, alert dispatcher (fakeredis + mocked notifiers + pytest-postgres when available, otherwise in-memory fake repo).
- HTTP: FastAPI `TestClient` for routes.
- Skip integration tests requiring a real DB unless `TEST_DATABASE_URL` is set.

## Out of scope

Authentication, multi-user audit, per-strategy controls, tiered kill (halt / cancel / flatten), charting / equity curve visualisations, historical report generation, mobile-optimised UI, production TLS termination (handled by reverse proxy).
