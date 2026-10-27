# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""A sentence of the bridge, and the tags that carry it to the LLM proxy.

The bridge speaks by asking the speech server for a reply whose instructions
hold the sentence between two tags; the speech server asks its LLM, which is
the bridge's proxy, and the proxy answers with the sentence itself. This is
the one contract between ``conversation`` and ``llmproxy``: the session writes
the tags with ``exact_speech``, the proxy finds them with ``scripted_sentence``.
"""

from __future__ import annotations

# The tags around a sentence of the bridge in the instructions of a response.
SAY_OPEN = "<voicebridge-say>"
SAY_CLOSE = "</voicebridge-say>"


def exact_speech(sentence: str) -> str:
    """The instructions that make the voice say a sentence exactly as written.

    The bridge's LLM proxy finds the sentence between the tags and answers with
    it, without asking the model. The words before the tags are for a model
    reached without the proxy; the read-back check catches it if it strays.
    """
    return ("Say exactly the text between the tags, word for word, with nothing before or after it, "
            f"and do not call any tool: {SAY_OPEN}{sentence}{SAY_CLOSE}")


def scripted_sentence(text: str) -> str | None:
    """The sentence ``exact_speech`` put in a text, e.g. a system message built around it."""
    start = text.find(SAY_OPEN)
    if start < 0:
        return None
    end = text.find(SAY_CLOSE, start)
    if end < 0:
        return None
    return text[start + len(SAY_OPEN):end]
