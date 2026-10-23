# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""One voice session: the conversation between one browser and the speech server.

The session sees every event in both directions and passes almost all of them
through unchanged. It does five things:

1. It adds the robot's tools and instructions to every ``session.update``.
2. It hides the robot's tool calls from the browser and handles them: it
   prepares the command and asks the voice to read it back, word for word.
3. It checks that the voice said the read-back exactly; only then is the
   command armed.
4. It reads the user's transcript and decides, with fixed word lists, whether
   it is yes, no or stop. On yes, it runs the armed command; the LLM is never
   asked whether the user confirmed.
5. When it takes over a user's turn (yes, no, stop), it mutes and cancels the
   speech server's own reply to that turn, and speaks its own.

The replies the bridge asks for are queued and sent one at a time, when the
server is not answering, and tagged in their metadata so that the bridge knows
them from the server's own. The answers to the LLM's tool calls always go
first: the server refuses a reply while a tool call has no answer. Its I/O is two async functions, ``to_browser`` and
``to_upstream``: the tests drive a session with lists.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from voicebridge.catalogue import Catalogue
from voicebridge.confirmation import Confirmation, Phase, Verdict
from voicebridge.phrases import Meaning, PhraseMatcher
from voicebridge.planner import Planner, Prepared, Rejected
from voicebridge.prompt import AWAITING_CONFIRMATION, instructions
from voicebridge.realtime import (
    USER_TRANSCRIPT,
    ToolCall,
    assistant_text,
    bridge_tag,
    command_call,
    exact_speech,
    function_call_output,
    hidden_ids,
    hides,
    inject_session,
    response_cancel,
    response_create,
    response_id,
    scrub_response_done,
)
from voicebridge.robot import Robot

log = logging.getLogger("voicebridge.session")

Send = Callable[[dict[str, Any]], Awaitable[None]]

# What the bridge says on its own.
CANCELLED = "Cancelled. Nothing was done."
TOO_LATE = "That came too late, so nothing was done. Please give the command again."
READ_BACK_FAILED = "I could not read the command back exactly, so I cancelled it. Please say it again."
ONE_AT_A_TIME = "Rejected: one command at a time. Nothing was done for this call."
BRIDGE_FAILED = "Something went wrong in the bridge. Nothing more was done."


@dataclass
class Utterance:
    """A reply the bridge asks the server for."""

    # read_back: say `text` exactly, then check it was; say: say `text` exactly;
    # free: let the LLM answer, e.g. to explain a rejection.
    kind: str
    text: str = ""
    tag: str = ""


class Session:
    def __init__(
        self,
        catalogue: Catalogue,
        robot: Robot,
        to_browser: Send,
        to_upstream: Send,
        *,
        clock: Callable[[], float] = time.monotonic,
        mute_window_s: float = 10.0,
    ) -> None:
        self._catalogue = catalogue
        self._robot = robot
        self._planner = Planner(catalogue, robot)
        self._to_browser = to_browser
        self._to_upstream = to_upstream
        self._clock = clock
        self._mute_window_s = mute_window_s

        self._names = set(catalogue.commands)
        self._tools = catalogue.tool_specs()
        self._instructions = instructions(catalogue)
        self._matcher = PhraseMatcher(catalogue.confirmation)
        self.confirmation: Confirmation[Prepared] = Confirmation(catalogue.confirmation.timeout_s, clock)

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
        self._hidden: set[str] = set()                    # item and call ids of robot calls
        self._commanded: set[str] = set()                 # responses that already called a command
        self._tags = itertools.count(1)
        self._tasks: set[asyncio.Task] = set()

    # ── The two directions ─────────────────────────────────────────────────────

    async def from_browser(self, event: dict[str, Any]) -> None:
        await self._to_upstream(inject_session(event, self._tools, self._instructions))

    async def from_upstream(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        rid = response_id(event)

        if kind == "input_audio_buffer.speech_started":
            # A new turn: whatever the server says from now on answers it, not the one we took over.
            self._mute_until = 0.0
        elif kind == "response.created":
            if self._on_created(event, rid):
                await self._to_upstream(response_cancel())
                self._cancels += 1
                return
        elif kind == "error":
            if self._on_error(event):
                return

        if rid is not None and rid in self._muted:
            if kind == "response.done":
                self._muted.discard(rid)
                await self._finished(rid, event)
            return

        if kind == USER_TRANSCRIPT:
            await self._to_browser(event)
            await self._on_user_said(str(event.get("transcript") or ""))
            return

        text = assistant_text(event)
        if text is not None and self._speaking is not None and rid == self._speaking[0]:
            self._heard.append(text)

        self._hidden.update(hidden_ids(event, self._names))
        call = command_call(event, self._names)
        if call is not None:
            self._on_tool_call(call)
            return
        if hides(event, self._names, self._hidden):
            return
        if kind == "response.done":
            await self._to_browser(scrub_response_done(event, self._names))
            await self._finished(rid, event)
            return
        await self._to_browser(event)

    async def close(self) -> None:
        """The browser left: drop the pending command and stop what the session started.

        A command that is running is cancelled with it: a robot never keeps moving
        for a voice session that no longer exists.
        """
        self.confirmation.cancel()
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            try:
                await task
            except BaseException:  # noqa: BLE001 - each task logs its own failure
                pass

    async def wait_idle(self) -> None:
        """Waits for the commands the session runs, for the tests."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ── The server's responses ─────────────────────────────────────────────────

    def _on_created(self, event: dict[str, Any], rid: str | None) -> bool:
        """Notes a new response. Returns True when it must be muted and cancelled."""
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
            return True
        return False

    def _on_error(self, event: dict[str, Any]) -> bool:
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

    async def _finished(self, rid: str | None, event: dict[str, Any]) -> None:
        if self._active == rid:
            self._active = None
        if self._speaking is not None and self._speaking[0] == rid:
            utterance = self._speaking[1]
            self._speaking = None
            if utterance.kind == "read_back":
                status = (event.get("response") or {}).get("status")
                self._check_read_back(utterance, status, " ".join(self._heard))
        await self._pump()

    def _check_read_back(self, utterance: Utterance, status: Any, heard: str) -> None:
        if self.confirmation.phase is not Phase.READING_BACK or self.confirmation.sentence != utterance.text:
            return
        if status not in (None, "completed"):
            # Interrupted: the user did not hear all of it.
            self.confirmation.cancel()
            return
        if self.confirmation.read_back(heard):
            log.info("Armed: %r", utterance.text)
        else:
            log.warning("The voice said %r instead of %r: cancelled", heard, utterance.text)
            self._queue.append(Utterance("say", READ_BACK_FAILED))

    # ── The user ───────────────────────────────────────────────────────────────

    async def _on_user_said(self, transcript: str) -> None:
        meaning = self._matcher.classify(transcript)
        stop = self._catalogue.confirmation.stop_command
        if stop is not None and self._matcher.mentions_stop(transcript):
            log.info("Stop: %r", transcript)
            self.confirmation.cancel()
            if meaning is Meaning.STOP:
                # Nothing but stop: the bridge answers this turn itself.
                await self._take_over()
                self._spawn(self._run_now(stop, speak=True))
                await self._pump()
            else:
                # "Stop the live view": the robot stops, and the LLM still hears the rest.
                self._spawn(self._run_now(stop, speak=False))
            return
        answer = self.confirmation.answer(meaning)
        if answer.verdict is Verdict.RUN and answer.command is not None:
            log.info("Confirmed by %r: %s", transcript, answer.command.command.name)
            await self._take_over()
            self._spawn(self._run_confirmed(answer.command))
        elif answer.verdict is Verdict.DECLINED:
            await self._take_over()
            self._say(CANCELLED)
        elif answer.verdict is Verdict.EXPIRED:
            await self._take_over()
            self._say(TOO_LATE)
        elif answer.verdict is Verdict.DROPPED:
            log.info("Dropped the pending command: the user said %r", transcript)
        await self._pump()

    async def _take_over(self) -> None:
        """The bridge answers this turn: the server's own reply to it is muted and cancelled."""
        self._mute_until = self._clock() + self._mute_window_s
        if self._active is not None:
            self._muted.add(self._active)
            if self._speaking is not None and self._speaking[0] == self._active:
                self._speaking = None
        await self._to_upstream(response_cancel())
        self._cancels += 1

    # ── The LLM's tool calls ───────────────────────────────────────────────────

    def _on_tool_call(self, call: ToolCall) -> None:
        self._hidden.add(call.call_id)
        key = call.response_id or call.call_id
        if key in self._commanded:
            self._outputs.append(function_call_output(call.call_id, ONE_AT_A_TIME))
            return
        self._commanded.add(key)
        # Counted now, not in the task: the response may end before the task starts.
        self._preparing += 1
        self._spawn(self._handle_call(call))

    async def _handle_call(self, call: ToolCall) -> None:
        try:
            await self._answer_call(call)
        finally:
            self._preparing -= 1
        await self._pump()

    async def _answer_call(self, call: ToolCall) -> None:
        try:
            if call.arguments is None:
                raise Rejected("the arguments were not a JSON object.")
            prepared = await self._planner.prepare(call.name, call.arguments)
        except Rejected as exc:
            log.info("Rejected %s(%s): %s", call.name, call.arguments, exc)
            self._outputs.append(function_call_output(call.call_id, f"Rejected: {exc} Nothing was done."))
            self._queue.append(Utterance("free"))
            return

        command = prepared.command
        if command.confirm:
            spoken = f"{prepared.sentence} {self._catalogue.confirmation.prompt}".strip()
            # A newer command replaces one not yet read back.
            self._queue = deque(u for u in self._queue if u.kind != "read_back")
            self.confirmation.propose(prepared, spoken)
            log.info("Proposed %s(%s): %r", command.name, dict(prepared.arguments), spoken)
            self._outputs.append(function_call_output(call.call_id, AWAITING_CONFIRMATION))
            self._queue.append(Utterance("read_back", spoken))
        else:
            sentence = await self._execute(prepared)
            self._outputs.append(function_call_output(call.call_id, sentence))
            self._queue.append(Utterance("say", sentence))

    # ── Running commands ───────────────────────────────────────────────────────

    async def _run_confirmed(self, prepared: Prepared) -> None:
        if prepared.command.started:
            self._say(str(prepared.command.started))
            await self._pump()
        self._say(await self._execute(prepared))
        await self._pump()

    async def _run_now(self, name: str, speak: bool) -> None:
        try:
            prepared = await self._planner.prepare(name, {})
            sentence = await self._execute(prepared)
        except Rejected as exc:
            sentence = str(exc)
        if speak:
            self._say(sentence)
            await self._pump()

    async def _execute(self, prepared: Prepared) -> str:
        """Runs a prepared command, or only says what a query found; returns what to say."""
        if prepared.request is None:
            return prepared.sentence
        outcome = await self._robot.execute(prepared.request)
        log.info("%s -> ok=%s %r", prepared.command.name, outcome.ok, outcome.message)
        return self._planner.outcome_sentence(prepared, outcome)

    # ── The bridge's own replies ───────────────────────────────────────────────

    def _say(self, text: str) -> None:
        self._queue.append(Utterance("say", text))

    async def _pump(self) -> None:
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

    def _spawn(self, coroutine: Awaitable[None]) -> None:
        async def guarded() -> None:
            try:
                await coroutine
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a failing command must not end the session
                log.exception("A command of the session failed")
                self._say(BRIDGE_FAILED)
                await self._pump()

        task = asyncio.create_task(guarded())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
