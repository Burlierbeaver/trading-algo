from __future__ import annotations

import logging
from typing import Protocol

from monitor.models import Alert

log = logging.getLogger(__name__)


class Notifier(Protocol):
    name: str

    async def send(self, alert: Alert) -> None: ...


class NullNotifier:
    """No-op notifier used when a channel is not configured.

    Keeps dispatcher code unconditional (no `if slack_enabled: ...` branches).
    """

    name = "null"

    async def send(self, alert: Alert) -> None:  # noqa: D401 - protocol impl
        log.debug("null notifier: skipping alert %s", alert.title)
