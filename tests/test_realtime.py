# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT

from voicebridge.realtime import (
    assistant_text,
    bridge_tag,
    command_call,
    hidden_ids,
    hides,
    inject_session,
    response_create,
    scrub_response_done,
)

NAMES = {"rotate_stage"}
CALL = {"id": "item_1", "type": "function_call", "name": "rotate_stage", "call_id": "call_1",
        "arguments": '{"degrees": 10, "direction": "clockwise"}'}


def test_inject_session_keeps_the_browser_tools_and_adds_the_robot():
    event = {"type": "session.update", "session": {"tools": [{"name": "web_search"}], "tool_choice": "none",
                                                   "instructions": "Hi."}}
    injected = inject_session(event, [{"name": "rotate_stage"}], "Robot rules.")
    assert [t["name"] for t in injected["session"]["tools"]] == ["web_search", "rotate_stage"]
    assert injected["session"]["tool_choice"] == "auto"
    assert injected["session"]["instructions"] == "Hi.\n\nRobot rules."
    # Twice is the same as once.
    again = inject_session(injected, [{"name": "rotate_stage"}], "Robot rules.")
    assert again["session"] == injected["session"]
    # The browser's event itself is not changed.
    assert event["session"]["tool_choice"] == "none"


def test_inject_session_leaves_other_events():
    event = {"type": "response.create"}
    assert inject_session(event, [{"name": "x"}], "rules") is event


def test_command_call():
    call = command_call({"type": "response.output_item.done", "response_id": "r", "item": CALL}, NAMES)
    assert (call.name, call.call_id, call.arguments, call.response_id) == (
        "rotate_stage", "call_1", {"degrees": 10, "direction": "clockwise"}, "r")
    assert command_call({"type": "response.output_item.done", "item": {**CALL, "name": "web_search"}}, NAMES) is None
    assert command_call({"type": "response.output_item.added", "item": CALL}, NAMES) is None
    bad = command_call({"type": "response.output_item.done", "item": {**CALL, "arguments": "[1]"}}, NAMES)
    assert bad.arguments is None


def test_hides_every_event_of_a_robot_call():
    hidden = hidden_ids({"type": "response.output_item.added", "item": CALL}, NAMES)
    assert set(hidden) == {"item_1", "call_1"}
    assert hides({"type": "response.output_item.added", "item": CALL}, NAMES)
    assert hides({"type": "response.function_call_arguments.delta", "item_id": "item_1", "delta": "{"}, NAMES, hidden)
    assert hides({"type": "response.function_call_arguments.done", "name": "rotate_stage"}, NAMES)
    assert hides({"type": "conversation.item.created",
                  "item": {"type": "function_call_output", "call_id": "call_1"}}, NAMES, hidden)
    assert not hides({"type": "response.function_call_arguments.delta", "item_id": "item_9"}, NAMES, hidden)
    assert not hides({"type": "response.output_audio.delta", "response_id": "r"}, NAMES, hidden)


def test_scrub_response_done():
    event = {"type": "response.done", "response": {"id": "r", "output": [CALL, {"type": "message"}]}}
    assert scrub_response_done(event, NAMES)["response"]["output"] == [{"type": "message"}]
    assert event["response"]["output"][0] is CALL


def test_the_bridge_tags_its_own_responses():
    create = response_create("vb-1", "Say this", "none")
    assert create["response"] == {"metadata": {"voicebridge": "vb-1"}, "instructions": "Say this",
                                  "tool_choice": "none"}
    assert bridge_tag({"type": "response.created", "response": {"metadata": {"voicebridge": "vb-1"}}}) == "vb-1"
    assert bridge_tag({"type": "response.created", "response": {"metadata": None}}) is None


def test_assistant_text():
    assert assistant_text({"type": "response.output_audio_transcript.done", "transcript": "Hi"}) == "Hi"
    assert assistant_text({"type": "response.output_text.done", "text": "Hi"}) == "Hi"
    assert assistant_text({"type": "response.output_audio.delta"}) is None
