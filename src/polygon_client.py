from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List, Optional, Sequence

import httpx

LOGGER = logging.getLogger(__name__)


class PolygonApiError(RuntimeError):
    """Raised when Polygon responds with a non-success status code."""


def _chunked(items: Sequence[str], chunk_size: int) -> Iterable[List[str]]:
    for idx in range(0, len(items), chunk_size):
        yield list(items[idx : idx + chunk_size])


async def fetch_all_active_stock_tickers(
    api_key: str,
    *,
    http_timeout: float = 20.0,
    http_read_timeout: float = 60.0,
    per_page_limit: int = 1000,
    active_only: bool = True,
) -> List[str]:
    """Return the full list of active stock tickers from Massive/Polygon."""
    if not api_key:
        raise ValueError("API key is required")

    base_url = "https://api.polygon.io/v3/reference/tickers"
    params = {
        "market": "stocks",
        "active": str(bool(active_only)).lower(),
        "order": "asc",
        "limit": per_page_limit,
        "sort": "ticker",
        "apiKey": api_key,
    }
    tickers: List[str] = []

    timeout = httpx.Timeout(http_timeout, read=http_read_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        next_url: Optional[str] = base_url
        query = params
        while next_url:
            LOGGER.debug("ticker_fetch_page", extra={"url": next_url})
            if next_url == base_url:
                resp = await client.get(next_url, params=query)
            else:
                if "apiKey=" in next_url:
                    resp = await client.get(next_url)
                else:
                    resp = await client.get(next_url, params={"apiKey": api_key})

            if resp.status_code >= 400:
                raise PolygonApiError(
                    f"Ticker page fetch failed status={resp.status_code} body={resp.text}"
                )

            payload = resp.json()
            page_results = payload.get("results") or []
            for item in page_results:
                ticker = item.get("ticker")
                if isinstance(ticker, str) and ticker:
                    tickers.append(ticker.upper())

            LOGGER.info(
                "ticker_page_fetched",
                extra={
                    "pageCount": len(page_results),
                    "totalTickers": len(tickers),
                    "hasNext": bool(payload.get("next_url")),
                },
            )

            next_url = payload.get("next_url")
            if next_url and "apiKey=" not in next_url:
                next_url = f"{next_url}&apiKey={api_key}"
            query = None

    LOGGER.info("ticker_discovery_complete", extra={"count": len(tickers)})
    return tickers


async def fetch_market_snapshots(
    api_key: str,
    tickers: Sequence[str],
    *,
    include_otc: bool = False,
    http_timeout: float = 20.0,
    http_read_timeout: float = 60.0,
    batch_size: int = 500,
    concurrency: int = 5,
) -> List[dict]:
    """
    Fetch snapshot payloads for batches of tickers.

    Returns the raw ticker dictionaries from Polygon's response.
    """
    if not api_key:
        raise ValueError("API key is required")

    tickers = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
    if not tickers:
        return []

    url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
    timeout = httpx.Timeout(http_timeout, read=http_read_timeout)
    results: List[dict] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def fetch_chunk(chunk: List[str]) -> List[dict]:
            params = {
                "tickers": ",".join(chunk),
                "include_otc": str(include_otc).lower(),
                "apiKey": api_key,
            }
            LOGGER.info(
                "snapshot_request",
                extra={"chunkSize": len(chunk), "firstTicker": chunk[0]},
            )
            async with semaphore:
                resp = await client.get(url, params=params)
            if resp.status_code >= 400:
                raise PolygonApiError(
                    f"Snapshot fetch failed status={resp.status_code} body={resp.text}"
                )
            payload = resp.json()
            data = payload.get("tickers") or []
            LOGGER.info(
                "snapshot_page_fetched",
                extra={"chunkSize": len(chunk), "returned": len(data)},
            )
            return data

        tasks = [
            asyncio.create_task(fetch_chunk(chunk))
            for chunk in _chunked(tickers, max(1, batch_size))
        ]

        for task in asyncio.as_completed(tasks):
            results.extend(await task)

    return results
