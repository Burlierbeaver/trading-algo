from __future__ import annotations

import json

import pytest

from monitor.redis_client import CHANNEL_ALERTS, KEY_ENGINE_HALTED
from monitor.services.kill_switch import KillSwitch


async def _collect_publish(redis, channel: str, count: int, timeout: float = 0.5):
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    msgs = []
    deadline_tries = 10
    tries = 0
    while len(msgs) < count and tries < deadline_tries:
        tries += 1
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        if msg is not None:
            msgs.append(msg)
    await pubsub.unsubscribe(channel)
    await pubsub.aclose()
    return msgs


@pytest.mark.asyncio
async def test_halt_sets_flag_records_audit_and_publishes_alert(redis, kill_audit_repo):
    ks = KillSwitch(redis=redis, audit=kill_audit_repo)

    # Subscribe before calling halt so we catch the publish
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL_ALERTS)

    await ks.halt(note="smoke")

    assert await redis.get(KEY_ENGINE_HALTED) == "1"
    assert kill_audit_repo.records == [("halt", "smoke")]

    # Drain until we see a non-subscribe message
    seen = None
    for _ in range(20):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg is not None:
            seen = msg
            break
    assert seen is not None, "expected an alert publish on halt"
    payload = json.loads(seen["data"])
    assert payload["severity"] == "warning"
    assert payload["source"] == "dashboard.kill"
    assert "halted" in payload["title"].lower()

    await pubsub.unsubscribe(CHANNEL_ALERTS)
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_resume_clears_flag_and_records(redis, kill_audit_repo):
    ks = KillSwitch(redis=redis, audit=kill_audit_repo)
    await redis.set(KEY_ENGINE_HALTED, "1")

    await ks.resume(note="back online")

    assert await redis.get(KEY_ENGINE_HALTED) == "0"
    assert kill_audit_repo.records == [("resume", "back online")]


@pytest.mark.asyncio
async def test_is_halted_reflects_flag(redis, kill_audit_repo):
    ks = KillSwitch(redis=redis, audit=kill_audit_repo)
    assert await ks.is_halted() is False
    await redis.set(KEY_ENGINE_HALTED, "1")
    assert await ks.is_halted() is True
    await redis.set(KEY_ENGINE_HALTED, "0")
    assert await ks.is_halted() is False
