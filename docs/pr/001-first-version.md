# 001: The Voice Bridge, with StepIt Macro's Commands

## Goal

Drive StepIt Macro by voice, safely: every command is read back and runs only after a spoken yes. Build it so that another robot needs only a new robot file.

## Decisions

**The LLM proposes, the bridge decides.** The LLM only turns words into a command. The bridge checks the values, reads the command back, checks that the voice said it exactly, and decides yes, no or stop from the transcript with fixed word lists.

**The read-back is the program's, not the LLM's.** The first test by voice showed the LLM paraphrasing the read-back, and answering commands in words, "I can do that, moving the camera closer", while nothing moved. The speech server sends every reply through its LLM, so the bridge became its LLM too: a proxy on port 8767 answers with the bridge's sentences itself, word for word.

**One JSON decision per turn.** The proxy asks the model for `{"command": ..., "arguments": ...}` or `{"reply": ...}`, in a JSON schema the LLM server enforces. Forcing a tool call was not enough: azllm ignores `tool_choice: required`, and llama.cpp leaves it unenforced with Qwen3.8's chat template. A reply that asks to confirm or claims an action is asked again with commands only.

**The model never sees the bridge's words.** After a few read-backs, the model started saying "Switching the lights on. Confirm?" itself, and the yes confirmed nothing. The proxy now removes the bridge's sentences from the history, and never passes on a yes, a no or a stop: the bridge answers those, including a yes with nothing waiting.

**Bonsai 2 27B on llama.cpp.** We compared three LLMs with the 35 examples and the replay of a session in which the LLM had pretended:

| LLM | GPU, with the voice | Examples | Replay |
|---|---|---|---|
| Bonsai 2 27B, ternary, llama.cpp b11840 | 14.5 GB | 35 of 35 | 10 of 10 |
| Qwen3.8-27B, 4 bits, llama.cpp | 23.7 GB | 35 of 35 | 10 of 10 |
| Qwen3.8-27B, azllm | 23.0 GB | answers in words | answers in words |

Bonsai is as accurate and as fast, about half a second, and leaves 10 GB free: with Qwen, the voice once crashed for lack of memory.

**"Confirm?" and "Ready."** The read-back ends with "Confirm?", shorter than "Say yes to confirm.". The robot file's `greeting`, "Ready.", replaces the LLM's greeting, and the LLM's rules forbid small talk.

**The name.** The repository is `stepit-speech`, the project StepIt Speech.

**rosbridge, not rclpy.** StepIt Commander already runs rosbridge for StepIt UI. The bridge needs no ROS, no DDS and no second thread, and its tests run without ROS.

**A command is YAML, not a Python package.** A command is a description, its parameters, the sentence to read back, what to run and examples. How it reaches the robot, the calls, is written once per robot. The loader checks the whole file at start and names the mistake.

**Left is counter-clockwise, and negative.** StepIt Macro counts counter-clockwise as negative (`docs/RotateStageBy.md`). "Rotate 10 degrees left" sends `deg: -10.0`, and the read-back says "counter-clockwise", never a sign.

**Stop anywhere.** A stop word anywhere in a sentence stops the rig at once, without the LLM. A stop heard by mistake costs nothing.

**`commands.md` is generated** from the robot file, by preparing every example, and a test keeps it up to date.

## Left Out

**Switching the rig off.** Too much for a voice; it stays on StepIt UI's held button.

**MoveJointsDirectlyTo, OffsetJointsDirectlyBy, ActivateController, Stack.** They take raw radians and controller names, for developers.

**WebRTC.** Its events do not go through a WebSocket the bridge can sit on. The demo uses WebSocket by default.

## Open Items

**The direction the user did not say.** Qwen3.8-27B chose one for "turn the table 20 degrees" and "move the camera 3 mm". The read-back catches it, as it says the direction. A rule in the robot file could require that a chosen word was heard.

**A self-contained project.** The LLM is served by llama-swap of another repository. `TODO.md` plans to build llama.cpp and download Bonsai inside this project.

**Confirm by "yes".** The speech-to-text heard "confirm" as "Koncern", which cancels the command. "Yes" is heard reliably.

**The commander's failure messages.** A failed objective returns "Tree finished with status: FAILURE", without the reason, which is only in the rig's log. The voice says "That did not work." The commander could return the message of the failed node.
