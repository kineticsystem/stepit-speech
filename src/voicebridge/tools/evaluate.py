# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""``voicebridge eval``: scores the LLM on the examples of a robot file, through the bridge's LLM proxy."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from voicebridge.conversation.prompt import instructions
from voicebridge.robotfile.model import Catalogue


def evaluate(catalogue: Catalogue, llm: str, model: str, phrases: list[str] | None = None,
             think: bool = False) -> int:
    """Asks the LLM, through chat completions, which tool it calls for each phrase.

    Without ``phrases``, the phrases are the examples of the robot file, scored against their arguments.
    """
    tools = [{"type": "function", "function": {key: spec[key] for key in ("name", "description", "parameters")}}
             for spec in catalogue.tool_specs()]
    cases: list[tuple[str, str | None, dict[str, Any] | None]] = []
    if phrases:
        cases = [(phrase, None, None) for phrase in phrases]
    else:
        for name, command in catalogue.commands.items():
            cases += [(example.phrase, name, dict(example.expect)) for example in command.examples]
    failures = 0
    for phrase, expected_name, expected in cases:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": instructions(catalogue)}, {"role": "user", "content": phrase}],
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
        if not think:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        request = urllib.request.Request(f"{llm.rstrip('/')}/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310 - a local endpoint
            message = json.load(response)["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            verdict = "FAIL" if expected_name else "----"
            failures += expected_name is not None
            print(f"{verdict} {phrase!r}: no tool; it said {message.get('content')!r}")
            continue
        function = calls[0]["function"]
        name = function["name"]
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except ValueError:
            arguments = None
        ok = expected_name is None or (name == expected_name and _same(catalogue, name, arguments, expected))
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {phrase!r}: {name}({json.dumps(arguments)})"
              + ("" if ok or expected_name is None else f", expected {expected_name}({json.dumps(expected)})"))
    print(f"{len(cases) - failures} of {len(cases)} understood as expected")
    return 1 if failures else 0


def _same(catalogue: Catalogue, name: str, arguments: Any, expected: Any) -> bool:
    command = catalogue.commands[name]
    try:
        got, want = command.check_arguments(arguments), command.check_arguments(expected)
    except Exception:  # noqa: BLE001 - arguments the bridge would reject are not the expected ones
        return False
    return all(
        abs(got[key] - want[key]) < 1e-6 if isinstance(want[key], float) and isinstance(got[key], float)
        else got[key] == want[key]
        for key in want
    )
