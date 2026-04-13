CREATE TABLE IF NOT EXISTS orders (
    id               BIGSERIAL PRIMARY KEY,
    client_order_id  UUID        NOT NULL UNIQUE,
    broker_order_id  TEXT        UNIQUE,
    symbol           TEXT        NOT NULL,
    side             TEXT        NOT NULL,
    qty              NUMERIC,
    notional         NUMERIC,
    order_type       TEXT        NOT NULL,
    limit_price      NUMERIC,
    time_in_force    TEXT        NOT NULL,
    status           TEXT        NOT NULL,
    filled_qty       NUMERIC     NOT NULL DEFAULT 0,
    filled_avg_price NUMERIC,
    submitted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    terminal_at      TIMESTAMPTZ,
    mode             TEXT        NOT NULL,
    raw              JSONB
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);

CREATE TABLE IF NOT EXISTS fills (
    id              BIGSERIAL PRIMARY KEY,
    broker_order_id TEXT        NOT NULL REFERENCES orders(broker_order_id),
    broker_fill_id  TEXT        UNIQUE,
    symbol          TEXT        NOT NULL,
    side            TEXT        NOT NULL,
    qty             NUMERIC     NOT NULL,
    price           NUMERIC     NOT NULL,
    filled_at       TIMESTAMPTZ NOT NULL,
    raw             JSONB
);

CREATE INDEX IF NOT EXISTS idx_fills_broker_order_id ON fills(broker_order_id);
