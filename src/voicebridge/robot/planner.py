# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""From a tool call of the LLM to a command ready to read back and run.

``prepare`` does every step that can refuse a command before the user is
asked to confirm it, in this order:

1. check the arguments against the command's parameters (types, ranges, choices);
2. run its reads on the robot, e.g. the plan of a focus stack;
3. compute its ``let`` values;
4. check its ``require`` conditions, e.g. both marks set;
5. render the sentence to read back, and the request to run.

So the sentence the user confirms and the request that runs are rendered
together, from the same values: what is read back is what runs.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from voicebridge.robot.request import Outcome, Request, Robot, render_request
from voicebridge.robotfile.model import ArgumentError, Catalogue, Command, Use
from voicebridge.robotfile.templating import TemplateError, evaluate, render

log = logging.getLogger("voicebridge.planner")


class Rejected(Exception):
    """The command cannot run; the message is a sentence for the LLM to explain."""


@dataclass(frozen=True)
class Prepared:
    """A command with everything decided: the sentence to read back and the request to run."""

    command: Command
    arguments: Mapping[str, Any]
    # The arguments, the reads and the let values: what the templates of the command see.
    variables: Mapping[str, Any]
    sentence: str
    request: Request | None


class Planner:
    def __init__(self, catalogue: Catalogue, robot: Robot | None) -> None:
        self._catalogue = catalogue
        self._robot = robot

    async def prepare(self, name: str, raw_arguments: Any,
                      reads: Mapping[str, Any] | None = None) -> Prepared:
        """Prepares a command. ``reads`` replaces the robot's reads, e.g. for the documentation."""
        command = self._catalogue.commands.get(name)
        if command is None:
            raise Rejected(f"There is no command {name}.")
        try:
            arguments = command.check_arguments(raw_arguments)
        except ArgumentError as exc:
            raise Rejected(str(exc)) from exc

        try:
            variables: dict[str, Any] = dict(arguments)
            variables["reads"] = await self._reads(command, variables, reads)
            for key, template in command.let.items():
                variables[key] = render(template, variables)
            for condition, message in command.require:
                if not evaluate(condition, variables):
                    raise Rejected(str(render(message, variables)))
            sentence = str(render(command.say, variables)).strip()
            request = self._request(command.run, variables) if command.run else None
        except TemplateError as exc:
            # A mistake of the robot file that its check could not see, e.g. a read
            # that returned another shape: refuse, and say why in the log.
            log.error("Cannot prepare %s: %s", name, exc)
            raise Rejected(f"{name} cannot be prepared: the robot file has a mistake.") from exc
        return Prepared(command, arguments, variables, sentence, request)

    def outcome_sentence(self, prepared: Prepared, outcome: Outcome) -> str:
        """What to say once a command ran: its `done` or `failed` sentence."""
        command = prepared.command
        variables = {**prepared.variables, "message": outcome.message}
        template = command.done if outcome.ok else command.failed
        if template:
            try:
                return str(render(template, variables)).strip()
            except TemplateError as exc:
                log.error("Cannot say the outcome of %s: %s", command.name, exc)
        if outcome.ok:
            return "Done."
        return f"That did not work: {outcome.message}." if outcome.message else "That did not work."

    async def _reads(self, command: Command, variables: Mapping[str, Any],
                     given: Mapping[str, Any] | None) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, use in command.reads.items():
            if given is not None:
                values[name] = given[name]
                continue
            if self._robot is None:
                raise Rejected("The robot cannot be read.")
            outcome = await self._robot.execute(self._request(use, variables))
            if not outcome.ok:
                raise Rejected(f"I could not read the {name.replace('_', ' ')} of the robot: {outcome.message}.")
            values[name] = outcome.value
        return values

    def _request(self, use: Use, variables: Mapping[str, Any]) -> Request:
        return render_request(self._catalogue.calls[use.call], render(use.arguments, variables))
