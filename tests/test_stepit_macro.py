# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The robot file of StepIt Macro: every example prepares, and the requests are those of the rig."""

import json

import pytest
from conftest import STEPIT_MACRO

from voicebridge.robot.planner import Planner, Rejected
from voicebridge.robotfile.loader import load
from voicebridge.tools.docs import generate

EXAMPLES = [(name, example) for name, command in load(STEPIT_MACRO).commands.items()
            for example in command.examples]


@pytest.mark.parametrize("name, example", EXAMPLES, ids=[example.phrase for _, example in EXAMPLES])
async def test_every_example_prepares(stepit_macro, name, example):
    prepared = await Planner(stepit_macro, None).prepare(name, example.expect, reads=example.reads)
    assert prepared.sentence
    if prepared.request is not None:
        json.dumps(prepared.request.message())


def test_every_command_has_an_example(stepit_macro):
    assert [name for name, command in stepit_macro.commands.items() if not command.examples] == []


async def objective(stepit_macro, name, arguments, reads=None):
    prepared = await Planner(stepit_macro, None).prepare(name, arguments, reads=reads)
    assert prepared.request.target == "/commander/execute_objective"
    assert prepared.request.type == "btcpp_ros2_interfaces/action/ExecuteTree"
    return prepared.sentence, prepared.request.payload


async def test_left_is_counter_clockwise_and_negative(stepit_macro):
    sentence, goal = await objective(stepit_macro, "rotate_stage", {"degrees": 10, "direction": "counter-clockwise"})
    assert sentence == "Rotating 10 degrees counter-clockwise."
    assert goal == {"target_tree": "RotateStageBy", "payload": "{deg: -10.0}"}
    _, goal = await objective(stepit_macro, "rotate_stage", {"degrees": 10, "direction": "clockwise"})
    assert goal["payload"] == "{deg: 10.0}"


async def test_closer_is_toward_the_subject_and_negative(stepit_macro):
    sentence, goal = await objective(stepit_macro, "move_camera",
                                     {"distance": 1, "unit": "millimetres", "direction": "closer"})
    assert sentence == "Moving closer 1 millimetre."
    assert goal == {"target_tree": "MoveRailBy", "payload": "{mm: -1.0}"}


@pytest.mark.parametrize(("distance", "said", "mm"), [
    (1, "1 centimetre", "10.0"),
    (2.5, "2.5 centimetres", "25.0"),
    (0.3, "0.3 centimetres", "3.0"),
    (5, "5 centimetres", "50.0"),
])
async def test_centimetres_are_read_back_as_said_and_run_in_millimetres(stepit_macro, distance, said, mm):
    sentence, goal = await objective(stepit_macro, "move_camera",
                                     {"distance": distance, "unit": "centimetres", "direction": "farther"})
    assert sentence == f"Moving farther {said}."
    assert goal == {"target_tree": "MoveRailBy", "payload": f"{{mm: {mm}}}"}


async def test_the_limit_holds_after_the_conversion(stepit_macro):
    with pytest.raises(Rejected, match="At most 50 millimetres"):
        await Planner(stepit_macro, None).prepare(
            "move_camera", {"distance": 6, "unit": "centimetres", "direction": "farther"})


async def test_a_test_shot(stepit_macro):
    sentence, goal = await objective(stepit_macro, "take_test_shot", {})
    assert sentence == "Taking a test shot."
    assert goal == {"target_tree": "TakeShot", "payload": ""}


async def test_manual_drive_off_hands_the_rig_to_the_trajectory_controller(stepit_macro):
    _, goal = await objective(stepit_macro, "manual_drive", {"state": "off"})
    assert goal == {"target_tree": "ActivateController", "payload": "{controllers: joint_trajectory_controller}"}


PLAN = {"state.shots": [10.0], "state.angles": [35.0], "state.turn": [17.0], "state.near": [-1.0], "state.far": [2.0]}


async def test_a_full_stack_reads_the_plan_of_the_rig(stepit_macro):
    sentence, goal = await objective(stepit_macro, "start_full_stack", {}, reads={"plan": PLAN})
    assert sentence == "Stacking 10 shots at 35 angles, plus or minus 17 degrees: 350 pictures."
    assert goal == {"target_tree": "FocusStack",
                    "payload": "{shots: 10, stage_from: -17.0, stage_to: 17.0, angles: 35}"}


async def test_one_stack_is_where_the_stage_stands_whatever_the_plan(stepit_macro):
    # FocusStack's angles are from where the stage stands: one angle at 0 does not turn it.
    sentence, goal = await objective(stepit_macro, "start_stack", {}, reads={"plan": PLAN})
    assert sentence == "Stacking 10 shots at this angle."
    assert goal == {"target_tree": "FocusStack",
                    "payload": "{shots: 10, stage_from: 0.0, stage_to: 0.0, angles: 1}"}


@pytest.mark.parametrize("command", ["start_stack", "start_full_stack"])
@pytest.mark.parametrize("missing, complaint", [("state.near", "near end"), ("state.far", "far end")])
async def test_a_focus_stack_needs_both_marks(stepit_macro, command, missing, complaint):
    plan = {"state.shots": [10.0], "state.angles": [35.0], "state.turn": [17.0], "state.near": [-1.0],
            "state.far": [2.0], missing: []}
    with pytest.raises(Rejected, match=complaint):
        await Planner(stepit_macro, None).prepare(command, {}, reads={"plan": plan})


async def test_set_stack_needs_something_to_change(stepit_macro):
    with pytest.raises(Rejected, match="Say what to change"):
        await Planner(stepit_macro, None).prepare("set_stack", {})


async def test_the_lights_keep_the_other_outputs(stepit_macro):
    planner = Planner(stepit_macro, None)
    on = await planner.prepare("lights", {"state": "on"}, reads={"outputs": {"outputs": 0b1100_0000}})
    assert on.request.payload == {"outputs": 0b1100_0011}
    off = await planner.prepare("lights", {"state": "off"}, reads={"outputs": {"outputs": 0b1100_0011}})
    assert off.request.payload == {"outputs": 0b1100_0000}


def test_stop_needs_no_confirmation(stepit_macro):
    assert stepit_macro.confirmation.stop_command == "stop"
    assert not stepit_macro.commands["stop"].confirm


def test_power_off_is_not_a_voice_command(stepit_macro):
    targets = json.dumps([command.run.arguments for command in stepit_macro.commands.values() if command.run])
    assert "power_off" not in targets


async def test_commands_md_is_up_to_date(stepit_macro):
    path = STEPIT_MACRO.parent / "commands.md"
    expected = await generate(stepit_macro, "robots/stepit-macro/robot.yaml")
    assert path.read_text(encoding="utf-8") == expected, (
        "commands.md is out of date: run "
        "voicebridge docs robots/stepit-macro/robot.yaml -o robots/stepit-macro/commands.md")
