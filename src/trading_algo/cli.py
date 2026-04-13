from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backtester import SignalEvent
from nlp_signal import RawEvent
from risk_manager import RiskConfig, RiskEngine
from risk_manager.types import Mode

from trading_algo.backtest import run_backtest
from trading_algo.fakes import FakeBroker, FakeNLP
from trading_algo.ingestion import JSONLIngestion
from trading_algo.pipeline import Pipeline


def _demo_event() -> RawEvent:
    return RawEvent(
        id="demo-1",
        source="demo",
        published_at=datetime.now(timezone.utc),
        title="Apple beats earnings estimates",
        body="Apple reported Q2 earnings above consensus.",
    )


def _build_pipeline() -> Pipeline:
    config = RiskConfig(mode=Mode.BACKTEST)
    risk = RiskEngine.from_config(config)
    risk.mark({"AAPL": Decimal("150.00"), "MSFT": Decimal("400.00")})
    return Pipeline(nlp=FakeNLP(), risk=risk, broker=FakeBroker())


async def _run_demo() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    pipeline = _build_pipeline()
    result = await pipeline.ingest(_demo_event())

    print(f"event={result.event_id}")
    print(f"  signals:  {len(result.signals)}")
    print(f"  intents:  {len(result.intents)}")
    print(f"  approved: {len(result.approved)}")
    print(f"  rejected: {len(result.rejected)}")
    print(f"  executed: {len(result.executed)}")
    for ex in result.executed:
        print(f"    -> {ex.status.value} qty={ex.filled_qty} @ {ex.filled_avg_price}")
    return 0


async def _run_ingest(path: str) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    pipeline = _build_pipeline()
    executed = 0
    for event in JSONLIngestion(path):
        result = await pipeline.ingest(event)
        executed += len(result.executed)
    print(f"done — total orders executed: {executed}")
    return 0


def _run_backtest_cmd() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    t0 = datetime.now(timezone.utc)
    events = [
        SignalEvent(ts=t0, symbol="AAPL", name="earnings_beat", value=0.8, confidence=0.9),
        SignalEvent(ts=t0 + timedelta(minutes=1), symbol="AAPL", name="noise", value=0.1, confidence=0.3),
        SignalEvent(ts=t0 + timedelta(minutes=2), symbol="MSFT", name="guidance_raise", value=0.6, confidence=0.8),
    ]
    result = run_backtest(events)
    report = result.report
    print(f"starting cash: {report.starting_cash}")
    print(f"ending equity: {report.ending_equity}")
    print(f"fills:         {report.trades.total_fills}")
    print(f"orders seen:   {result.orders_submitted}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="trading-algo")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="pipeline with in-memory fakes")
    sub.add_parser("backtest", help="run through the backtester harness")
    run_p = sub.add_parser("run", help="ingest JSONL RawEvents through the pipeline")
    run_p.add_argument("--events", required=True, help="path to JSONL file of RawEvents")

    args = parser.parse_args()
    if args.command == "demo":
        return asyncio.run(_run_demo())
    if args.command == "backtest":
        return _run_backtest_cmd()
    if args.command == "run":
        return asyncio.run(_run_ingest(args.events))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
