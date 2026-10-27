# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

StepIt Speech drives a ROS 2 robot by voice. Its package, `voicebridge` in `src/voicebridge`, is a WebSocket bridge between the browser demo of Hugging Face Speech-to-Speech and its server (OpenAI Realtime API events), which adds the robot's commands as tools of the LLM, reads every command back, hears the yes itself, and runs the command on the robot through rosbridge. It is also the speech server's LLM: its proxy (the package `llmproxy`, port 8767) says the bridge's sentences without the model, and asks the model for one JSON decision per turn, a command or a reply, enforced by the LLM server's JSON schema. The architecture is in `docs/ARCHITECTURE.md`.

The package is split by function: `robotfile`, `safety`, `robot`, `scripted`, `conversation`, `llmproxy`, `tools` and `cli`, each importing only the parts below it (`tests/test_layers.py`). Put new code in the part that owns its job, give a module one job, and update `ALLOWED` in the test and the architecture document when a part's imports change.

**The LLM proposes, the bridge decides.** Never let the LLM decide whether the user confirmed, never let it write a sentence of the bridge (read-backs, outcomes, the greeting go through `scripted.exact_speech` and the proxy), and never run a command that was not read back exactly and confirmed, except the stop command and queries (`confirm: false`). The rules are listed in `docs/ARCHITECTURE.md`, "The Safety Rules", each with a test in `tests/test_session.py`: a change to the session keeps them, and a new rule gets a test.

**Generic.** Nothing in `src/voicebridge` names a robot. Everything about one is its robot file, `robots/<robot>/robot.yaml`: its commands (anyone writes them) and its calls (how they reach it over rosbridge). Calls of standard ROS 2 interfaces go in `src/voicebridge/robotfile/calls.yaml`. StepIt Macro's file will move into the stepit-macro repository; keep it working on its own.

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
- `voicebridge eval <robot file>` scores the LLM on the examples, through the running bridge's proxy (`http://localhost:8767/v1`, model `stepit-macro-bonsai`); not in CI.

The LLM must enforce a JSON schema (`response_format`): llama.cpp does, azllm does not. The voice uses Bonsai 2 27B on upstream llama.cpp, served for now by llama-swap of `~/repo/qwen-4090-bench`, entry `stepit-macro-bonsai`; `TODO.md` plans to bring the model and llama.cpp into this repository.

A test that talks to a robot uses the fakes of `tests/conftest.py`, never the real rig. Run commands on the real rig only with fake hardware (`use_dummy`, `fake`, `use_fake` in stepit-macro's `rig.yaml`), unless the user asks otherwise, and restore any state changed, e.g. the plan of the stack.

## Conventions

- Every source file carries the MIT copyright header and SPDX line.
- ruff, line length 120 (`pyproject.toml`). Python 3.10 or newer.
- The robot file is for people who do not know Python: keep its templates short, add a filter to `robotfile/templating.py` rather than a long expression, and keep the loader's error messages pointing at the key that is wrong.
- Docs follow the write-docs house style; British spelling. Mermaid diagrams follow the beautiful-mermaid-diagrams skill instead of write-docs' blue style: colors by role, compact, readable in light and dark mode.
- A diagram shown as an image has its source in `docs/diagrams/<name>.mmd`: change the source, run `bin/render-diagrams.sh` (outside the container: it needs Node.js and Chrome), and commit both. `tests/test_diagrams.py` fails when an SVG is older than its source. The diagrams of the README and of the architecture document are all shown this way.

## Pull Request Notes

Each pull request has a notes file in [docs/pr/](../docs/pr/README.md): what we discussed, what we chose, and why. One file per pull request, written while the branch is open. Keep them simple: short sentences, one idea per paragraph, and a Mermaid diagram when it explains faster than words.
