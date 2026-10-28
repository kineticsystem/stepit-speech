# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""What keeps the model from pretending: a reply that asks to confirm, or says the robot acts.

A model that has heard the bridge read commands back starts doing it itself,
in a reply, without calling the command: "Moving the camera closer. Confirm?",
and the user's yes confirms nothing. ``pretends`` finds such a reply, with the
robot's confirmation question and the verbs of its own read-backs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from voicebridge.robotfile.model import Catalogue
from voicebridge.safety.phrases import PhraseMatcher, words


@dataclass(frozen=True)
class Guard:
    """What the proxy knows of the robot to keep the model from pretending."""

    # The robot's confirmation question, e.g. "Confirm?".
    prompt: str = ""
    # The verbs of the robot's read-backs, e.g. moving, taking: a reply with one claims an action.
    verbs: frozenset[str] = frozenset()
    # Yes, no and stop, which the bridge answers itself.
    matcher: PhraseMatcher | None = field(default=None, compare=False)
    # The words of the bridge's sentences on falling asleep and on waking up; empty without a sleep mode.
    falls_asleep: tuple[str, ...] = ()
    wakes_up: tuple[str, ...] = ()

    @classmethod
    def of(cls, catalogue: Catalogue) -> Guard:
        texts = [text for command in catalogue.commands.values()
                 for text in (command.say, command.started) if isinstance(text, str)]
        verbs = {word for text in texts for word in words(_TEMPLATE_CODE.sub(" ", text))
                 if word.endswith("ing") and len(word) > 4}
        verbs |= {word for text in texts for word in re.findall(r"'([^']*)'", text) for word in words(word)
                  if word.endswith("ing") and len(word) > 4}
        sleep = catalogue.sleep
        if sleep is not None:
            # "Goodnight, I'm going to sleep.": the voice only sleeps when the bridge puts it to sleep.
            verbs |= _SLEEPING
        return cls(catalogue.confirmation.prompt, frozenset(verbs | _ACTING),
                   PhraseMatcher(catalogue.confirmation),
                   tuple(words(sleep.asleep)) if sleep else (), tuple(words(sleep.awake)) if sleep else ())


# Words of any robot's action, besides the verbs of its own read-backs.
_ACTING = frozenset({"turning", "done"})

# Words of a reply that pretends to fall asleep, for a robot with a sleep mode.
_SLEEPING = frozenset({"sleep", "sleeping", "asleep", "goodnight", "night"})


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
