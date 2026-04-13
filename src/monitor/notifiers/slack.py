from __future__ import annotations

import logging

import httpx

from monitor.models import Alert

log = logging.getLogger(__name__)

_COLOR = {"info": "#2ecc71", "warning": "#f39c12", "critical": "#e74c3c"}
_ICON = {"info": ":information_source:", "warning": ":warning:", "critical": ":rotating_light:"}


class SlackNotifier:
    name = "slack"

    def __init__(self, webhook_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._url = webhook_url
        self._client = client
        self._owns_client = client is None

    async def send(self, alert: Alert) -> None:
        payload = {
            "attachments": [
                {
                    "color": _COLOR.get(alert.severity, "#7f8c8d"),
                    "title": f"{_ICON.get(alert.severity, '')} {alert.title}",
                    "text": alert.detail or "",
                    "footer": f"source: {alert.source}",
                }
            ]
        }
        client = self._client or httpx.AsyncClient(timeout=5.0)
        try:
            resp = await client.post(self._url, json=payload)
            if resp.status_code >= 400:
                log.error("slack webhook returned %s: %s", resp.status_code, resp.text)
        finally:
            if self._owns_client:
                await client.aclose()
