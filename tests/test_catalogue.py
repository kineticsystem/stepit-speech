# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT

import pytest

from voicebridge.robotfile.loader import RobotFileError, parse, read_yaml
from voicebridge.robotfile.model import SLEEP_COMMAND, ArgumentError

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


# ── The sleep mode ─────────────────────────────────────────────────────────────

SLEEP = """
sleep:
  wake: ["Wake up, robot", wake up robots]
  examples: [go to sleep, take a nap]
"""


def test_without_a_sleep_section_there_is_no_sleep_mode():
    catalogue = robot()
    assert catalogue.sleep is None
    assert SLEEP_COMMAND not in catalogue.commands


def test_the_sleep_section_makes_a_confirmed_command_that_runs_nothing():
    catalogue = robot(MINIMAL + SLEEP)
    command = catalogue.commands[SLEEP_COMMAND]
    assert command.confirm is True
    assert command.run is None and not command.reads and not command.parameters
    assert [example.phrase for example in command.examples] == ["go to sleep", "take a nap"]
    assert command.say == "Putting the voice to sleep."
    sleep = catalogue.sleep
    assert sleep.wake == ("Wake up, robot", "wake up robots")
    assert sleep.asleep == "Going to sleep. To wake me, say: Wake up, robot."
    assert sleep.awake == "I'm listening."
    assert sleep.example == "go to sleep"
    assert SLEEP_COMMAND in {tool["name"] for tool in catalogue.tool_specs()}


def test_the_sentences_of_the_sleep_mode_can_be_written():
    text = MINIMAL + SLEEP + "  say: Sleeping.\n  asleep: Good night.\n  awake: Hello again.\n"
    catalogue = robot(text)
    assert catalogue.commands[SLEEP_COMMAND].say == "Sleeping."
    assert (catalogue.sleep.asleep, catalogue.sleep.awake) == ("Good night.", "Hello again.")


@pytest.mark.parametrize(("old", "new", "complaint"), [
    ('  wake: ["Wake up, robot", wake up robots]\n', "", "sleep.wake: list the phrase"),
    ("  examples: [go to sleep, take a nap]\n", "", "sleep.examples: list what we say"),
    ("  examples: [go to sleep, take a nap]\n", "  examples: [go to sleep]\n  snooze: 5\n", "snooze"),
])
def test_a_wrong_sleep_section_says_where(old, new, complaint):
    with pytest.raises(RobotFileError, match=complaint):
        robot(MINIMAL + SLEEP.replace(old, new))


def test_no_sleep_phrase_may_hold_a_stop_word():
    # "Stop listening" would stop the robot before the LLM heard the rest.
    halt = "  halt:\n    description: Halts.\n    say: Halting.\n    confirm: false\n    run:\n      move: {}\n"
    stops = MINIMAL.replace("  confirm: [yes]", "  confirm: [yes]\n  stop: [stop]\n  stop_command: halt") + halt
    with pytest.raises(RobotFileError, match=r"sleep.examples: 'stop listening' holds the stop word 'stop'"):
        robot(stops + SLEEP.replace("take a nap", "stop listening"))
    with pytest.raises(RobotFileError, match=r"sleep.wake: 'wake up and stop'"):
        robot(stops + SLEEP.replace("wake up robots", "wake up and stop"))
    # "nonstop" holds no stop word.
    assert robot(stops + SLEEP.replace("take a nap", "sleep nonstop")).sleep is not None


def test_no_command_may_take_the_sleep_command_name():
    text = MINIMAL + """  sleep:
    description: Sleeps.
    say: Sleeping.
    run:
      move: {}
""" + SLEEP
    with pytest.raises(RobotFileError, match="commands.sleep: the name is the sleep section's command"):
        robot(text)
