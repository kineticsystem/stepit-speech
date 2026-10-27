# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The confirmation of a command: one pending command at a time, and its states.

    IDLE ──propose──▶ READING_BACK ──read back heard, the same──▶ ARMED ──yes──▶ run
      ▲                    │                                        │
      └── said otherwise ──┘◀──────── no, anything else, late ──────┘

A command is only ever run from ARMED, and only by ``answer`` with
``Meaning.CONFIRM``. It gets there only once the voice has said the read-back
sentence exactly, so the user confirms what they heard and what will run.
Anything else, at any point, drops it. Pure logic: no I/O, the clock is given.
"""

from __future__ import annotations

import enum
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from voicebridge.safety.phrases import Meaning, same_sentence

T = TypeVar("T")


class Phase(enum.Enum):
    IDLE = "idle"
    READING_BACK = "reading back"
    ARMED = "armed"


class Verdict(enum.Enum):
    """What the bridge must do after the user answered."""

    RUN = "run"                # confirmed in time: run the command
    DECLINED = "declined"      # the user said no: say it was cancelled
    EXPIRED = "expired"        # a yes, but too late: say nothing was done
    DROPPED = "dropped"        # the user said something else: let the LLM answer it
    NOTHING_PENDING = "none"   # no command was waiting


@dataclass(frozen=True)
class Answer(Generic[T]):
    verdict: Verdict
    command: T | None = None


class Confirmation(Generic[T]):
    """Holds the one command that waits for the user's yes."""

    def __init__(self, timeout_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._timeout_s = timeout_s
        self._clock = clock
        self._phase = Phase.IDLE
        self._command: T | None = None
        self._sentence = ""
        self._deadline = 0.0

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def command(self) -> T | None:
        return self._command

    @property
    def sentence(self) -> str:
        """The read-back sentence of the pending command."""
        return self._sentence

    def propose(self, command: T, sentence: str) -> None:
        """A new command to read back; it replaces any command still pending."""
        self._phase = Phase.READING_BACK
        self._command = command
        self._sentence = sentence

    def read_back(self, heard: str) -> bool:
        """The voice finished the read-back: arms the command when it said the sentence exactly.

        Returns False, and drops the command, when the voice said anything else.
        """
        if self._phase is not Phase.READING_BACK:
            return False
        if not same_sentence(heard, self._sentence):
            self.cancel()
            return False
        self._phase = Phase.ARMED
        self._deadline = self._clock() + self._timeout_s
        return True

    def answer(self, meaning: Meaning) -> Answer[T]:
        """The user spoke while a command is pending: what to do with it. Always ends in IDLE."""
        phase, command = self._phase, self._command
        if phase is Phase.IDLE:
            return Answer(Verdict.NOTHING_PENDING)
        self.cancel()
        if phase is Phase.READING_BACK:
            # Spoke over the read-back: they cannot have confirmed what they did not hear.
            return Answer(Verdict.DROPPED, command)
        if meaning is Meaning.CONFIRM:
            if self._clock() > self._deadline:
                return Answer(Verdict.EXPIRED, command)
            return Answer(Verdict.RUN, command)
        if meaning in (Meaning.DECLINE, Meaning.STOP):
            return Answer(Verdict.DECLINED, command)
        return Answer(Verdict.DROPPED, command)

    def cancel(self) -> None:
        self._phase = Phase.IDLE
        self._command = None
        self._sentence = ""
