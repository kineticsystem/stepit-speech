# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""From a tool call to the robot and back.

- ``planner``: a tool call becomes a ``Prepared`` command: checked, read back, and its request.
- ``request``: a ``Request``, an ``Outcome``, and the ``Robot`` port the rest of the bridge talks to.
- ``rosbridge_robot``: the real ``Robot``, over rosbridge.
- ``rosbridge``: the client of rosbridge's protocol.
"""
