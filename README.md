# Backtester + Paper Harness

Isolated component that replays a stream of `RawEvent`s through a strategy and
produces a JSON P&L report. Same code path serves both modes:

- **Historical** — offline replay of a JSONL event file against a deterministic
  local fill simulator.
- **Paper** — live event stream through either the local simulator or the
  Alpaca paper-trading endpoint (end-to-end validation before real money).

## Install

```bash
pip install -e .
# optional, for Alpaca paper broker:
pip install -e '.[alpaca]'
```

## Quickstart

Write a strategy:

```python
# mystrat.py
from backtester import Strategy, Order, OrderSide, QuoteEvent

class BuyAndHold(Strategy):
    def on_event(self, event, ctx):
        if isinstance(event, QuoteEvent) and not ctx.portfolio.positions:
            ctx.broker.submit(Order(symbol=event.symbol, side=OrderSide.BUY, qty=10))
```

Prepare an event file (`events.jsonl`, one JSON object per line):

```jsonl
{"type":"quote","ts":"2026-04-12T14:00:00Z","symbol":"SPY","bid":500.0,"ask":500.1}
{"type":"quote","ts":"2026-04-12T14:01:00Z","symbol":"SPY","bid":501.0,"ask":501.1}
```

Run:

```bash
backtester run \
  --source events.jsonl \
  --strategy mystrat:BuyAndHold \
  --cash 100000 \
  --report out/report.json
```

## Event types

All events are timezone-aware, frozen dataclasses under `backtester.events`:

| Type      | Class          | Key fields                             |
| --------- | -------------- | -------------------------------------- |
| `quote`   | `QuoteEvent`   | `bid`, `ask`, `bid_size`, `ask_size`   |
| `trade`   | `TradeEvent`   | `price`, `size`                        |
| `bar`     | `BarEvent`     | `open`, `high`, `low`, `close`, `volume` |
| `news`    | `NewsEvent`    | `headline`, `body`, `source`, `tags`   |
| `signal`  | `SignalEvent`  | `name`, `value`, `confidence`, `payload` |

The harness does not filter — every event reaches `Strategy.on_event`. Filter
by `isinstance` in your strategy.

## Fill model

`LocalSimBroker` is deterministic and configurable via `FillConfig`:

- `slippage_bps` — basis-point adjustment on market fills.
- `latency_events` — delay before a submitted order is eligible for matching.
- `fee_per_share` — per-share commission.
- `allow_partial` — reserved; full fills only at present.

Market orders fill at the ask (buy) or bid (sell) of the next market event;
limit orders fill only when a subsequent event crosses the limit. Orders with
`TimeInForce.IOC` that don't match immediately are dropped.

## Paper mode

```python
from backtester import ReplayHarness, HarnessConfig, Mode, LocalSimBroker
from backtester.broker import AlpacaPaperBroker

harness = ReplayHarness(
    source=live_source,       # supplied by the data-ingestion component
    strategy=MyStrategy(),
    broker=AlpacaPaperBroker(api_key=..., api_secret=...),
    config=HarnessConfig(mode=Mode.PAPER),
)
harness.run()
```

`AlpacaPaperBroker` is the seam; its concrete submit/cancel wiring lives in
the `alpaca-broker-adapter-order-execution-and-fill-rec` branch.

## Report

`harness.run()` returns a `Report` with:

- `ending_equity`, `total_return_pct`
- `trades`: `total_fills`, `realized_pnl`, `unrealized_pnl`, `net_pnl`,
  `win_rate`, `avg_win`, `avg_loss`
- `risk`: `max_drawdown`, `max_drawdown_pct`, `sharpe`, `volatility`
- `equity_curve`: list of `(iso_ts, equity)`
- `fills`: complete trade log

Serialize with `report.to_json(path)`.

## Tests

```bash
python -m unittest discover -s tests -v
```

No runtime deps; stdlib only.

## Design doc

See `docs/superpowers/specs/2026-04-12-backtester-paper-harness-design.md`.
