# 001: The Voice Bridge, with StepIt Macro's Commands

## Goal

Drive StepIt Macro by voice, safely: every command is read back and runs only after a spoken yes. Build it so that another robot needs only a new robot file.

It follows s2s-ros2, which ran a command as soon as the LLM produced it.

## Decisions

**The LLM proposes, the bridge decides.** The LLM only turns words into a tool call. The bridge checks the values, reads the command back, checks that the voice said it exactly, and decides yes, no or stop from the transcript with fixed word lists.

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

**The direction the user did not say.** Qwen3.8-27B still chooses one for "turn the table 20 degrees" and "move the camera 3 mm". The read-back catches it, as it says the direction. A rule in the robot file could require that a chosen word was heard.

**A run with the real speech server.** The bridge was tested with a fake speech server, and on the rig with fake hardware, but not yet with the speech server, a microphone and the voice.

**The commander's failure messages.** A failed objective returns "Tree finished with status: FAILURE", without the reason, which is only in the rig's log. The voice says "That did not work." The commander could return the message of the failed node.
