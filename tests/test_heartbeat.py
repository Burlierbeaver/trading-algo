from __future__ import annotations

import json

import pytest

from monitor.redis_client import CHANNEL_ALERTS, KEY_ENGINE_HEARTBEAT
from monitor.services.heartbeat import HeartbeatMonitor


async def _drain(pubsub, n: int):
    messages = []
    for _ in range(n * 3):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if msg is not None:
            messages.append(msg)
            if len(messages) >= n:
                break
    return messages


@pytest.mark.asyncio
async def test_publishes_critical_when_no_heartbeat(redis):
    hb = HeartbeatMonitor(redis=redis, poll_interval=1, stale_after=15, repeat_suppress=60)
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL_ALERTS)

    fired = await hb.check_once(now=1000.0)
    assert fired is True

    msgs = await _drain(pubsub, 1)
    assert msgs
    payload = json.loads(msgs[0]["data"])
    assert payload["severity"] == "critical"
    assert payload["source"] == "dashboard.heartbeat"

    await pubsub.unsubscribe(CHANNEL_ALERTS)
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_suppresses_repeat_alerts(redis):
    hb = HeartbeatMonitor(redis=redis, poll_interval=1, stale_after=5, repeat_suppress=60)

    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL_ALERTS)

    await hb.check_once(now=1000.0)           # fires
    second = await hb.check_once(now=1005.0)  # within suppress window — no fire
    assert second is False

    msgs = await _drain(pubsub, 2)
    # Should only have 1 alert message; second call was suppressed
    severities = [json.loads(m["data"])["severity"] for m in msgs]
    assert severities.count("critical") == 1

    await pubsub.unsubscribe(CHANNEL_ALERTS)
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_recovery_alert_after_stale(redis):
    hb = HeartbeatMonitor(redis=redis, poll_interval=1, stale_after=5, repeat_suppress=60)
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL_ALERTS)

    await hb.check_once(now=1000.0)  # stale (no key) -> critical
    await redis.set(KEY_ENGINE_HEARTBEAT, "1100.0")
    await hb.check_once(now=1100.0)  # fresh -> recovery info alert

    msgs = await _drain(pubsub, 2)
    severities = [json.loads(m["data"])["severity"] for m in msgs]
    assert "info" in severities

    await pubsub.unsubscribe(CHANNEL_ALERTS)
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_fresh_heartbeat_does_not_alert(redis):
    hb = HeartbeatMonitor(redis=redis, poll_interval=1, stale_after=15, repeat_suppress=60)
    await redis.set(KEY_ENGINE_HEARTBEAT, "1000.0")
    fired = await hb.check_once(now=1002.0)
    assert fired is False
