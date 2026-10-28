# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The safety rules of a voice session, driven by the events the speech server sends."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from conftest import FakeClock, FakeRobot

from voicebridge.conversation.prompt import AWAITING_CONFIRMATION
from voicebridge.conversation.session import (
    CANCELLED,
    MUTED_CALL,
    NOTHING_TO_CONFIRM,
    ONE_AT_A_TIME,
    READ_BACK_FAILED,
    SPOKE_OVER,
    TOO_LATE,
    Session,
)
from voicebridge.robot.request import Outcome
from voicebridge.safety.confirmation import Phase
from voicebridge.scripted import scripted_sentence

READ_BACK = "Turning 10 degrees left. Say yes to confirm."


class Harness:
    """A session between a fake browser and a fake speech server."""

    def __init__(self, catalogue, robot: FakeRobot | None = None) -> None:
        self.browser: list[dict[str, Any]] = []
        self.upstream: list[dict[str, Any]] = []
        self.robot = robot or FakeRobot()
        self.clock = FakeClock()
        self.session = Session(catalogue, self.robot, self._to_browser, self._to_upstream, clock=self.clock)
        self._responses = 0

    async def _to_browser(self, event):
        self.browser.append(event)

    async def _to_upstream(self, event):
        self.upstream.append(event)

    async def server(self, *events: dict[str, Any]) -> None:
        for event in events:
            await self.session.from_upstream(event)
        await self.session.wait_idle()

    def new_id(self) -> str:
        self._responses += 1
        return f"resp_{self._responses}"

    # ── What the speech server sends ──

    async def llm_calls(self, name: str, arguments: Any, call_id: str = "call_1",
                        response: str | None = None) -> str:
        """A response of the LLM that calls one tool."""
        rid = response or self.new_id()
        item = {"id": f"item_{call_id}", "type": "function_call", "name": name, "call_id": call_id, "arguments": ""}
        text = arguments if isinstance(arguments, str) else json.dumps(arguments)
        await self.server(
            {"type": "response.created", "response": {"id": rid, "status": "in_progress"}},
            {"type": "response.output_item.added", "response_id": rid, "item": item},
            {"type": "response.function_call_arguments.delta", "response_id": rid, "item_id": item["id"],
             "call_id": call_id, "delta": text},
            {"type": "response.function_call_arguments.done", "response_id": rid, "item_id": item["id"],
             "call_id": call_id, "arguments": text},
            {"type": "response.output_item.done", "response_id": rid, "item": {**item, "arguments": text}},
        )
        return rid

    async def response_done(self, rid: str, status: str = "completed") -> None:
        await self.server({"type": "response.done", "response": {"id": rid, "status": status, "output": []}})

    async def bridge_reply_said(self, text: str | None = None, status: str = "completed") -> str:
        """The server answers the bridge's last response.create, and the voice says `text`."""
        create = self.last("response.create")
        assert create is not None, "the bridge asked for nothing"
        tag = create["response"]["metadata"]["voicebridge"]
        rid = self.new_id()
        events = [{"type": "response.created", "response": {"id": rid, "metadata": {"voicebridge": tag}}}]
        if text is not None:
            events.append({"type": "response.output_audio_transcript.done", "response_id": rid, "transcript": text})
        events.append({"type": "response.done",
                       "response": {"id": rid, "status": status, "metadata": {"voicebridge": tag}, "output": []}})
        await self.server(*events)
        return rid

    async def user_says(self, text: str) -> None:
        await self.server({"type": "input_audio_buffer.speech_started"},
                          {"type": USER_TRANSCRIPT, "item_id": "item_user", "transcript": text})

    async def server_replies_itself(self, text: str = "Okay!") -> str:
        """The speech server's own reply to the user's turn, which nobody asked for."""
        rid = self.new_id()
        await self.server(
            {"type": "response.created", "response": {"id": rid}},
            {"type": "response.output_audio.delta", "response_id": rid, "delta": "AAAA"},
            {"type": "response.output_audio_transcript.done", "response_id": rid, "transcript": text},
            {"type": "response.done", "response": {"id": rid, "status": "completed", "output": []}},
        )
        return rid

    # ── What the bridge sent ──

    def last(self, kind: str) -> dict[str, Any] | None:
        return next((event for event in reversed(self.upstream) if event.get("type") == kind), None)

    def said(self) -> list[str]:
        """The sentences the bridge asked the voice to say exactly."""
        return [scripted_sentence(event["response"]["instructions"]) for event in self.upstream
                if event.get("type") == "response.create" and "instructions" in event.get("response", {})]

    def outputs(self) -> list[str]:
        return [event["item"]["output"] for event in self.upstream
                if event.get("type") == "conversation.item.create"
                and event["item"].get("type") == "function_call_output"]

    def count(self, kind: str) -> int:
        return sum(1 for event in self.upstream if event.get("type") == kind)


USER_TRANSCRIPT = "conversation.item.input_audio_transcription.completed"


@pytest.fixture
def harness(arm):
    return Harness(arm)


async def armed(harness: Harness) -> None:
    """A turn_joint command, read back exactly: waiting for the yes."""
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await harness.response_done(rid)
    await harness.bridge_reply_said(READ_BACK)
    assert harness.session.confirmation.phase is Phase.ARMED


# ── The happy path ─────────────────────────────────────────────────────────────

async def test_a_command_is_read_back_and_runs_after_yes(harness):
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    # The bridge answers the call only once the LLM's response is over.
    assert harness.outputs() == []
    await harness.response_done(rid)
    assert harness.outputs() == [AWAITING_CONFIRMATION]
    create = harness.last("response.create")
    assert create["response"]["tool_choice"] == "none"
    assert harness.said() == [READ_BACK]
    assert harness.robot.requests == []

    await harness.bridge_reply_said(READ_BACK)
    assert harness.session.confirmation.phase is Phase.ARMED
    assert harness.robot.requests == []

    await harness.user_says("yes please")
    assert harness.robot.targets == ["/arm/move"]
    assert harness.robot.requests[0].payload == {"joint": "base", "angle": 10.0}
    assert harness.said()[-1] == "Turned."


async def test_the_browser_never_sees_the_robot_tool_calls(harness):
    await armed(harness)
    kinds = [event["type"] for event in harness.browser]
    assert "response.output_item.added" not in kinds
    assert "response.output_item.done" not in kinds
    assert "response.function_call_arguments.delta" not in kinds
    assert "response.function_call_arguments.done" not in kinds
    # It does see the responses themselves, and the read-back the voice said.
    assert "response.output_audio_transcript.done" in kinds


async def test_the_server_reply_to_the_yes_is_muted_and_cancelled(harness):
    await armed(harness)
    await harness.user_says("yes")
    cancels = harness.count("response.cancel")
    browser_before = len(harness.browser)
    await harness.server_replies_itself("Sure, I'll do that!")
    assert harness.count("response.cancel") == cancels + 1
    assert harness.browser[browser_before:] == []


async def test_a_new_turn_is_not_muted(harness):
    await armed(harness)
    await harness.user_says("yes")
    await harness.server({"type": "input_audio_buffer.speech_started"})
    before = len(harness.browser)
    await harness.server_replies_itself("Hello")
    assert len(harness.browser) > before


# ── Everything that is not a clear yes ─────────────────────────────────────────

async def test_no_cancels(harness):
    await armed(harness)
    await harness.user_says("no")
    assert harness.robot.requests == []
    assert harness.said()[-1] == CANCELLED


async def test_anything_else_drops_the_command_and_goes_to_the_llm(harness):
    await armed(harness)
    await harness.user_says("actually make it 20 degrees")
    assert harness.session.confirmation.phase is Phase.IDLE
    before = len(harness.browser)
    await harness.server_replies_itself("Sure.")
    assert len(harness.browser) > before, "the LLM answers the new request"
    await harness.user_says("yes")
    assert harness.robot.requests == []


async def test_an_empty_transcript_keeps_the_pending_command(harness):
    # Seen on the rig: a noise became an empty transcript, which dropped the command waiting for its yes.
    await armed(harness)
    for said in ("", " ", "..."):
        await harness.user_says(said)
    assert harness.session.confirmation.phase is Phase.ARMED
    await harness.user_says("yes")
    assert harness.robot.targets == ["/arm/move"]


async def test_a_late_yes_runs_nothing(harness):
    await armed(harness)
    harness.clock.now += 11
    await harness.user_says("yes")
    assert harness.robot.requests == []
    assert harness.said()[-1] == TOO_LATE


async def test_a_yes_over_the_read_back_runs_nothing(harness):
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await harness.response_done(rid)
    await harness.user_says("yes")
    await harness.bridge_reply_said(READ_BACK)
    await harness.user_says("yes")
    assert harness.robot.requests == []


async def test_a_wrong_read_back_cancels_the_command(harness):
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await harness.response_done(rid)
    await harness.bridge_reply_said("Turning 10 degrees right. Say yes to confirm.")
    assert harness.session.confirmation.phase is Phase.IDLE
    assert harness.said()[-1] == READ_BACK_FAILED
    await harness.bridge_reply_said(READ_BACK_FAILED)
    await harness.user_says("yes")
    assert harness.robot.requests == []


async def test_an_interrupted_read_back_cancels_the_command(harness):
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await harness.response_done(rid)
    await harness.bridge_reply_said("Turning 10", status="cancelled")
    assert harness.session.confirmation.phase is Phase.IDLE


async def test_a_yes_with_no_command_pending_is_answered_by_the_bridge(harness):
    # The LLM never gets to play along with a yes that confirms nothing.
    await harness.user_says("yes")
    assert harness.count("response.cancel") == 1
    assert harness.said() == [NOTHING_TO_CONFIRM]
    assert harness.robot.requests == []


async def test_a_call_in_a_muted_reply_is_answered_and_not_run(harness):
    await harness.user_says("yes")
    # The server is already answering the yes itself, so it refuses the bridge's reply for now.
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await harness.server({"type": "error", "error": {"code": "conversation_already_has_active_response"}})
    await harness.response_done(rid)
    assert harness.outputs() == [MUTED_CALL]
    assert harness.said() == [NOTHING_TO_CONFIRM, NOTHING_TO_CONFIRM]
    assert harness.session.confirmation.phase is Phase.IDLE
    assert harness.robot.requests == []
    assert not [event for event in harness.browser if event.get("type") == "response.output_item.done"]


async def test_a_yes_over_the_read_back_is_answered_by_the_bridge(harness):
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await harness.response_done(rid)
    tag = harness.last("response.create")["response"]["metadata"]["voicebridge"]
    reading = harness.new_id()
    await harness.server({"type": "response.created", "response": {"id": reading, "metadata": {"voicebridge": tag}}})
    await harness.user_says("yes")
    await harness.response_done(reading, "cancelled")
    assert harness.said()[-1] == SPOKE_OVER
    assert harness.robot.requests == []


# ── Stop ───────────────────────────────────────────────────────────────────────

async def test_stop_runs_at_once_and_drops_the_pending_command(harness):
    await armed(harness)
    await harness.user_says("stop")
    assert harness.robot.targets == ["/arm/halt"]
    assert harness.said()[-1] == "Halted."
    assert harness.count("response.cancel") >= 1
    await harness.user_says("yes")
    assert harness.robot.targets == ["/arm/halt"]


async def test_a_stop_inside_a_request_stops_and_the_llm_still_hears_it(harness):
    await harness.user_says("stop and turn left 5 degrees")
    assert harness.robot.targets == ["/arm/halt"]
    assert harness.count("response.cancel") == 0
    before = len(harness.browser)
    await harness.server_replies_itself()
    assert len(harness.browser) > before


async def test_stop_while_the_bridge_speaks_cuts_it(harness):
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await harness.response_done(rid)
    create = harness.last("response.create")
    tag = create["response"]["metadata"]["voicebridge"]
    await harness.server({"type": "response.created", "response": {"id": "resp_speaking",
                                                                    "metadata": {"voicebridge": tag}}})
    await harness.user_says("halt")
    assert harness.robot.targets == ["/arm/halt"]
    await harness.server({"type": "response.done", "response": {"id": "resp_speaking", "status": "cancelled"}})
    assert harness.session.confirmation.phase is Phase.IDLE
    assert harness.said()[-1] == "Halted."


# ── Calls the bridge refuses or runs at once ──────────────────────────────────

async def test_wrong_arguments_are_rejected_and_the_llm_explains(harness):
    rid = await harness.llm_calls("turn_joint", {"degrees": 200, "direction": "left"})
    await harness.response_done(rid)
    assert harness.outputs()[0].startswith("Rejected: degrees must be at most 90")
    create = harness.last("response.create")
    assert "instructions" not in create["response"], "the LLM explains in its own words"
    assert harness.session.confirmation.phase is Phase.IDLE
    assert harness.robot.requests == []


async def test_arguments_that_are_not_json_are_rejected(harness):
    rid = await harness.llm_calls("turn_joint", "{degrees: ten")
    await harness.response_done(rid)
    assert harness.outputs()[0].startswith("Rejected:")


async def test_a_command_without_confirmation_runs_at_once(harness):
    rid = await harness.llm_calls("halt", {})
    assert harness.robot.targets == ["/arm/halt"], "it runs before the LLM's response is over"
    await harness.response_done(rid)
    assert harness.outputs() == ["Halted."]
    assert harness.said() == ["Halted."]


async def test_a_failure_is_said(harness):
    harness.robot.outcomes["/arm/halt"] = Outcome(False, "the motors are off")
    rid = await harness.llm_calls("halt", {})
    await harness.response_done(rid)
    assert harness.said() == ["That did not work: the motors are off."]


async def test_a_query_reads_and_answers(harness):
    harness.robot.outcomes["/arm/state"] = Outcome(True, "", {"angle": 30.0})
    rid = await harness.llm_calls("where", {})
    await harness.response_done(rid)
    assert harness.robot.targets == ["/arm/state"]
    assert harness.said() == ["The joint is at 30 degrees."]


async def test_one_command_per_response(harness):
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"}, call_id="call_1")
    await harness.llm_calls("halt", {}, call_id="call_2", response=rid)
    await harness.response_done(rid)
    assert ONE_AT_A_TIME in harness.outputs()
    assert harness.robot.requests == []


async def test_a_newer_command_replaces_one_not_yet_read_back(harness):
    first = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"}, call_id="call_1")
    second = await harness.llm_calls("turn_joint", {"degrees": 20, "direction": "right"}, call_id="call_2")
    await harness.response_done(first)
    await harness.response_done(second)
    # Both calls are answered; only the second is read back.
    assert len(harness.outputs()) == 2
    assert harness.said() == ["Turning 20 degrees right. Say yes to confirm."]
    await harness.bridge_reply_said("Turning 20 degrees right. Say yes to confirm.")
    await harness.user_says("ok")
    assert harness.robot.requests[0].payload["angle"] == -20.0


# ── Talking to the server ──────────────────────────────────────────────────────

async def test_the_session_update_gets_the_robot_tools(harness):
    await harness.session.from_browser({"type": "session.update", "session": {
        "instructions": "Be nice.", "tools": [{"type": "function", "name": "web_search"}], "tool_choice": "none"}})
    session = harness.upstream[0]["session"]
    assert [tool["name"] for tool in session["tools"]] == ["web_search", "turn_joint", "halt", "where"]
    assert session["tool_choice"] == "auto"
    assert session["instructions"].startswith("Be nice.")
    assert "You are the voice of Test Arm" in session["instructions"]


async def test_other_browser_events_pass_unchanged(harness):
    event = {"type": "input_audio_buffer.append", "audio": "AAAA"}
    await harness.session.from_browser(event)
    assert harness.upstream == [event]


async def test_a_busy_server_gets_asked_again_later(harness):
    rid = await harness.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await harness.response_done(rid)
    assert harness.count("response.create") == 1
    # The server was answering a turn of its own and refused.
    await harness.server({"type": "response.created", "response": {"id": "resp_other"}},
                         {"type": "error", "error": {"type": "invalid_request_error",
                                                     "code": "conversation_already_has_active_response",
                                                     "message": "Cannot create response"}})
    assert all(event.get("type") != "error" for event in harness.browser)
    await harness.response_done("resp_other")
    assert harness.count("response.create") == 2
    assert harness.said() == [READ_BACK, READ_BACK]
    await harness.bridge_reply_said(READ_BACK)
    assert harness.session.confirmation.phase is Phase.ARMED


async def test_closing_the_session_cancels_a_running_command(harness):
    harness.robot.gate = asyncio.Event()
    await armed(harness)
    await harness.session.from_upstream({"type": USER_TRANSCRIPT, "transcript": "yes"})
    await asyncio.sleep(0)
    assert harness.robot.targets == ["/arm/move"]
    await harness.session.close()
    assert harness.robot.cancelled


# ── Greeting ───────────────────────────────────────────────────────────────────

GREETING_PROMPT = {"type": "conversation.item.create", "item": {
    "type": "message", "role": "user",
    "content": [{"type": "input_text", "text": "Start the conversation now with a brief greeting."}]}}


async def test_the_robot_greets_in_place_of_the_llm(stepit_macro):
    harness = Harness(stepit_macro)
    await harness.session.from_browser(GREETING_PROMPT)
    await harness.session.from_browser({"type": "response.create"})
    assert harness.said() == ["Ready."]
    assert harness.count("response.create") == 1
    assert harness.count("conversation.item.create") == 0


async def test_a_typed_message_after_the_user_spoke_goes_to_the_llm(stepit_macro):
    harness = Harness(stepit_macro)
    await harness.user_says("hello")
    await harness.session.from_browser(GREETING_PROMPT)
    assert harness.count("conversation.item.create") == 1
    assert harness.said() == []


async def test_without_a_greeting_the_llm_greets(harness):
    await harness.session.from_browser(GREETING_PROMPT)
    await harness.session.from_browser({"type": "response.create"})
    assert harness.count("conversation.item.create") == 1
    assert harness.said() == []


# ── Sleeping and waking ────────────────────────────────────────────────────────

SLEEP_READ_BACK = "Putting the voice to sleep. Say yes to confirm."
ASLEEP = "Going to sleep. To wake me, say: Wake up, robot."
AWAKE = "I'm listening."


@pytest.fixture
def sleepy(sleepy_arm):
    return Harness(sleepy_arm)


def states(harness: Harness) -> list[str]:
    return [event["state"] for event in harness.browser if event.get("type") == "voicebridge.state"]


async def asleep(harness: Harness) -> None:
    """The sleep command, read back and confirmed: the voice sleeps."""
    rid = await harness.llm_calls("sleep", {})
    await harness.response_done(rid)
    await harness.bridge_reply_said(SLEEP_READ_BACK)
    await harness.user_says("yes")
    await harness.bridge_reply_said(ASLEEP)
    assert harness.session.asleep


async def test_the_sleep_command_is_confirmed_and_runs_nothing_on_the_robot(sleepy):
    rid = await sleepy.llm_calls("sleep", {})
    await sleepy.response_done(rid)
    assert sleepy.said() == [SLEEP_READ_BACK]
    assert not sleepy.session.asleep
    await sleepy.bridge_reply_said(SLEEP_READ_BACK)
    await sleepy.user_says("yes")
    assert sleepy.said()[-1] == ASLEEP
    assert sleepy.session.asleep
    assert sleepy.robot.requests == []
    assert states(sleepy) == ["asleep"]


async def test_a_declined_sleep_keeps_the_voice_awake(sleepy):
    rid = await sleepy.llm_calls("sleep", {})
    await sleepy.response_done(rid)
    await sleepy.bridge_reply_said(SLEEP_READ_BACK)
    await sleepy.user_says("no")
    assert not sleepy.session.asleep
    assert sleepy.said()[-1] == CANCELLED


async def test_asleep_every_turn_is_muted_and_cancelled(sleepy):
    await asleep(sleepy)
    said = len(sleepy.said())
    cancels = sleepy.count("response.cancel")
    await sleepy.user_says("turn left 10 degrees")
    assert sleepy.count("response.cancel") == cancels + 1
    before = len(sleepy.browser)
    await sleepy.server_replies_itself("Turning left.")
    assert sleepy.browser[before:] == []
    assert len(sleepy.said()) == said
    assert sleepy.session.asleep


async def test_asleep_a_command_of_the_llm_is_not_run(sleepy):
    await asleep(sleepy)
    await sleepy.user_says("turn left 10 degrees")
    rid = await sleepy.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await sleepy.response_done(rid)
    assert sleepy.outputs()[-1] == MUTED_CALL
    await sleepy.user_says("yes")
    assert sleepy.robot.requests == []


async def test_asleep_stop_still_stops(sleepy):
    await asleep(sleepy)
    await sleepy.user_says("stop")
    assert sleepy.robot.targets == ["/arm/halt"]
    assert sleepy.said()[-1] == "Halted."
    assert sleepy.session.asleep


async def test_only_the_wake_phrase_said_alone_wakes(sleepy):
    await asleep(sleepy)
    for said in ("wake up robot please", "wake up robot and turn left 10 degrees", "wake up",
                 "Please wake up robot.", "Wake up, robot. Turn left 10 degrees."):
        await sleepy.user_says(said)
        assert sleepy.session.asleep, said
    await sleepy.user_says("Wake up, robot!")
    assert not sleepy.session.asleep
    assert sleepy.said()[-1] == AWAKE
    assert states(sleepy) == ["asleep", "awake"]
    assert sleepy.robot.requests == []


async def test_the_wake_phrase_wakes_at_the_end_of_a_turn_that_grew_while_asleep(sleepy):
    # As on the rig: the speech server keeps the turn open after each cancelled reply.
    await asleep(sleepy)
    await sleepy.user_says("Can you hear me?")
    await sleepy.user_says("Can you hear me? Hello, can you hear me? Wake up.")
    assert sleepy.session.asleep
    await sleepy.user_says("Can you hear me? Hello, can you hear me? Wake up. Robot.")
    assert not sleepy.session.asleep
    assert sleepy.said()[-1] == AWAKE


async def test_awake_again_commands_work(sleepy):
    await asleep(sleepy)
    await sleepy.user_says("wake up robots")
    await sleepy.bridge_reply_said(AWAKE)
    await sleepy.user_says("turn left 10 degrees")
    rid = await sleepy.llm_calls("turn_joint", {"degrees": 10, "direction": "left"})
    await sleepy.response_done(rid)
    await sleepy.bridge_reply_said(READ_BACK)
    await sleepy.user_says("yes")
    assert sleepy.robot.targets == ["/arm/move"]


async def test_a_session_starts_awake_and_tells_its_client_the_phrases(sleepy):
    await sleepy.session.from_browser({"type": "session.update", "session": {}})
    await sleepy.session.from_browser({"type": "session.update", "session": {}})
    told = [event for event in sleepy.browser if event.get("type") == "voicebridge.state"]
    assert told == [{"type": "voicebridge.state", "state": "awake", "wake": "Wake up, robot", "sleep": "go to sleep"}]
    assert not sleepy.session.asleep


async def test_the_llm_is_told_to_call_the_sleep_command(sleepy, harness):
    for each in (sleepy, harness):
        await each.session.from_browser({"type": "session.update", "session": {}})
    assert "call the tool sleep" in sleepy.upstream[0]["session"]["instructions"]
    assert "sleep" not in harness.upstream[0]["session"]["instructions"]


async def test_without_a_sleep_mode_there_is_no_state_and_no_wake_phrase(harness):
    await harness.session.from_browser({"type": "session.update", "session": {}})
    await harness.user_says("wake up robot")
    assert states(harness) == []
    assert harness.said() == []
