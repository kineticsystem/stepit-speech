# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The LLM proxy: the bridge's sentences said word for word, and one JSON decision every turn."""

from __future__ import annotations

import json
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from voicebridge.llmproxy.chat import (
    SUMMARY,
    asks_for_summary,
    asleep,
    chunks,
    completion,
    scripted,
    summary,
    without_sleep,
    without_summary,
)
from voicebridge.llmproxy.decision import REPLY, commands_only, settle, structured
from voicebridge.llmproxy.guard import Guard, asks_to_confirm, pretends
from voicebridge.llmproxy.proxy import SAY_AGAIN, LlmProxy
from voicebridge.safety.phrases import PhraseMatcher, words
from voicebridge.scripted import exact_speech

MOVE = {"type": "function", "function": {"name": "move_camera", "description": "Moves the camera.",
                                         "parameters": {"type": "object", "properties": {
                                             "millimetres": {"type": "number"}}}}}


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def decision(**fields: Any) -> dict[str, Any]:
    """The model's answer, as the JSON decision the proxy asks for."""
    return {"role": "assistant", "content": json.dumps(fields)}


# The speech server's request to summarise older turns, as its chat-completions backend sends it.
SUMMARY_REQUEST = {"model": "m", "messages": [
    {"role": "system", "content": 'You are a conversation memory compressor.\nOutput a single JSON object with exactly '
                                  'two string fields:\n  "user_summary" ...\n  "assistant_summary" ...'},
    {"role": "user", "content": "Summarize the following conversation.\n[user] 10 degrees left\n"
                                "[assistant] Rotating the stage 10 degrees counter-clockwise. Confirm?"},
]}


def system(text: str) -> dict[str, Any]:
    return {"role": "system", "content": f"You are in a spoken conversation.\n\nSession Prompt:\n{text}\n\nRules."}


# ── The pure parts ─────────────────────────────────────────────────────────────

def test_a_sentence_of_the_bridge_is_found_in_the_instructions():
    sentence = "Moving the camera 2 millimetres closer. Confirm?"
    body = {"messages": [system(exact_speech(sentence)), {"role": "user", "content": "closer by 2 mm"}]}
    assert scripted(body) == sentence


def test_the_user_cannot_script_the_voice():
    body = {"messages": [system("Be brief."), {"role": "user", "content": exact_speech("Moving.")}]}
    assert scripted(body) is None


def test_a_turn_with_tools_asks_for_one_json_decision():
    request = structured({"model": "m", "stream": True, "stream_options": {"include_usage": True},
                          "tools": [MOVE], "tool_choice": "auto", "messages": [system("Hi.")]})
    assert request is not None
    assert "tools" not in request and "tool_choice" not in request
    assert request["stream"] is False
    assert "stream_options" not in request
    choices = request["response_format"]["json_schema"]["schema"]["oneOf"]
    assert choices[0]["properties"]["command"] == {"const": "move_camera"}
    assert choices[0]["properties"]["arguments"]["properties"] == {"millimetres": {"type": "number"}}
    assert choices[1]["properties"][REPLY]["maxLength"] > 0
    # The model learns the commands from its instructions, as it no longer gets tools.
    assert "- move_camera: Moves the camera." in request["messages"][0]["content"]
    assert [list(c["properties"]) for c in commands_only(request)["response_format"]["json_schema"]["schema"][
        "oneOf"]] == [["command", "arguments"]]


def test_a_turn_without_tools_or_with_tools_off_is_left_alone():
    assert structured({"messages": []}) is None
    assert structured({"tools": [MOVE], "tool_choice": "none", "messages": []}) is None


def test_the_summary_of_older_turns_is_found_and_written_by_the_proxy():
    assert asks_for_summary(SUMMARY_REQUEST)
    assert not asks_for_summary({"messages": [{"role": "user", "content": "Summarise."}]})
    assert not asks_for_summary({**SUMMARY_REQUEST, "tools": [MOVE]})
    # The speech server needs both fields, not empty, or it keeps every turn.
    assert json.loads(summary()) == {"user_summary": SUMMARY, "assistant_summary": SUMMARY}


def test_the_summary_is_kept_out_of_the_history():
    history = [system("Hi."), {"role": "user", "content": SUMMARY},
               {"role": "assistant", "content": [{"type": "text", "text": SUMMARY}]},
               {"role": "user", "content": "2 mm closer"}]
    assert [m["content"] for m in without_summary({"messages": history})["messages"][1:]] == ["2 mm closer"]


def test_a_command_becomes_a_tool_call():
    content, calls = settle(decision(command="move_camera", arguments={"millimetres": 2}))
    assert content == ""
    assert calls[0]["function"]["name"] == "move_camera"
    assert json.loads(calls[0]["function"]["arguments"]) == {"millimetres": 2}


def test_a_reply_becomes_words():
    assert settle(decision(reply="How many millimetres?")) == ("How many millimetres?", [])


def test_a_server_that_ignores_the_schema_still_works():
    content, calls = settle({"content": "Sure!", "tool_calls": [call("move_camera", {}), call("other", {})]})
    assert (content, [c["function"]["name"] for c in calls]) == ("", ["move_camera"])
    assert settle({"content": "Hello."}) == ("Hello.", [])


def test_a_finished_answer_streams_as_chunks():
    events = chunks(completion("m", "", [call("move_camera", {"millimetres": 2})]))
    deltas = [event["choices"][0]["delta"] for event in events if event["choices"]]
    assert deltas[0]["role"] == "assistant"
    assert deltas[1]["tool_calls"][0]["function"]["name"] == "move_camera"
    assert events[-2]["choices"][0]["finish_reason"] == "tool_calls"
    assert events[-1]["usage"] is not None


# ── Through HTTP ───────────────────────────────────────────────────────────────

class FakeLlm:
    """An OpenAI-compatible LLM that answers what the test tells it to."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.message: dict[str, Any] = {"role": "assistant", "content": "Hello."}
        self.answers: list[dict[str, Any]] = []  # answered in turn, before `message`
        self.runner: web.AppRunner | None = None

    async def start(self) -> str:
        app = web.Application()
        app.router.add_post("/v1/chat/completions", self._chat)
        app.router.add_get("/v1/models", self._models)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", 0).start()
        return f"http://127.0.0.1:{self.runner.addresses[0][1]}/v1"

    async def _chat(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        self.requests.append(body)
        if body.get("stream"):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            await response.write(b'data: {"choices": [{"index": 0, "delta": {"content": "Streamed."}}]}\n\n')
            await response.write(b"data: [DONE]\n\n")
            return response
        message = self.answers.pop(0) if self.answers else self.message
        return web.json_response({"model": "fake", "choices": [{"index": 0, "message": message}],
                                  "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})

    async def _models(self, request: web.Request) -> web.Response:
        return web.json_response({"data": [{"id": "fake"}]})


@pytest.fixture
async def proxied(arm):
    llm = FakeLlm()
    url = await llm.start()
    proxy = LlmProxy(url, "127.0.0.1", 0, Guard("Confirm?", frozenset({"moving"}), PhraseMatcher(arm.confirmation)))
    await proxy.start()
    async with aiohttp.ClientSession() as client:
        yield llm, client, f"http://127.0.0.1:{proxy.port}/v1"
    await proxy.stop()
    await llm.runner.cleanup()


async def stream(client: aiohttp.ClientSession, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    async with client.post(url + "/chat/completions", json={**body, "stream": True}) as reply:
        assert reply.status == 200
        text = await reply.text()
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: {")]


def streamed_text(events: list[dict[str, Any]]) -> str:
    return "".join(event["choices"][0]["delta"].get("content") or "" for event in events if event["choices"])


async def test_the_bridge_sentence_is_said_without_asking_the_model(proxied):
    llm, client, url = proxied
    sentence = "Moving the camera 2 millimetres closer. Confirm?"
    events = await stream(client, url, {"model": "m", "tools": [MOVE],
                                        "messages": [system(exact_speech(sentence))]})
    assert streamed_text(events) == sentence
    assert llm.requests == []


async def test_a_command_reaches_the_speech_server_without_words(proxied):
    llm, client, url = proxied
    llm.message = decision(command="move_camera", arguments={"millimetres": 2, "direction": "closer"})
    events = await stream(client, url, {"model": "m", "tools": [MOVE], "tool_choice": "auto",
                                        "messages": [system("Be brief."), {"role": "user", "content": "2 mm closer"}]})
    assert llm.requests[0]["response_format"]["type"] == "json_schema"
    assert streamed_text(events) == ""
    calls = [d["tool_calls"][0] for e in events if e["choices"] for d in [e["choices"][0]["delta"]]
             if d.get("tool_calls")]
    assert calls[0]["function"]["name"] == "move_camera"
    assert json.loads(calls[0]["function"]["arguments"]) == {"millimetres": 2, "direction": "closer"}


async def test_small_talk_comes_back_as_words(proxied):
    llm, client, url = proxied
    llm.message = decision(reply="I am fine.")
    events = await stream(client, url, {"model": "m", "tools": [MOVE], "messages": [system("Hi.")]})
    assert streamed_text(events) == "I am fine."


async def test_a_request_without_tools_passes_through(proxied):
    llm, client, url = proxied
    events = await stream(client, url, {"model": "m", "messages": [{"role": "user", "content": "Summarise."}]})
    assert streamed_text(events) == "Streamed."
    assert llm.requests[0]["stream"] is True
    async with client.get(url + "/models") as reply:
        assert (await reply.json())["data"][0]["id"] == "fake"


async def test_the_summary_of_older_turns_never_reaches_the_model(proxied):
    llm, client, url = proxied
    async with client.post(url + "/chat/completions", json=SUMMARY_REQUEST) as reply:
        answer = await reply.json()
    assert json.loads(answer["choices"][0]["message"]["content"]) == json.loads(summary())
    assert llm.requests == []
    llm.message = decision(reply="Up to 360 degrees.")
    history = [system("Hi."), {"role": "user", "content": SUMMARY}, {"role": "assistant", "content": SUMMARY},
               {"role": "user", "content": "how far can it turn?"}]
    await stream(client, url, {"model": "m", "tools": [MOVE], "messages": history})
    assert [m.get("content") for m in llm.requests[0]["messages"][1:]] == ["how far can it turn?"]


def test_a_reply_that_asks_to_confirm_is_caught():
    assert asks_to_confirm("Switching the lights on. Confirm?", "Confirm?")
    assert asks_to_confirm("Turning on the lights, confirm?")
    assert asks_to_confirm("Lights on. Shall I go?", "Shall I go?")
    assert not asks_to_confirm("How many millimetres?", "Confirm?")


async def test_an_imitated_read_back_is_asked_again_with_commands_only(proxied):
    llm, client, url = proxied
    llm.answers = [decision(reply="Moving the camera 2 mm closer. Confirm?"),
                   decision(command="move_camera", arguments={"millimetres": 2})]
    events = await stream(client, url, {"model": "m", "tools": [MOVE], "messages": [system("Hi.")]})
    again = llm.requests[1]["response_format"]["json_schema"]["schema"]["oneOf"]
    assert [choice["properties"]["command"]["const"] for choice in again] == ["move_camera"]
    assert streamed_text(events) == ""
    assert any(e["choices"] and e["choices"][0]["delta"].get("tool_calls") for e in events)


async def test_an_imitated_read_back_is_never_said(proxied):
    llm, client, url = proxied
    llm.message = decision(reply="Moving the camera. Confirm?")
    events = await stream(client, url, {"model": "m", "tools": [MOVE], "messages": [system("Hi.")]})
    assert streamed_text(events) == SAY_AGAIN


def test_the_verbs_of_the_robot_come_from_its_sentences(stepit_macro):
    guard = Guard.of(stepit_macro)
    assert {"moving", "rotating", "taking", "switching", "enabling", "disabling", "turning"} <= guard.verbs
    assert pretends("I can do that. Moving the camera closer by 10 millimetres.", guard)
    assert pretends("Taking a test shot now.", guard)
    assert not pretends("How many millimetres closer?", guard)
    assert not pretends("The rail goes from 0 to 300 millimetres.", guard)


async def test_a_pretended_action_is_asked_again_with_commands_only(proxied):
    llm, client, url = proxied
    llm.answers = [decision(reply="I can do that. Moving the camera closer."),
                   decision(command="move_camera", arguments={"millimetres": 2})]
    events = await stream(client, url, {"model": "m", "tools": [MOVE], "messages": [system("Hi.")]})
    assert len(llm.requests) == 2
    assert streamed_text(events) == ""


async def test_yes_no_and_stop_never_reach_the_model(proxied):
    llm, client, url = proxied
    for said in ("Yes.", "no", "stop!"):
        events = await stream(client, url, {"model": "m", "tools": [MOVE],
                                            "messages": [system("Hi."), {"role": "user", "content": said}]})
        assert streamed_text(events) == ""
    assert llm.requests == []


async def test_the_model_never_sees_what_the_bridge_said(proxied):
    llm, client, url = proxied
    sentence = "Moving the camera 2 millimetres closer. Confirm?"
    await stream(client, url, {"model": "m", "tools": [MOVE], "messages": [system(exact_speech(sentence))]})
    history = [system("Hi."), {"role": "user", "content": "2 mm closer"},
               {"role": "assistant", "content": sentence}, {"role": "user", "content": "how far can it go?"}]
    await stream(client, url, {"model": "m", "tools": [MOVE], "messages": history})
    assert [m.get("content") for m in llm.requests[0]["messages"][1:]] == ["2 mm closer", "how far can it go?"]


async def test_the_follow_up_of_a_command_is_skipped_but_a_rejection_is_explained(proxied):
    llm, client, url = proxied
    history = [system("Hi."), {"role": "user", "content": "2 mm closer"},
               {"role": "assistant", "content": None, "tool_calls": [call("move_camera", {"millimetres": 2})]}]
    pending = {"role": "tool", "tool_call_id": "call_move_camera", "content": "Not done yet."}
    events = await stream(client, url, {"model": "m", "tools": [MOVE], "messages": [*history, pending]})
    assert streamed_text(events) == ""
    assert llm.requests == []
    rejected = {**pending, "content": "Rejected: 80 is more than 50. Nothing was done."}
    llm.message = decision(reply="That is too far.")
    events = await stream(client, url, {"model": "m", "tools": [MOVE], "messages": [*history, rejected]})
    assert streamed_text(events) == "That is too far."


async def test_every_request_goes_to_the_chosen_model(arm):
    llm = FakeLlm()
    proxy = LlmProxy(await llm.start(), "127.0.0.1", 0, Guard(), model="chosen")
    await proxy.start()
    try:
        async with aiohttp.ClientSession() as client:
            url = f"http://127.0.0.1:{proxy.port}/v1"
            await stream(client, url, {"model": "named", "messages": [{"role": "user", "content": "Summarise."}]})
            await stream(client, url, {"model": "named", "tools": [MOVE], "messages": [system("Hi.")]})
        assert [request["model"] for request in llm.requests] == ["chosen", "chosen"]
    finally:
        await proxy.stop()
        await llm.runner.cleanup()


# ── The sleep mode ─────────────────────────────────────────────────────────────

ASLEEP = "Going to sleep. To wake me, say: Wake up, robot."
AWAKE = "I'm listening."


def said(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text}


def heard(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def test_the_state_is_the_later_of_the_two_sentences():
    falls, wakes = tuple(words(ASLEEP)), tuple(words(AWAKE))
    assert not asleep({"messages": [system("Hi."), heard("go to sleep")]}, falls, wakes)
    assert asleep({"messages": [heard("yes"), said(ASLEEP), heard("turn left")]}, falls, wakes)
    assert not asleep({"messages": [said(ASLEEP), heard("wake up robot"), said(AWAKE), heard("hi")]}, falls, wakes)
    assert asleep({"messages": [said(ASLEEP), said(AWAKE), said(ASLEEP)]}, falls, wakes)


def test_the_sleeping_turns_are_dropped_from_the_history():
    falls, wakes = tuple(words(ASLEEP)), tuple(words(AWAKE))
    history = [system("Hi."), heard("go to sleep"), said(ASLEEP), heard("turn left 10 degrees"), said(""),
               heard("wake up robot"), said(AWAKE), heard("how far can it go?")]
    kept = without_sleep({"messages": history}, falls, wakes)["messages"]
    assert [m["content"] for m in kept] == ["You are in a spoken conversation.\n\nSession Prompt:\nHi.\n\nRules.",
                                            "go to sleep", ASLEEP, AWAKE, "how far can it go?"]


@pytest.fixture
async def sleepy_proxied(sleepy_arm):
    llm = FakeLlm()
    url = await llm.start()
    proxy = LlmProxy(url, "127.0.0.1", 0, Guard.of(sleepy_arm))
    await proxy.start()
    async with aiohttp.ClientSession() as client:
        yield llm, client, f"http://127.0.0.1:{proxy.port}/v1"
    await proxy.stop()
    await llm.runner.cleanup()


async def test_asleep_a_turn_never_reaches_the_model(sleepy_proxied):
    llm, client, url = sleepy_proxied
    history = [system("Hi."), heard("go to sleep"), said(ASLEEP), heard("turn left 10 degrees")]
    events = await stream(client, url, {"model": "m", "tools": [MOVE], "messages": history})
    assert streamed_text(events) == ""
    assert llm.requests == []


async def test_awake_again_the_model_never_sees_the_sleeping_turns(sleepy_proxied):
    llm, client, url = sleepy_proxied
    # The bridge's two sentences go through the proxy, which keeps them from the model too.
    for sentence in (ASLEEP, AWAKE):
        await stream(client, url, {"model": "m", "tools": [MOVE], "messages": [system(exact_speech(sentence))]})
    llm.message = decision(reply="Up to 50 millimetres.")
    history = [system("Hi."), heard("go to sleep"), said(ASLEEP), heard("move it 80 mm, they said"),
               heard("wake up robot"), said(AWAKE), heard("how far can it go?")]
    events = await stream(client, url, {"model": "m", "tools": [MOVE], "messages": history})
    assert streamed_text(events) == "Up to 50 millimetres."
    contents = [m.get("content") for m in llm.requests[0]["messages"][1:]]
    # Nor the wake phrase, which is the bridge's to answer.
    assert contents == ["go to sleep", "how far can it go?"]


def test_a_reply_that_pretends_to_sleep_is_caught_only_with_a_sleep_mode(arm, sleepy_arm):
    # Measured on Bonsai with the speech server's voice rules: about one "go to sleep" in three got these.
    for reply in ("Goodnight.", "Good night, I'm going to sleep.", "Sleeping, wake me when you need it."):
        assert pretends(reply, Guard.of(sleepy_arm)), reply
        assert not pretends(reply, Guard.of(arm)), reply
