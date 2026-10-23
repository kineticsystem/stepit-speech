# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The command line of voicebridge.

    voicebridge serve ROBOT_FILE     the bridge, between the browser and the speech server
    voicebridge check ROBOT_FILE     checks the file and prepares every example, without a robot
    voicebridge docs ROBOT_FILE      writes the list of commands, commands.md
    voicebridge run ROBOT_FILE COMMAND [name=value ...]
                                     runs one command on the robot, confirmed on the keyboard
    voicebridge eval ROBOT_FILE      asks the LLM to understand every example, and scores it
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

from voicebridge.catalogue import Catalogue, RobotFileError, load, read_yaml
from voicebridge.docs import generate
from voicebridge.llmproxy import Guard, LlmProxy
from voicebridge.planner import Planner, Rejected
from voicebridge.prompt import instructions
from voicebridge.robot import RosbridgeRobot
from voicebridge.rosbridge import Rosbridge
from voicebridge.server import BridgeServer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voicebridge", description="Drive a ROS 2 robot by voice.")
    commands = parser.add_subparsers(dest="action", required=True)

    serve = commands.add_parser("serve", help="run the bridge")
    serve.add_argument("robot", help="the robot file, e.g. robots/stepit-macro/robot.yaml")
    serve.add_argument("--listen", default=os.environ.get("VOICEBRIDGE_LISTEN", "0.0.0.0:8766"),
                       help="where the browser connects, host:port (default %(default)s)")
    serve.add_argument("--upstream", default=os.environ.get("VOICEBRIDGE_UPSTREAM", "ws://127.0.0.1:8765/v1/realtime"),
                       help="the speech-to-speech server (default %(default)s)")
    serve.add_argument("--rosbridge", default=os.environ.get("VOICEBRIDGE_ROSBRIDGE"),
                       help="rosbridge, instead of the robot file's")
    serve.add_argument("--llm-listen", default=os.environ.get("VOICEBRIDGE_LLM_LISTEN", "127.0.0.1:8767"),
                       help="the LLM proxy, which the speech server must use as its LLM (default %(default)s)")
    serve.add_argument("--llm", default=os.environ.get("VOICEBRIDGE_LLM_URL", "http://localhost:8085/v1"),
                       help="the LLM behind the proxy, OpenAI-compatible (default %(default)s)")
    serve.add_argument("--llm-model", default=os.environ.get("VOICEBRIDGE_LLM_MODEL"),
                       help="the model to ask, instead of the one the speech server names")

    check = commands.add_parser("check", help="check a robot file and prepare its examples")
    check.add_argument("robot")

    docs = commands.add_parser("docs", help="write the list of commands")
    docs.add_argument("robot")
    docs.add_argument("-o", "--output", help="the file to write; the standard output by default")

    run = commands.add_parser("run", help="run one command on the robot")
    run.add_argument("robot")
    run.add_argument("command")
    run.add_argument("arguments", nargs="*", help="name=value, e.g. degrees=10")
    run.add_argument("--yes", action="store_true", help="do not ask before running it")
    run.add_argument("--rosbridge", default=os.environ.get("VOICEBRIDGE_ROSBRIDGE"))

    evaluate = commands.add_parser("eval", help="score the LLM on the examples of a robot file")
    evaluate.add_argument("robot")
    evaluate.add_argument("--llm", default="http://localhost:8767/v1",
                          help="the bridge's LLM proxy, which asks the LLM as the bridge does (default %(default)s)")
    evaluate.add_argument("--model", default=os.environ.get("VOICEBRIDGE_LLM_MODEL", "stepit-macro-bonsai"))
    evaluate.add_argument("--say", action="append", help="a phrase to try instead of the examples; repeatable")
    evaluate.add_argument("--think", action="store_true", help="let the model think first")

    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        catalogue = load(args.robot)
    except RobotFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.action == "serve":
        return asyncio.run(_serve(catalogue, args))
    if args.action == "check":
        return asyncio.run(_check(catalogue))
    if args.action == "docs":
        text = asyncio.run(generate(catalogue, _relative(args.robot)))
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    if args.action == "run":
        return asyncio.run(_run(catalogue, args))
    return _eval(catalogue, args)


def _relative(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path.cwd()))
    except ValueError:
        return Path(path).name


async def _serve(catalogue: Catalogue, args: argparse.Namespace) -> int:
    host, _, port = args.listen.rpartition(":")
    rosbridge = Rosbridge(args.rosbridge or catalogue.rosbridge_url)
    server = BridgeServer(catalogue, RosbridgeRobot(rosbridge), args.upstream, host or "0.0.0.0", int(port))
    llm_host, _, llm_port = args.llm_listen.rpartition(":")
    proxy = LlmProxy(args.llm, llm_host or "127.0.0.1", int(llm_port), Guard.of(catalogue),
                     model=args.llm_model)
    logging.getLogger("voicebridge").info("%s: %d commands, rosbridge at %s", catalogue.name,
                                          len(catalogue.commands), rosbridge.url)
    try:
        await proxy.start()
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        await proxy.stop()
        await rosbridge.close()
    return 0


async def _check(catalogue: Catalogue) -> int:
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


async def _run(catalogue: Catalogue, args: argparse.Namespace) -> int:
    raw: dict[str, Any] = {}
    for item in args.arguments:
        key, separator, value = item.partition("=")
        if not separator:
            print(f"error: {item!r} is not name=value", file=sys.stderr)
            return 2
        raw[key] = read_yaml(value)
    rosbridge = Rosbridge(args.rosbridge or catalogue.rosbridge_url)
    robot = RosbridgeRobot(rosbridge)
    planner = Planner(catalogue, robot)
    try:
        try:
            prepared = await planner.prepare(args.command, raw)
        except Rejected as exc:
            print(f"Rejected: {exc}")
            return 1
        print(f"Read back: {prepared.sentence}")
        if prepared.request is None:
            return 0
        print(f"Request:   {json.dumps(prepared.request.message())}")
        if not args.yes and input("Run it? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 1
        outcome = await robot.execute(prepared.request)
        print(f"Outcome:   ok={outcome.ok} {outcome.message!r}")
        print(f"Says:      {planner.outcome_sentence(prepared, outcome)}")
        return 0 if outcome.ok else 1
    finally:
        await rosbridge.close()


def _eval(catalogue: Catalogue, args: argparse.Namespace) -> int:
    """Asks the LLM, through chat completions, which tool it calls for each phrase."""
    tools = [{"type": "function", "function": {key: spec[key] for key in ("name", "description", "parameters")}}
             for spec in catalogue.tool_specs()]
    cases: list[tuple[str, str | None, dict[str, Any] | None]] = []
    if args.say:
        cases = [(phrase, None, None) for phrase in args.say]
    else:
        for name, command in catalogue.commands.items():
            cases += [(example.phrase, name, dict(example.expect)) for example in command.examples]
    failures = 0
    for phrase, expected_name, expected in cases:
        body: dict[str, Any] = {
            "model": args.model,
            "messages": [{"role": "system", "content": instructions(catalogue)}, {"role": "user", "content": phrase}],
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
        if not args.think:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        request = urllib.request.Request(f"{args.llm.rstrip('/')}/chat/completions", data=json.dumps(body).encode(),
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


if __name__ == "__main__":
    sys.exit(main())
