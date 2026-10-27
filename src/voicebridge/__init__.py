# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""voicebridge: drive a ROS 2 robot by voice. The LLM proposes, the bridge decides.

Its parts, from the bottom up; a part imports only from the parts above it in this list:

- ``robotfile``: the robot file, loaded and checked, and its templates.
- ``safety``: yes, no and stop from fixed words, and the pending command's state machine.
- ``robot``: a tool call prepared into a command, and run on the robot through rosbridge.
- ``scripted``: the tags of a sentence of the bridge, shared by ``conversation`` and ``llmproxy``.
- ``conversation``: the WebSocket bridge and the session that holds the safety rules.
- ``llmproxy``: the speech server's LLM: the bridge's sentences, and one JSON decision per turn.
- ``tools``: ``check``, ``docs``, ``run`` and ``eval``.
- ``cli``: the command line, and the wiring of ``voicebridge serve``.

See docs/ARCHITECTURE.md.
"""
