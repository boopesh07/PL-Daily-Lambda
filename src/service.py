from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any, Dict, Iterable, List

from .config import AppConfig
from .polygon_client import (
    fetch_all_active_stock_tickers,
    fetch_market_snapshots,
)

LOGGER = logging.getLogger(__name__)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class TickerPL:
    ticker: str
    daily_pl: float | None
    daily_pl_percent: float | None
    min_close: float | None
    date: str

    def to_dict(self) -> Dict[str, float | str | None]:
        return asdict(self)


async def collect_daily_pl(config: AppConfig) -> List[TickerPL]:
    LOGGER.info("collect_daily_pl_start")
    try:
        tz = ZoneInfo(config.pl_timezone)
    except ZoneInfoNotFoundError:
        LOGGER.warning("timezone_not_found", extra={"timezone": config.pl_timezone})
        tz = ZoneInfo("America/New_York")
    as_of = datetime.now(tz).strftime("%Y-%m-%d")
    tickers = await fetch_all_active_stock_tickers(
        config.api_key,
        http_timeout=config.http_timeout,
        http_read_timeout=config.http_read_timeout,
    )

    if config.ticker_limit is not None:
        tickers = tickers[: config.ticker_limit]
        LOGGER.info(
            "ticker_limit_applied",
            extra={"limit": config.ticker_limit, "actual": len(tickers)},
        )

    LOGGER.info("ticker_fetch_done", extra={"count": len(tickers)})

    snapshots = await fetch_market_snapshots(
        config.api_key,
        tickers,
        include_otc=config.include_otc,
        http_timeout=config.http_timeout,
        http_read_timeout=config.http_read_timeout,
        batch_size=config.ticker_batch_size,
        concurrency=config.snapshot_concurrency,
    )
    LOGGER.info("snapshot_fetch_done", extra={"count": len(snapshots)})

    pl_entries: List[TickerPL] = []
    for snap in snapshots:
        ticker = snap.get("ticker")
        if not isinstance(ticker, str) or not ticker:
            continue

        todays_change = _to_float(snap.get("todaysChange"))
        todays_change_perc = _to_float(snap.get("todaysChangePerc"))
        minute_close = None
        minute_block = snap.get("min")
        if isinstance(minute_block, dict):
            minute_close = _to_float(minute_block.get("c"))

        pl_entries.append(
            TickerPL(
                ticker=ticker.upper(),
                daily_pl=todays_change,
                daily_pl_percent=todays_change_perc,
                min_close=minute_close,
                date=as_of,
            )
        )

    LOGGER.info("collect_daily_pl_complete", extra={"count": len(pl_entries)})
    return pl_entries


def serialize_pl(entries: Iterable[TickerPL]) -> List[Dict[str, float | str | None]]:
    """Return plain dictionaries, ready for JSON serialization."""
    return [entry.to_dict() for entry in entries]
