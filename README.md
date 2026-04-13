# Trading Monitor / Dashboard

Human-in-the-loop FastAPI dashboard for a live trading algorithm.

- **Live P&L** and positions view, pushed via Server-Sent Events
- **Halt** button that flips a Redis flag the strategy engine watches
- **Alert relay**: engine/risk components publish to Redis pub/sub; dashboard
  persists and fans out to Slack + email
- **Heartbeat monitor**: infra alert when the engine stops writing its
  heartbeat key
- **Designed for isolation**: the dashboard only talks to Postgres + Redis,
  never imports from sibling components

## Quick start

```bash
# 1. Spin up Postgres + Redis (applies schema.sql on first boot)
make up

# 2. Install deps into a local venv
make install

# 3. Copy env file and edit as needed
cp .env.example .env

# 4. Run tests
make test

# 5. Run the app
make run           # http://localhost:8787
```

## Configuration

All config is env-driven (see `.env.example`). Only `DATABASE_URL` and
`REDIS_URL` are strictly required. Slack/email notifiers stay disabled unless
their settings are provided.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://trader:trader@localhost:5432/trading` | Postgres DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `SLACK_WEBHOOK_URL` | `` | Incoming webhook; leave blank to disable |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_FROM` / `SMTP_TO` | `` | SMTP relay; leave blank to disable |
| `HEARTBEAT_STALE_SECONDS` | `15` | Age above which heartbeat is stale |
| `HEARTBEAT_POLL_SECONDS` | `5` | Heartbeat check cadence |
| `HEARTBEAT_REPEAT_SUPPRESS_SECONDS` | `60` | Repeat-alert suppression |
| `SSE_TICK_SECONDS` | `1.0` | Dashboard refresh cadence |

## Integration contract for sibling components

The dashboard is the *only* component that writes to `engine:halted`,
`kill_audit`, and (via the dispatcher) `alerts`. All other integration
points are inbound — sibling components write, dashboard reads.

### Postgres tables (see `src/monitor/schema.sql`)

| Table | Writer(s) | Dashboard use |
|---|---|---|
| `positions` | strategy / broker adapter | read |
| `trades` | broker adapter | read |
| `pnl_snapshots` | strategy / a snapshotter | read |
| `alerts` | **dashboard** (persists every dispatched alert) | read + write |
| `kill_audit` | **dashboard** | write |

### Redis keys / channels

| Name | Kind | Writer | Reader | Purpose |
|---|---|---|---|---|
| `engine:halted` | string `"0"` / `"1"` | dashboard | engine | When `"1"`, engine must stop placing NEW orders. |
| `engine:heartbeat` | string (epoch seconds) | engine (every ≤5s) | dashboard | Staleness check → critical infra alert. |
| `pnl:live` | JSON string | engine | dashboard | Live PnL ticker: `{equity, cash, realized_pnl, unrealized_pnl, daily_pnl, as_of}` |
| `alerts:events` | pub/sub channel | any component | dashboard | JSON `{severity, source, title, detail?}`; dashboard persists + notifies |

### Example: publishing an alert from the risk component

```python
import json, redis.asyncio as aioredis
redis = aioredis.from_url("redis://...", decode_responses=True)
await redis.publish("alerts:events", json.dumps({
    "severity": "warning",
    "source": "risk.position_breach",
    "title": "AAPL position exceeds 20% of equity",
    "detail": "current=$21,400 limit=$20,000",
}))
```

### Example: engine reading the kill flag

```python
if await redis.get("engine:halted") == "1":
    return  # skip new order placement this tick
```

## Kill semantics

The halt button is intentionally minimal: flip the flag, record an audit row,
emit an info alert. Existing positions are **not** closed automatically —
the operator unwinds them manually. Resume is the inverse.

If you want "cancel opens" or "flatten all" behavior, those belong in the
broker adapter and should be triggered explicitly (e.g., a separate button
that calls a broker-side endpoint). Kept out of scope here so the most common
safety action stays fast and low-consequence.

## Running behind a reverse proxy / tailnet

The app listens on `0.0.0.0:8787` by default with no auth. This is
appropriate for solo operators on a tailnet (Tailscale / Wireguard). If you
expose it to the open internet, front it with a reverse proxy that handles
TLS and authentication.

## Layout

```
src/monitor/
  config.py                  # pydantic-settings
  db.py                      # asyncpg pool
  redis_client.py            # shared Redis key / channel constants
  models.py                  # Pydantic models
  schema.sql                 # authoritative Postgres schema
  deps.py                    # FastAPI dependency accessors
  main.py                    # FastAPI app factory + lifespan wiring
  repositories/              # one module per table
  services/
    kill_switch.py           # halt / resume / audit
    heartbeat.py             # infra alert loop
    alert_dispatcher.py      # pub/sub subscriber + notifier fanout
    snapshot.py              # aggregated dashboard view
  notifiers/                 # slack, email, null
  routes/                    # pages, api, SSE events
  templates/                 # Jinja2
  static/                    # CSS + live-update JS
tests/                       # pytest + fakeredis, no real DB required
docs/superpowers/specs/      # design spec
```

## Testing

Tests use `fakeredis` for Redis and an in-memory fake for Postgres
repositories. No external services required for the default suite.

```bash
make test
```
