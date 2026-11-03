# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""Whether the user's words ask for a command that runs without confirmation.

A command with ``confirm: false``, the stop command or a query, runs as soon
as the LLM calls it: no read-back stands between the LLM's guess and the
robot. The LLM guesses on fragments: "Three centimetres.", said to correct a
read-back, once called stop. So the bridge runs such a command only when the
user's last words share a word with it: a word of its name or of one of its
examples, or, for the stop command, one of the stop phrases. The common words
of a request, "what", "is", "the", do not count.

A command that needs confirmation does not need this: its read-back is the check.
"""

from __future__ import annotations

from voicebridge.robotfile.model import Command, ConfirmationSettings
from voicebridge.safety.phrases import words

# Words of any request: sharing one of them says nothing about which command it asks for.
COMMON = frozenset("""
a an the this that these those it its it's there there's here
i me my we us our you your
is are was were be been am do does did can could will would should shall may might must
what what's how how's where where's when which who why
of to in on at for by with from about as and or but if so not no
please now then just very much some any all
""".split())


def _stem(word: str) -> str:
    """The word without a plural or third-person s: "stacks" and "stack" are the same word."""
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def command_words(command: Command, settings: ConfirmationSettings) -> frozenset[str]:
    """The words that ask for a command: of its name, of its examples, and the stop phrases for the stop command."""
    found = set(words(command.name.replace("_", " ")))
    for example in command.examples:
        found |= set(words(example.phrase)) - COMMON
    if command.name == settings.stop_command:
        for phrase in settings.stop:
            found |= set(words(phrase))
    return frozenset(_stem(word) for word in found)


def asked_for(heard: str | None, command: Command, settings: ConfirmationSettings) -> bool:
    """Whether the user's last words share a word with the command. Nothing heard asks for nothing."""
    if not heard:
        return False
    return bool({_stem(word) for word in words(heard)} & command_words(command, settings))
