# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The bridge's LLM proxy: the speech server asks its LLM through here.

The speech server sends every reply through its LLM, even a sentence the
bridge wants said word for word. The proxy sits on that path, as an
OpenAI-compatible ``/v1/chat/completions``, and makes sure the model can
never seem to run a command that the bridge has not read back:

1. **Scripted replies.** When the instructions carry a sentence of the bridge
   (``realtime.exact_speech``), the proxy answers with that sentence itself and
   never asks the model: the read-back, the outcome and every other sentence
   of the bridge are spoken exactly as written.
2. **One decision every turn, in JSON.** On a turn with tools, the proxy
   lists the commands in the instructions and asks the model for one JSON
   object, enforced by the server with a JSON schema: ``{"command": ...,
   "arguments": {...}}`` to act, or ``{"reply": "..."}`` to talk, at most
   ``REPLY_CHARS`` long. The model cannot answer a command in loose words, and
   the proxy turns a command into the tool call the speech server expects.
   Tool calls are not enough: a server can leave ``tool_choice: required``
   unenforced, as llama.cpp does with some chat templates, while it enforces a
   JSON schema with a grammar.
3. **No pretending.** A model that has heard the bridge read commands back
   starts doing it itself, in a reply, without calling the command: "Moving
   the camera closer. Confirm?", and the user's yes confirms nothing. So the
   model never sees the bridge's sentences in its history; a turn of yes, no
   or stop never reaches it, as the bridge answers those; and a reply that
   asks to confirm, or says the robot is acting with a verb of the robot's
   own sentences ("moving", "taking"), is asked again with the commands only,
   so that the schema leaves it no reply. If it still gives none, e.g. on a
   server that ignores the schema, the user hears ``SAY_AGAIN``.
4. **No follow-up.** After the bridge answers a command, the speech server
   asks the model to go on; the bridge speaks next, so the proxy answers with
   nothing, except after a rejection, which the model explains.

Anything else, e.g. a request with no tools, passes through unchanged.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import deque
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import web

from voicebridge.catalogue import Catalogue
from voicebridge.phrases import Meaning, PhraseMatcher, words
from voicebridge.realtime import scripted_sentence

log = logging.getLogger("voicebridge.llmproxy")

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

# Said instead of a reply that pretended to run a command the model did not call.
SAY_AGAIN = "Sorry, I did not get that as a command. Please say it again."

# Headers that belong to one hop, never copied from one connection to the next.
_HOP = {"connection", "content-length", "content-encoding", "transfer-encoding", "keep-alive", "host"}


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


def commands_only(request: Mapping[str, Any]) -> dict[str, Any]:
    """The structured request without the reply: the schema leaves the model a command only."""
    schema = request["response_format"]["json_schema"]
    choices = [choice for choice in schema["schema"]["oneOf"] if REPLY not in choice["properties"]]
    return {**request, "response_format": {**request["response_format"],
                                           "json_schema": {**schema, "schema": {"oneOf": choices}}}}


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


@dataclass(frozen=True)
class Guard:
    """What the proxy knows of the robot to keep the model from pretending."""

    # The robot's confirmation question, e.g. "Confirm?".
    prompt: str = ""
    # The verbs of the robot's read-backs, e.g. moving, taking: a reply with one claims an action.
    verbs: frozenset[str] = frozenset()
    # Yes, no and stop, which the bridge answers itself.
    matcher: PhraseMatcher | None = field(default=None, compare=False)

    @classmethod
    def of(cls, catalogue: Catalogue) -> Guard:
        texts = [text for command in catalogue.commands.values()
                 for text in (command.say, command.started) if isinstance(text, str)]
        verbs = {word for text in texts for word in words(_TEMPLATE_CODE.sub(" ", text))
                 if word.endswith("ing") and len(word) > 4}
        verbs |= {word for text in texts for word in re.findall(r"'([^']*)'", text) for word in words(word)
                  if word.endswith("ing") and len(word) > 4}
        return cls(catalogue.confirmation.prompt, frozenset(verbs | _ACTING),
                   PhraseMatcher(catalogue.confirmation))


# Words of any robot's action, besides the verbs of its own read-backs.
_ACTING = frozenset({"turning", "done"})


# The code of a template, {{ ... }} or {% ... %}: its words are not spoken, except quoted ones.
_TEMPLATE_CODE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)


def pretends(text: str, guard: Guard) -> bool:
    """Whether a reply asks to confirm a command or says the robot is acting, as only the bridge may."""
    return asks_to_confirm(text, guard.prompt) or bool(set(words(text)) & guard.verbs)


def asks_to_confirm(text: str, prompt: str = "") -> bool:
    """Whether a reply asks the user to confirm, as only the bridge may."""
    said = words(text)
    if "confirm" in said:
        return True
    asked = words(prompt)
    return bool(asked) and any(said[i:i + len(asked)] == asked for i in range(len(said) - len(asked) + 1))


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


class LlmProxy:
    def __init__(self, upstream: str, host: str = "127.0.0.1", port: int = 8767,
                 guard: Guard | None = None, model: str | None = None) -> None:
        self._upstream = upstream.rstrip("/")
        self._model = model  # asked instead of the model the speech server names
        self._guard = guard or Guard()
        # The sentences the proxy said in place of the model, kept out of its history.
        self._said: deque[tuple[str, ...]] = deque([tuple(words(SAY_AGAIN))], maxlen=500)
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None
        self._client: aiohttp.ClientSession | None = None

    @property
    def port(self) -> int:
        """The port listened on: the one asked for, or the one given for port 0."""
        if self._runner is None or not self._runner.addresses:
            return self._port
        return self._runner.addresses[0][1]

    async def start(self) -> None:
        self._client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))
        app = web.Application(client_max_size=64 * 1024 * 1024)
        app.router.add_post("/v1/chat/completions", self._chat)
        app.router.add_route("*", "/{tail:.*}", self._pass)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self._host, self._port).start()
        log.info("LLM proxy on http://%s:%d/v1, forwarding to %s", self._host, self.port, self._upstream)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        if self._client is not None:
            await self._client.close()

    async def _chat(self, request: web.Request) -> web.StreamResponse:
        raw = await request.read()
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return await self._pass(request, raw)
        if self._model:
            # Every request, the ones passed through included: llama-swap would otherwise
            # swap the chosen model out for the one the speech server names.
            body["model"] = self._model
            raw = json.dumps(body).encode()
        model = str(body.get("model") or "")

        sentence = scripted(body)
        if sentence is not None:
            log.info("The bridge said %r", sentence)
            self._said.append(tuple(words(sentence)))
            return await self._answer(request, body, completion(model, sentence, []))

        upstream_body = structured(body)
        if upstream_body is None:
            return await self._pass(request, raw)
        if after_command(body):
            # The speech server's own follow-up to the bridge's answer: the bridge speaks next, not the model.
            log.debug("Skipped the follow-up of a command")
            return await self._answer(request, body, completion(model, "", []))
        heard = last_user_text(body)
        matcher = self._guard.matcher
        if heard is not None and matcher is not None and matcher.classify(heard) is not Meaning.OTHER:
            # Yes, no or stop: the bridge answers it, and the model must not answer it too.
            log.info("Left to the bridge: %r", heard)
            return await self._answer(request, body, completion(model, "", []))
        upstream_body = without(upstream_body, set(self._said))
        answer = await self._ask(upstream_body, request.headers)
        if isinstance(answer, web.Response):
            return answer
        content, calls = settle(_message(answer))
        if not calls and pretends(content, self._guard):
            log.warning("The LLM said %r without calling a command: asked again, with commands only", content)
            again = await self._ask(commands_only(upstream_body), request.headers)
            if isinstance(again, web.Response):
                return again
            answer = again
            content, calls = settle(_message(answer))
            if not calls:
                log.warning("The LLM still called no command: %r", content)
                content = SAY_AGAIN
        if calls:
            log.info("The LLM called %s", ", ".join(
                f"{call['function']['name']}({call['function'].get('arguments') or ''})" for call in calls))
        else:
            log.info("The LLM said %r", content)
        return await self._answer(request, body, completion(answer.get("model") or model, content, calls,
                                                            answer.get("usage")))

    async def _ask(self, body: Mapping[str, Any], headers: Mapping[str, str]) -> dict[str, Any] | web.Response:
        """The model's answer, or the upstream's error as it is."""
        assert self._client is not None
        async with self._client.post(self._upstream + "/chat/completions", json=body,
                                     headers=_forwarded(headers)) as reply:
            if reply.status != 200:
                return web.Response(status=reply.status, body=await reply.read(), content_type=reply.content_type)
            answer = await reply.json(content_type=None)
        return answer if isinstance(answer, dict) else {}

    async def _answer(self, request: web.Request, body: Mapping[str, Any],
                      answer: dict[str, Any]) -> web.StreamResponse:
        if not body.get("stream"):
            return web.json_response(answer)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await response.prepare(request)
        for event in chunks(answer):
            await response.write(f"data: {json.dumps(event)}\n\n".encode())
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    async def _pass(self, request: web.Request, raw: bytes | None = None) -> web.StreamResponse:
        """Forwards a request as it is, and streams the answer back."""
        assert self._client is not None
        if raw is None:
            raw = await request.read()
        # The upstream URL ends with /v1, as the paths the speech server asks for start with it.
        path = request.path[len("/v1"):] if request.path.startswith("/v1/") else request.path
        url = self._upstream + path + (f"?{request.query_string}" if request.query_string else "")
        async with self._client.request(request.method, url, data=raw or None,
                                        headers=_forwarded(request.headers)) as reply:
            response = web.StreamResponse(status=reply.status, headers={
                key: value for key, value in reply.headers.items() if key.lower() not in _HOP})
            await response.prepare(request)
            async for data in reply.content.iter_any():
                await response.write(data)
            await response.write_eof()
            return response


def _message(answer: Mapping[str, Any]) -> Mapping[str, Any]:
    choices = answer.get("choices") or [{}]
    return choices[0].get("message") or {}


def _forwarded(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items()
            if key.lower() not in _HOP and key.lower() != "accept-encoding"}
