# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The bridge's WebSocket server: the browser connects here instead of to the speech server.

For each browser that connects, the server opens its own connection to the
speech-to-speech server, creates a ``Session``, and pumps the events of both
connections through it. Frames that are not JSON pass through unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any
from urllib.parse import urlsplit

import websockets

from voicebridge.catalogue import Catalogue
from voicebridge.robot import Robot
from voicebridge.session import Session

log = logging.getLogger("voicebridge.server")


class BridgeServer:
    def __init__(self, catalogue: Catalogue, robot: Robot, upstream_url: str,
                 host: str = "0.0.0.0", port: int = 8766, mute_window_s: float = 10.0) -> None:
        self._catalogue = catalogue
        self._robot = robot
        self._upstream_url = upstream_url
        self._host = host
        self._port = port
        self._mute_window_s = mute_window_s
        self._server: Any = None

    @property
    def port(self) -> int:
        """The port listened on: the one asked for, or the one given for port 0."""
        if self._server is None:
            return self._port
        return next(iter(self._server.sockets)).getsockname()[1]

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle, self._host, self._port, max_size=None,
                                              select_subprotocol=_select_subprotocol)
        log.info("Listening on ws://%s:%d, forwarding to %s", self._host, self.port, self._upstream_url)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def serve_forever(self) -> None:
        await self.start()
        try:
            await asyncio.Future()
        finally:
            await self.stop()

    def _upstream_for(self, browser: Any) -> str:
        # Keep the browser's query string, e.g. ?model=..., on the way to the speech server.
        path = getattr(getattr(browser, "request", None), "path", "") or ""
        query = urlsplit(path).query
        if not query:
            return self._upstream_url
        return self._upstream_url + ("&" if "?" in self._upstream_url else "?") + query

    async def _handle(self, browser: Any) -> None:
        log.info("Browser connected")
        try:
            async with websockets.connect(self._upstream_for(browser), max_size=None,
                                          subprotocols=_offered(browser) or ["realtime"]) as upstream:
                await self._relay(browser, upstream)
        except (OSError, websockets.exceptions.InvalidHandshake) as exc:
            log.error("Cannot reach the speech server at %s: %s", self._upstream_url, exc)
            with contextlib.suppress(Exception):
                await browser.close(code=1011, reason="The speech-to-speech server cannot be reached")
        finally:
            log.info("Browser disconnected")

    async def _relay(self, browser: Any, upstream: Any) -> None:
        upstream_lock = asyncio.Lock()

        async def to_browser(event: dict[str, Any]) -> None:
            await browser.send(json.dumps(event))

        async def to_upstream(event: dict[str, Any]) -> None:
            async with upstream_lock:
                await upstream.send(json.dumps(event))

        session = Session(self._catalogue, self._robot, to_browser, to_upstream,
                          mute_window_s=self._mute_window_s)

        async def browser_to_upstream() -> None:
            async for raw in browser:
                event = _parse(raw)
                if event is None:
                    async with upstream_lock:
                        await upstream.send(raw)
                else:
                    await session.from_browser(event)

        async def upstream_to_browser() -> None:
            async for raw in upstream:
                event = _parse(raw)
                if event is None:
                    await browser.send(raw)
                else:
                    await session.from_upstream(event)

        tasks = {asyncio.create_task(browser_to_upstream()), asyncio.create_task(upstream_to_browser())}
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                error = task.exception()
                if error is not None and not isinstance(error, websockets.exceptions.ConnectionClosed):
                    log.error("A relay ended with an error: %r", error)
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            await session.close()


def _offered(browser: Any) -> list[str]:
    """The subprotocols the browser offered, passed on to the speech server: the OpenAI Agents
    SDK offers `realtime`, its key as `openai-insecure-api-key.<key>`, and its version."""
    headers = getattr(getattr(browser, "request", None), "headers", None)
    if headers is None:
        return []
    return [value.strip() for header in headers.get_all("Sec-WebSocket-Protocol")
            for value in header.split(",") if value.strip()]


def _select_subprotocol(connection: Any, subprotocols: Any) -> Any:
    # `realtime` when the browser offers it, as the speech server answers; none otherwise,
    # rather than refusing a client that offers none.
    return "realtime" if "realtime" in subprotocols else None


def _parse(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        event = json.loads(raw)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None
