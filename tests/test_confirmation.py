# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT

from conftest import FakeClock

from voicebridge.safety.confirmation import Confirmation, Phase, Verdict
from voicebridge.safety.phrases import Meaning

SENTENCE = "Turning 10 degrees left. Say yes to confirm."


def armed(clock: FakeClock) -> Confirmation[str]:
    confirmation: Confirmation[str] = Confirmation(timeout_s=10, clock=clock)
    confirmation.propose("turn", SENTENCE)
    assert confirmation.read_back(SENTENCE)
    return confirmation


def test_a_command_runs_only_after_its_read_back_and_a_yes():
    clock = FakeClock()
    confirmation: Confirmation[str] = Confirmation(timeout_s=10, clock=clock)
    assert confirmation.phase is Phase.IDLE
    confirmation.propose("turn", SENTENCE)
    assert confirmation.phase is Phase.READING_BACK
    assert confirmation.read_back("turning 10 degrees left, say yes to confirm")
    assert confirmation.phase is Phase.ARMED
    answer = confirmation.answer(Meaning.CONFIRM)
    assert (answer.verdict, answer.command) == (Verdict.RUN, "turn")
    assert confirmation.phase is Phase.IDLE


def test_a_yes_before_the_read_back_ends_drops_the_command():
    confirmation: Confirmation[str] = Confirmation(timeout_s=10, clock=FakeClock())
    confirmation.propose("turn", SENTENCE)
    assert confirmation.answer(Meaning.CONFIRM).verdict is Verdict.DROPPED
    assert confirmation.phase is Phase.IDLE


def test_a_read_back_that_says_something_else_drops_the_command():
    confirmation: Confirmation[str] = Confirmation(timeout_s=10, clock=FakeClock())
    confirmation.propose("turn", SENTENCE)
    assert not confirmation.read_back("Turning 10 degrees right. Say yes to confirm.")
    assert confirmation.phase is Phase.IDLE
    assert confirmation.answer(Meaning.CONFIRM).verdict is Verdict.NOTHING_PENDING


def test_a_late_yes_runs_nothing():
    clock = FakeClock()
    confirmation = armed(clock)
    clock.now += 10.5
    assert confirmation.answer(Meaning.CONFIRM).verdict is Verdict.EXPIRED


def test_a_yes_just_in_time_runs():
    clock = FakeClock()
    confirmation = armed(clock)
    clock.now += 9.9
    assert confirmation.answer(Meaning.CONFIRM).verdict is Verdict.RUN


def test_no_stop_and_anything_else_drop_the_command():
    for meaning, verdict in ((Meaning.DECLINE, Verdict.DECLINED), (Meaning.STOP, Verdict.DECLINED),
                             (Meaning.OTHER, Verdict.DROPPED)):
        confirmation = armed(FakeClock())
        assert confirmation.answer(meaning).verdict is verdict
        assert confirmation.phase is Phase.IDLE


def test_a_command_is_confirmed_once():
    confirmation = armed(FakeClock())
    assert confirmation.answer(Meaning.CONFIRM).verdict is Verdict.RUN
    assert confirmation.answer(Meaning.CONFIRM).verdict is Verdict.NOTHING_PENDING


def test_a_new_command_replaces_the_pending_one():
    confirmation = armed(FakeClock())
    confirmation.propose("other", "Other. Say yes to confirm.")
    assert confirmation.phase is Phase.READING_BACK
    assert confirmation.command == "other"
    assert not confirmation.read_back(SENTENCE)
