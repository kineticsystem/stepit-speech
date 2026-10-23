# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""What the user's words mean to the bridge: yes, no, stop, or anything else.

This is deliberately not the LLM. The words come from the speech-to-text
transcript and are matched against fixed lists of the robot file, so that a
command runs only when the user said a word on the list. The rule is strict:
the whole utterance must be made of confirming phrases (and fillers such as
"please"); "yes, but 20 degrees" is not a yes. Anything that is not clearly
yes cancels the pending command.

Stop is the opposite: a stop phrase anywhere in the utterance stops, e.g.
"ok stop" or "stop the live view" (``mentions_stop``). A stop heard by mistake
costs nothing; a stop missed is the failure that matters. Only an utterance
made of stop phrases alone means STOP; "stop the live view" also stops, then
goes on to the LLM as any other request.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Iterable, Sequence

from voicebridge.catalogue import ConfirmationSettings


class Meaning(enum.Enum):
    CONFIRM = "confirm"
    DECLINE = "decline"
    STOP = "stop"
    OTHER = "other"


# Letters, digits and apostrophes make words; everything else separates them.
_WORD = re.compile(r"[a-z0-9']+")


def words(text: str) -> list[str]:
    """The words of a text, lowercased, without punctuation: "Yes, go ahead!" is [yes, go, ahead]."""
    return _WORD.findall(text.lower().replace("’", "'"))


def _phrases(items: Iterable[str]) -> list[tuple[str, ...]]:
    # Longest first, so that "go ahead" is matched before "go".
    return sorted({tuple(words(item)) for item in items if words(item)}, key=len, reverse=True)


def _contains(sequence: Sequence[str], phrases: list[tuple[str, ...]]) -> bool:
    return any(tuple(sequence[i:i + len(phrase)]) == phrase
               for phrase in phrases for i in range(len(sequence) - len(phrase) + 1))


def _covers(sequence: Sequence[str], meaningful: list[tuple[str, ...]], fillers: list[tuple[str, ...]]) -> bool:
    """Whether the words are made entirely of meaningful phrases and fillers, with at least one meaningful."""
    position, found = 0, False
    while position < len(sequence):
        for phrase in meaningful:
            if tuple(sequence[position:position + len(phrase)]) == phrase:
                position += len(phrase)
                found = True
                break
        else:
            for phrase in fillers:
                if tuple(sequence[position:position + len(phrase)]) == phrase:
                    position += len(phrase)
                    break
            else:
                return False
    return found


class PhraseMatcher:
    """Classifies an utterance with the word lists of the robot file."""

    def __init__(self, settings: ConfirmationSettings) -> None:
        self._confirm = _phrases(settings.confirm)
        self._decline = _phrases(settings.decline)
        self._stop = _phrases(settings.stop)
        self._fillers = _phrases(settings.fillers)

    def mentions_stop(self, text: str) -> bool:
        """Whether a stop phrase occurs anywhere in the utterance."""
        return _contains(words(text), self._stop)

    def classify(self, text: str) -> Meaning:
        sequence = words(text)
        if not sequence:
            return Meaning.OTHER
        # Stop first: "stop" must never be taken for anything else.
        if self._stop and _covers(sequence, self._stop, self._fillers):
            return Meaning.STOP
        if _covers(sequence, self._confirm, self._fillers):
            return Meaning.CONFIRM
        if self._decline and _covers(sequence, self._decline, self._fillers):
            return Meaning.DECLINE
        return Meaning.OTHER


def same_sentence(heard: str, expected: str) -> bool:
    """Whether the voice said the expected sentence, ignoring case and punctuation."""
    return words(heard) == words(expected)
