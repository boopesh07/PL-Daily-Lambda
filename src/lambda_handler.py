from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Dict

from .config import get_config
from .redis_cache import push_daily_pl_to_redis
from .service import collect_daily_pl, serialize_pl

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def _async_collect() -> Dict[str, Any]:
    config = get_config()
    entries = await collect_daily_pl(config)
    await push_daily_pl_to_redis(config, entries)
    payload = {
        "count": len(entries),
        "items": serialize_pl(entries),
    }
    return payload


def _run_async(coro: Awaitable[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        return asyncio.run(coro)
    except RuntimeError as exc:
        if "asyncio.run()" not in str(exc):
            raise
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            asyncio.set_event_loop(None)
            loop.close()


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler.

    The event is expected to be provided by EventBridge; it is not used directly.
    Returns a JSON-serializable dictionary containing the ticker count and P&L data.
    """
    LOGGER.info("lambda_invocation")
    payload = _run_async(_async_collect())

    LOGGER.info("lambda_completed", extra={"count": payload.get("count", 0)})
    return payload
