# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The bridge's voice: how it asks the speech server to say its sentences, and silences the server's own.

The bridge has no voice of its own: it asks the speech server for a reply,
and the server's LLM proxy answers with the sentence. Four rules keep these
requests from colliding with the server's own work:

- **Tagged.** Each request carries ``metadata: {voicebridge: vb-<n>}``, which
  the server echoes, so that the bridge knows its replies by their tag.
- **Queued, one at a time.** A reply is asked for only when no response is in
  progress; one the server refuses as busy is asked again when it is done.
- **Tool answers first.** The server refuses a reply while a tool call has no
  answer, so the answers go first, and nothing is asked while a call is still
  being prepared.
- **Heard.** What the voice said in a reply of the bridge is collected, so
  that the session can check a read-back.

And when the bridge takes over a turn of the user, the speaker cancels the
server's own reply to it, and mutes any reply it did not ask for until the
user speaks again, or for ``mute_window_s``.

The speaker decides nothing about commands: the session tells it what to say.
"""

from __future__ import annotations

import itertools
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from voicebridge.conversation.events import (
    bridge_tag,
    function_call_output,
    response_cancel,
    response_create,
)
from voicebridge.scripted import exact_speech

log = logging.getLogger("voicebridge.session")

Send = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class Utterance:
    """A reply the bridge asks the server for."""

    # read_back: say `text` exactly, then check it was; say: say `text` exactly;
    # free: let the LLM answer, e.g. to explain a rejection.
    kind: str
    text: str = ""
    tag: str = ""


@dataclass(frozen=True)
class Spoken:
    """A reply of the bridge that ended: what was asked, what the voice said, and how it ended."""

    utterance: Utterance
    heard: str
    # The status of response.done, e.g. completed or cancelled; None when the server gave none.
    status: Any


class Speaker:
    def __init__(self, to_upstream: Send, clock: Callable[[], float], mute_window_s: float) -> None:
        self._to_upstream = to_upstream
        self._clock = clock
        self._mute_window_s = mute_window_s

        self._queue: deque[Utterance] = deque()
        self._outputs: list[dict[str, Any]] = []          # answers to tool calls, sent before anything
        self._preparing = 0                               # tool calls not answered yet
        self._asked: Utterance | None = None              # sent response.create, not created yet
        self._speaking: tuple[str, Utterance] | None = None  # our response in progress
        self._heard: list[str] = []                       # what our response in progress said
        self._active: str | None = None                   # the response in progress, anyone's
        self._muted: set[str] = set()                     # server replies to a turn we took over
        self._mute_until = 0.0
        self._cancels = 0                                 # response.cancel sent, errors expected
        self._tags = itertools.count(1)

    # ── What to say ────────────────────────────────────────────────────────────

    def say(self, text: str) -> None:
        """Queues a sentence, to be said exactly."""
        self._queue.append(Utterance("say", text))

    def read_back(self, text: str) -> None:
        """Queues a read-back, to be said exactly and heard; it replaces one not yet asked for."""
        self._queue = deque(u for u in self._queue if u.kind != "read_back")
        self._queue.append(Utterance("read_back", text))

    def let_llm_answer(self) -> None:
        """Queues a reply of the LLM's own, e.g. to explain a rejection."""
        self._queue.append(Utterance("free"))

    def answer_call(self, call_id: str, output: str) -> None:
        """Queues the answer to a tool call: it goes before any reply."""
        self._outputs.append(function_call_output(call_id, output))

    def begin_call(self) -> None:
        """A tool call is being prepared: no reply is asked for until it is answered."""
        self._preparing += 1

    def end_call(self) -> None:
        self._preparing -= 1

    async def pump(self) -> None:
        """Sends the answers to tool calls, then the next queued reply, when the server is not answering."""
        if self._asked is not None or self._active is not None or self._speaking is not None:
            return
        outputs, self._outputs = self._outputs, []
        for output in outputs:
            await self._to_upstream(output)
        # Every tool call of the LLM must have its answer before the server takes a new reply.
        if self._queue and self._preparing == 0:
            utterance = self._queue.popleft()
            utterance.tag = f"vb-{next(self._tags)}"
            self._asked = utterance
            if utterance.kind == "free":
                await self._to_upstream(response_create(utterance.tag))
            else:
                await self._to_upstream(response_create(utterance.tag, exact_speech(utterance.text), "none"))

    # ── Taking over a turn ─────────────────────────────────────────────────────

    async def take_over(self) -> None:
        """The bridge answers this turn: the server's own reply to it is muted and cancelled."""
        self._mute_until = self._clock() + self._mute_window_s
        if self._active is not None:
            self._muted.add(self._active)
            if self._speaking is not None and self._speaking[0] == self._active:
                self._speaking = None
        await self._cancel()

    def is_muted(self, rid: str | None) -> bool:
        return rid is not None and rid in self._muted

    # ── The server's responses ─────────────────────────────────────────────────

    def speech_started(self) -> None:
        """A new turn: whatever the server says from now on answers it, not the one we took over."""
        self._mute_until = 0.0

    async def created(self, event: dict[str, Any], rid: str | None) -> bool:
        """Notes a new response. Returns True when it was muted and cancelled: nobody must hear it."""
        tag = bridge_tag(event)
        if self._asked is not None and tag == self._asked.tag:
            self._speaking = (rid or "", self._asked)
            self._asked = None
            self._heard = []
            self._active = rid
            return False
        self._active = rid
        if rid is not None and tag is None and self._clock() < self._mute_until:
            log.info("Muting the server's reply %s to a turn the bridge took over", rid)
            self._muted.add(rid)
            await self._cancel()
            return True
        return False

    def error(self, event: dict[str, Any]) -> bool:
        """Handles an error the bridge caused. Returns True when the browser must not see it."""
        error = event.get("error") if isinstance(event.get("error"), dict) else {}
        text = f"{error.get('type', '')} {error.get('code', '')} {error.get('message', '')}".lower()
        if self._asked is not None and ("active response" in text or "already_has_active_response" in text):
            # The server was still answering: ask again once it is done.
            self._queue.appendleft(self._asked)
            self._asked = None
            return True
        if self._cancels > 0 and "cancel" in text:
            self._cancels -= 1
            return True
        return False

    def hear(self, rid: str | None, text: str) -> None:
        """What a response said, from its transcript: kept when it is the bridge's reply in progress."""
        if self._speaking is not None and rid == self._speaking[0]:
            self._heard.append(text)

    def finished(self, rid: str | None, event: dict[str, Any]) -> Spoken | None:
        """A response ended. Returns what the bridge said, when it was one of its replies."""
        self._muted.discard(rid or "")
        if self._active == rid:
            self._active = None
        if self._speaking is None or self._speaking[0] != rid:
            return None
        utterance = self._speaking[1]
        self._speaking = None
        status = (event.get("response") or {}).get("status")
        return Spoken(utterance, " ".join(self._heard), status)

    async def _cancel(self) -> None:
        await self._to_upstream(response_cancel())
        self._cancels += 1
