"""Smoke tests confirming every component worktree is importable in the
integrated venv. Catches accidental drops from the Makefile install list."""

from __future__ import annotations


def test_nlp_signal():
    import nlp_signal
    assert nlp_signal.Signal


def test_risk_manager():
    import risk_manager
    assert risk_manager.RiskEngine


def test_alpaca_broker_adapter():
    import alpaca_broker_adapter
    assert alpaca_broker_adapter.BrokerAdapter


def test_backtester():
    import backtester
    assert backtester.ReplayHarness


def test_monitor_dashboard():
    import monitor
    assert monitor.__version__
