# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT

import pytest

from voicebridge.safety.phrases import Meaning, PhraseMatcher, ends_with, same_sentence, words


@pytest.fixture
def matcher(stepit_macro):
    return PhraseMatcher(stepit_macro.confirmation)


@pytest.mark.parametrize("said", [
    "yes", "Yes.", "YES!", "yes please", "OK", "okay", "ok go ahead", "Go with it.", "confirm", "do it",
    "yes, go ahead", "that's right", "That’s correct.", "um yes", "Yes, please.",
])
def test_confirm(matcher, said):
    assert matcher.classify(said) is Meaning.CONFIRM


@pytest.mark.parametrize("said", ["no", "No.", "nope", "cancel", "don't", "never mind", "no thanks", "wait"])
def test_decline(matcher, said):
    assert matcher.classify(said) is Meaning.DECLINE


@pytest.mark.parametrize("said", [
    # Not clearly yes: a pending command is dropped, never run.
    "yes but 20 degrees", "yes no", "rotate 10 degrees left", "go left", "maybe", "I think so",
    "right", "", "   ", "yes and then take a picture",
])
def test_anything_else_is_other(matcher, said):
    assert matcher.classify(said) is Meaning.OTHER


@pytest.mark.parametrize("said", ["stop", "Stop!", "STOP STOP", "halt", "abort", "freeze", "stop please"])
def test_stop_alone(matcher, said):
    assert matcher.classify(said) is Meaning.STOP
    assert matcher.mentions_stop(said)


@pytest.mark.parametrize("said", ["ok stop", "stop the live view", "please stop it now", "no, stop", "yes stop"])
def test_a_stop_anywhere_is_heard(matcher, said):
    assert matcher.mentions_stop(said)
    assert matcher.classify(said) is not Meaning.CONFIRM


def test_a_word_containing_stop_is_not_a_stop(matcher):
    assert not matcher.mentions_stop("the stopwatch")
    assert not matcher.mentions_stop("take a photo")


def test_words():
    assert words("Yes, go ahead!") == ["yes", "go", "ahead"]
    assert words("That’s right") == ["that's", "right"]


def test_same_sentence_ignores_case_and_punctuation():
    assert same_sentence("rotating the stage 10 degrees counter-clockwise, say yes to confirm",
                         "Rotating the stage 10 degrees counter-clockwise. Say yes to confirm.")
    assert not same_sentence("Rotating the stage 10 degrees clockwise. Say yes to confirm.",
                             "Rotating the stage 10 degrees counter-clockwise. Say yes to confirm.")
    assert not same_sentence("Rotating the stage 100 degrees.", "Rotating the stage 10 degrees.")


@pytest.mark.parametrize("said", ["Wake up, robot.", "wake up robot", "WAKE UP ROBOT!", "wake up robots",
                                  # The speech server's turn grows while the voice sleeps.
                                  "Can you hear me? Hello? Wake up, robot.", "Hello. Wake up. Robot."])
def test_the_wake_phrase_at_the_end_wakes(said):
    assert ends_with(said, ["Wake up, robot", "wake up robots"])


@pytest.mark.parametrize("said", ["wake up robot please", "please wake up robot", "wake up robot and turn left",
                                  "Wake up, robot. Turn left.", "wake up", "robot", "Hello. Wake up.", ""])
def test_the_wake_phrase_with_anything_else_does_not(said):
    assert not ends_with(said, ["Wake up, robot", "wake up robots"])
