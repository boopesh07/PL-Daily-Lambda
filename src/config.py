from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

# Load .env when running locally; Lambda ignores missing files.
load_dotenv()


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y"}


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    include_otc: bool
    ticker_batch_size: int
    snapshot_concurrency: int
    http_timeout: float
    http_read_timeout: float
    ticker_limit: int | None
    redis_url: str | None
    redis_token: str | None
    redis_pipeline_size: int
    redis_key_prefix: str
    redis_ttl_seconds: int | None
    pl_timezone: str


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    api_key = os.getenv("POLYGON_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "POLYGON_API_KEY is required. "
            "Set it via environment variable or .env file."
        )

    include_otc = _parse_bool(os.getenv("INCLUDE_OTC"), default=False)
    batch_size = max(1, _parse_int(os.getenv("TICKER_BATCH_SIZE"), default=500))
    concurrency = max(1, _parse_int(os.getenv("SNAPSHOT_CONCURRENCY"), default=5))

    http_timeout = float(os.getenv("HTTP_CONNECT_TIMEOUT", "20"))
    http_read_timeout = float(os.getenv("HTTP_READ_TIMEOUT", "60"))
    ticker_limit_raw = os.getenv("TICKER_LIMIT")
    ticker_limit = None
    if ticker_limit_raw:
        try:
            value = int(ticker_limit_raw)
            if value > 0:
                ticker_limit = value
        except ValueError:
            ticker_limit = None

    redis_url = os.getenv("REDIS_URL")
    redis_token = os.getenv("REDIS_TOKEN")
    redis_pipeline_size = max(1, _parse_int(os.getenv("REDIS_PIPELINE_SIZE"), default=50))
    redis_key_prefix = os.getenv("REDIS_KEY_PREFIX", "stock:pl_daily")
    redis_ttl_seconds_raw = os.getenv("REDIS_TTL_SECONDS", "86400")
    redis_ttl_seconds = None
    try:
        ttl_val = int(redis_ttl_seconds_raw)
        if ttl_val > 0:
            redis_ttl_seconds = ttl_val
    except ValueError:
        redis_ttl_seconds = None
    pl_timezone = os.getenv("PL_TIMEZONE", "America/New_York")

    return AppConfig(
        api_key=api_key,
        include_otc=include_otc,
        ticker_batch_size=batch_size,
        snapshot_concurrency=concurrency,
        http_timeout=http_timeout,
        http_read_timeout=http_read_timeout,
        ticker_limit=ticker_limit,
        redis_url=redis_url,
        redis_token=redis_token,
        redis_pipeline_size=redis_pipeline_size,
        redis_key_prefix=redis_key_prefix,
        redis_ttl_seconds=redis_ttl_seconds,
        pl_timezone=pl_timezone,
    )
