"""Retrying HTTP requests shared by every external adapter.

Every adapter calls `send`, so retries, backoff and Retry-After handling behave
the same for all third-party APIs. Status codes an API uses to mean something
specific (PredictHQ's 402 for an empty plan) are checked by the adapter on the
response `send` returns.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Collection

log = logging.getLogger(__name__)

# Rate limited, or a server-side failure worth waiting out.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

type Sleep = Callable[[float], Awaitable[None]]


class RetriesExhaustedError(Exception):
    """Still rate limited or failing after every retry.

    `response` is the last response, or None if the last attempt never got one
    (a network error).
    """

    def __init__(self, message: str, response: httpx.Response | None) -> None:
        super().__init__(message)
        self.response = response


async def send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    backoff: float = 2.0,
    retry_on: Collection[int] = RETRY_STATUSES,
    sleep: Sleep = asyncio.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request, retrying `retry_on` statuses and network errors.

    Pass a narrower `retry_on` for an API whose 429 means "come back
    tomorrow" rather than "slow down", so it fails fast instead of waiting.

    Waits the server's Retry-After when it gives one, otherwise `backoff`
    doubling per attempt. Returns the first response whose status isn't
    retryable, without raising for it: the caller decides what a 4xx means.

    Raises:
        RetriesExhaustedError: If every attempt was retryable.
    """
    response: httpx.Response | None = None
    problem = ""
    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            response, problem = None, f"network error: {exc}"
            delay = backoff * 2**attempt
        else:
            if response.status_code not in retry_on:
                return response
            problem = f"HTTP {response.status_code}"
            delay = _retry_after(response) or backoff * 2**attempt

        if attempt < max_retries:
            log.warning("%s %s: %s, retrying in %.0fs", method, url, problem, delay)
            await sleep(delay)

    raise RetriesExhaustedError(f"{problem} after {max_retries} retries", response)


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None
