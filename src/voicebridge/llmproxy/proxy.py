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
from collections import deque
from collections.abc import Mapping
from typing import Any

import aiohttp
from aiohttp import web

from voicebridge.llmproxy.chat import after_command, chunks, completion, last_user_text, message, scripted, without
from voicebridge.llmproxy.decision import commands_only, settle, structured
from voicebridge.llmproxy.guard import Guard, pretends
from voicebridge.safety.phrases import Meaning, words

log = logging.getLogger("voicebridge.llmproxy")

# Said instead of a reply that pretended to run a command the model did not call.
SAY_AGAIN = "Sorry, I did not get that as a command. Please say it again."

# Headers that belong to one hop, never copied from one connection to the next.
_HOP = {"connection", "content-length", "content-encoding", "transfer-encoding", "keep-alive", "host"}


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
            # Every request, the ones passed through included: a server of several models would otherwise
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
        content, calls = settle(message(answer))
        if not calls and pretends(content, self._guard):
            log.warning("The LLM said %r without calling a command: asked again, with commands only", content)
            again = await self._ask(commands_only(upstream_body), request.headers)
            if isinstance(again, web.Response):
                return again
            answer = again
            content, calls = settle(message(answer))
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


def _forwarded(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items()
            if key.lower() not in _HOP and key.lower() != "accept-encoding"}
