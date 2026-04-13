from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from .broker import FillConfig, LocalSimBroker
from .harness import HarnessConfig, Mode, ReplayHarness
from .source import FileEventSource
from .strategy import Strategy


def _load_strategy(spec: str) -> Strategy:
    if ":" not in spec:
        raise SystemExit(f"strategy spec must be 'module:ClassName', got {spec!r}")
    module_name, cls_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, cls_name)
    instance = cls()
    if not isinstance(instance, Strategy):
        raise SystemExit(f"{spec} did not yield a Strategy instance")
    return instance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backtester")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run a backtest or paper session")
    run.add_argument("--source", required=True, help="Path to JSONL event file")
    run.add_argument("--strategy", required=True, help="module:ClassName")
    run.add_argument("--mode", choices=["historical", "paper"], default="historical")
    run.add_argument("--cash", type=float, default=100_000.0)
    run.add_argument("--slippage-bps", type=float, default=0.0)
    run.add_argument("--latency-events", type=int, default=0)
    run.add_argument("--report", default=None, help="Path to write JSON report")
    run.add_argument("--seed", type=int, default=None)

    args = parser.parse_args(argv)

    if args.cmd == "run":
        source = FileEventSource(Path(args.source))
        strategy = _load_strategy(args.strategy)
        broker = LocalSimBroker(
            config=FillConfig(
                slippage_bps=args.slippage_bps,
                latency_events=args.latency_events,
            )
        )
        cfg = HarnessConfig(
            starting_cash=args.cash,
            mode=Mode(args.mode),
            seed=args.seed,
        )
        harness = ReplayHarness(source=source, strategy=strategy, broker=broker, config=cfg)
        report = harness.run()
        out = report.to_json(args.report) if args.report else report.to_json()
        if not args.report:
            sys.stdout.write(out + "\n")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
