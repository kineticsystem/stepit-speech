# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The voice conversation: the bridge between the browser and the speech server.

- ``server``: the WebSocket server, one ``Session`` per browser.
- ``session``: the safety rules: read-back, yes, no, stop, hidden tool calls.
- ``speaker``: how the bridge's sentences reach the voice, and the server's own replies are muted.
- ``events``: pure functions on the events of the OpenAI Realtime API.
- ``prompt``: the LLM's instructions.
"""
