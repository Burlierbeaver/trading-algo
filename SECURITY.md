# Security Policy

This project moves money when wired to a live broker. Treat every deployment
decision accordingly: the risk engine, kill switch, and audit log are safety
controls, not optional features.

## Supported Versions

The project is pre-1.0. Only the latest code on `main` (currently `0.1.x`)
receives security fixes; component branches are integrated through `main`
and are not patched independently.

| Version | Supported          |
| ------- | ------------------ |
| `main` (0.1.x) | :white_check_mark: |
| anything else  | :x:                |

## Reporting a Vulnerability

**Do not open a public issue for security problems.**

1. Report privately via
   [GitHub private vulnerability reporting](../../security/advisories/new).
2. Include: affected module (e.g. `pipeline.py`, `bridges/strategy_engine.py`),
   reproduction steps, and impact — especially whether the issue can cause an
   **unintended order submission**, bypass the risk engine, or defeat the
   kill switch.
3. Expect an acknowledgement within **72 hours** and a status update at least
   weekly until resolution. Accepted reports are fixed on `main` and credited
   in the advisory unless you prefer otherwise; declined reports get a written
   rationale.

Issues that can place, modify, or suppress trades are treated as **critical**
regardless of any other classification.

## Threat Model

The trust boundary sits at the **risk engine**. Everything upstream of it is
untrusted:

- **Ingestion** (`ingestion.py`): RawEvents come from RSS feeds, third-party
  APIs, and filings — attacker-controllable content. JSONL input is parsed,
  never executed, and malformed lines must fail the event, not the process.
- **NLP / LLM stage**: signals are extracted by an LLM from untrusted text.
  Treat its output as adversarial (prompt injection can fabricate tickers,
  scores, and event types). A signal must **never** be able to skip or weaken
  a risk check — only the risk engine turns a `TradeIntent` into an `Order`.
- **Strategy engine bridge** (`bridges/strategy_engine.py`): the TypeScript
  engine communicates through Postgres tables. Anyone with write access to
  `strategy_intents` can originate trades — scope database credentials so the
  strategy engine cannot write to order/fill/audit tables.

Downstream controls are fail-safe by design and must stay that way:

- **Kill switch** (`killswitch.py`) is *fail-closed*: `is_enabled()` returns
  `False` on any error, halting new orders. It is re-armed only by a human,
  and every state change records an `actor`.
- **Broker execution** (`pipeline.py`) wraps `execute_order` so a broker
  failure logs and skips — it never retries blindly (no accidental duplicate
  orders).
- **Audit log** (`audit.py`) records every stage with a correlation id. Audit
  failures are logged but do not block trading; alert on them, because a
  silent audit gap is itself an incident.

## Secrets and Credentials

- **Never commit keys.** Anthropic and Alpaca API keys are supplied via
  environment variables only. Use paper-trading Alpaca keys for anything
  that is not a vetted production deployment.
- The credentials in `docker-compose.yml` (`trader`/`trader`) are for
  **local development only**. Production Postgres needs unique credentials,
  TLS, and network isolation — the compose file publishes `5432` and `6379`
  on all interfaces, which is not acceptable outside a dev machine.
- Run Redis with `requirepass` (or ACLs) in any shared environment; the dev
  compose Redis is unauthenticated.
- Use per-service database roles: ingestion/NLP get no table access, the
  strategy engine gets `strategy_signals` (read) + `strategy_intents`
  (write), the broker adapter owns orders/fills, the dashboard is read-only.

## Deployment Hardening Checklist

- [ ] Real broker keys only after backtest + paper-trading validation
- [ ] Kill switch wired to a durable store (`system_flags` table) and tested
      by actually tripping it
- [ ] Alerting (`alerting.py`) connected to a paging channel for
      `Severity.CRITICAL` (killswitch trips) and audit-write failures
- [ ] Postgres/Redis not exposed publicly; per-service credentials; TLS
- [ ] Daily loss limits and position caps configured in the risk engine
      before the first live order
- [ ] Audit log retention meets your record-keeping obligations

## Scalability and Operational Resilience

Availability is a safety property here — a half-alive system that can submit
orders but not see fills or trip the kill switch is dangerous. Scale with
these invariants:

- **Pipeline workers are stateless.** All durable state (signals, intents,
  orders, fills, flags, audit) lives in Postgres, so the Python pipeline
  scales horizontally — but every worker must check the *shared* kill switch
  and risk state, never an in-memory copy.
- **Idempotency is the dedupe mechanism.** `client_order_id` /
  `approval_id` uniqueness is what makes retries and concurrent workers safe.
  Enforce it with database constraints, not application logic, before running
  more than one worker.
- **Risk checks must be serialized per account.** Position caps and daily
  loss limits are read-modify-write; under concurrency they require row
  locks or a single risk-engine writer, or two workers can each approve half
  of an over-limit position.
- **The Postgres bus is the backpressure point.** Ingestion bursts (earnings
  days, news storms) should queue in `strategy_signals`, not in worker
  memory. Monitor queue depth and lag; shed load at ingestion, never at the
  risk or reconciliation stages.
- **External rate limits are hard ceilings.** The LLM and Alpaca APIs are
  rate-limited; budget per-worker throughput so retries can't amplify into
  a self-inflicted outage, and prefer dropping *signals* over delaying
  *fill reconciliation*.
- **Audit volume grows with throughput.** Partition or archive the audit
  table by time; the correlation-id query path must stay fast enough to use
  during an incident, which is exactly when the table is largest.
- **Degrade toward "halted", not "best effort".** If Postgres, the clock
  source, or the kill-switch store is unreachable, stop submitting new
  orders (the kill switch's fail-closed default) while keeping read paths —
  dashboard, fill reconciliation — alive as long as possible.
