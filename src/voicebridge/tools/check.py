# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""``voicebridge check``: prepares every example of a robot file, without a robot."""

from __future__ import annotations

import json

from voicebridge.robot.planner import Planner, Rejected
from voicebridge.robotfile.model import Catalogue


async def check(catalogue: Catalogue) -> int:
    """Prepares every example of a robot file without a robot, and prints what each says and runs."""
    planner = Planner(catalogue, robot=None)
    failures = 0
    for name, command in catalogue.commands.items():
        if not command.examples:
            print(f"{name}: no example: add one, it teaches the LLM and tests the command")
        for example in command.examples:
            try:
                prepared = await planner.prepare(name, example.expect, reads=example.reads)
            except Rejected as exc:
                failures += 1
                print(f"FAIL {name}: {example.phrase!r}: {exc}")
                continue
            print(f"ok   {name}: {example.phrase!r}\n       says: {prepared.sentence}")
            if prepared.request is not None:
                print(f"       runs: {json.dumps(prepared.request.message())}")
    print(f"{catalogue.name}: {len(catalogue.commands)} commands, {failures} failures")
    return 1 if failures else 0
