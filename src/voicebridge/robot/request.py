# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The robot, as the bridge sees it: requests in, outcomes out.

``render_request`` fills the templates of a call with the arguments a command
gives it, and returns the exact request that goes to rosbridge. ``Robot`` is
the port the rest of the bridge talks to: ``rosbridge_robot.RosbridgeRobot`` is
the real one, and tests use a fake. ``judge`` turns the robot's answer into an
``Outcome`` with the call's own ``success``, ``message`` and ``result``
templates.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from voicebridge.robotfile.model import Call
from voicebridge.robotfile.templating import TemplateError, evaluate, render

log = logging.getLogger("voicebridge.robot")

# GoalStatus of action_msgs.
SUCCEEDED = 4
CANCELED = 5


@dataclass(frozen=True)
class Request:
    """A call with every template filled in: what goes to rosbridge."""

    call: Call
    target: str
    type: str
    payload: Any
    # The arguments the command gave the call, which its success, message and result also see.
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def message(self) -> dict[str, Any]:
        """The rosbridge message of the request, as it goes on the wire, without its id."""
        kind = self.call.kind
        if kind == "action":
            return {"op": "send_action_goal", "action": self.target, "action_type": self.type, "args": self.payload}
        if kind == "service":
            return {"op": "call_service", "service": self.target, "type": self.type, "args": self.payload}
        if kind == "topic":
            return {"op": "subscribe", "topic": self.target, "type": self.type}
        return {"op": "publish", "topic": self.target, "msg": self.payload}


@dataclass(frozen=True)
class Outcome:
    ok: bool
    # A short sentence of the robot's, e.g. why it failed.
    message: str = ""
    # What a read returns to the command, after the call's `result`.
    value: Any = None


class Robot(Protocol):
    async def execute(self, request: Request) -> Outcome: ...


def render_request(call: Call, arguments: Mapping[str, Any]) -> Request:
    """Fills a call's templates with the arguments a command gives it. Raises TemplateError."""
    variables = dict(arguments)
    return Request(
        call=call,
        target=str(render(call.target, variables)),
        type=str(render(call.type, variables)),
        payload=render(call.request, variables) if call.kind != "topic" else None,
        arguments=variables,
    )


def judge(request: Request, response: Any, status: int | None = None) -> Outcome:
    """The outcome of an answer, by the call's templates. Without `success`, an action
    succeeded when its status is 4, and a service or a topic whenever it answered."""
    call = request.call
    variables = {**request.arguments, "response": response, "status": status}
    try:
        if call.success is not None:
            ok = bool(evaluate(call.success, variables))
        else:
            ok = status == SUCCEEDED if call.kind == "action" else True
        message = str(render(call.message, variables)).strip() if call.message else ""
        value = evaluate(call.result, variables) if call.result else response
    except TemplateError as exc:
        log.error("Cannot read the answer of %s: %s", call.name, exc)
        return Outcome(False, f"the answer of {call.name} could not be read")
    if not ok and not message and status == CANCELED:
        message = "it was stopped"
    return Outcome(ok, message, value)
