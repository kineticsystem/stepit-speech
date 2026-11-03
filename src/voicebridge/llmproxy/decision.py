# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""One decision per turn: the request that asks the model for one JSON object, and its answer.

The proxy removes the tools from the speech server's request, lists the
commands in the instructions, and asks for a JSON object of a schema that the
LLM server enforces: ``{"command": ..., "arguments": {...}}`` to act, or
``{"reply": "..."}`` to talk, at most ``REPLY_CHARS`` long. ``settle`` turns
the answer back into what the speech server expects: words, or one tool call.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

REPLY = "reply"
# The longest reply, in characters: a model can repeat itself without end inside a string.
REPLY_CHARS = 200
# The most tokens of an answer: a command or a reply of REPLY_CHARS, with room to spare.
MAX_TOKENS = 300

_HOW_TO_ANSWER = """\

# How to Answer

Answer with one JSON object and nothing else:
- {{"command": "<name>", "arguments": {{...}}}} to make the robot do something, with one of the commands below. \
The system then reads the command back to the user and runs it only if they confirm.
- {{"reply": "<text>"}} to talk: to answer a question, to ask for a value the user did not give, or to explain. \
A reply never makes the robot do anything, so it never says that the robot is doing or did something, and never \
asks the user to confirm.

# Commands

{commands}"""


def _functions(body: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    tools = [tool for tool in body.get("tools") or [] if isinstance(tool, Mapping)]
    return [tool.get("function") or tool for tool in tools]


def _command_schema(function: Mapping[str, Any]) -> dict[str, Any]:
    arguments = dict(function.get("parameters") or {"type": "object", "properties": {}})
    arguments.setdefault("additionalProperties", False)
    return {"type": "object", "properties": {"command": {"const": function["name"]}, "arguments": arguments},
            "required": ["command", "arguments"], "additionalProperties": False}


def _reply_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {REPLY: {"type": "string", "maxLength": REPLY_CHARS}},
            "required": [REPLY], "additionalProperties": False}


def _commands_text(functions: list[Mapping[str, Any]]) -> str:
    lines = []
    for function in functions:
        parameters = (function.get("parameters") or {}).get("properties") or {}
        lines.append(f"- {function['name']}: {function.get('description') or ''} "
                     f"Arguments: {json.dumps(parameters, ensure_ascii=False)}")
    return "\n".join(lines)


def structured(body: Mapping[str, Any]) -> dict[str, Any] | None:
    """The request that asks for one JSON decision instead of tool calls; None when it has no tools."""
    functions = [f for f in _functions(body) if isinstance(f, Mapping) and f.get("name") and f.get("name") != REPLY]
    if not functions or body.get("tool_choice") == "none":
        return None
    choices = [_command_schema(function) for function in functions] + [_reply_schema()]
    messages = [dict(m) if isinstance(m, Mapping) else m for m in body.get("messages") or []]
    how = _HOW_TO_ANSWER.format(commands=_commands_text(functions))
    first = messages[0] if messages else None
    if isinstance(first, dict) and first.get("role") in ("system", "developer") and isinstance(
            first.get("content"), str):
        first["content"] = first["content"] + "\n" + how
    else:
        messages.insert(0, {"role": "system", "content": how.strip()})
    request = {key: value for key, value in body.items()
               if key not in ("stream", "stream_options", "tools", "tool_choice", "parallel_tool_calls")}
    request.update(messages=messages, stream=False, max_tokens=MAX_TOKENS, response_format={
        "type": "json_schema",
        "json_schema": {"name": "decision", "strict": True, "schema": {"oneOf": choices}},
    })
    return request


def _decision(content: str) -> Mapping[str, Any] | None:
    try:
        decision = json.loads(content)
    except (TypeError, ValueError):
        return None
    return decision if isinstance(decision, Mapping) else None


def settle(message: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """What the speech server gets from the model's answer: words, or a command call, never both.

    The answer is the JSON decision; tool calls are read too, from a server that made them anyway.
    """
    content = str(message.get("content") or "")
    decision = _decision(content)
    if decision is not None and isinstance(decision.get("command"), str):
        arguments = decision.get("arguments")
        return "", [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function", "function": {
            "name": decision["command"], "arguments": json.dumps(arguments if isinstance(arguments, Mapping) else {})}}]
    if decision is not None and REPLY in decision:
        return str(decision.get(REPLY) or ""), []
    calls = [dict(call) for call in message.get("tool_calls") or [] if isinstance(call, Mapping)]
    if calls:
        return "", calls[:1]
    return content, []
