# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT

import pytest

from voicebridge.robotfile.loader import RobotFileError, parse, read_yaml
from voicebridge.robotfile.model import ArgumentError

MINIMAL = """
confirmation:
  confirm: [yes]
calls:
  move:
    action: /move
    type: pkg/action/Move
commands:
  turn:
    description: Turns.
    parameters:
      degrees: {type: number, min: 1, max: 90}
      side: [left, right]
      speed: {type: integer, optional: true}
    say: Turning {{ degrees }} {{ side }}.
    run:
      move: {angle: "{{ degrees }}"}
"""


def robot(text: str = MINIMAL):
    return parse(read_yaml(text))


def broken(old: str, new: str) -> str:
    assert old in MINIMAL
    return MINIMAL.replace(old, new)


def test_a_minimal_robot_file():
    catalogue = robot()
    command = catalogue.commands["turn"]
    assert [p.name for p in command.parameters] == ["degrees", "side", "speed"]
    assert command.confirm is True
    assert set(catalogue.calls) >= {"move", "get_parameters", "set_parameters", "trigger", "read_latched_topic"}


def test_on_off_yes_no_stay_words():
    assert read_yaml("[yes, no, on, off, true, false]") == ["yes", "no", "on", "off", True, False]


def test_the_tool_the_llm_sees():
    spec = robot().commands["turn"].tool_spec()
    assert spec["name"] == "turn"
    assert spec["parameters"]["required"] == ["degrees", "side"]
    assert spec["parameters"]["properties"]["side"] == {"type": "string", "enum": ["left", "right"]}
    assert spec["parameters"]["properties"]["degrees"] == {"type": "number", "minimum": 1.0, "maximum": 90.0}
    assert spec["parameters"]["additionalProperties"] is False


def test_arguments_are_checked_and_typed():
    command = robot().commands["turn"]
    assert command.check_arguments({"degrees": "10", "side": "LEFT"}) == {"degrees": 10.0, "side": "left",
                                                                          "speed": None}
    assert command.check_arguments({"degrees": 5, "side": "right", "speed": 2.0})["speed"] == 2


@pytest.mark.parametrize("arguments, complaint", [
    ({"degrees": 100, "side": "left"}, "at most 90"),
    ({"degrees": 0, "side": "left"}, "at least 1"),
    ({"degrees": "ten", "side": "left"}, "must be a number"),
    ({"degrees": True, "side": "left"}, "must be a number"),
    ({"degrees": float("nan"), "side": "left"}, "must be a number"),
    ({"degrees": 10, "side": "up"}, "one of left, right"),
    ({"side": "left"}, "needs degrees"),
    ({"degrees": 10, "side": "left", "speed": 1.5}, "whole number"),
    ({"degrees": 10, "side": "left", "colour": "red"}, "no argument colour"),
    ([1, 2], "must be an object"),
])
def test_wrong_arguments_are_refused_with_a_sentence(arguments, complaint):
    with pytest.raises(ArgumentError, match=complaint):
        robot().commands["turn"].check_arguments(arguments)


@pytest.mark.parametrize("old, new, complaint", [
    ("    say: Turning", "    sya: Turning", "unknown sya"),
    ("      move: {angle", "      mvoe: {angle", "no call named 'mvoe'"),
    ("{type: number, min: 1, max: 90}", "{type: nubmer}", "type must be one of"),
    ("{type: number, min: 1, max: 90}", "{type: number, description: far, in degrees}",
     "a comma inside { } starts a new key"),
    ("Turning {{ degrees }}", "Turning {{ degrees + }}", "commands.turn"),
    ("    action: /move\n", "", "needs exactly one of"),
    ("  confirm: [yes]", "  confirm: []", "list the words that confirm"),
    ("  turn:\n", "  turn left:\n", "letters, digits"),
])
def test_mistakes_fail_at_load_and_say_where(old, new, complaint):
    with pytest.raises(RobotFileError, match=complaint):
        robot(broken(old, new))


def test_a_query_must_say_it_needs_no_confirmation():
    text = MINIMAL + """
  where:
    description: Where.
    say: Here.
"""
    with pytest.raises(RobotFileError, match="query: set confirm: false"):
        robot(text)
    assert robot(text.replace("    say: Here.", "    say: Here.\n    confirm: false")).commands["where"].is_query


def test_an_example_must_fit_its_parameters():
    text = MINIMAL + """    examples:
      - turn left 100: {degrees: 100, side: left}
"""
    with pytest.raises(RobotFileError, match="at most 90"):
        robot(text)


def test_the_stop_words_need_a_stop_command():
    with pytest.raises(RobotFileError, match="stop_command"):
        robot(MINIMAL.replace("  confirm: [yes]", "  confirm: [yes]\n  stop: [stop]"))
    with pytest.raises(RobotFileError, match="no command named"):
        robot(MINIMAL.replace("  confirm: [yes]", "  confirm: [yes]\n  stop: [stop]\n  stop_command: halt"))
