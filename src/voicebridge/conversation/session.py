# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""One voice session: the conversation between one browser and the speech server.

The session sees every event in both directions and passes almost all of them
through unchanged. It holds the safety rules of the bridge:

1. It adds the robot's tools and instructions to every ``session.update``.
2. It hides the robot's tool calls from the browser and handles them: it
   prepares the command and asks the voice to read it back, word for word.
3. It checks that the voice said the read-back exactly; only then is the
   command armed.
4. It reads the user's transcript and decides, with fixed word lists, whether
   it is yes, no or stop. On yes, it runs the armed command; the LLM is never
   asked whether the user confirmed.
5. When it takes over a user's turn (yes, no, stop), it has the ``Speaker``
   mute and cancel the speech server's own reply to that turn, and speaks its own.
6. When the robot has a greeting, it says it in place of the browser's
   opening message, which asks the LLM to greet in its own words.

How a sentence reaches the voice, queued, tagged and one at a time, is the
``Speaker``'s. Its I/O is two async functions, ``to_browser`` and
``to_upstream``: the tests drive a session with lists.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from voicebridge.conversation.events import (
    USER_TRANSCRIPT,
    ToolCall,
    assistant_text,
    command_call,
    hidden_ids,
    hides,
    inject_session,
    response_id,
    scrub_response_done,
)
from voicebridge.conversation.prompt import AWAITING_CONFIRMATION, instructions
from voicebridge.conversation.speaker import Send, Speaker, Spoken
from voicebridge.robot.planner import Planner, Prepared, Rejected
from voicebridge.robot.request import Robot
from voicebridge.robotfile.model import Catalogue
from voicebridge.safety.confirmation import Confirmation, Phase, Verdict
from voicebridge.safety.phrases import Meaning, PhraseMatcher

log = logging.getLogger("voicebridge.session")

# What the bridge says on its own.
CANCELLED = "Cancelled. Nothing was done."
TOO_LATE = "That came too late, so nothing was done. Please give the command again."
READ_BACK_FAILED = "I could not read the command back exactly, so I cancelled it. Please say it again."
ONE_AT_A_TIME = "Rejected: one command at a time. Nothing was done for this call."
BRIDGE_FAILED = "Something went wrong in the bridge. Nothing more was done."
MUTED_CALL = "Not done: the system answered the user's last words itself. Nothing was done for this call."
NOTHING_TO_CONFIRM = "There is no command waiting for confirmation, so nothing was done."
SPOKE_OVER = "I had not finished reading the command back, so nothing was done. Please give the command again."


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
        self._speaker = Speaker(to_upstream, clock, mute_window_s)

        self._names = set(catalogue.commands)
        self._tools = catalogue.tool_specs()
        self._instructions = instructions(catalogue)
        self._matcher = PhraseMatcher(catalogue.confirmation)
        self.confirmation: Confirmation[Prepared] = Confirmation(catalogue.confirmation.timeout_s, clock)

        self._hidden: set[str] = set()                    # item and call ids of robot calls
        self._commanded: set[str] = set()                 # responses that already called a command
        self._greeted = not catalogue.greeting            # no greeting: nothing to replace
        self._skip_create = False                         # the response.create of the opening message
        self._tasks: set[asyncio.Task] = set()

    # ── The two directions ─────────────────────────────────────────────────────

    async def from_browser(self, event: dict[str, Any]) -> None:
        if not self._greeted and _user_message(event):
            # The browser's opening message, e.g. "start the conversation with a greeting":
            # the robot's own greeting answers it, word for word.
            self._greeted = True
            self._skip_create = True
            self._speaker.say(self._catalogue.greeting)
            await self._speaker.pump()
            return
        if self._skip_create and event.get("type") == "response.create":
            self._skip_create = False
            return
        await self._to_upstream(inject_session(event, self._tools, self._instructions))

    async def from_upstream(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        rid = response_id(event)

        if kind == "input_audio_buffer.speech_started":
            self._speaker.speech_started()
        elif kind == "response.created":
            if await self._speaker.created(event, rid):
                return
        elif kind == "error":
            if self._speaker.error(event):
                return

        if self._speaker.is_muted(rid):
            muted_call = command_call(event, self._names)
            if muted_call is not None:
                # The server waits for an answer to every call, even in a reply nobody hears.
                self._hidden.add(muted_call.call_id)
                self._speaker.answer_call(muted_call.call_id, MUTED_CALL)
            if kind == "response.done":
                await self._finished(rid, event)
            return

        if kind == USER_TRANSCRIPT:
            self._greeted = True  # the user spoke first: a later typed message is theirs
            await self._to_browser(event)
            await self._on_user_said(str(event.get("transcript") or ""))
            return

        text = assistant_text(event)
        if text is not None:
            self._speaker.hear(rid, text)

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

    # ── The read-back ──────────────────────────────────────────────────────────

    async def _finished(self, rid: str | None, event: dict[str, Any]) -> None:
        spoken = self._speaker.finished(rid, event)
        if spoken is not None and spoken.utterance.kind == "read_back":
            self._check_read_back(spoken)
        await self._speaker.pump()

    def _check_read_back(self, spoken: Spoken) -> None:
        text = spoken.utterance.text
        if self.confirmation.phase is not Phase.READING_BACK or self.confirmation.sentence != text:
            return
        if spoken.status not in (None, "completed"):
            # Interrupted: the user did not hear all of it.
            self.confirmation.cancel()
            return
        if self.confirmation.read_back(spoken.heard):
            log.info("Armed: %r", text)
        else:
            log.warning("The voice said %r instead of %r: cancelled", spoken.heard, text)
            self._speaker.say(READ_BACK_FAILED)

    # ── The user ───────────────────────────────────────────────────────────────

    async def _on_user_said(self, transcript: str) -> None:
        meaning = self._matcher.classify(transcript)
        stop = self._catalogue.confirmation.stop_command
        if stop is not None and self._matcher.mentions_stop(transcript):
            log.info("Stop: %r", transcript)
            self.confirmation.cancel()
            if meaning is Meaning.STOP:
                # Nothing but stop: the bridge answers this turn itself.
                await self._speaker.take_over()
                self._spawn(self._run_now(stop, speak=True))
                await self._speaker.pump()
            else:
                # "Stop the live view": the robot stops, and the LLM still hears the rest.
                self._spawn(self._run_now(stop, speak=False))
            return
        answer = self.confirmation.answer(meaning)
        if answer.verdict is Verdict.RUN and answer.command is not None:
            log.info("Confirmed by %r: %s", transcript, answer.command.command.name)
            await self._speaker.take_over()
            self._spawn(self._run_confirmed(answer.command))
        elif answer.verdict is Verdict.DECLINED:
            await self._speaker.take_over()
            self._speaker.say(CANCELLED)
        elif answer.verdict is Verdict.EXPIRED:
            await self._speaker.take_over()
            self._speaker.say(TOO_LATE)
        elif meaning is Meaning.CONFIRM:
            # A yes that confirms nothing: the bridge says so, rather than the LLM playing along.
            log.info("Nothing to confirm: the user said %r (%s)", transcript, answer.verdict.name)
            await self._speaker.take_over()
            self._speaker.say(NOTHING_TO_CONFIRM if answer.verdict is Verdict.NOTHING_PENDING else SPOKE_OVER)
        elif answer.verdict is Verdict.DROPPED:
            log.info("Dropped the pending command: the user said %r", transcript)
        await self._speaker.pump()

    # ── The LLM's tool calls ───────────────────────────────────────────────────

    def _on_tool_call(self, call: ToolCall) -> None:
        self._hidden.add(call.call_id)
        key = call.response_id or call.call_id
        if key in self._commanded:
            self._speaker.answer_call(call.call_id, ONE_AT_A_TIME)
            return
        self._commanded.add(key)
        # Counted now, not in the task: the response may end before the task starts.
        self._speaker.begin_call()
        self._spawn(self._handle_call(call))

    async def _handle_call(self, call: ToolCall) -> None:
        try:
            await self._answer_call(call)
        finally:
            self._speaker.end_call()
        await self._speaker.pump()

    async def _answer_call(self, call: ToolCall) -> None:
        try:
            if call.arguments is None:
                raise Rejected("the arguments were not a JSON object.")
            prepared = await self._planner.prepare(call.name, call.arguments)
        except Rejected as exc:
            log.info("Rejected %s(%s): %s", call.name, call.arguments, exc)
            self._speaker.answer_call(call.call_id, f"Rejected: {exc} Nothing was done.")
            self._speaker.let_llm_answer()
            return

        command = prepared.command
        if command.confirm:
            spoken = f"{prepared.sentence} {self._catalogue.confirmation.prompt}".strip()
            # A newer command replaces one not yet read back.
            self.confirmation.propose(prepared, spoken)
            log.info("Proposed %s(%s): %r", command.name, dict(prepared.arguments), spoken)
            self._speaker.answer_call(call.call_id, AWAITING_CONFIRMATION)
            self._speaker.read_back(spoken)
        else:
            sentence = await self._execute(prepared)
            self._speaker.answer_call(call.call_id, sentence)
            self._speaker.say(sentence)

    # ── Running commands ───────────────────────────────────────────────────────

    async def _run_confirmed(self, prepared: Prepared) -> None:
        if prepared.command.started:
            self._speaker.say(str(prepared.command.started))
            await self._speaker.pump()
        self._speaker.say(await self._execute(prepared))
        await self._speaker.pump()

    async def _run_now(self, name: str, speak: bool) -> None:
        try:
            prepared = await self._planner.prepare(name, {})
            sentence = await self._execute(prepared)
        except Rejected as exc:
            sentence = str(exc)
        if speak:
            self._speaker.say(sentence)
            await self._speaker.pump()

    async def _execute(self, prepared: Prepared) -> str:
        """Runs a prepared command, or only says what a query found; returns what to say."""
        if prepared.request is None:
            return prepared.sentence
        outcome = await self._robot.execute(prepared.request)
        log.info("%s -> ok=%s %r", prepared.command.name, outcome.ok, outcome.message)
        return self._planner.outcome_sentence(prepared, outcome)

    def _spawn(self, coroutine: Awaitable[None]) -> None:
        async def guarded() -> None:
            try:
                await coroutine
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a failing command must not end the session
                log.exception("A command of the session failed")
                self._speaker.say(BRIDGE_FAILED)
                await self._speaker.pump()

        task = asyncio.create_task(guarded())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def _user_message(event: dict[str, Any]) -> bool:
    item = event.get("item")
    return (event.get("type") == "conversation.item.create" and isinstance(item, dict)
            and item.get("type", "message") == "message" and item.get("role") == "user")
