# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The LLM proxy: the speech server asks its LLM through here.

- ``proxy``: the HTTP server, and the order in which it answers a request.
- ``decision``: the request for one JSON decision, and its answer as words or one tool call.
- ``guard``: a reply that pretends to act, or asks to confirm.
- ``chat``: reading and writing the messages of chat completions.
"""
