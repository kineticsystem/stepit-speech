# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""A client of rosbridge: ROS 2 over a WebSocket that speaks JSON, so the bridge needs no ROS.

The operations are those of StepIt UI's rosbridge.ts:

    → call_service       a request                 ← service_response
    → send_action_goal   a goal                    ← action_feedback, action_result
    → cancel_action_goal
    → subscribe          a topic                   ← publish, for each message
    → unsubscribe
    → advertise, publish a message
                                                   ← fragment, parts of a large message
                                                   ← status, a refused request

The client connects on first use and again after the connection drops, e.g.
while the robot restarts. It never retries an operation: a goal whose end is
unknown fails, so that the user is told rather than misled.

The bridge also keeps it connected (``keep_connected``), so that the first
command does not wait for the connection: over Wi-Fi, the robot's first
answer after a quiet spell took more than 3 seconds, and the command failed.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
from dataclasses import dataclass
from typing import Any

import websockets

log = logging.getLogger("voicebridge.rosbridge")


class RosbridgeError(Exception):
    """rosbridge cannot be reached, refused the request, or did not answer in time."""


@dataclass(frozen=True)
class ActionResult:
    """How an action goal ended: the GoalStatus of action_msgs (4 succeeded, 5 canceled, 6 aborted)."""

    status: int
    values: Any


_ids = itertools.count()


def _unique_id(what: str) -> str:
    return f"voicebridge-{what}-{next(_ids)}"


class Rosbridge:
    """One connection to rosbridge, shared by every session of the bridge."""

    def __init__(self, url: str, connect_timeout_s: float = 10.0) -> None:
        self.url = url
        self._connect_timeout_s = connect_timeout_s
        self._keeper: asyncio.Task | None = None
        self._socket: Any = None
        self._reader: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future] = {}
        self._topics: dict[str, asyncio.Queue] = {}
        self._fragments: dict[str, list[str | None]] = {}
        self._advertised: dict[str, str] = {}

    async def call_service(self, service: str, type: str, args: Any, timeout_s: float = 10.0) -> Any:
        """Calls a service and returns its response."""
        id = _unique_id("call")
        future = await self._send_and_expect(
            id, {"op": "call_service", "id": id, "service": service, "type": type, "args": args or {}}
        )
        return await self._wait(future, id, timeout_s, f"{service} did not answer in {timeout_s:g} s")

    async def send_action_goal(self, action: str, type: str, goal: Any, timeout_s: float = 600.0) -> ActionResult:
        """Sends a goal and waits for its end. On timeout or cancellation, cancels the goal."""
        id = _unique_id("goal")
        future = await self._send_and_expect(
            id,
            {"op": "send_action_goal", "id": id, "action": action, "action_type": type, "args": goal or {},
             "feedback": False},
        )
        try:
            return await self._wait(future, id, timeout_s, f"{action} did not end in {timeout_s:g} s")
        except (RosbridgeError, asyncio.CancelledError):
            with contextlib.suppress(Exception):
                await self._send({"op": "cancel_action_goal", "id": id, "action": action})
            raise

    async def read_topic(self, topic: str, type: str, qos: dict[str, Any] | None = None,
                         timeout_s: float = 3.0) -> Any:
        """The next message of a topic, e.g. the last one of a latched topic."""
        id = _unique_id("subscribe")
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            await self._connect()
            self._topics[topic] = queue
            message = {"op": "subscribe", "id": id, "topic": topic, "type": type, "queue_length": 1}
            if qos:
                message["qos"] = qos
            await self._socket.send(json.dumps(message))
        try:
            return await asyncio.wait_for(queue.get(), timeout_s)
        except asyncio.TimeoutError as exc:
            raise RosbridgeError(f"no message on {topic} in {timeout_s:g} s") from exc
        finally:
            if self._topics.get(topic) is queue:
                del self._topics[topic]
                with contextlib.suppress(Exception):
                    await self._send({"op": "unsubscribe", "id": id, "topic": topic})

    async def publish(self, topic: str, type: str, message: Any) -> None:
        """Publishes one message, advertising the topic first when needed."""
        async with self._lock:
            await self._connect()
            if self._advertised.get(topic) != type:
                await self._socket.send(json.dumps({"op": "advertise", "id": _unique_id("advertise"),
                                                    "topic": topic, "type": type}))
                self._advertised[topic] = type
            await self._socket.send(json.dumps({"op": "publish", "topic": topic, "msg": message}))

    def keep_connected(self, interval_s: float = 5.0) -> None:
        """Connects now, in the background, and again every ``interval_s`` while the connection is down."""
        if self._keeper is None:
            self._keeper = asyncio.create_task(self._keep_connected(interval_s))

    async def _keep_connected(self, interval_s: float) -> None:
        reported = False
        while True:
            try:
                async with self._lock:
                    await self._connect()
                reported = False
            except RosbridgeError as exc:
                if not reported:
                    # Once per outage: the robot may be off for hours.
                    log.warning("%s: trying again every %g s", exc, interval_s)
                    reported = True
            await asyncio.sleep(interval_s)

    async def close(self) -> None:
        if self._keeper is not None:
            self._keeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keeper
            self._keeper = None
        socket, self._socket = self._socket, None
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close()
        self._fail_pending("the connection to rosbridge was closed")

    # ── Internals ──────────────────────────────────────────────────────────────

    async def _send_and_expect(self, id: str, message: dict[str, Any]) -> asyncio.Future:
        future = asyncio.get_running_loop().create_future()
        async with self._lock:
            await self._connect()
            self._pending[id] = future
            await self._socket.send(json.dumps(message))
        return future

    async def _wait(self, future: asyncio.Future, id: str, timeout_s: float, late: str) -> Any:
        try:
            return await asyncio.wait_for(future, timeout_s)
        except asyncio.TimeoutError as exc:
            raise RosbridgeError(late) from exc
        finally:
            self._pending.pop(id, None)

    async def _send(self, message: dict[str, Any]) -> None:
        async with self._lock:
            if self._socket is not None:
                await self._socket.send(json.dumps(message))

    async def _connect(self) -> None:
        if self._socket is not None:
            return
        try:
            self._socket = await asyncio.wait_for(
                websockets.connect(self.url, max_size=None), self._connect_timeout_s
            )
        except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException) as exc:
            raise RosbridgeError(f"cannot reach rosbridge at {self.url}") from exc
        self._advertised.clear()
        self._reader = asyncio.create_task(self._read(self._socket))
        log.info("Connected to rosbridge at %s", self.url)

    async def _read(self, socket: Any) -> None:
        try:
            async for raw in socket:
                self._receive(raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if self._socket is socket:
                self._socket = None
                self._fail_pending(f"the connection to rosbridge at {self.url} was lost")
                log.warning("Lost the connection to rosbridge at %s", self.url)

    def _receive(self, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            return
        op, id = message.get("op"), message.get("id")
        if op == "fragment" and id is not None:
            parts = self._fragments.setdefault(id, [None] * int(message.get("total", 1)))
            parts[int(message.get("num", 0))] = message.get("data", "")
            if all(part is not None for part in parts):
                del self._fragments[id]
                self._receive("".join(parts))  # type: ignore[arg-type]
        elif op == "publish":
            queue = self._topics.get(message.get("topic"))
            if queue is not None:
                queue.put_nowait(message.get("msg"))
        elif op == "service_response":
            # On failure, e.g. an unknown service, rosbridge puts its error in values.
            if message.get("result") is False:
                self._settle(id, error=str(message.get("values")))
            else:
                self._settle(id, value=message.get("values"))
        elif op == "action_result":
            if message.get("result") is False:
                self._settle(id, error=str(message.get("values")))
            else:
                self._settle(id, value=ActionResult(int(message.get("status", 0)), message.get("values")))
        elif op == "status" and message.get("level") == "error" and id is not None:
            self._settle(id, error=str(message.get("msg", "rosbridge refused the request")))

    def _settle(self, id: str | None, value: Any = None, error: str | None = None) -> None:
        future = self._pending.get(id) if id is not None else None
        if future is None or future.done():
            return
        if error is not None:
            future.set_exception(RosbridgeError(error))
        else:
            future.set_result(value)

    def _fail_pending(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RosbridgeError(reason))
        self._pending.clear()
        self._fragments.clear()
