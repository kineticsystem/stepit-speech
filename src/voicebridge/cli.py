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
import logging
import os
import sys
from pathlib import Path

from voicebridge.conversation.server import BridgeServer
from voicebridge.llmproxy.guard import Guard
from voicebridge.llmproxy.proxy import LlmProxy
from voicebridge.robot.rosbridge import Rosbridge
from voicebridge.robot.rosbridge_robot import RosbridgeRobot
from voicebridge.robotfile.loader import RobotFileError, load
from voicebridge.robotfile.model import Catalogue
from voicebridge.tools.check import check as check_robot_file
from voicebridge.tools.docs import generate
from voicebridge.tools.evaluate import evaluate as evaluate_llm
from voicebridge.tools.run import run as run_command


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
    evaluate.add_argument("--model", default=os.environ.get("VOICEBRIDGE_LLM_MODEL", "bonsai-2-27b"))
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
        return asyncio.run(check_robot_file(catalogue))
    if args.action == "docs":
        text = asyncio.run(generate(catalogue, _relative(args.robot)))
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    if args.action == "run":
        return asyncio.run(run_command(catalogue, args.command, args.arguments, args.rosbridge, args.yes))
    return evaluate_llm(catalogue, args.llm, args.model, args.say, args.think)


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
        rosbridge.keep_connected()
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        await proxy.stop()
        await rosbridge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
