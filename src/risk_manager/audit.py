from __future__ import annotations

from .persistence import SQLiteStore
from .types import Decision, PortfolioSnapshot


class AuditLog:
    """Tiny wrapper that tags audit writes as a distinct subsystem."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def record(self, decision: Decision, snapshot: PortfolioSnapshot | None) -> None:
        self._store.record_decision(decision, snapshot)

    def recent(self, limit: int = 100) -> list[dict]:
        return self._store.audit_entries(limit)
