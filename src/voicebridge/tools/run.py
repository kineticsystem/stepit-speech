# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""``voicebridge run``: one command on the robot, read back and confirmed on the keyboard."""

from __future__ import annotations

import json
import sys
from typing import Any

from voicebridge.robot.planner import Planner, Rejected
from voicebridge.robot.rosbridge import Rosbridge
from voicebridge.robot.rosbridge_robot import RosbridgeRobot
from voicebridge.robotfile.loader import read_yaml
from voicebridge.robotfile.model import Catalogue


async def run(catalogue: Catalogue, command: str, arguments: list[str], rosbridge_url: str | None,
              yes: bool = False) -> int:
    """Prepares one command from name=value arguments, prints its read-back, and runs it once confirmed."""
    raw: dict[str, Any] = {}
    for item in arguments:
        key, separator, value = item.partition("=")
        if not separator:
            print(f"error: {item!r} is not name=value", file=sys.stderr)
            return 2
        raw[key] = read_yaml(value)
    rosbridge = Rosbridge(rosbridge_url or catalogue.rosbridge_url)
    robot = RosbridgeRobot(rosbridge)
    planner = Planner(catalogue, robot)
    try:
        try:
            prepared = await planner.prepare(command, raw)
        except Rejected as exc:
            print(f"Rejected: {exc}")
            return 1
        print(f"Read back: {prepared.sentence}")
        if prepared.request is None:
            return 0
        print(f"Request:   {json.dumps(prepared.request.message())}")
        if not yes and input("Run it? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 1
        outcome = await robot.execute(prepared.request)
        print(f"Outcome:   ok={outcome.ok} {outcome.message!r}")
        print(f"Says:      {planner.outcome_sentence(prepared, outcome)}")
        return 0 if outcome.ok else 1
    finally:
        await rosbridge.close()
