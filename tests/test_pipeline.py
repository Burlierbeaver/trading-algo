from __future__ import annotations

from trading_algo.fakes import FakeBroker, FakeNLP
from trading_algo.pipeline import Pipeline
from tests.conftest import make_signal


async def test_happy_path(raw_event, risk_engine):
    broker = FakeBroker()
    pipeline = Pipeline(nlp=FakeNLP(), risk=risk_engine, broker=broker)

    result = await pipeline.ingest(raw_event)

    assert len(result.signals) == 1
    assert len(result.intents) == 1
    assert len(result.approved) == 1
    assert len(result.executed) == 1
    assert len(broker.submitted) == 1
    assert result.executed[0].filled_qty > 0


async def test_low_confidence_signal_is_filtered(raw_event, risk_engine):
    nlp = FakeNLP(signals=[make_signal(confidence=0.2)])
    pipeline = Pipeline(nlp=nlp, risk=risk_engine, broker=FakeBroker())

    result = await pipeline.ingest(raw_event)

    assert result.signals
    assert result.intents == []
    assert result.approved == []


async def test_kill_switch_rejects_intent(raw_event, risk_engine):
    risk_engine.kill("manual halt")

    pipeline = Pipeline(nlp=FakeNLP(), risk=risk_engine, broker=FakeBroker())
    result = await pipeline.ingest(raw_event)

    assert len(result.intents) == 1
    assert result.approved == []
    assert len(result.rejected) == 1
    assert result.rejected[0].rule == "kill_switch"
