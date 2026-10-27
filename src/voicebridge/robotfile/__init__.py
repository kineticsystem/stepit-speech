# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The robot file: everything the bridge knows of a robot.

- ``model``: the commands, calls and settings, as frozen dataclasses.
- ``loader``: reads a robot file and checks all of it.
- ``templating``: the Jinja2 templates of its values, sandboxed and typed.
- ``calls.yaml``: the calls of standard ROS 2 interfaces, for every robot.
"""
