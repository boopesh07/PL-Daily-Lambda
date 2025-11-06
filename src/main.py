from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from .config import get_config
from .redis_cache import push_daily_pl_to_redis
from .service import collect_daily_pl, serialize_pl


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def _async_entry(limit: Optional[int]) -> None:
    config = get_config()
    entries = await collect_daily_pl(config)
    await push_daily_pl_to_redis(config, entries)
    print(f"Collected daily P&L for {len(entries)} tickers.")

    serialized = serialize_pl(entries)
    if limit is not None and limit >= 0:
        subset = serialized[:limit]
    else:
        subset = serialized[:5]

    print(json.dumps(subset, indent=2))


def main() -> None:
    _setup_logging()
    limit_env = os.getenv("PRINT_LIMIT")
    try:
        limit = int(limit_env) if limit_env is not None else 5
    except ValueError:
        limit = 5
    asyncio.run(_async_entry(limit))


if __name__ == "__main__":
    main()
