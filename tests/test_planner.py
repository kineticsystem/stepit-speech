# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT

import pytest
from conftest import FakeRobot

from voicebridge.planner import Planner, Rejected
from voicebridge.robot import Outcome


async def test_prepare_renders_the_sentence_and_the_request_together(arm):
    prepared = await Planner(arm, FakeRobot()).prepare("turn_joint", {"degrees": 10, "direction": "right"})
    assert prepared.sentence == "Turning 10 degrees right."
    assert prepared.request.target == "/arm/move"
    assert prepared.request.payload == {"joint": "base", "angle": -10.0}


async def test_wrong_arguments_are_rejected(arm):
    with pytest.raises(Rejected, match="at most 90"):
        await Planner(arm, FakeRobot()).prepare("turn_joint", {"degrees": 91, "direction": "right"})
    with pytest.raises(Rejected, match="no command"):
        await Planner(arm, FakeRobot()).prepare("fly", {})


async def test_reads_go_to_the_robot(arm):
    robot = FakeRobot()
    robot.outcomes["/arm/state"] = Outcome(True, "", {"angle": 1.0})
    prepared = await Planner(arm, robot).prepare("where", {})
    assert prepared.sentence == "The joint is at 1 degree."
    assert prepared.request is None
    assert robot.targets == ["/arm/state"]


async def test_a_failed_read_rejects_the_command(arm):
    robot = FakeRobot()
    robot.outcomes["/arm/state"] = Outcome(False, "no message on /arm/state in 3 s")
    with pytest.raises(Rejected, match="could not read the state"):
        await Planner(arm, robot).prepare("where", {})


async def test_given_reads_replace_the_robot(arm):
    prepared = await Planner(arm, None).prepare("where", {}, reads={"state": {"angle": 5}})
    assert prepared.sentence == "The joint is at 5 degrees."


async def test_a_read_of_another_shape_is_rejected_not_crashed(arm):
    with pytest.raises(Rejected, match="robot file has a mistake"):
        await Planner(arm, None).prepare("where", {}, reads={"state": {"speed": 5}})


async def test_outcome_sentences(arm):
    planner = Planner(arm, None)
    prepared = await planner.prepare("turn_joint", {"degrees": 10, "direction": "right"})
    assert planner.outcome_sentence(prepared, Outcome(True)) == "Turned."
    assert planner.outcome_sentence(prepared, Outcome(False, "blocked")) == "That did not work: blocked."
    assert planner.outcome_sentence(prepared, Outcome(False)) == "That did not work."
