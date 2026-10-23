# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The whole bridge over real WebSockets: a browser, a fake speech server and a fake rosbridge."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import websockets
from conftest import ARM

from voicebridge.catalogue import load
from voicebridge.realtime import scripted_sentence
from voicebridge.robot import RosbridgeRobot
from voicebridge.rosbridge import Rosbridge
from voicebridge.server import BridgeServer


class FakeSpeechServer:
    """The speech-to-speech server: records what it gets; the test says what it sends."""

    def __init__(self) -> None:
        self.received: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.socket: Any = None
        self.connected = asyncio.Event()
        self.path = ""

    async def start(self) -> str:
        self._server = await websockets.serve(self._handle, "127.0.0.1", 0, subprotocols=["realtime"])
        port = next(iter(self._server.sockets)).getsockname()[1]
        return f"ws://127.0.0.1:{port}/v1/realtime"

    async def stop(self) -> None:
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, socket: Any) -> None:
        self.socket, self.path = socket, socket.request.path
        self.offered = [v.strip() for v in socket.request.headers.get("Sec-WebSocket-Protocol", "").split(",")]
        self.connected.set()
        async for raw in socket:
            await self.received.put(json.loads(raw))

    async def send(self, *events: dict[str, Any]) -> None:
        for event in events:
            await self.socket.send(json.dumps(event))

    async def expect(self, kind: str) -> dict[str, Any]:
        while True:
            event = await asyncio.wait_for(self.received.get(), 5)
            if event.get("type") == kind:
                return event


async def test_a_spoken_command_from_the_browser_to_the_robot(fake_rosbridge):
    speech = FakeSpeechServer()
    upstream_url = await speech.start()
    rosbridge = Rosbridge(fake_rosbridge.url)
    bridge = BridgeServer(load(ARM), RosbridgeRobot(rosbridge), upstream_url, "127.0.0.1", 0)
    await bridge.start()
    try:
        # As the OpenAI Agents SDK in the browser connects.
        async with websockets.connect(f"ws://127.0.0.1:{bridge.port}/v1/realtime?model=x",
                                      subprotocols=["realtime", "openai-insecure-api-key.k", "openai-beta.v1"]) \
                as browser:
            await asyncio.wait_for(speech.connected.wait(), 5)
            assert speech.path.endswith("?model=x")
            assert browser.subprotocol == "realtime"
            assert speech.offered == ["realtime", "openai-insecure-api-key.k", "openai-beta.v1"]

            # The browser configures its session: the robot's tools are added on the way.
            await browser.send(json.dumps({"type": "session.update", "session": {"instructions": "Hi."}}))
            update = await speech.expect("session.update")
            assert [tool["name"] for tool in update["session"]["tools"]] == ["turn_joint", "halt", "where"]

            # The LLM calls the tool; the browser never sees the call.
            call = {"id": "item_1", "type": "function_call", "name": "turn_joint", "call_id": "call_1",
                    "arguments": json.dumps({"degrees": 10, "direction": "left"})}
            await speech.send(
                {"type": "response.created", "response": {"id": "r1"}},
                {"type": "response.output_item.added", "response_id": "r1", "item": {**call, "arguments": ""}},
                {"type": "response.output_item.done", "response_id": "r1", "item": call},
                {"type": "response.done", "response": {"id": "r1", "status": "completed", "output": [call]}},
            )
            output = await speech.expect("conversation.item.create")
            assert output["item"]["call_id"] == "call_1"
            create = await speech.expect("response.create")
            tag = create["response"]["metadata"]["voicebridge"]
            said = scripted_sentence(create["response"]["instructions"])
            assert said == "Turning 10 degrees left. Say yes to confirm."

            # The voice reads it back; the user says yes.
            await speech.send(
                {"type": "response.created", "response": {"id": "r2", "metadata": {"voicebridge": tag}}},
                {"type": "response.output_audio_transcript.done", "response_id": "r2",
                 "transcript": "Turning 10 degrees left. Say yes to confirm."},
                {"type": "response.done", "response": {"id": "r2", "status": "completed",
                                                       "metadata": {"voicebridge": tag}, "output": []}},
                {"type": "input_audio_buffer.speech_started"},
                {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Yes."},
            )
            await speech.expect("response.cancel")
            done = await speech.expect("response.create")
            assert scripted_sentence(done["response"]["instructions"]) == "Turned."

            # The goal went to rosbridge, exactly once.
            goals = fake_rosbridge.ops("send_action_goal")
            assert [(g["action"], g["args"]) for g in goals] == [("/arm/move", {"joint": "base", "angle": 10.0})]

            # What the browser saw: the responses and the transcript, never the call.
            await asyncio.sleep(0.1)
            seen = []
            while True:
                try:
                    seen.append(json.loads(await asyncio.wait_for(browser.recv(), 0.1)))
                except asyncio.TimeoutError:
                    break
            kinds = [event["type"] for event in seen]
            assert "response.output_item.added" not in kinds and "response.output_item.done" not in kinds
            assert "conversation.item.input_audio_transcription.completed" in kinds
            r1_done = next(e for e in seen if e["type"] == "response.done" and e["response"]["id"] == "r1")
            assert r1_done["response"]["output"] == []
    finally:
        await bridge.stop()
        await rosbridge.close()
        await speech.stop()


async def test_the_browser_is_told_when_the_speech_server_is_down():
    bridge = BridgeServer(load(ARM), RosbridgeRobot(Rosbridge("ws://127.0.0.1:9")), "ws://127.0.0.1:9/v1/realtime",
                          "127.0.0.1", 0)
    await bridge.start()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{bridge.port}") as browser:
            await asyncio.wait_for(browser.wait_closed(), 5)
            assert browser.close_code == 1011
    finally:
        await bridge.stop()
