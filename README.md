# Risk / Portfolio Manager

Veto layer between the strategy engine and broker adapter. Enforces:

- Per-symbol position caps (notional and % of equity)
- Sector exposure caps (% of equity)
- Daily loss limit (realized + unrealized vs start-of-day equity)
- Kill switch (config flag, file flag, programmatic)

Runs in **live**, **paper**, and **backtest** modes from a single implementation.

## Install

```
pip install -e .[dev]
```

## Run tests

```
pytest
```

## Usage sketch

```python
from risk_manager import RiskEngine, load_config
from risk_manager.brokers.simulated import SimulatedBroker

config = load_config("config.yaml")
engine = RiskEngine.from_config(config)

decision = engine.check(intent)  # Order or Reject

# broker adapter pushes fills back:
engine.on_fill(fill)

# strategy/data loop pushes marks:
engine.mark({"AAPL": 190.12, "MSFT": 420.50})
```

See [`docs/superpowers/specs/2026-04-12-risk-management-design.md`](docs/superpowers/specs/2026-04-12-risk-management-design.md) for the design.
