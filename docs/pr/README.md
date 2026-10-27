# Pull Request Notes

Each pull request has a notes file here. It keeps what the pull request does not: what we discussed, what we chose, and why.

## The Notes

| Note | Pull request |
|---|---|
| [001-first-version.md](001-first-version.md) | [#1](https://github.com/kineticsystem/stepit-speech/pull/1) The voice bridge, with StepIt Macro's commands |
| [002-split-voicebridge.md](002-split-voicebridge.md) | [#2](https://github.com/kineticsystem/stepit-speech/pull/2) Refactor: split voicebridge into parts by function |
| [003-bundled-llm.md](003-bundled-llm.md) | [#3](https://github.com/kineticsystem/stepit-speech/pull/3) Run Bonsai on llama.cpp from the project, started with the bridge |

## How to Write One

- One file per pull request: `<number>-<branch>.md`, e.g. `002-new-command.md`. Before it has a number, use the branch name.
- Sections: **Goal**, **Decisions**, **Left Out**, **Open Items**. Skip the ones that do not apply.
- Short sentences. One idea per paragraph. A diagram when it explains faster.
- Write it while the branch is open. Do not rewrite it after the merge.
