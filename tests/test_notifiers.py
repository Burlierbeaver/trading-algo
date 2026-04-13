from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from monitor.models import Alert
from monitor.notifiers.slack import SlackNotifier


@pytest.mark.asyncio
async def test_slack_notifier_posts_json():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        captured["url"] = str(request.url)
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = SlackNotifier("https://hooks.slack.example/test", client=client)
        alert = Alert(
            id=1,
            created_at=datetime.now(tz=timezone.utc),
            severity="warning",
            source="test",
            title="Position breach",
            detail="AAPL > limit",
        )
        await notifier.send(alert)

    assert captured["url"] == "https://hooks.slack.example/test"
    assert "Position breach" in captured["body"]
    assert "attachments" in captured["body"]
