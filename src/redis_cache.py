from __future__ import annotations

import json
import logging
from typing import Iterable, List, Sequence

import httpx

from .config import AppConfig
from .service import TickerPL

LOGGER = logging.getLogger(__name__)


class RedisCacheError(RuntimeError):
    """Raised when Redis/Upstash operations fail."""


def _chunked(entries: Sequence[TickerPL], chunk_size: int) -> Iterable[Sequence[TickerPL]]:
    for idx in range(0, len(entries), chunk_size):
        yield entries[idx : idx + chunk_size]


async def push_daily_pl_to_redis(config: AppConfig, entries: Sequence[TickerPL]) -> None:
    """
    Persist each ticker's daily P&L snapshot to Upstash Redis using pipeline calls.

    A key with the pattern `{prefix}:{TICKER}` is written with a JSON payload containing
    `ticker`, `daily_pl`, and `daily_pl_percent`. Optional TTL is applied when configured.
    """
    if not config.redis_url or not config.redis_token:
        LOGGER.info("redis_disabled")
        return

    entries = list(entries)
    if not entries:
        LOGGER.info("redis_skipped_empty")
        return

    pipeline_size = max(1, config.redis_pipeline_size)
    redis_url = config.redis_url.rstrip("/")
    endpoint = f"{redis_url}/pipeline"
    headers = {
        "Authorization": f"Bearer {config.redis_token}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(config.http_timeout, read=config.http_read_timeout)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for batch in _chunked(entries, pipeline_size):
            commands: List[List[str]] = []
            for ticker_pl in batch:
                key = f"{config.redis_key_prefix}:{ticker_pl.ticker}"
                value = json.dumps(ticker_pl.to_dict(), separators=(",", ":"))
                commands.append(["SET", key, value])
                if config.redis_ttl_seconds is not None:
                    commands.append(
                        ["EXPIRE", key, str(config.redis_ttl_seconds)]
                    )

            payload = commands
            LOGGER.info(
                "redis_pipeline_publish",
                extra={"batchSize": len(batch), "commands": len(commands)},
            )
            resp = await client.post(endpoint, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise RedisCacheError(
                    f"Redis pipeline failed status={resp.status_code} body={resp.text}"
                )

    LOGGER.info("redis_publish_complete", extra={"count": len(entries)})
