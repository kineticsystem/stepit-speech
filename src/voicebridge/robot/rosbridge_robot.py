# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The real robot: a ``Robot`` that sends each request through rosbridge."""

from __future__ import annotations

import logging

from voicebridge.robot.request import Outcome, Request, judge
from voicebridge.robot.rosbridge import Rosbridge, RosbridgeError

log = logging.getLogger("voicebridge.robot")


class RosbridgeRobot:
    """The real robot, over rosbridge."""

    def __init__(self, rosbridge: Rosbridge) -> None:
        self._rosbridge = rosbridge

    async def execute(self, request: Request) -> Outcome:
        call = request.call
        log.info("%s %s", call.kind, request.message())
        try:
            if call.kind == "action":
                result = await self._rosbridge.send_action_goal(request.target, request.type, request.payload,
                                                                timeout_s=call.timeout_s)
                return judge(request, result.values, result.status)
            if call.kind == "service":
                response = await self._rosbridge.call_service(request.target, request.type, request.payload,
                                                              timeout_s=call.timeout_s)
                return judge(request, response)
            if call.kind == "topic":
                message = await self._rosbridge.read_topic(request.target, request.type,
                                                           dict(call.qos) if call.qos else None, call.timeout_s)
                return judge(request, message)
            await self._rosbridge.publish(request.target, request.type, request.payload)
            return judge(request, None)
        except RosbridgeError as exc:
            return Outcome(False, str(exc))
