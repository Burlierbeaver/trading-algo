-- Monitor / Dashboard Postgres contract.
-- This file is the authoritative schema for the shared tables the dashboard
-- reads from and writes to. Sibling components (strategy engine, broker,
-- risk) must conform to these definitions.

CREATE TABLE IF NOT EXISTS positions (
    symbol          TEXT        PRIMARY KEY,
    quantity        NUMERIC     NOT NULL,
    avg_price       NUMERIC     NOT NULL,
    market_value    NUMERIC,
    unrealized_pnl  NUMERIC,
    realized_pnl    NUMERIC     NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trades (
    id              BIGSERIAL   PRIMARY KEY,
    symbol          TEXT        NOT NULL,
    side            TEXT        NOT NULL CHECK (side IN ('buy','sell')),
    quantity        NUMERIC     NOT NULL,
    price           NUMERIC     NOT NULL,
    pnl             NUMERIC,
    broker_order_id TEXT,
    strategy        TEXT,
    executed_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON trades (executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol);

CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id              BIGSERIAL   PRIMARY KEY,
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    equity          NUMERIC     NOT NULL,
    cash            NUMERIC     NOT NULL,
    realized_pnl    NUMERIC     NOT NULL,
    unrealized_pnl  NUMERIC     NOT NULL,
    daily_pnl       NUMERIC     NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_at ON pnl_snapshots (snapshot_at DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id              BIGSERIAL   PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity        TEXT        NOT NULL CHECK (severity IN ('info','warning','critical')),
    source          TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    detail          TEXT,
    acknowledged_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_open ON alerts (acknowledged_at) WHERE acknowledged_at IS NULL;

CREATE TABLE IF NOT EXISTS kill_audit (
    id            BIGSERIAL   PRIMARY KEY,
    triggered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action        TEXT        NOT NULL CHECK (action IN ('halt','resume')),
    note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_kill_audit_at ON kill_audit (triggered_at DESC);
