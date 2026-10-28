# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""What a robot file becomes once loaded: frozen dataclasses, which nothing changes.

A robot file has two halves, written by two different people:

- ``commands``: what the user can say. One entry per command, a few lines
  each: a description, its parameters, the sentence read back to the user,
  what to run, and example phrases. Writing one needs no ROS knowledge.
- ``calls``: how a command reaches the robot over rosbridge: the action,
  service or topic, its message type, the request, and how to tell success.
  Written once per robot by someone who knows its ROS interface.

``loader`` reads and checks the file; this module only holds what it found,
and the two checks that run while the bridge does: a parameter's value, and
the arguments of a command.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class ArgumentError(Exception):
    """The arguments of a command are wrong; the message is a sentence for the LLM."""


# The kinds of call, by the key that names their target in the file.
CALL_KINDS = ("action", "service", "topic", "publish")
PARAMETER_TYPES = ("number", "integer", "string", "boolean")


@dataclass(frozen=True)
class Parameter:
    """One argument of a command, as the LLM fills it in and the bridge checks it."""

    name: str
    type: str
    description: str = ""
    choices: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    optional: bool = False

    def schema(self) -> dict[str, Any]:
        """The JSON schema of the parameter, for the tool the LLM sees."""
        schema: dict[str, Any] = {"type": self.type}
        if self.choices is not None:
            schema["enum"] = list(self.choices)
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.description:
            schema["description"] = self.description
        return schema

    def check(self, value: Any) -> Any:
        """Returns the value in its type, or raises ArgumentError with a sentence for the LLM."""
        if self.type in ("number", "integer"):
            number = to_number(value)
            if number is None:
                raise ArgumentError(f"{self.name} must be a number, not {value!r}.")
            if self.type == "integer":
                if not float(number).is_integer():
                    raise ArgumentError(f"{self.name} must be a whole number, not {value!r}.")
                number = int(number)
            else:
                number = float(number)
            if self.minimum is not None and number < self.minimum:
                raise ArgumentError(f"{self.name} must be at least {_plain(self.minimum)}, not {_plain(number)}.")
            if self.maximum is not None and number > self.maximum:
                raise ArgumentError(f"{self.name} must be at most {_plain(self.maximum)}, not {_plain(number)}.")
            return number
        if self.type == "boolean":
            if not isinstance(value, bool):
                raise ArgumentError(f"{self.name} must be true or false, not {value!r}.")
            return value
        # A string.
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ArgumentError(f"{self.name} must be text, not {value!r}.")
        text = str(value).strip()
        if self.choices is not None:
            for choice in self.choices:
                if text.lower() == choice.lower():
                    return choice
            raise ArgumentError(f"{self.name} must be one of {', '.join(self.choices)}, not {text!r}.")
        if not text:
            raise ArgumentError(f"{self.name} must not be empty.")
        return text


def to_number(value: Any) -> float | int | None:
    """A finite number from a number or a text of one; None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _plain(number: float) -> str:
    return str(int(number)) if float(number).is_integer() else f"{number:g}"


@dataclass(frozen=True)
class Call:
    """How to reach the robot: one action, service or topic, with templates for its request."""

    name: str
    kind: str
    target: str
    type: str
    request: Any = field(default_factory=dict)
    description: str = ""
    qos: Mapping[str, Any] | None = None
    success: str | None = None
    message: str | None = None
    result: str | None = None
    timeout_s: float = 10.0


@dataclass(frozen=True)
class Use:
    """A command's use of a call: its name, and the arguments to fill its templates."""

    call: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class Example:
    """A phrase the user could say, and the arguments the LLM is expected to give."""

    phrase: str
    expect: Mapping[str, Any]
    # For a command that reads the robot first: what the reads return, to render it without one.
    reads: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Command:
    """One thing the user can ask for: one tool of the LLM."""

    name: str
    description: str
    say: str
    parameters: tuple[Parameter, ...] = ()
    run: Use | None = None
    reads: Mapping[str, Use] = field(default_factory=dict)
    let: Mapping[str, Any] = field(default_factory=dict)
    require: tuple[tuple[str, str], ...] = ()
    confirm: bool = True
    started: str | None = None
    done: str | None = None
    failed: str | None = None
    examples: tuple[Example, ...] = ()

    @property
    def is_query(self) -> bool:
        """A query only reads the robot and says what it found: it has nothing to run."""
        return self.run is None

    def tool_spec(self) -> dict[str, Any]:
        """The function tool of the command, in the shape of the OpenAI Realtime API."""
        description = self.description.strip()
        if self.examples:
            phrases = "; ".join(f'"{example.phrase}"' for example in self.examples[:4])
            description += f" Examples: {phrases}."
        return {
            "type": "function",
            "name": self.name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {parameter.name: parameter.schema() for parameter in self.parameters},
                "required": [parameter.name for parameter in self.parameters if not parameter.optional],
                "additionalProperties": False,
            },
        }

    def check_arguments(self, raw: Any) -> dict[str, Any]:
        """The arguments the LLM gave, checked and typed; an optional one left out is None.

        Raises ArgumentError with a sentence the LLM can act on.
        """
        if raw is None:
            raw = {}
        if not isinstance(raw, Mapping):
            raise ArgumentError("The arguments must be an object.")
        known = {parameter.name for parameter in self.parameters}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ArgumentError(f"{self.name} takes no argument {', '.join(unknown)}.")
        arguments: dict[str, Any] = {}
        for parameter in self.parameters:
            value = raw.get(parameter.name)
            if value is None or (isinstance(value, str) and not value.strip() and parameter.optional):
                if not parameter.optional:
                    raise ArgumentError(f"{self.name} needs {parameter.name}.")
                arguments[parameter.name] = None
                continue
            arguments[parameter.name] = parameter.check(value)
        return arguments


@dataclass(frozen=True)
class ConfirmationSettings:
    """How the bridge hears yes, no and stop: fixed lists of words, never the LLM."""

    timeout_s: float = 20.0
    prompt: str = "Confirm?"
    confirm: tuple[str, ...] = ()
    decline: tuple[str, ...] = ()
    stop: tuple[str, ...] = ()
    fillers: tuple[str, ...] = ()
    stop_command: str | None = None


# The name of the command that puts the voice to sleep, built from the robot file's `sleep` section.
SLEEP_COMMAND = "sleep"


@dataclass(frozen=True)
class SleepSettings:
    """The voice's sleep mode: asleep, it hears nothing but the wake phrase and stop.

    Going to sleep is a command, ``SLEEP_COMMAND``, read back and confirmed like
    any other, that runs nothing on the robot. Waking up is one of the ``wake``
    phrases, said alone: the bridge hears it, never the LLM, which hears nothing
    while the voice sleeps.
    """

    wake: tuple[str, ...]
    # Said when the voice falls asleep, and when it wakes up.
    asleep: str
    awake: str
    # How to put it to sleep, e.g. "go to sleep", for the phone to show.
    example: str


@dataclass(frozen=True)
class Catalogue:
    """Everything the bridge knows of a robot, loaded from its robot file."""

    name: str
    description: str
    instructions: str
    rosbridge_url: str
    confirmation: ConfirmationSettings
    calls: Mapping[str, Call]
    commands: Mapping[str, Command]
    # Said when a session starts, in place of the LLM's own greeting; empty: the LLM greets.
    greeting: str = ""
    # The voice's sleep mode; None: it is always awake.
    sleep: SleepSettings | None = None

    def tool_specs(self) -> list[dict[str, Any]]:
        return [command.tool_spec() for command in self.commands.values()]

    def command(self, name: str) -> Command:
        return self.commands[name]
