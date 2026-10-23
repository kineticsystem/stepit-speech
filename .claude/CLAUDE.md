# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

StepIt Speech2Speech drives a ROS 2 robot by voice. Its package, `voicebridge` in `src/voicebridge`, is a WebSocket bridge between the browser demo of Hugging Face Speech-to-Speech and its server (OpenAI Realtime API events), which adds the robot's commands as tools of the LLM, reads every command back, hears the yes itself, and runs the command on the robot through rosbridge. The architecture is in `docs/ARCHITECTURE.md`.

**The LLM proposes, the bridge decides.** Never let the LLM decide whether the user confirmed, and never run a command that was not read back exactly and confirmed, except the stop command and queries (`confirm: false`). The rules are listed in `docs/ARCHITECTURE.md`, "The Safety Rules", each with a test in `tests/test_session.py`: a change to the session keeps them, and a new rule gets a test.

**Generic.** Nothing in `src/voicebridge` names a robot. Everything about one is its robot file, `robots/<robot>/robot.yaml`: its commands (anyone writes them) and its calls (how they reach it over rosbridge). Calls of standard ROS 2 interfaces go in `src/voicebridge/calls.yaml`. StepIt Macro's file will move into the stepit-macro repository; keep it working on its own.

## Working environment

Everything is built and tested in the image of `docker/Dockerfile`, as CI does; no ROS is needed.

```bash
./docker/dock.sh build    # the image
./docker/dock.sh test     # bin/test.sh: ruff, voicebridge check of every robot file, pytest
./docker/dock.sh serve    # the bridge, on the host's network
./docker/dock.sh shell
```

A virtual environment works too: `uv venv && uv pip install -e '.[dev]' && bin/test.sh`.

- `voicebridge check <robot file>` prepares every example without a robot.
- `voicebridge docs robots/stepit-macro/robot.yaml -o robots/stepit-macro/commands.md` regenerates the list of commands: `test_commands_md_is_up_to_date` fails when it is stale. Regenerate it after every change of the robot file.
- `voicebridge run <robot file> <command> name=value...` runs one command on the robot, asking first.
- `voicebridge eval <robot file>` scores the LLM on the examples (llama-swap on `http://localhost:8085/v1`, model `azllm-text`); not in CI.

A test that talks to a robot uses the fakes of `tests/conftest.py`, never the real rig. Run commands on the real rig only with fake hardware (`use_dummy`, `fake`, `use_fake` in stepit-macro's `rig.yaml`), unless the user asks otherwise, and restore any state changed, e.g. the plan of the stack.

## Conventions

- Every source file carries the MIT copyright header and SPDX line.
- ruff, line length 120 (`pyproject.toml`). Python 3.10 or newer.
- The robot file is for people who do not know Python: keep its templates short, add a filter to `templating.py` rather than a long expression, and keep the loader's error messages pointing at the key that is wrong.
- Docs follow the write-docs house style; British spelling.

## Pull Request Notes

Each pull request has a notes file in [docs/pr/](../docs/pr/README.md): what we discussed, what we chose, and why. One file per pull request, written while the branch is open. Keep them simple: short sentences, one idea per paragraph, and a Mermaid diagram when it explains faster than words.
