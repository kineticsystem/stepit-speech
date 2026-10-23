# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""Fakes shared by the tests: a robot, a clock, and a rosbridge server."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import websockets

from voicebridge.catalogue import Catalogue, load
from voicebridge.robot import Outcome, Request

ROOT = Path(__file__).resolve().parent.parent
ARM = ROOT / "tests" / "robots" / "arm.yaml"
STEPIT_MACRO = ROOT / "robots" / "stepit-macro" / "robot.yaml"


@pytest.fixture
def arm() -> Catalogue:
    return load(ARM)


@pytest.fixture
def stepit_macro() -> Catalogue:
    return load(STEPIT_MACRO)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeRobot:
    """Records every request; answers by target, with an Outcome or a value to read."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.outcomes: dict[str, Outcome] = {}
        # Set it to make execute wait, e.g. to test a command that runs while the session closes.
        self.gate: asyncio.Event | None = None
        self.cancelled = False

    async def execute(self, request: Request) -> Outcome:
        self.requests.append(request)
        if self.gate is not None:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self.outcomes.get(request.target, Outcome(True, "", None))

    @property
    def targets(self) -> list[str]:
        return [request.target for request in self.requests]


class FakeRosbridge:
    """A rosbridge server: answers by service, action and topic name, and records what it got."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.services: dict[str, Any] = {}       # name -> values, or an Exception for result false
        self.actions: dict[str, tuple[int, Any]] = {}  # name -> (status, values)
        self.topics: dict[str, Any] = {}          # name -> the message published on subscribe
        self.hold_actions = False                 # never answer goals, e.g. to test cancellation
        self.fragment_size: int | None = None
        self._server: Any = None
        self.sockets: set[Any] = set()

    @property
    def url(self) -> str:
        port = next(iter(self._server.sockets)).getsockname()[1]
        return f"ws://127.0.0.1:{port}"

    async def start(self, port: int = 0) -> None:
        self._server = await websockets.serve(self._handle, "127.0.0.1", port)

    async def stop(self) -> None:
        for socket in list(self.sockets):
            await socket.close()
        self._server.close()
        await self._server.wait_closed()

    def ops(self, op: str) -> list[dict[str, Any]]:
        return [message for message in self.received if message.get("op") == op]

    async def _send(self, socket: Any, message: dict[str, Any]) -> None:
        text = json.dumps(message)
        if self.fragment_size is None or len(text) <= self.fragment_size:
            await socket.send(text)
            return
        parts = [text[i:i + self.fragment_size] for i in range(0, len(text), self.fragment_size)]
        for number, part in enumerate(parts):
            await socket.send(json.dumps({"op": "fragment", "id": "f", "data": part, "num": number,
                                          "total": len(parts)}))

    async def _handle(self, socket: Any) -> None:
        self.sockets.add(socket)
        try:
            async for raw in socket:
                message = json.loads(raw)
                self.received.append(message)
                op = message.get("op")
                if op == "call_service":
                    answer = self.services.get(message["service"])
                    if answer is None:
                        await self._send(socket, {"op": "status", "id": message["id"], "level": "error",
                                                  "msg": f"no service {message['service']}"})
                    elif isinstance(answer, Exception):
                        await self._send(socket, {"op": "service_response", "id": message["id"],
                                                  "result": False, "values": str(answer)})
                    else:
                        await self._send(socket, {"op": "service_response", "id": message["id"],
                                                  "service": message["service"], "result": True, "values": answer})
                elif op == "send_action_goal" and not self.hold_actions:
                    status, values = self.actions.get(message["action"], (4, {}))
                    await self._send(socket, {"op": "action_result", "id": message["id"],
                                              "action": message["action"], "status": status,
                                              "result": True, "values": values})
                elif op == "subscribe" and message["topic"] in self.topics:
                    await self._send(socket, {"op": "publish", "topic": message["topic"],
                                              "msg": self.topics[message["topic"]]})
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.sockets.discard(socket)


@pytest.fixture
async def fake_rosbridge():
    server = FakeRosbridge()
    await server.start()
    yield server
    await server.stop()
