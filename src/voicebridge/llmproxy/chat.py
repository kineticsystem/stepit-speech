# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""Reading and writing the messages of OpenAI's chat completions, as the speech server sends them.

Pure functions on plain dicts, with no I/O: what a request says, a request
without some of its messages, and an answer written by the proxy itself, as
one completion or as the chunks of a stream.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Collection, Mapping
from typing import Any

from voicebridge.safety.phrases import words
from voicebridge.scripted import scripted_sentence


def _system_texts(body: Mapping[str, Any]) -> list[str]:
    texts: list[str] = []
    for message in body.get("messages") or []:
        if not isinstance(message, Mapping) or message.get("role") not in ("system", "developer"):
            continue
        content = message.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.extend(str(part.get("text") or "") for part in content if isinstance(part, Mapping))
    return texts


def scripted(body: Mapping[str, Any]) -> str | None:
    """The sentence of the bridge that a request carries in its instructions, if any."""
    for text in _system_texts(body):
        sentence = scripted_sentence(text)
        if sentence is not None:
            return sentence
    return None


def last_user_text(body: Mapping[str, Any]) -> str | None:
    """What the user said, when the last message of a request is theirs."""
    messages = [m for m in body.get("messages") or [] if isinstance(m, Mapping)]
    if not messages or messages[-1].get("role") != "user":
        return None
    content = messages[-1].get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text") or "") for part in content if isinstance(part, Mapping))
    return ""


def after_command(body: Mapping[str, Any]) -> bool:
    """Whether a request follows the bridge's answer to a command, other than a rejection to explain."""
    messages = [m for m in body.get("messages") or [] if isinstance(m, Mapping)]
    if not messages or messages[-1].get("role") != "tool":
        return False
    return not str(messages[-1].get("content") or "").startswith("Rejected")


def without(body: dict[str, Any], sentences: Collection[tuple[str, ...]]) -> dict[str, Any]:
    """The request without the assistant's messages that said one of the sentences."""
    def spoken(message: Any) -> bool:
        return (isinstance(message, Mapping) and message.get("role") == "assistant"
                and not message.get("tool_calls") and isinstance(message.get("content"), str)
                and tuple(words(message["content"])) in sentences)

    return {**body, "messages": [m for m in body.get("messages") or [] if not spoken(m)]}


def completion(model: str, content: str, tool_calls: list[dict[str, Any]],
               usage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-vb-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": dict(usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
    }


def chunks(answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A finished completion as the chunks of a stream, as the OpenAI clients read them."""
    choice = answer["choices"][0]
    message = choice["message"]
    head = {key: answer[key] for key in ("id", "created", "model")} | {"object": "chat.completion.chunk"}

    def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
        return head | {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    events = [chunk({"role": "assistant", "content": ""})]
    if message.get("content"):
        events.append(chunk({"content": message["content"]}))
    for index, call in enumerate(message.get("tool_calls") or []):
        events.append(chunk({"tool_calls": [{
            "index": index, "id": call.get("id") or f"call_{index}", "type": "function",
            "function": {"name": call["function"]["name"], "arguments": call["function"].get("arguments") or ""},
        }]}))
    events.append(chunk({}, choice["finish_reason"]))
    events.append(head | {"choices": [], "usage": answer["usage"]})
    return events


def message(answer: Mapping[str, Any]) -> Mapping[str, Any]:
    """The message of the first choice of an answer."""
    choices = answer.get("choices") or [{}]
    return choices[0].get("message") or {}
