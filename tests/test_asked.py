# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""Whether the user's words ask for a command that runs without confirmation."""

from __future__ import annotations

import pytest

from voicebridge.safety.asked import asked_for, command_words


def ask(catalogue, heard, name):
    return asked_for(heard, catalogue.commands[name], catalogue.confirmation)


@pytest.mark.parametrize(("heard", "name"), [
    ("stop everything", "stop"),
    ("halt the robot", "stop"),
    ("freeze", "stop"),
    ("what is the rig doing", "report_status"),
    ("what's the status?", "report_status"),
    ("is anything running", "report_status"),
    ("how far is the stack", "report_progress"),
    ("what's the plan of the stack", "describe_stack"),
])
def test_the_words_of_a_command_ask_for_it(stepit_macro, heard, name):
    assert ask(stepit_macro, heard, name)


@pytest.mark.parametrize(("heard", "name"), [
    # Said to correct a read-back, or a turn cut short: none of these asks for a command.
    ("Three centimeter.", "stop"),
    ("Three centimeter.", "report_status"),
    ("Can you", "stop"),
    ("move it uh one", "report_progress"),
    ("Move the camera closer.", "stop"),
    ("Move the camera closer.", "report_status"),
    ("", "stop"),
    (None, "report_status"),
])
def test_a_fragment_asks_for_no_command(stepit_macro, heard, name):
    assert not ask(stepit_macro, heard, name)


def test_common_words_do_not_count(stepit_macro):
    words = command_words(stepit_macro.commands["report_status"], stepit_macro.confirmation)
    assert not words & {"what", "is", "the"}


def test_a_plural_is_the_same_word(stepit_macro):
    assert ask(stepit_macro, "what are the stacks like", "describe_stack")


def test_every_example_of_a_command_without_confirmation_asks_for_it(stepit_macro):
    for command in stepit_macro.commands.values():
        if not command.confirm:
            for example in command.examples:
                assert ask(stepit_macro, example.phrase, command.name), (command.name, example.phrase)
