# StepIt Speech Architecture

## Table of Contents <!-- omit in toc -->

- [Introduction](#introduction)
- [The Big Picture](#the-big-picture)
- [A Command, Step by Step](#a-command-step-by-step)
- [The Safety Rules](#the-safety-rules)
  - [The Confirmation, as a State Machine](#the-confirmation-as-a-state-machine)
  - [What Can Go Wrong, and What Catches It](#what-can-go-wrong-and-what-catches-it)
  - [Stop](#stop)
- [The Robot File](#the-robot-file)
  - [Commands and Calls](#commands-and-calls)
  - [Every Key of a Command](#every-key-of-a-command)
  - [Templates](#templates)
  - [What the Loader Checks](#what-the-loader-checks)
- [The Modules](#the-modules)
- [The Objects at Run Time](#the-objects-at-run-time)
- [Inside a Session](#inside-a-session)
  - [The Events It Reads](#the-events-it-reads)
  - [The Bridge's Own Replies](#the-bridges-own-replies)
  - [Muting the Server's Reply](#muting-the-servers-reply)
- [The LLM Proxy](#the-llm-proxy)
  - [One Decision per Turn](#one-decision-per-turn)
  - [What the Model Never Sees](#what-the-model-never-sees)
- [Talking to the Robot](#talking-to-the-robot)
- [Threads and Time](#threads-and-time)
- [Tests](#tests)
- [How to Extend StepIt Speech](#how-to-extend-stepit-speech)
- [Design Decisions and Trade-offs](#design-decisions-and-trade-offs)

## Introduction

This document explains how StepIt Speech is built, what each part is responsible for, and where to start when we want to change something. It assumes you have read the [README](../README.md). Its code is the Python package `voicebridge`, in `src/voicebridge`, about 3,200 lines with their docstrings; the robot it drives first is StepIt Macro, through [`robots/stepit-macro/robot.yaml`](../robots/stepit-macro/robot.yaml).

It follows one idea: **the LLM proposes, the bridge decides**. The LLM is good at understanding "spin the turntable forty five degrees anticlockwise", and bad at being certain: it can mishear, guess or invent. So it is given one job only, turning words into a proposed command. Everything that decides whether the robot moves is plain code with fixed rules: the limits of each value, the sentence read back, the words that mean yes, and stop. Even the LLM's answer has a fixed shape: one JSON object, a command or a short reply, which its server enforces.

A waiter works the same way. We order in our own words; the waiter writes the order on a slip in the kitchen's words and reads it back to us; the kitchen cooks only once we said "yes, that's it". If we say anything else, the slip goes in the bin, and if we shout "stop!", everything stops, whatever is written on the slip.

## The Big Picture

Five programs take part. The bridge is the only one of this project; the others are used as they are.

```mermaid
---
config:
  theme: base
  flowchart:
    curve: basis
    padding: 12
    nodeSpacing: 46
    rankSpacing: 32
    subGraphTitleMargin:
      top: 4
      bottom: 10
  class:
    padding: 10
  themeVariables:
    lineColor: "#94a3b8"
    textColor: "#64748b"
    primaryColor: "#f1f5f9"
    primaryBorderColor: "#64748b"
    primaryTextColor: "#0f172a"
    secondaryColor: "#f1f5f9"
    secondaryBorderColor: "#64748b"
    secondaryTextColor: "#0f172a"
    tertiaryColor: "#f1f5f9"
    tertiaryBorderColor: "#64748b"
    tertiaryTextColor: "#0f172a"
    mainBkg: "#f1f5f9"
    nodeBorder: "#64748b"
    nodeTextColor: "#0f172a"
    classText: "#0f172a"
    clusterBkg: "transparent"
    clusterBorder: "#94a3b8"
    titleColor: "#64748b"
    edgeLabelBackground: "#ffffff"
  themeCSS: >
    .node rect, .node polygon, .node path {
      filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18));
    }
    .node rect { rx: 14px; ry: 14px; }
    .cluster rect { rx: 18px; ry: 18px; }
    .edgeLabel, .edgeLabel p, .edgeLabel span {
      background: #ffffff; color: #475569; border-radius: 999px;
    }
    .edgeLabel p { padding: 3px 10px; }
    .labelBkg { background: transparent !important; fill: none !important; }
---
flowchart TB
    Browser(["<b>Browser demo</b><br/>microphone and speaker"])

    Bridge("<b>voicebridge</b><br/>port 8766")
    Speech("<b>Speech-to-Speech server</b><br/>port 8765<br/>VAD: when we speak<br/>STT: speech to text<br/>TTS: text to speech")
    Proxy("<b>voicebridge LLM proxy</b><br/>port 8767")
    LLM{{"<b>LLM</b><br/>Bonsai 2 27B on llama.cpp, port 8085"}}
    Rosbridge("<b>rosbridge</b><br/>port 9090")

    subgraph Rig["STEPIT MACRO"]
        Commander("<b>StepIt Commander</b><br/>the objectives")
        Drivers("<b>camera, Freezer, stack_state</b>")
    end

    Browser == "audio, events" ==> Bridge
    Bridge == "audio, events, robot tools" ==> Speech
    Speech -- "transcript, tools" --> Proxy
    Proxy -- "a JSON schema of the commands" --> LLM
    LLM -- "one JSON decision" --> Proxy
    Proxy -- "reply or tool call" --> Speech
    Bridge -. "confirmed commands" .-> Rosbridge
    Rosbridge -. "actions" .-> Commander
    Rosbridge -. "services, topics" .-> Drivers

    classDef human fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#881337
    classDef voice fill:#ccfbf1,stroke:#0d9488,stroke-width:2px,color:#134e4a
    classDef mind  fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    classDef brain fill:#7c3aed,stroke:#5b21b6,stroke-width:2px,color:#ffffff
    classDef robot fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
    classDef data  fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a
    classDef ext   fill:#f1f5f9,stroke:#64748b,stroke-width:2px,color:#0f172a

    class Browser human
    class Speech voice
    class Bridge brain
    class Proxy,LLM mind
    class Rosbridge,Commander,Drivers robot

    style Rig fill:#f59e0b12,stroke:#f59e0b,stroke-width:1.5px,stroke-dasharray:6 5,color:#d97706

    linkStyle 0,1 stroke:#14b8a6,stroke-width:3px
    linkStyle 2,3,4,5 stroke:#8b5cf6,stroke-width:2px
    linkStyle 6,7,8 stroke:#f59e0b,stroke-width:2px
```

The speech server and the browser speak the [OpenAI Realtime API](https://platform.openai.com/docs/guides/realtime): JSON events over a WebSocket, e.g. `session.update` from the browser, `response.created`, `conversation.item.input_audio_transcription.completed` (what we said) and `response.output_item.done` (a finished tool call) from the server. The bridge sits in the middle of that WebSocket. To the browser it looks like the server; to the server it looks like the browser. It passes almost every event through unchanged.

The bridge also sits on the speech server's way to its LLM. The speech server asks an OpenAI-compatible `/v1/chat/completions` for every reply it speaks, and its address is the bridge's LLM proxy, which forwards to the real LLM. That is how the bridge makes the voice say its own sentences exactly, and how it keeps the LLM from answering a command in words: see [The LLM Proxy](#the-llm-proxy).

| Name | Type | What it does |
|---|---|---|
| `ws://0.0.0.0:8766/v1/realtime` | WebSocket server | Where the browser connects, instead of the speech server. One session per browser. |
| `ws://127.0.0.1:8765/v1/realtime` | WebSocket client | The speech server. The bridge opens one connection per browser, with the browser's own subprotocols. |
| `http://127.0.0.1:8767/v1/chat/completions` | HTTP server | The LLM proxy, the speech server's LLM. Any other path passes through. |
| `http://localhost:8085/v1` | HTTP client | The LLM, any OpenAI-compatible server that enforces a JSON schema, e.g. llama.cpp. |
| `ws://localhost:9090` | WebSocket client | rosbridge, for every request to the robot. One connection for the whole bridge. |
| `robots/<robot>/robot.yaml` | File | Everything about the robot: its commands, how they reach it, the words of yes, no and stop. |
| `voicebridge serve`, `check`, `docs`, `run`, `eval` | Command line | The bridge, and the tools that try a robot file without a voice. |

## A Command, Step by Step

In plain words, this is what happens when we say "rotate the rig 10 degrees left":

1. The speech server hears us, transcribes us, and gives the text to its LLM, with the robot's commands as tools: the bridge added them to the session when the browser connected. Its LLM is the bridge's proxy, which asks the real LLM for one JSON object: a command, or a reply.
2. The LLM answers `{"command": "rotate_stage", "arguments": {"degrees": 10, "direction": "counter-clockwise"}}`, and the proxy hands it to the speech server as a call of the tool `rotate_stage`.
3. The bridge catches the call, so the browser never sees it, and checks the values: 10 is between 0.1 and 360, counter-clockwise is one of the two directions.
4. From the same values, it writes the sentence to read back, "Rotating the stage 10 degrees counter-clockwise. Confirm?", and the request it will send, the objective `RotateStageBy` with `{deg: -10.0}`.
5. It asks the speech server to say that sentence. The speech server asks its LLM for the words, and the proxy answers with the sentence itself, without the model. The bridge still compares what the voice said with the sentence: only when they are the same is the command **armed**, ready, waiting for a yes, for 20 seconds.
6. We say "yes". The bridge reads our transcript itself and finds only confirming words. The LLM never hears the yes: the proxy answers that turn with nothing, and the bridge cancels the server's reply to it.
7. The bridge sends the goal to the commander through rosbridge and waits for its end.
8. It asks the voice to say the outcome: "The stage turned 10 degrees counter-clockwise."

The same, as the messages between the programs, in three steps. First, the request becomes a proposed command, steps 1 and 2:

```mermaid
---
config:
  theme: base
  sequence:
    actorMargin: 24
    width: 130
    diagramMarginX: 10
    boxMargin: 12
    boxTextMargin: 8
    messageMargin: 40
    noteMargin: 22
    labelBoxWidth: 56
    labelBoxHeight: 28
    messageFontSize: 16
    actorFontSize: 16
    noteFontSize: 15
    wrap: false
  themeVariables:
    textColor: "#8b5cf6"
    actorBkg: "#ede9fe"
    actorBorder: "#7c3aed"
    actorTextColor: "#4c1d95"
    actorLineColor: "#a78bfa"
    signalColor: "#8b949e"
    signalTextColor: "#6e7781"
    labelBoxBkgColor: "#ccfbf1"
    labelBoxBorderColor: "#0d9488"
    labelTextColor: "#134e4a"
    loopTextColor: "#0d9488"
    noteBkgColor: "#fef3c7"
    noteBorderColor: "#d97706"
    noteTextColor: "#78350f"
    activationBkgColor: "#c4b5fd"
    activationBorderColor: "#7c3aed"
    mainBkg: "#ede9fe"
    nodeBorder: "#7c3aed"
    secondaryColor: "#ede9fe"
    secondaryBorderColor: "#7c3aed"
    secondaryTextColor: "#4c1d95"
    tertiaryColor: "#ede9fe"
    tertiaryBorderColor: "#7c3aed"
    tertiaryTextColor: "#4c1d95"
  themeCSS: >
    .actor { filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18)); }
    rect.actor { rx: 12px; ry: 12px; }
---
sequenceDiagram
    participant User
    participant Browser
    participant Bridge as voicebridge
    participant Speech as Speech server
    participant Proxy as LLM proxy
    participant LLM

    User ->> Browser: "rotate the rig<br/>10 degrees left"
    Browser ->> Bridge: audio
    Bridge ->> Speech: audio
    Speech ->> Proxy: chat completion,<br/>the transcript and the tools
    Proxy ->> LLM: the same, with<br/>a JSON schema<br/>of the commands
    LLM -->> Proxy: {"command":<br/>"rotate_stage", ...}
    Proxy -->> Speech: tool call rotate_stage<br/>(10, counter-clockwise)
    Speech ->> Bridge: response.output_item<br/>.done, the tool call
```

Then the bridge reads it back, steps 3 to 5:

```mermaid
---
config:
  theme: base
  sequence:
    actorMargin: 24
    width: 130
    diagramMarginX: 10
    boxMargin: 12
    boxTextMargin: 8
    messageMargin: 40
    noteMargin: 22
    labelBoxWidth: 56
    labelBoxHeight: 28
    messageFontSize: 16
    actorFontSize: 16
    noteFontSize: 15
    wrap: false
  themeVariables:
    textColor: "#8b5cf6"
    actorBkg: "#ede9fe"
    actorBorder: "#7c3aed"
    actorTextColor: "#4c1d95"
    actorLineColor: "#a78bfa"
    signalColor: "#8b949e"
    signalTextColor: "#6e7781"
    labelBoxBkgColor: "#ccfbf1"
    labelBoxBorderColor: "#0d9488"
    labelTextColor: "#134e4a"
    loopTextColor: "#0d9488"
    noteBkgColor: "#fef3c7"
    noteBorderColor: "#d97706"
    noteTextColor: "#78350f"
    activationBkgColor: "#c4b5fd"
    activationBorderColor: "#7c3aed"
    mainBkg: "#ede9fe"
    nodeBorder: "#7c3aed"
    secondaryColor: "#ede9fe"
    secondaryBorderColor: "#7c3aed"
    secondaryTextColor: "#4c1d95"
    tertiaryColor: "#ede9fe"
    tertiaryBorderColor: "#7c3aed"
    tertiaryTextColor: "#4c1d95"
  themeCSS: >
    .actor { filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18)); }
    rect.actor { rx: 12px; ry: 12px; }
---
sequenceDiagram
    participant Browser
    participant Bridge as voicebridge
    participant Speech as Speech server
    participant Proxy as LLM proxy

    Note over Bridge: hidden from the browser.<br/>Check the values, render<br/>the read-back and the request.
    Bridge ->> Speech: function_call_output<br/>"Not done yet..."
    Bridge ->> Speech: response.create, the<br/>read-back in its instructions
    Speech ->> Proxy: chat completion,<br/>with the read-back
    Proxy -->> Speech: "Rotating the stage 10 degrees<br/>counter-clockwise. Confirm?"
    Speech ->> Browser: the read-back, spoken
    Speech ->> Bridge: response.output_audio<br/>_transcript.done
    Note over Bridge: the same sentence: armed
```

Last, the yes and the run, steps 6 to 8:

```mermaid
---
config:
  theme: base
  sequence:
    actorMargin: 24
    width: 130
    diagramMarginX: 10
    boxMargin: 12
    boxTextMargin: 8
    messageMargin: 40
    noteMargin: 22
    labelBoxWidth: 56
    labelBoxHeight: 28
    messageFontSize: 16
    actorFontSize: 16
    noteFontSize: 15
    wrap: false
  themeVariables:
    textColor: "#8b5cf6"
    actorBkg: "#ede9fe"
    actorBorder: "#7c3aed"
    actorTextColor: "#4c1d95"
    actorLineColor: "#a78bfa"
    signalColor: "#8b949e"
    signalTextColor: "#6e7781"
    labelBoxBkgColor: "#ccfbf1"
    labelBoxBorderColor: "#0d9488"
    labelTextColor: "#134e4a"
    loopTextColor: "#0d9488"
    noteBkgColor: "#fef3c7"
    noteBorderColor: "#d97706"
    noteTextColor: "#78350f"
    activationBkgColor: "#c4b5fd"
    activationBorderColor: "#7c3aed"
    mainBkg: "#ede9fe"
    nodeBorder: "#7c3aed"
    secondaryColor: "#ede9fe"
    secondaryBorderColor: "#7c3aed"
    secondaryTextColor: "#4c1d95"
    tertiaryColor: "#ede9fe"
    tertiaryBorderColor: "#7c3aed"
    tertiaryTextColor: "#4c1d95"
  themeCSS: >
    .actor { filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18)); }
    rect.actor { rx: 12px; ry: 12px; }
---
sequenceDiagram
    participant User
    participant Browser
    participant Bridge as voicebridge
    participant Speech as Speech server
    participant Proxy as LLM proxy
    participant Rosbridge as rosbridge<br/>and the rig

    User ->> Browser: "yes"
    Speech ->> Bridge: input_audio_transcription<br/>.completed "Yes."
    Note over Bridge: only confirming words: run it
    Speech ->> Proxy: chat completion, "Yes."
    Proxy -->> Speech: nothing: the<br/>bridge answers it
    Bridge ->> Speech: response.cancel
    Bridge ->> Rosbridge: send_action_goal<br/>RotateStageBy {deg: -10.0}
    Rosbridge -->> Bridge: action_result,<br/>status 4, SUCCESS
    Bridge ->> Speech: response.create, the outcome
    Speech ->> Proxy: chat completion,<br/>with the outcome
    Proxy -->> Speech: "The stage turned 10<br/>degrees counter-clockwise."
    Speech ->> Browser: the outcome, spoken
```

## The Safety Rules

The bridge exists for these rules. Each one is code, not a request to the LLM, and each has tests in [`tests/test_session.py`](../tests/test_session.py), [`tests/test_confirmation.py`](../tests/test_confirmation.py) or [`tests/test_llmproxy.py`](../tests/test_llmproxy.py).

1. **The LLM never runs anything.** Its commands are proposals: the bridge catches every call of a robot command before the browser sees it.
2. **The values are checked before the read-back.** Each parameter has a type and, for a number, limits, e.g. at most 360 degrees and 50 mm: a value out of them is refused, and the LLM is told why, so that it can tell us.
3. **What is read back is what runs.** The sentence and the request are rendered together, from the same checked values, in `Planner.prepare`.
4. **The voice says the read-back exactly.** The LLM never writes it: the proxy gives the speech server the sentence itself. The bridge still compares what the voice said with the sentence, ignoring case and punctuation; anything else cancels the command, and the voice says so.
5. **Only a clear yes runs it.** The bridge decides from our transcript, with the robot file's list of words: the whole answer must be made of them, e.g. "yes", "ok go ahead", "yes please". "Yes but 20 degrees" is not a yes.
6. **The yes must come after the read-back, and in time.** A yes over the read-back, before it ended, does not count: we cannot have confirmed what we did not hear. After 20 seconds, a yes runs nothing.
7. **Anything else cancels.** "No", "wait", or any other sentence drops the command; a sentence that is not a yes or a no then goes to the LLM as a new request.
8. **Stop needs nothing.** A stop word anywhere in what we say runs the stop command at once, without the LLM and without a confirmation. See [Stop](#stop).
9. **A command never outlives its session.** When the browser disconnects, the goals the session sent are cancelled.
10. **One command per answer of the LLM.** A second tool call in the same answer is refused.
11. **What is not in the robot file cannot be said.** StepIt Macro's file leaves out switching the rig off, and the objectives that take raw radians.
12. **The LLM cannot pretend.** Every turn it answers with a command or a reply, in a JSON schema its server enforces, so a command cannot hide in words. A reply that asks to confirm, or says the robot is acting, is asked again with commands only. See [The LLM Proxy](#the-llm-proxy).
13. **Yes, no and stop never reach the LLM.** A yes with no command waiting is answered by the bridge: "There is no command waiting for confirmation, so nothing was done."

### The Confirmation, as a State Machine

The pending command lives in a `Confirmation` object, in [`confirmation.py`](../src/voicebridge/confirmation.py). It holds at most one command, and is always in one of three states:

```mermaid
---
config:
  theme: base
  flowchart:
    curve: basis
    padding: 12
    nodeSpacing: 46
    rankSpacing: 32
    subGraphTitleMargin:
      top: 4
      bottom: 10
  class:
    padding: 10
  themeVariables:
    lineColor: "#94a3b8"
    textColor: "#64748b"
    primaryColor: "#f1f5f9"
    primaryBorderColor: "#64748b"
    primaryTextColor: "#0f172a"
    secondaryColor: "#f1f5f9"
    secondaryBorderColor: "#64748b"
    secondaryTextColor: "#0f172a"
    tertiaryColor: "#f1f5f9"
    tertiaryBorderColor: "#64748b"
    tertiaryTextColor: "#0f172a"
    mainBkg: "#f1f5f9"
    nodeBorder: "#64748b"
    nodeTextColor: "#0f172a"
    classText: "#0f172a"
    clusterBkg: "transparent"
    clusterBorder: "#94a3b8"
    titleColor: "#64748b"
    edgeLabelBackground: "#ffffff"
  themeCSS: >
    .node rect, .node polygon, .node path {
      filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18));
    }
    .node rect { rx: 14px; ry: 14px; }
    .cluster rect { rx: 18px; ry: 18px; }
    .edgeLabel, .edgeLabel p, .edgeLabel span {
      background: #ffffff; color: #475569; border-radius: 999px;
    }
    .edgeLabel p { padding: 3px 10px; }
    .labelBkg { background: transparent !important; fill: none !important; }
---
flowchart TB
    Idle(["<b>Idle</b><br/>no command waits"])
    ReadingBack(["<b>ReadingBack</b><br/>the voice reads it back"])
    Armed(["<b>Armed</b><br/>waits 20 s for a yes"])
    Run("<b>The command runs</b>")
    Dropped("<b>Dropped</b><br/>nothing runs")

    Idle -- "propose a checked command" --> ReadingBack
    ReadingBack -- "the voice said the sentence exactly" --> Armed
    ReadingBack -- "the voice said something else,<br/>or the user spoke over it" --> Dropped
    Armed == "yes, within 20 s" ==> Run
    Armed -- "yes too late, no, stop,<br/>or anything else" --> Dropped
    Run -. "back to" .-> Idle
    Dropped -. "back to" .-> Idle

    classDef human fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#881337
    classDef voice fill:#ccfbf1,stroke:#0d9488,stroke-width:2px,color:#134e4a
    classDef mind  fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    classDef brain fill:#7c3aed,stroke:#5b21b6,stroke-width:2px,color:#ffffff
    classDef robot fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
    classDef data  fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a
    classDef ext   fill:#f1f5f9,stroke:#64748b,stroke-width:2px,color:#0f172a

    class Idle ext
    class ReadingBack voice
    class Armed mind
    class Run brain
    class Dropped human

    linkStyle 0,1 stroke:#8b5cf6,stroke-width:2px
    linkStyle 2,4 stroke:#f43f5e,stroke-width:2px
    linkStyle 3 stroke:#7c3aed,stroke-width:3px
    linkStyle 5,6 stroke:#94a3b8,stroke-width:2px
```

Every way out of `Armed` goes back to `Idle`, so a command is confirmed once at most. Only one arrow runs a command, and it starts from `Armed`. A newer command, proposed while one is read back or armed, replaces it and starts its own read-back. The object does no I/O and takes its clock as an argument, so the tests move time forward by hand.

### What Can Go Wrong, and What Catches It

| What goes wrong | What catches it |
|---|---|
| The STT mishears "fifteen" as "fifty". | The read-back says "50 degrees": we hear it and say no. |
| The LLM picks the wrong direction, or guesses one we did not say. | The read-back says the direction in words: we hear it and say no. Measured on Qwen3.8-27B: "turn the table 20 degrees" became clockwise. |
| The LLM asks for 400 degrees, or 2 metres. | The limits of the parameter: the command is refused before the read-back. |
| The LLM calls a tool while we only chat. | The read-back: an unexpected "Rotating the stage..." is answered with no, or with anything else. |
| The LLM answers "I'll switch the lights on for you" and calls nothing. | The JSON schema: an answer is a command or a reply. A reply with a verb of the robot's read-backs, e.g. "switching", is asked again with commands only; if no command comes, the voice says "Sorry, I did not get that as a command." |
| The LLM asks "Switching the lights on. Confirm?" itself, and our yes confirms nothing. | The proxy refuses a reply that asks to confirm, and the model never sees the bridge's read-backs to copy. A yes with nothing waiting is answered by the bridge. |
| The model repeats a sentence without end. | A reply is at most 200 characters, and an answer at most 300 tokens. |
| The LLM decides that "sure, why not" or "yes but slower" is a yes. | It is not asked: the bridge matches the words itself, and neither sentence is made only of confirming words. |
| We say yes before the read-back is over. | Rule 6: the command is dropped. |
| We say yes a minute later, to something else. | The 20 seconds have passed: nothing runs, and the voice says so. |
| The LLM speaks its own answer to our yes, e.g. "Done!" before anything ran. | The proxy answers a yes, a no or a stop with nothing, and the bridge mutes and cancels the server's reply to every turn it answers itself. |
| The browser tab closes during a move. | The session cancels its goals. |
| rosbridge is down. | The request fails at once, and the voice says "cannot reach rosbridge". |

What it does not catch: a command that is read back correctly, that we confirm without listening. The read-back is as safe as our attention to it. The voice stop takes about a second, the time to hear the end of our sentence and transcribe it: it does not replace the stop of the gamepad or of StepIt UI.

### Stop

The robot file lists the stop words, e.g. `stop`, `halt`, `abort`, `freeze`, and the command they run, `stop`, which cancels every goal of the commander. A stop word anywhere in a sentence stops the robot, because a stop heard by mistake costs nothing, and a stop missed is the failure that matters. Two cases:

- **Only stop words**, e.g. "stop!" or "stop stop": the bridge answers this turn itself. It drops any pending command, mutes the server's reply, runs `stop`, and says "Stopped."
- **More than a stop**, e.g. "stop the live view": the bridge runs `stop` silently, drops any pending command, and lets the LLM hear the sentence as a request: the live view is then read back and confirmed as usual.

```mermaid
---
config:
  theme: base
  sequence:
    actorMargin: 24
    width: 130
    diagramMarginX: 10
    boxMargin: 12
    boxTextMargin: 8
    messageMargin: 40
    noteMargin: 22
    labelBoxWidth: 56
    labelBoxHeight: 28
    messageFontSize: 16
    actorFontSize: 16
    noteFontSize: 15
    wrap: false
  themeVariables:
    textColor: "#8b5cf6"
    actorBkg: "#ede9fe"
    actorBorder: "#7c3aed"
    actorTextColor: "#4c1d95"
    actorLineColor: "#a78bfa"
    signalColor: "#8b949e"
    signalTextColor: "#6e7781"
    labelBoxBkgColor: "#ccfbf1"
    labelBoxBorderColor: "#0d9488"
    labelTextColor: "#134e4a"
    loopTextColor: "#0d9488"
    noteBkgColor: "#fef3c7"
    noteBorderColor: "#d97706"
    noteTextColor: "#78350f"
    activationBkgColor: "#c4b5fd"
    activationBorderColor: "#7c3aed"
    mainBkg: "#ede9fe"
    nodeBorder: "#7c3aed"
    secondaryColor: "#ede9fe"
    secondaryBorderColor: "#7c3aed"
    secondaryTextColor: "#4c1d95"
    tertiaryColor: "#ede9fe"
    tertiaryBorderColor: "#7c3aed"
    tertiaryTextColor: "#4c1d95"
  themeCSS: >
    .actor { filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18)); }
    rect.actor { rx: 12px; ry: 12px; }
---
sequenceDiagram
    participant User
    participant Speech as Speech server
    participant Bridge as voicebridge
    participant Rig as rosbridge<br/>and the rig

    Note over Rig: RotateStageBy<br/>360 degrees, running
    User ->> Speech: "stop!"
    Speech ->> Bridge: input_audio_transcription<br/>.completed "Stop!"
    Note over Bridge: only stop words:<br/>no LLM, no confirmation
    Bridge ->> Speech: response.cancel
    Bridge ->> Rig: call_service<br/>.../_action/cancel_goal
    Rig -->> Bridge: the goal is cancelled,<br/>the stage brakes
    Bridge ->> Speech: response.create, "Stopped."
    Rig -->> Bridge: action_result of<br/>the move, status 5
    Bridge ->> Speech: response.create, "That did<br/>not work: it was stopped<br/>before the end."
```

On the rig, with its fake motors, the commander logged the cancel 1.5 seconds after the move started, and halted the tree.

## The Robot File

### Commands and Calls

A robot file has two halves, for two people:

- **`commands`**: what the user can say. Anyone can write one: it names no topic and no message type.
- **`calls`**: how a command reaches the robot over rosbridge: an action, a service or a topic, its message type, the request, and how to tell success. Someone who knows the robot's ROS interface writes them once. The calls of standard ROS 2 interfaces, `get_parameters`, `set_parameters`, `trigger` and `read_latched_topic`, come with voicebridge in [`calls.yaml`](../src/voicebridge/calls.yaml).

A command uses a call by its name, and gives it values. `rotate_stage` runs the call `objective` with a name and a payload; the call `objective` knows that this means a goal of `btcpp_ros2_interfaces/action/ExecuteTree` on `/commander/execute_objective`, and that the goal succeeded when its status is 4 and the tree returned SUCCESS. Ten of the twelve StepIt Macro commands that run something use three calls: `objective`, `set_parameters` and `trigger`.

The loader turns the file into these objects, in [`catalogue.py`](../src/voicebridge/catalogue.py). They are frozen dataclasses: once loaded, nothing changes them.

```mermaid
---
config:
  theme: base
  flowchart:
    curve: basis
    padding: 12
    nodeSpacing: 46
    rankSpacing: 32
    subGraphTitleMargin:
      top: 4
      bottom: 10
  class:
    padding: 10
  themeVariables:
    lineColor: "#94a3b8"
    textColor: "#64748b"
    primaryColor: "#f1f5f9"
    primaryBorderColor: "#64748b"
    primaryTextColor: "#0f172a"
    secondaryColor: "#f1f5f9"
    secondaryBorderColor: "#64748b"
    secondaryTextColor: "#0f172a"
    tertiaryColor: "#f1f5f9"
    tertiaryBorderColor: "#64748b"
    tertiaryTextColor: "#0f172a"
    mainBkg: "#f1f5f9"
    nodeBorder: "#64748b"
    nodeTextColor: "#0f172a"
    classText: "#0f172a"
    clusterBkg: "transparent"
    clusterBorder: "#94a3b8"
    titleColor: "#64748b"
    edgeLabelBackground: "#ffffff"
  themeCSS: >
    .node rect, .node polygon, .node path {
      filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18));
    }
    .node rect { rx: 14px; ry: 14px; }
    .cluster rect { rx: 18px; ry: 18px; }
    .edgeLabel, .edgeLabel p, .edgeLabel span {
      background: #ffffff; color: #475569; border-radius: 999px;
    }
    .edgeLabel p { padding: 3px 10px; }
    .labelBkg { background: transparent !important; fill: none !important; }
---
classDiagram
    direction TB
    class Catalogue {
        name
        description
        rosbridge_url
        tool_specs()
    }
    class ConfirmationSettings {
        timeout_s
        prompt
        confirm, decline, stop, fillers
        stop_command
    }
    class Command {
        name
        description
        say
        confirm
        started, done, failed
        tool_spec()
        check_arguments(raw)
    }
    class Parameter {
        name
        type
        choices, minimum, maximum
        optional
        check(value)
    }
    class Use {
        call
        arguments
    }
    class Example {
        phrase
        expect
        reads
    }
    class Call {
        name
        kind: action, service, topic, publish
        target, type
        request
        success, message, result
        timeout_s
    }
    Catalogue *-- ConfirmationSettings : confirmation
    Catalogue *-- Command : commands
    Catalogue *-- Call : calls
    Command *-- Parameter : parameters
    Command *-- Use : run, at most one
    Command *-- Use : read
    Command *-- Example : examples
    Use --> Call : names

    style Catalogue fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a
    style ConfirmationSettings fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#881337
    style Command fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    style Parameter fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    style Use fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    style Example fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    style Call fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
```

### Every Key of a Command

| Key | Needed | What it is |
|---|---|---|
| `description` | yes | What the command does. The LLM chooses a command by it, so it says it in the user's words: "the turntable the subject stands on". |
| `parameters` | no | What the LLM fills in. `[a, b]` is a choice of words; `number`, `integer`, `string` or `boolean` a value; the long form `{type, min, max, description, optional}` adds limits. The LLM sees them as the JSON schema of the tool; the bridge checks them again, as the LLM may ignore a schema. |
| `say` | yes | The sentence read back, or, for a query, the answer. |
| `run` | no | The call to run, and its values. A command without `run` is a query: it reads, says, and changes nothing. |
| `confirm` | no | `true` by default. `false` runs the command at once: only for `stop`, and for queries, which must say so. |
| `read` | no | Calls to run before the read-back, e.g. the plan of the stack. Their results are `reads.<name>`. |
| `let` | no | Values computed from the parameters and the reads, in order, e.g. `shots` from `reads.plan`. |
| `require` | no | Conditions that must hold, each with the sentence that refuses the command, e.g. `Mark the near end first.` |
| `started` | no | What to say as soon as the command is confirmed, for a long one: "The focus stack has started." |
| `done`, `failed` | no | What to say once it ended; `failed` sees `{{ message }}`, the robot's reason. Without them: "Done." and "That did not work: <reason>." |
| `examples` | no, but expected | Phrases and the arguments the LLM should give for them. The LLM sees the first four in the tool; `voicebridge check`, the tests and `commands.md` prepare every one; `voicebridge eval` scores the LLM on them. |

`Planner.prepare` uses the keys in this order: check the arguments, run the reads, compute the lets, check the requires, render `say` and `run`. Anything that refuses a command happens before the read-back, so the user never confirms a command that would be refused.

### Templates

Values are [Jinja2](https://jinja.palletsprojects.com/) templates, in [`templating.py`](../src/voicebridge/templating.py). One rule makes them work for requests as well as for sentences: **a string that is a single `{{ expression }}` keeps the type of the expression**. `"{{ -degrees }}"` is the number -10.0, not the text "-10.0"; `"{{ [shots | float] }}"` is a list. Any other string is text: `"Rotating the stage {{ degrees }} degrees"`.

The filters the robot files need:

| Filter | What it does | Example |
|---|---|---|
| `plural` | A count with its word. | `{{ 1 \| plural('degree') }}` is "1 degree" |
| `flow_yaml` | A value as one line of YAML, the payload of a StepIt objective. | `{deg: -10.0}` |
| `ros_parameters` | A mapping as `rcl_interfaces/msg/Parameter` messages; a value of none is left out. | `{iso: '400'}` |
| `param_value` | The value of an `rcl_interfaces/msg/ParameterValue`. | `[17.0]` |
| `scalar` | The first item of a list, none for an empty one. | `17.0` |
| `bit_or`, `bit_and_not` | Bits of a number, e.g. the outputs of the Freezer. | `0 \| bit_or(3)` is 3 |

A number printed into a text reads as a person says it: 10.0 is "10". The environment is sandboxed and immutable: a template cannot reach Python's internals or change its values. A name that does not exist is an error, never an empty value.

### What the Loader Checks

`load` checks the whole file before the bridge starts, and says where a mistake is: a key it does not know, e.g. `sya` for `say`; a call that does not exist; a template that does not compile; a name a template reads that is not a parameter, `reads` or a `let`, with the names it knows; an example whose arguments do not fit its parameters; a query that does not say `confirm: false`; stop words without a stop command. Two traps of YAML are handled for us: `yes`, `no`, `on` and `off` stay words, not booleans, and a key with a space, which a comma inside `{ }` creates, comes with a hint to use quotes.

## The Modules

The package is fifteen modules in [`src/voicebridge`](../src/voicebridge), in four layers. A module imports only from the layers below it.

| Layer | Module | Responsibility | Must never |
|---|---|---|---|
| Tools | `cli` | The command line: `serve`, `check`, `docs`, `run`, `eval`. | Hold logic the bridge needs. |
| | `docs` | `commands.md`, from the robot file and its examples. | |
| Conversation | `server` | The WebSocket server; one `Session` per browser, and its connection to the speech server. | Look into the events. |
| | `session` | The rules of [Inside a Session](#inside-a-session). | Decide yes with the LLM; talk to rosbridge itself. |
| | `llmproxy` | The LLM proxy of [The LLM Proxy](#the-llm-proxy): the bridge's sentences, one JSON decision per turn, what the model never sees. | Run a command, or decide a yes. |
| Robot | `planner` | From a tool call to a `Prepared` command: checks, reads, read-back and request. | Run the command. |
| | `robot` | `render_request`, `judge`, the `Robot` port and `RosbridgeRobot`. | Know a robot's names. |
| | `prompt` | The LLM's instructions. | |
| Model | `catalogue` | The robot file: load, check, the tools of the LLM, the check of arguments. | Do I/O beyond reading the file. |
| | `confirmation` | The state machine of the pending command. | Do I/O, or read a clock of its own. |
| | `phrases` | Yes, no, stop or other, from fixed lists of words. | Ask the LLM. |
| Foundation | `templating` | Jinja2, sandboxed, with typed results and the filters. | Know of robots. |
| | `rosbridge` | The client of rosbridge's protocol. | Know of commands. |
| | `realtime` | Pure functions on the events of the Realtime API. | Do I/O. |

The imports, as they are:

```mermaid
---
config:
  theme: base
  flowchart:
    curve: basis
    padding: 12
    nodeSpacing: 46
    rankSpacing: 32
    subGraphTitleMargin:
      top: 4
      bottom: 10
  class:
    padding: 10
  themeVariables:
    lineColor: "#94a3b8"
    textColor: "#64748b"
    primaryColor: "#f1f5f9"
    primaryBorderColor: "#64748b"
    primaryTextColor: "#0f172a"
    secondaryColor: "#f1f5f9"
    secondaryBorderColor: "#64748b"
    secondaryTextColor: "#0f172a"
    tertiaryColor: "#f1f5f9"
    tertiaryBorderColor: "#64748b"
    tertiaryTextColor: "#0f172a"
    mainBkg: "#f1f5f9"
    nodeBorder: "#64748b"
    nodeTextColor: "#0f172a"
    classText: "#0f172a"
    clusterBkg: "transparent"
    clusterBorder: "#94a3b8"
    titleColor: "#64748b"
    edgeLabelBackground: "#ffffff"
  themeCSS: >
    .node rect, .node polygon, .node path {
      filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18));
    }
    .node rect { rx: 14px; ry: 14px; }
    .cluster rect { rx: 18px; ry: 18px; }
    .edgeLabel, .edgeLabel p, .edgeLabel span {
      background: #ffffff; color: #475569; border-radius: 999px;
    }
    .edgeLabel p { padding: 3px 10px; }
    .labelBkg { background: transparent !important; fill: none !important; }
---
flowchart TB
    subgraph Tools["TOOLS"]
        cli("<b>cli</b>")
        docs("<b>docs</b>")
    end
    subgraph Conversation["CONVERSATION"]
        server("<b>server</b>")
        session("<b>session</b>")
        llmproxy("<b>llmproxy</b>")
    end
    subgraph Robot["ROBOT"]
        planner("<b>planner</b>")
        robot("<b>robot</b>")
        prompt("<b>prompt</b>")
    end
    subgraph Model["MODEL"]
        catalogue("<b>catalogue</b>")
        confirmation("<b>confirmation</b>")
        phrases("<b>phrases</b>")
    end
    subgraph Foundation["FOUNDATION"]
        templating("<b>templating</b>")
        rosbridge("<b>rosbridge</b>")
        realtime("<b>realtime</b>")
    end

    cli --> server
    cli --> llmproxy
    llmproxy --> phrases
    llmproxy --> realtime
    cli --> docs
    docs --> planner
    server --> session
    session --> planner
    session --> confirmation
    session --> phrases
    session --> prompt
    session --> realtime
    planner --> robot
    planner --> catalogue
    robot --> catalogue
    robot --> rosbridge
    robot --> templating
    prompt --> catalogue
    confirmation --> phrases
    phrases --> catalogue
    catalogue --> templating

    classDef human fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#881337
    classDef voice fill:#ccfbf1,stroke:#0d9488,stroke-width:2px,color:#134e4a
    classDef mind  fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    classDef brain fill:#7c3aed,stroke:#5b21b6,stroke-width:2px,color:#ffffff
    classDef robot fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
    classDef data  fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a
    classDef ext   fill:#f1f5f9,stroke:#64748b,stroke-width:2px,color:#0f172a

    class cli,docs ext
    class server,session,llmproxy voice
    class planner,robot,prompt robot
    class catalogue,confirmation,phrases mind
    class templating,rosbridge,realtime data

    style Tools fill:#64748b12,stroke:#64748b,stroke-width:1.5px,stroke-dasharray:6 5,color:#64748b
    style Conversation fill:#14b8a612,stroke:#14b8a6,stroke-width:1.5px,stroke-dasharray:6 5,color:#0d9488
    style Robot fill:#f59e0b12,stroke:#f59e0b,stroke-width:1.5px,stroke-dasharray:6 5,color:#d97706
    style Model fill:#8b5cf612,stroke:#8b5cf6,stroke-width:1.5px,stroke-dasharray:6 5,color:#7c3aed
    style Foundation fill:#3b82f612,stroke:#3b82f6,stroke-width:1.5px,stroke-dasharray:6 5,color:#2563eb

    linkStyle 0,1,4,5 stroke:#64748b,stroke-width:2px
    linkStyle 2,3,6,7,8,9,10,11 stroke:#14b8a6,stroke-width:2px
    linkStyle 12,13,14,15,16,17 stroke:#f59e0b,stroke-width:2px
    linkStyle 18,19,20 stroke:#8b5cf6,stroke-width:2px
```

Some edges are left out for clarity, e.g. `cli` imports most modules, `session` also imports `catalogue` and `robot`, and `llmproxy` imports `catalogue`; `session` and `llmproxy` share only `realtime.exact_speech` and `scripted_sentence`, the tags of a sentence of the bridge; none goes up a layer, and there is no cycle. One edge is worth knowing: `robot` holds both the `Robot` port and its rosbridge implementation, so `session` imports, through it, the module of the rosbridge client, without using it. The session only ever calls `Robot.execute`, and the tests give it a fake.

## The Objects at Run Time

Once `voicebridge serve` runs, these objects exist. One `Catalogue`, one `Rosbridge` connection and one `LlmProxy` serve every browser; each browser gets its own `Session`, with its own pending command.

```mermaid
---
config:
  theme: base
  flowchart:
    curve: basis
    padding: 12
    nodeSpacing: 46
    rankSpacing: 32
    subGraphTitleMargin:
      top: 4
      bottom: 10
  class:
    padding: 10
  themeVariables:
    lineColor: "#94a3b8"
    textColor: "#64748b"
    primaryColor: "#f1f5f9"
    primaryBorderColor: "#64748b"
    primaryTextColor: "#0f172a"
    secondaryColor: "#f1f5f9"
    secondaryBorderColor: "#64748b"
    secondaryTextColor: "#0f172a"
    tertiaryColor: "#f1f5f9"
    tertiaryBorderColor: "#64748b"
    tertiaryTextColor: "#0f172a"
    mainBkg: "#f1f5f9"
    nodeBorder: "#64748b"
    nodeTextColor: "#0f172a"
    classText: "#0f172a"
    clusterBkg: "transparent"
    clusterBorder: "#94a3b8"
    titleColor: "#64748b"
    edgeLabelBackground: "#ffffff"
  themeCSS: >
    .node rect, .node polygon, .node path {
      filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18));
    }
    .node rect { rx: 14px; ry: 14px; }
    .cluster rect { rx: 18px; ry: 18px; }
    .edgeLabel, .edgeLabel p, .edgeLabel span {
      background: #ffffff; color: #475569; border-radius: 999px;
    }
    .edgeLabel p { padding: 3px 10px; }
    .labelBkg { background: transparent !important; fill: none !important; }
---
classDiagram
    direction TB
    class BridgeServer {
        start()
        stop()
    }
    class Session {
        from_browser(event)
        from_upstream(event)
        close()
    }
    class Planner {
        prepare(name, arguments) Prepared
        outcome_sentence(prepared, outcome)
    }
    class Confirmation {
        phase
        propose(command, sentence)
        read_back(heard) bool
        answer(meaning) Answer
    }
    class PhraseMatcher {
        classify(text) Meaning
        mentions_stop(text) bool
    }
    class Robot {
        <<interface>>
        execute(request) Outcome
    }
    class RosbridgeRobot
    class Rosbridge {
        call_service()
        send_action_goal()
        read_topic()
        publish()
    }
    class Catalogue
    class LlmProxy {
        start()
        stop()
    }
    class Guard {
        prompt
        verbs
        matcher
    }

    BridgeServer --> Catalogue
    LlmProxy *-- Guard
    Guard ..> Catalogue : made from
    BridgeServer --> Robot
    BridgeServer ..> Session : one per browser
    Session --> Planner
    Session *-- Confirmation
    Session *-- PhraseMatcher
    Session --> Robot
    Planner --> Catalogue
    Planner --> Robot
    Robot <|.. RosbridgeRobot
    RosbridgeRobot --> Rosbridge

    style BridgeServer fill:#ccfbf1,stroke:#0d9488,stroke-width:2px,color:#134e4a
    style LlmProxy fill:#ccfbf1,stroke:#0d9488,stroke-width:2px,color:#134e4a
    style Guard fill:#ccfbf1,stroke:#0d9488,stroke-width:2px,color:#134e4a
    style Session fill:#7c3aed,stroke:#5b21b6,stroke-width:2px,color:#ffffff
    style Planner fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    style Confirmation fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    style PhraseMatcher fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    style Robot fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
    style RosbridgeRobot fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
    style Rosbridge fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
    style Catalogue fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a
```

Three small values travel between them. A `Request` is a call with its templates filled in: exactly what goes to rosbridge. A `Prepared` is a command with everything decided: its checked arguments, its read-back sentence and its `Request`. An `Outcome` is how a request ended: ok or not, the robot's message, and, for a read, its value.

## Inside a Session

A `Session`, in [`session.py`](../src/voicebridge/session.py), is the only place where the rules live. It has no WebSocket: it gets events through `from_browser` and `from_upstream`, and sends them through two functions it was given, `to_browser` and `to_upstream`. The tests give it two lists.

### The Events It Reads

From the browser, it changes two things. Every `session.update` gets the robot's tools and the LLM's instructions added, and `tool_choice: auto`, so that the robot's tools survive whatever the browser does with its own, e.g. switching its web search off. And when the robot file has a `greeting`, the browser's opening message, the demo's "start the conversation with a greeting", is replaced by the greeting, "Ready." for StepIt Macro, said as written; once we have spoken, a typed message goes to the LLM as usual. Everything else passes unchanged.

From the speech server, each event goes through these questions, in order:

```mermaid
---
config:
  theme: base
  flowchart:
    curve: basis
    padding: 12
    nodeSpacing: 46
    rankSpacing: 32
    subGraphTitleMargin:
      top: 4
      bottom: 10
  class:
    padding: 10
  themeVariables:
    lineColor: "#94a3b8"
    textColor: "#64748b"
    primaryColor: "#f1f5f9"
    primaryBorderColor: "#64748b"
    primaryTextColor: "#0f172a"
    secondaryColor: "#f1f5f9"
    secondaryBorderColor: "#64748b"
    secondaryTextColor: "#0f172a"
    tertiaryColor: "#f1f5f9"
    tertiaryBorderColor: "#64748b"
    tertiaryTextColor: "#0f172a"
    mainBkg: "#f1f5f9"
    nodeBorder: "#64748b"
    nodeTextColor: "#0f172a"
    classText: "#0f172a"
    clusterBkg: "transparent"
    clusterBorder: "#94a3b8"
    titleColor: "#64748b"
    edgeLabelBackground: "#ffffff"
  themeCSS: >
    .node rect, .node polygon, .node path {
      filter: drop-shadow(0 3px 6px rgba(15, 23, 42, 0.18));
    }
    .node rect { rx: 14px; ry: 14px; }
    .cluster rect { rx: 18px; ry: 18px; }
    .edgeLabel, .edgeLabel p, .edgeLabel span {
      background: #ffffff; color: #475569; border-radius: 999px;
    }
    .edgeLabel p { padding: 3px 10px; }
    .labelBkg { background: transparent !important; fill: none !important; }
---
flowchart TB
    Event(["<b>An event from the speech server</b>"])
    Muted("Part of a reply<br/>the bridge muted?")
    Drop("<b>Dropped</b>")
    Said("A transcript<br/>of the user?")
    Hear("<b>Forwarded, then:</b><br/>stop, yes, no or other")
    Call("A finished call<br/>of a robot command?")
    Prepare("<b>Hidden; prepared</b><br/>in the background")
    Part("Another part<br/>of a robot call?")
    Hide("<b>Hidden</b>")
    Forward("<b>Forwarded to the browser</b>")

    Event --> Muted
    Muted -- "yes" --> Drop
    Muted -- "no" --> Said
    Said -- "yes" --> Hear
    Said -- "no" --> Call
    Call -- "yes" --> Prepare
    Call -- "no" --> Part
    Part -- "yes" --> Hide
    Part -- "no" --> Forward

    classDef human fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#881337
    classDef voice fill:#ccfbf1,stroke:#0d9488,stroke-width:2px,color:#134e4a
    classDef mind  fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    classDef brain fill:#7c3aed,stroke:#5b21b6,stroke-width:2px,color:#ffffff
    classDef robot fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
    classDef data  fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a
    classDef ext   fill:#f1f5f9,stroke:#64748b,stroke-width:2px,color:#0f172a

    class Event voice
    class Muted,Said,Call,Part mind
    class Drop human
    class Hear,Forward voice
    class Prepare brain
    class Hide ext

    linkStyle 0,2,4,6,8 stroke:#94a3b8,stroke-width:2px
    linkStyle 1 stroke:#f43f5e,stroke-width:2px
    linkStyle 3 stroke:#14b8a6,stroke-width:2px
    linkStyle 5 stroke:#7c3aed,stroke-width:3px
    linkStyle 7 stroke:#64748b,stroke-width:2px
```

A robot call is hidden in every form the server sends it: `response.output_item.added` and `.done`, the argument deltas, which name neither the tool nor the item but only its ids, which the session remembers, and the copy inside `response.done`. The browser's own tool executor knows only its own tools: it would answer "unknown tool", racing the bridge.

### The Bridge's Own Replies

The bridge speaks by asking the server for a reply: a `response.create` whose `instructions` carry the sentence between the tags `<voicebridge-say>` and `</voicebridge-say>`, with `tool_choice: none`. The server builds its LLM request with those instructions, and the proxy, finding the tags, answers with the sentence itself. Four rules keep these requests from colliding with the server's own work:

- **Tagged.** Each request carries `metadata: {voicebridge: vb-<n>}`, which the server echoes in `response.created` and `response.done`. The bridge tells its replies from the server's by the tag, never by timing.
- **Queued, one at a time.** A reply is sent only when no response is in progress; the next waits for the `response.done` of the one before. A server that refuses one, `conversation_already_has_active_response`, gets it again at its next `response.done`, and the browser never sees the error.
- **Tool answers first.** The server refuses a reply while a tool call has no answer, so the `function_call_output` of every call is sent before any `response.create`, and no reply is asked for while a call is still being prepared.
- **Checked.** For a read-back, the bridge collects what the voice said, from `response.output_audio_transcript.done`, and checks it at the `response.done`. Through the proxy it is always the sentence; the check catches a speech server that reaches its LLM directly.

### Muting the Server's Reply

The speech server answers every turn of the user by itself: VAD, STT, LLM and TTS run as one pipeline, and there is no option to stop it. When the bridge answers a turn itself, after a yes, a no, a late yes or a stop, it must silence that answer: otherwise the LLM might say "Done!" before anything ran, or call a tool again. So the bridge sends `response.cancel`, and for the next 10 seconds mutes and cancels any reply it did not ask for. A new turn, `input_audio_buffer.speech_started`, ends the mute at once: what the server says after it answers the new turn.

## The LLM Proxy

The speech server sends every reply through its LLM: there is no event that makes it say a fixed text. And an LLM asked to "say exactly" a sentence sometimes says another, or answers a command in words without calling it: "I can do that. Moving the camera closer by 10 millimetres.", while nothing moves. The proxy, in [`llmproxy.py`](../src/voicebridge/llmproxy.py), takes the LLM's place for the speech server, so that the bridge decides what reaches the model and what comes back. For each request of the speech server, in order:

1. **A sentence of the bridge** in the instructions, between the tags: the proxy answers with it, and the model is not asked.
2. **A request without tools**, e.g. a summary the speech server asks for on its own: passed through as it is.
3. **The speech server's follow-up** after the bridge answered a command, a request that ends with the tool's output: answered with nothing, as the bridge speaks next. A rejection is the exception: the model explains it.
4. **A turn of yes, no or stop**, by the same word lists as the session: answered with nothing, as the bridge answers it.
5. **Any other turn**: the model is asked for one decision, below.

The proxy also replaces the model a request names with the one given to `voicebridge serve --llm-model`, for every request, the passed-through ones included: with llama-swap, a request naming another model would unload the voice's model and load that one.

### One Decision per Turn

The proxy removes the tools from the request, lists the commands in the instructions, and asks for a JSON object of this schema, as `response_format`:

```json
{"oneOf": [
  {"properties": {"command": {"const": "move_camera"}, "arguments": {"properties": {"millimetres": {"type": "number"}, "direction": {"enum": ["closer", "farther"]}}}}},
  {"properties": {"command": {"const": "take_test_shot"}, "arguments": {}}},
  {"properties": {"reply": {"type": "string", "maxLength": 200}}}
]}
```

A server that enforces the schema, as llama.cpp does with a grammar, can only produce one of these: the model cannot answer a command in loose words. The proxy turns a command into the tool call the speech server expects, and a reply into its words. A command and a reply never come together, so the user hears only the bridge's read-back about a command.

A reply can still pretend. The proxy refuses a reply that asks to confirm, or that says the robot is acting with a verb of the robot's own sentences, e.g. "moving", "taking", "switching": the verbs come from the `say` and `started` templates of the robot file, plus "turning" and "done". It then asks again with the commands only, which the schema leaves the model no way out of. If no command comes back, e.g. from a server that ignores the schema, the voice says "Sorry, I did not get that as a command. Please say it again."

### What the Model Never Sees

A model that has heard the bridge read commands back starts doing it itself: after a few turns it answers "Switching the lights on. Confirm?" without calling the command. So the proxy removes from the history every sentence it said in the model's place, the read-backs, outcomes and greeting, before it asks the model. The model sees our requests and its own calls, never the bridge's words. And it never sees the turn of a yes, a no or a stop, which the proxy answers with nothing.

## Talking to the Robot

[`rosbridge.py`](../src/voicebridge/rosbridge.py) is a client of [rosbridge's protocol](https://github.com/RobotWebTools/rosbridge_suite/blob/ros2/ROSBRIDGE_PROTOCOL.md), with the operations of StepIt UI's `rosbridge.ts`: `call_service`, `send_action_goal` and `cancel_action_goal`, `subscribe` for one message, and `publish`. It connects on first use, and again after the connection drops, e.g. while the rig restarts. It never repeats a request: a goal whose end is unknown fails, so that we are told rather than misled.

[`robot.py`](../src/voicebridge/robot.py) turns a call into a `Request` with `render_request`, and an answer into an `Outcome` with `judge`, by the call's `success`, `message` and `result` templates. They see `response`, the answer, and `status`, the GoalStatus of an action. Without `success`, an action succeeded when its status is 4 and a service whenever it answered.

| Timeout | Default | Where |
|---|---|---|
| Connecting to rosbridge | 3 s | `Rosbridge(connect_timeout_s)` |
| A service | 10 s | `timeout_s` of the call |
| A latched topic | 3 s | `read_latched_topic` |
| An objective | 2 hours | `objective` in StepIt Macro's file: a stack of 350 pictures takes about half an hour |
| A goal that runs out of time | cancelled | `send_action_goal` sends `cancel_action_goal` |

## Threads and Time

There is one thread and one asyncio event loop. The WebSocket servers and clients, the sessions, the LLM proxy, an aiohttp server and client, and the rosbridge client all run on it. A command that runs, e.g. a focus stack of half an hour, is an asyncio task of its session, so the session keeps reading events, and hears "stop", while it runs. Closing a session cancels its tasks; cancelling the task of a goal sends `cancel_action_goal`.

There is no second thread because there is no rclpy: a ROS 2 node would need its own thread for `rclpy.spin`, and a pool of threads for the commands that block. Through rosbridge, the robot is one more WebSocket on the same loop.

## Tests

`./docker/dock.sh test` runs [`bin/test.sh`](../bin/test.sh), as CI does: ruff, `voicebridge check` of every robot file, and pytest. The tests need no ROS, no speech server and no LLM: they use a fake robot, a fake rosbridge server, a fake speech server and a fake LLM. The session and server tests use a made-up robot, [`tests/robots/arm.yaml`](../tests/robots/arm.yaml), which also shows that nothing in the bridge is StepIt's.

| Test | What it covers |
|---|---|
| `test_session.py` | Every safety rule: the read-back and the yes, no, anything else, a late yes, a yes over the read-back, a wrong or interrupted read-back, stop alone and inside a sentence, stop over the bridge's own speech, rejected arguments, commands without confirmation, queries, one command per answer, a busy server, the muted reply and a call inside it, a yes with nothing waiting, the greeting, closing during a command. |
| `test_llmproxy.py` | The proxy against a fake LLM: the bridge's sentences said without the model, the JSON schema and its decisions, a pretended action or read-back asked again, yes, no and stop kept from the model, the history without the bridge's sentences, the skipped follow-up, the chosen model, pass-through. |
| `test_confirmation.py` | The state machine, with a fake clock. |
| `test_phrases.py` | What counts as yes, no and stop, and what does not, e.g. "yes but 20 degrees", "right". |
| `test_catalogue.py` | The robot file: short forms, the tool of the LLM, the check of arguments, and each mistake the loader finds. |
| `test_templating.py` | Typed results, the filters, the sandbox, undefined names. |
| `test_planner.py` | The order of `prepare`, reads, refusals, outcome sentences. |
| `test_rosbridge.py` | The client against a fake rosbridge: services, goals and their cancellation, latched topics, fragments, a lost connection; how an objective is judged. |
| `test_realtime.py` | Injecting the tools, finding and hiding robot calls, tags. |
| `test_server.py` | The whole bridge over real WebSockets: a browser with the Agents SDK's subprotocols, a fake speech server and a fake rosbridge, from the tool call to the goal. |
| `test_stepit_macro.py` | StepIt Macro's file: every example prepares; left is counter-clockwise and negative, closer is negative; the plan of a stack, its marks, the lights' bits; no power off; `commands.md` is up to date. |

Not tested automatically, and how to check it by hand:

- **The LLM's understanding.** `voicebridge eval` scores it on the examples through the bridge's proxy, as the bridge asks, and on phrases of our own with `--say`. Bonsai 2 27B on llama.cpp understood 35 of 35 examples, and 10 of 10 requests replayed after a history in which the LLM had pretended; Qwen3.8-27B on llama.cpp did the same. With the rule against guessing, both ask back for "move the camera closer"; Qwen3.8-27B still chose a direction for "turn the table 20 degrees".
- **The real rig.** `voicebridge run` sends one command through rosbridge. Every command of StepIt Macro was run on the rig with its fake hardware; `TakeShot` and `FocusStack` fail there, as the fake camera does not see the fake Freezer's shots.
- **The real speech server and the voice.** Checked by voice with Bonsai: 15 commands read back, confirmed and run, a "no" that cancelled, a missing value asked for, and "stop it" during a test shot. The read-back, the mute and the tags rely on the events of the speech server's code. Talk to the rig as in the README, and watch the bridge's log, which names every decision of the LLM, every sentence of the bridge, every proposal, answer and outcome.
- **WebRTC.** Not supported: see [Design Decisions and Trade-offs](#design-decisions-and-trade-offs).

## How to Extend StepIt Speech

**Add a command.** Copy one that looks like it in the robot file, change it, and run `voicebridge check`; the [README](../README.md#adding-a-command) has the steps. Add `examples`: they teach the LLM, test the command, and fill `commands.md`. Regenerate `commands.md` and restart the bridge.

**Add a call.** When a command needs a part of the robot no call reaches, add a call under `calls`: one of `action`, `service`, `topic` (a read) or `publish`, its `type`, its `request` with templates for the values commands give it, and `success` and `message` when the answer says more than "it answered". A call of a standard ROS 2 interface belongs in `src/voicebridge/calls.yaml`, for every robot.

**Add a filter.** When a template would be hard to read without one, e.g. `plural`, add it to `_make_environment` in `templating.py`, with a test. Keep the robot files readable by someone who does not know Jinja2.

**Drive another robot.** Write its robot file and start the bridge with it. Nothing in `src/voicebridge` names a robot.

**Move StepIt Macro's file into the rig.** The file can live in stepit-macro, next to `rig.yaml`, with this project as a module of the rig: the bridge only needs its path.

**Add a transport.** A WebRTC browser would need the bridge to be the WebRTC peer, or the speech server to offer a hook: the `Session` would not change, as it only sees events.

## Design Decisions and Trade-offs

**rosbridge, not rclpy.** The bridge reaches the robot through rosbridge, which StepIt Commander runs on port 9090 for StepIt UI already. It needs no ROS installation, no DDS configuration and no second thread, runs anywhere, and is tested without ROS. The price: a message type rosbridge does not know fails at run time, not at start, and every request is a JSON round trip through one more program.

**YAML templates, not Python plugins.** A command could be a Python class, discovered as a plugin. Here a command is a dozen lines of YAML: anyone who can read the rig's objectives can add one, and the loader checks it before anything runs. The price: a command that needs real logic, e.g. a loop, does not fit; it becomes an objective of the commander, which is where the logic of the rig belongs anyway.

**One choice per command.** Each command is a choice of its own in the schema, with the schema of its parameters, and a tool of its own for the speech server, not one generic command with a name. The schema guides the values, e.g. a direction is one of two words. The price: the LLM's prompt grows with the commands: for StepIt Macro's fifteen, the tools are about 6,300 characters and the instructions 1,800.

**The bridge answers for the LLM, rather than speaking itself.** The bridge has no voice of its own: only the speech server's TTS speaks, and it speaks what its LLM writes. So the bridge became the speech server's LLM, and answers with its own sentences when it has one. The voice says them exactly, in the same voice as the rest. A TTS in the bridge would be exact too, at the price of a second voice and a second model on the GPU. The price of the proxy: the speech server must be configured to reach its LLM through the bridge.

**A JSON schema, not tool calls.** Forcing a tool call, `tool_choice: required`, would also stop the model from answering in words, but servers do not all enforce it: azllm ignores it, and llama.cpp leaves it unenforced with the chat template of Qwen3.8, where the model answered "I'll switch the lights on for you" and called nothing. A JSON schema is enforced by llama.cpp's grammar whatever the template. The price: the LLM server must support `response_format` of type `json_schema`, and the proxy translates between the schema and the speech server's tool calls.

**Bonsai 2 27B on llama.cpp.** PrismML's ternary build of Qwen3.8-27B is 7.6 GB, against 17.6 GB for Qwen3.8-27B in 4 bits, and was as accurate on our tests, in about half a second per answer. It leaves 10 GB of the 24 GB GPU free, where Qwen left the voice so little that it once crashed. The price: it needs upstream llama.cpp b11555 or newer, and PrismML lists malformed tool calls among its known issues, which the JSON schema avoids.

**Fixed words for yes, never the LLM.** Whether we confirmed is decided by matching our transcript against lists of the robot file. An LLM would understand "go on then"; it would also find a yes where there is none. The price: a yes not on the list cancels, and we say it again.

**Stop anywhere, at once.** A stop word anywhere in a sentence stops the robot, before the LLM has heard it. The price: "stop" can never be part of another command; "stop the live view" also stops the rig, then stops the live view.

**Muting the server's reply, not preventing it.** The speech server answers every turn, and has no option to let a client decide. The bridge cancels and mutes the reply to a turn it answers itself. The price: with speculative turns, the first audio of that reply may reach the browser before the transcript does; it is cut, but can be heard for a moment.

**A session cancels its goals when it ends.** A tab that closes during a focus stack stops it. We cannot stop by voice a robot whose session is gone, so the bridge does not let one move. The price: a long stack needs the page to stay open, as StepIt UI's sliders do.

**Read the robot each time, keep nothing.** A command that needs the robot's state, e.g. the plan of a stack, reads it before its read-back, every time. The bridge keeps no copy that could be stale. The price: a read before the read-back, a few milliseconds.

**`commands.md` is generated.** The list of commands is written from the robot file, by preparing every example, and a test fails when it is out of date. It cannot drift from what the bridge does. The price: its wording is that of the generator, and the robot file is the place to change it.
