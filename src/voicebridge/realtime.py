# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The events of the OpenAI Realtime API that the bridge reads, changes or writes.

Pure functions on plain dicts, the JSON frames on the wire, with no I/O, so
that they are tested alone. The speech-to-speech server speaks this API, and
so does the browser demo: the bridge sits between them.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

# The key of the metadata that marks a response the bridge asked for: the server
# echoes the metadata of response.create in response.created and response.done.
BRIDGE_KEY = "voicebridge"

# The events that carry a user's finished transcript, and an assistant's spoken or written text.
USER_TRANSCRIPT = "conversation.item.input_audio_transcription.completed"
ASSISTANT_TEXT = ("response.output_audio_transcript.done", "response.audio_transcript.done",
                  "response.output_text.done", "response.text.done")


@dataclass(frozen=True)
class ToolCall:
    name: str
    call_id: str
    # None when the model wrote arguments that are not a JSON object.
    arguments: dict[str, Any] | None
    response_id: str | None


def inject_session(event: dict[str, Any], tools: Collection[Mapping[str, Any]], instructions: str) -> dict[str, Any]:
    """Adds the robot's tools and instructions to a ``session.update`` of the browser.

    Every session.update gets them, so the robot's tools survive whatever the
    browser changes, e.g. switching its own tools off, which would set
    tool_choice to none. Any other event is returned as it is.
    """
    if event.get("type") != "session.update" or not isinstance(event.get("session"), dict):
        return event
    session = dict(event["session"])
    present = [tool for tool in session.get("tools") or [] if isinstance(tool, dict)]
    names = {tool.get("name") for tool in present}
    session["tools"] = present + [dict(tool) for tool in tools if tool.get("name") not in names]
    session["tool_choice"] = "auto"
    existing = str(session.get("instructions") or "").strip()
    if instructions and instructions not in existing:
        session["instructions"] = (existing + "\n\n" + instructions).strip()
    return {**event, "session": session}


def _is_command_item(item: Any, names: Collection[str]) -> bool:
    return isinstance(item, Mapping) and item.get("type") == "function_call" and item.get("name") in names


def command_call(event: Mapping[str, Any], names: Collection[str]) -> ToolCall | None:
    """The finished call of a robot command, from ``response.output_item.done``; None otherwise."""
    if event.get("type") != "response.output_item.done":
        return None
    item = event.get("item")
    if not _is_command_item(item, names):
        return None
    try:
        arguments = json.loads(item.get("arguments") or "{}")
    except (TypeError, ValueError):
        arguments = None
    if not isinstance(arguments, dict):
        arguments = None
    return ToolCall(
        name=str(item.get("name")),
        call_id=str(item.get("call_id") or ""),
        arguments=arguments,
        response_id=event.get("response_id"),
    )


def hides(event: Mapping[str, Any], names: Collection[str], hidden: Collection[str] = ()) -> bool:
    """Whether an event belongs to a robot command call, which the browser must never see:
    it does not know these tools and would answer them itself with "unknown tool".

    ``hidden`` holds the item ids and call ids of the robot calls seen so far: the
    argument deltas name neither the tool nor carry the item, only these ids.
    """
    kind = event.get("type")
    if kind in ("response.output_item.added", "response.output_item.done"):
        return _is_command_item(event.get("item"), names)
    if kind in ("response.function_call_arguments.delta", "response.function_call_arguments.done"):
        return (event.get("name") in names or event.get("item_id") in hidden
                or event.get("call_id") in hidden)
    if kind in ("conversation.item.created", "conversation.item.added", "conversation.item.done"):
        item = event.get("item")
        if _is_command_item(item, names):
            return True
        # The bridge's own answers to those calls.
        return isinstance(item, Mapping) and item.get("type") == "function_call_output" and (
            item.get("call_id") in hidden)
    return False


def hidden_ids(event: Mapping[str, Any], names: Collection[str]) -> list[str]:
    """The item id and call id of a robot command call that an event announces."""
    item = event.get("item")
    if not _is_command_item(item, names):
        return []
    return [str(value) for value in (item.get("id"), item.get("call_id")) if value]


def scrub_response_done(event: dict[str, Any], names: Collection[str]) -> dict[str, Any]:
    """Removes the robot command calls from the output of a ``response.done``."""
    if event.get("type") != "response.done" or not isinstance(event.get("response"), dict):
        return event
    response = event["response"]
    output = response.get("output")
    if not isinstance(output, list):
        return event
    kept = [item for item in output if not _is_command_item(item, names)]
    if len(kept) == len(output):
        return event
    return {**event, "response": {**response, "output": kept}}


def response_id(event: Mapping[str, Any]) -> str | None:
    """The response an event belongs to, if any."""
    if isinstance(event.get("response"), Mapping):
        return event["response"].get("id")
    return event.get("response_id")


def bridge_tag(event: Mapping[str, Any]) -> str | None:
    """The tag the bridge put on a response it asked for, from response.created or response.done."""
    response = event.get("response")
    if not isinstance(response, Mapping):
        return None
    metadata = response.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    tag = metadata.get(BRIDGE_KEY)
    return str(tag) if tag is not None else None


def assistant_text(event: Mapping[str, Any]) -> str | None:
    """The text an assistant's response said or wrote, from its ``*.done`` event."""
    if event.get("type") not in ASSISTANT_TEXT:
        return None
    return str(event.get("transcript") or event.get("text") or "")


def function_call_output(call_id: str, output: str) -> dict[str, Any]:
    """Answers a tool call, as the browser would have."""
    return {"type": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": call_id, "output": output}}


def response_create(tag: str, instructions: str | None = None, tool_choice: str | None = None) -> dict[str, Any]:
    """Asks the server for a reply, tagged so that the bridge knows it for its own."""
    response: dict[str, Any] = {"metadata": {BRIDGE_KEY: tag}}
    if instructions is not None:
        response["instructions"] = instructions
    if tool_choice is not None:
        response["tool_choice"] = tool_choice
    return {"type": "response.create", "response": response}


def response_cancel() -> dict[str, Any]:
    return {"type": "response.cancel"}


def exact_speech(sentence: str) -> str:
    """The instructions that make the voice say a sentence exactly as written."""
    return (
        "Say exactly the following text, word for word, with nothing before or after it, "
        f"and do not call any tool:\n{sentence}"
    )
