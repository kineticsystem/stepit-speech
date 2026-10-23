# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The list of a robot's commands, commands.md, generated from its robot file.

Every example of the file is prepared as the bridge would prepare it, so the
document shows the real read-back and the real rosbridge request: it cannot
drift from the file, and a test fails when it is out of date.
"""

from __future__ import annotations

import json
import re

from voicebridge.catalogue import Catalogue, Command, Parameter
from voicebridge.planner import Planner
from voicebridge.robot import Outcome


def _anchor(title: str) -> str:
    return re.sub(r"[^a-z0-9 _-]", "", title.lower()).replace(" ", "-")


def _values(parameter: Parameter) -> str:
    if parameter.choices:
        return ", ".join(f"`{choice}`" for choice in parameter.choices)
    if parameter.minimum is not None or parameter.maximum is not None:
        low = "" if parameter.minimum is None else f"{parameter.minimum:g}"
        high = "" if parameter.maximum is None else f"{parameter.maximum:g}"
        return f"{low} to {high}"
    return "any"


def _flags(command: Command) -> str:
    if command.is_query:
        return "no, it changes nothing"
    return "yes" if command.confirm else "no, it runs at once"


async def generate(catalogue: Catalogue, source: str) -> str:
    planner = Planner(catalogue, robot=None)
    settings = catalogue.confirmation
    title = f"{catalogue.name} Voice Commands"
    lines = [
        f"# {title}",
        "",
        f"<!-- Generated from {source} by `voicebridge docs`: edit the robot file, not this document. -->",
        "",
        "## Table of Contents <!-- omit in toc -->",
        "",
        "- [Introduction](#introduction)",
        "- [Confirming and Stopping](#confirming-and-stopping)",
        "- [The Commands at a Glance](#the-commands-at-a-glance)",
        "- [The Commands](#the-commands)",
    ]
    lines += [f"  - [{name}](#{_anchor(name)})" for name in catalogue.commands]
    lines += [
        "",
        "## Introduction",
        "",
        f"This document lists every command we can give {catalogue.name} by voice, and what each one becomes. "
        f"It is generated from the robot file `{source}`: every example below is prepared by the bridge itself, "
        "so the sentence read back and the request sent to rosbridge are the real ones.",
        "",
        "We do not have to say the examples word for word: the LLM understands other ways of saying the same "
        "thing, and the examples teach it the common ones. Whatever it understood, the bridge reads the "
        "command back before anything moves.",
        "",
        "## Confirming and Stopping",
        "",
        "A command that changes the robot is read back, and runs only once we confirm it:",
        "",
        f"- The read-back ends with \"{settings.prompt}\" and waits {settings.timeout_s:g} seconds for the answer.",
        f"- **Confirm** with an answer made only of: {', '.join(settings.confirm)}.",
        f"- **Cancel** with: {', '.join(settings.decline)}. Anything else we say also cancels the command, "
        "and is then heard as a new request.",
    ]
    if settings.fillers:
        lines.append(f"- These words may come with an answer and change nothing: {', '.join(settings.fillers)}.")
    if settings.stop_command:
        lines += [
            f"- **Stop** with any of: {', '.join(settings.stop)}, anywhere in what we say. The bridge runs "
            f"`{settings.stop_command}` at once, without the LLM and without a confirmation. A sentence that is "
            "more than a stop, e.g. \"stop the live view\", stops the robot and is then heard as a request.",
        ]
    lines += [
        "",
        "> [!WARNING]",
        "> The voice stop takes about a second, the time to hear the end of the sentence and transcribe it. "
        "It does not replace the stop of the gamepad or of the page.",
        "",
        "## The Commands at a Glance",
        "",
        "| Command | What it does | Confirmed |",
        "|---|---|---|",
    ]
    for name, command in catalogue.commands.items():
        lines.append(f"| [`{name}`](#{_anchor(name)}) | {command.description} | {_flags(command)} |")
    lines += ["", "## The Commands", ""]
    for name, command in catalogue.commands.items():
        lines += await _command_section(planner, catalogue, name, command)
    return "\n".join(lines).rstrip() + "\n"


async def _command_section(planner: Planner, catalogue: Catalogue, name: str, command: Command) -> list[str]:
    lines = [f"### {name}", "", command.description, ""]
    if command.parameters:
        lines += ["| Parameter | Values | Description |", "|---|---|---|"]
        for parameter in command.parameters:
            optional = " Optional." if parameter.optional else ""
            lines.append(f"| `{parameter.name}` | {_values(parameter)} | {parameter.description}{optional} |")
        lines.append("")
    if command.reads:
        reads = ", ".join(f"`{read}` with `{use.call}`" for read, use in command.reads.items())
        lines += [f"It first reads the robot: {reads}.", ""]
    for example in command.examples:
        prepared = await planner.prepare(name, example.expect, reads=example.reads)
        arguments = ", ".join(f"{key}: {value!r}" for key, value in prepared.arguments.items() if value is not None)
        lines += [f"**\"{example.phrase}\"** becomes `{name}({arguments})`.", ""]
        if command.is_query:
            lines += [f"- It answers: \"{prepared.sentence}\"", ""]
            continue
        if command.confirm:
            lines.append(f"- It reads back: \"{prepared.sentence} {catalogue.confirmation.prompt}\"")
        else:
            lines.append(f"- It says: \"{prepared.sentence}\"")
        lines += ["- It sends to rosbridge:", "", "  ```json"]
        lines += ["  " + line for line in json.dumps(prepared.request.message(), indent=2).splitlines()]
        lines += ["  ```", ""]
        lines.append(f"- When it is done: \"{planner.outcome_sentence(prepared, Outcome(True))}\"")
        lines.append("")
    return lines
