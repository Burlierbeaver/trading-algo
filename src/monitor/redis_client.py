from __future__ import annotations

import logging

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

KEY_ENGINE_HALTED = "engine:halted"
KEY_ENGINE_HEARTBEAT = "engine:heartbeat"
KEY_PNL_LIVE = "pnl:live"
CHANNEL_ALERTS = "alerts:events"


def make_redis(url: str) -> aioredis.Redis:
    """Create an async Redis client that decodes responses to str.

    Decoding at the client level keeps downstream code from sprinkling
    `.decode()` everywhere and makes fakeredis behave identically.
    """

    return aioredis.from_url(url, decode_responses=True)
