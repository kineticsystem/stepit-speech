# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The robot file: what the user can say, and how each command reaches the robot.

A robot file has two halves, written by two different people:

- ``commands``: what the user can say. One entry per command, a few lines
  each: a description, its parameters, the sentence read back to the user,
  what to run, and example phrases. Writing one needs no ROS knowledge.
- ``calls``: how a command reaches the robot over rosbridge: the action,
  service or topic, its message type, the request, and how to tell success.
  Written once per robot by someone who knows its ROS interface. The calls of
  standard ROS 2 interfaces, e.g. ``set_parameters``, ship with voicebridge in
  ``calls.yaml`` and every robot file can use them.

Loading a file checks all of it: an unknown key, an unknown call, a template
that does not compile, or an example whose arguments do not fit its
parameters fails here, with the path to the mistake, not on the robot.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from voicebridge.templating import TemplateError, check_syntax, names_used


class RobotFileError(Exception):
    """The robot file is wrong; the message names where."""


class ArgumentError(Exception):
    """The arguments of a command are wrong; the message is a sentence for the LLM."""


# The kinds of call, by the key that names their target in the file.
CALL_KINDS = ("action", "service", "topic", "publish")
PARAMETER_TYPES = ("number", "integer", "string", "boolean")
_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


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
            number = _to_number(value)
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


def _to_number(value: Any) -> float | int | None:
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

    def tool_specs(self) -> list[dict[str, Any]]:
        return [command.tool_spec() for command in self.commands.values()]

    def command(self, name: str) -> Command:
        return self.commands[name]


# ── Loading ──────────────────────────────────────────────────────────────────

_TOP_KEYS = {"robot", "rosbridge", "confirmation", "calls", "commands"}
_ROBOT_KEYS = {"name", "description", "instructions", "greeting"}
_CONFIRMATION_KEYS = {"timeout_s", "prompt", "confirm", "decline", "stop", "fillers", "stop_command"}
_CALL_KEYS = {"description", "type", "request", "qos", "success", "message", "result", "timeout_s", *CALL_KINDS}
_COMMAND_KEYS = {
    "description", "parameters", "say", "run", "read", "let", "require",
    "confirm", "started", "done", "failed", "examples",
}
_PARAMETER_KEYS = {"type", "description", "choices", "min", "max", "optional"}


class _Loader(yaml.SafeLoader):
    """YAML as people read it: only true and false are booleans.

    Plain YAML 1.1 also reads yes, no, on and off as booleans, so that
    `state: [on, off]` would be [True, False]: in a file of spoken words, a trap.
    """


_Loader.yaml_implicit_resolvers = {
    first: [resolver for resolver in resolvers if resolver[0] != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def read_yaml(text: str) -> Any:
    """Parses YAML where only true and false are booleans."""
    return yaml.load(text, Loader=_Loader)  # noqa: S506 - a SafeLoader


def load(path: str | Path) -> Catalogue:
    """Loads and checks a robot file, on top of the calls that ship with voicebridge."""
    path = Path(path)
    try:
        data = read_yaml(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RobotFileError(f"{path}: {exc}") from exc
    return parse(data, source=str(path))


def builtin_calls() -> dict[str, Any]:
    """The calls of standard ROS 2 interfaces, which every robot file can use."""
    text = resources.files("voicebridge").joinpath("calls.yaml").read_text(encoding="utf-8")
    return read_yaml(text) or {}


def parse(data: Any, source: str = "robot file") -> Catalogue:
    """Builds a catalogue from the parsed YAML of a robot file, checking all of it."""
    if not isinstance(data, Mapping):
        raise RobotFileError(f"{source}: must be a mapping with robot, calls and commands")
    _no_unknown_keys(data, _TOP_KEYS, source)

    robot = _mapping(data.get("robot", {}), f"{source}: robot")
    _no_unknown_keys(robot, _ROBOT_KEYS, f"{source}: robot")

    raw_calls = {**builtin_calls(), **_mapping(data.get("calls", {}), f"{source}: calls")}
    calls = {name: _parse_call(name, spec, f"{source}: calls.{name}") for name, spec in raw_calls.items()}

    raw_commands = _mapping(data.get("commands", {}), f"{source}: commands")
    if not raw_commands:
        raise RobotFileError(f"{source}: commands: there must be at least one command")
    commands = {
        name: _parse_command(name, spec, calls, f"{source}: commands.{name}") for name, spec in raw_commands.items()
    }

    confirmation = _parse_confirmation(data.get("confirmation", {}), commands, f"{source}: confirmation")
    return Catalogue(
        name=str(robot.get("name", "the robot")),
        description=str(robot.get("description", "")).strip(),
        instructions=str(robot.get("instructions", "")).strip(),
        greeting=str(robot.get("greeting", "")).strip(),
        rosbridge_url=str(data.get("rosbridge", "ws://localhost:9090")),
        confirmation=confirmation,
        calls=calls,
        commands=commands,
    )


def _parse_call(name: str, spec: Any, where: str) -> Call:
    spec = _mapping(spec, where)
    _no_unknown_keys(spec, _CALL_KEYS, where)
    kinds = [kind for kind in CALL_KINDS if kind in spec]
    if len(kinds) != 1:
        raise RobotFileError(f"{where}: needs exactly one of {', '.join(CALL_KINDS)}")
    kind = kinds[0]
    if "type" not in spec:
        raise RobotFileError(f"{where}: needs the type of its message, e.g. std_srvs/srv/Trigger")
    call = Call(
        name=name,
        kind=kind,
        target=str(spec[kind]),
        type=str(spec["type"]),
        request=spec.get("request", {}),
        description=str(spec.get("description", "")).strip(),
        qos=spec.get("qos"),
        success=_optional_str(spec.get("success")),
        message=_optional_str(spec.get("message")),
        result=_optional_str(spec.get("result")),
        timeout_s=float(spec.get("timeout_s", 10.0)),
    )
    _check_templates(where, call.target, call.type, call.request, call.message)
    for expression in (call.success, call.result):
        if expression is not None:
            _check_templates(where, "{{ " + expression + " }}")
    return call


def _parse_command(name: str, spec: Any, calls: Mapping[str, Call], where: str) -> Command:
    if not _TOOL_NAME.match(name):
        raise RobotFileError(f"{where}: a command name may hold letters, digits, _ and - only")
    spec = _mapping(spec, where)
    _no_unknown_keys(spec, _COMMAND_KEYS, where)
    for key in ("description", "say"):
        if not str(spec.get(key, "")).strip():
            raise RobotFileError(f"{where}: needs {key}")

    parameters = tuple(
        _parse_parameter(parameter, value, f"{where}.parameters.{parameter}")
        for parameter, value in _mapping(spec.get("parameters", {}), f"{where}.parameters").items()
    )
    run = _parse_use(spec["run"], calls, f"{where}.run") if "run" in spec else None
    reads = {
        read: _parse_use(value, calls, f"{where}.read.{read}")
        for read, value in _mapping(spec.get("read", {}), f"{where}.read").items()
    }
    let = _mapping(spec.get("let", {}), f"{where}.let")
    require = tuple(_one_pair(item, f"{where}.require") for item in _list(spec.get("require", []), f"{where}.require"))
    confirm = spec.get("confirm", True)
    if not isinstance(confirm, bool):
        raise RobotFileError(f"{where}.confirm: must be true or false")
    if run is None and confirm:
        # A query changes nothing: there is nothing to confirm. Saying so keeps the file honest.
        raise RobotFileError(f"{where}: a command with nothing to run is a query: set confirm: false")

    command = Command(
        name=name,
        description=str(spec["description"]).strip(),
        say=str(spec["say"]).strip(),
        parameters=parameters,
        run=run,
        reads=reads,
        let=let,
        require=require,
        confirm=confirm,
        started=_optional_str(spec.get("started")),
        done=_optional_str(spec.get("done")),
        failed=_optional_str(spec.get("failed")),
    )
    _check_templates(where, command.say, command.let, command.started, command.done, command.failed)
    for condition, message in command.require:
        _check_templates(f"{where}.require", "{{ " + condition + " }}", message)
    _check_names(command, where)

    examples = tuple(
        _parse_example(item, command, f"{where}.examples")
        for item in _list(spec.get("examples", []), f"{where}.examples")
    )
    return Command(**{**command.__dict__, "examples": examples})


def _parse_parameter(name: str, spec: Any, where: str) -> Parameter:
    # Short forms: `number` is a number, [left, right] is a choice of words.
    if isinstance(spec, str):
        spec = {"type": spec}
    elif isinstance(spec, list):
        spec = {"type": "string", "choices": spec}
    spec = _mapping(spec, where)
    _no_unknown_keys(spec, _PARAMETER_KEYS, where)
    choices = spec.get("choices")
    kind = spec.get("type", "string" if choices is not None else None)
    if kind not in PARAMETER_TYPES:
        raise RobotFileError(f"{where}: type must be one of {', '.join(PARAMETER_TYPES)}, not {kind!r}")
    if choices is not None:
        if kind != "string" or not isinstance(choices, list) or not choices:
            raise RobotFileError(f"{where}: choices must be a non-empty list of words")
        choices = tuple(str(choice) for choice in choices)
    minimum, maximum = spec.get("min"), spec.get("max")
    for bound, label in ((minimum, "min"), (maximum, "max")):
        if bound is not None and (kind not in ("number", "integer") or _to_number(bound) is None):
            raise RobotFileError(f"{where}: {label} must be a number, on a number")
    return Parameter(
        name=name,
        type=kind,
        description=str(spec.get("description", "")).strip(),
        choices=choices,
        minimum=None if minimum is None else float(minimum),
        maximum=None if maximum is None else float(maximum),
        optional=bool(spec.get("optional", False)),
    )


def _parse_use(spec: Any, calls: Mapping[str, Call], where: str) -> Use:
    # `objective: {name: TakeShot}` runs the call `objective` with those arguments.
    spec = _mapping(spec, where)
    if len(spec) != 1:
        raise RobotFileError(f"{where}: must name one call, e.g. `objective: {{name: TakeShot}}`")
    (call, arguments), = spec.items()
    if call not in calls:
        raise RobotFileError(f"{where}: no call named {call!r}; the calls are {', '.join(sorted(calls))}")
    arguments = _mapping(arguments if arguments is not None else {}, f"{where}.{call}")
    _check_templates(where, arguments)
    return Use(call=call, arguments=arguments)


def _parse_example(item: Any, command: Command, where: str) -> Example:
    # Short form: `- rotate the stage 10 degrees left: {degrees: 10, direction: counter-clockwise}`.
    # Long form, for a command that reads the robot: `- {say: ..., expect: {...}, reads: {...}}`.
    item = _mapping(item, where)
    if "say" in item:
        _no_unknown_keys(item, {"say", "expect", "reads"}, where)
        phrase, expect, reads = item["say"], item.get("expect") or {}, item.get("reads") or {}
    else:
        phrase, expect = _one_pair(item, where)
        expect, reads = expect or {}, {}
    try:
        command.check_arguments(expect)
    except ArgumentError as exc:
        raise RobotFileError(f"{where}: {phrase!r}: {exc}") from exc
    missing = set(command.reads) - set(reads)
    if command.reads and missing:
        raise RobotFileError(f"{where}: {phrase!r}: give what the reads return, for {', '.join(sorted(missing))}")
    return Example(phrase=str(phrase), expect=dict(expect), reads=dict(reads))


def _parse_confirmation(spec: Any, commands: Mapping[str, Command], where: str) -> ConfirmationSettings:
    spec = _mapping(spec, where)
    _no_unknown_keys(spec, _CONFIRMATION_KEYS, where)
    words = {key: tuple(str(word) for word in _list(spec.get(key, []), f"{where}.{key}"))
             for key in ("confirm", "decline", "stop", "fillers")}
    if not words["confirm"]:
        raise RobotFileError(f"{where}.confirm: list the words that confirm a command, e.g. yes")
    stop_command = _optional_str(spec.get("stop_command"))
    if stop_command is not None:
        if stop_command not in commands:
            raise RobotFileError(f"{where}.stop_command: no command named {stop_command!r}")
        if commands[stop_command].parameters and any(not p.optional for p in commands[stop_command].parameters):
            raise RobotFileError(f"{where}.stop_command: the stop command must take no argument")
    elif words["stop"]:
        raise RobotFileError(f"{where}.stop: the stop words need a stop_command to run")
    return ConfirmationSettings(
        timeout_s=float(spec.get("timeout_s", 20.0)),
        prompt=str(spec.get("prompt", "Confirm?")),
        stop_command=stop_command,
        **words,
    )


def _check_names(command: Command, where: str) -> None:
    """Finds a misspelt name when the file loads, not on the robot: every name a template of the
    command reads must be a parameter, `reads`, or a `let` defined before it."""
    known = {parameter.name for parameter in command.parameters} | {"reads"}

    def check(part: str, value: Any, names: set[str]) -> None:
        unknown = sorted(names_used(value) - names)
        if unknown:
            raise RobotFileError(f"{where}.{part}: unknown name {', '.join(unknown)}; "
                                 f"the names are {', '.join(sorted(names))}")

    for read, use in command.reads.items():
        check(f"read.{read}", use.arguments, known - {"reads"})
    for key, value in command.let.items():
        check(f"let.{key}", value, known)
        known = known | {key}
    for condition, message in command.require:
        check("require", ["{{ " + condition + " }}", message], known)
    check("say", command.say, known)
    if command.run is not None:
        check("run", command.run.arguments, known)
    check("started", command.started, known)
    check("done", command.done, known | {"message"})
    check("failed", command.failed, known | {"message"})


def _check_templates(where: str, *values: Any) -> None:
    for value in values:
        try:
            check_syntax(value)
        except TemplateError as exc:
            raise RobotFileError(f"{where}: {exc}") from exc


def _no_unknown_keys(spec: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(str(key) for key in set(spec) - allowed)
    if unknown:
        hint = ""
        if any(" " in key for key in unknown):
            hint = " (a comma inside { } starts a new key: put a text with a comma in quotes)"
        raise RobotFileError(f"{where}: unknown {', '.join(unknown)}; allowed: {', '.join(sorted(allowed))}{hint}")


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RobotFileError(f"{where}: must be a mapping")
    return value


def _list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RobotFileError(f"{where}: must be a list")
    return value


def _one_pair(item: Any, where: str) -> tuple[str, Any]:
    if not isinstance(item, Mapping) or len(item) != 1:
        raise RobotFileError(f"{where}: each entry is one `key: value`, got {item!r}")
    (key, value), = item.items()
    return str(key), value


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value).strip()
