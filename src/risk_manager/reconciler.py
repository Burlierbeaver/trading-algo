from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .engine import RiskEngine


logger = logging.getLogger(__name__)


class Reconciler:
    """Runs `engine.reconcile()` on a fixed cadence in a daemon thread.

    After `max_consecutive_failures` broker errors in a row, trips the kill
    switch. Any drift detected by the engine already trips the switch.
    """

    def __init__(
        self,
        engine: RiskEngine,
        interval_seconds: int | None = None,
        max_consecutive_failures: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._engine = engine
        cfg = engine.config.reconciler
        self._interval = interval_seconds or cfg.interval_seconds
        self._max_failures = max_consecutive_failures or cfg.max_consecutive_failures
        self._sleep = sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._consecutive_failures = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="risk-reconciler", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def tick(self) -> None:
        """One reconciliation cycle. Used directly in backtest mode."""
        try:
            ok, reason = self._engine.reconcile()
        except Exception as e:  # noqa: BLE001
            self._consecutive_failures += 1
            logger.warning(
                "reconciler broker error (%d/%d): %r",
                self._consecutive_failures,
                self._max_failures,
                e,
            )
            if self._consecutive_failures >= self._max_failures:
                self._engine.kill(
                    f"reconciler: {self._consecutive_failures} consecutive broker failures"
                )
            return
        if not ok:
            logger.error("reconciler drift: %s", reason)
        self._consecutive_failures = 0

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            # Sleep in small slices so stop() is responsive.
            slept = 0.0
            while slept < self._interval and not self._stop.is_set():
                step = min(0.5, self._interval - slept)
                self._sleep(step)
                slept += step
