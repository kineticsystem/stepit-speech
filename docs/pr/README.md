# Pull Request Notes

Each pull request has a notes file here. It keeps what the pull request does not: what we discussed, what we chose, and why.

## The Notes

| Note | Pull request |
|---|---|
| [001-first-version.md](001-first-version.md) | [#1](https://github.com/kineticsystem/stepit-speech/pull/1) The voice bridge, with StepIt Macro's commands |
| [002-split-voicebridge.md](002-split-voicebridge.md) | [#2](https://github.com/kineticsystem/stepit-speech/pull/2) Refactor: split voicebridge into parts by function |
| [003-bundled-llm.md](003-bundled-llm.md) | [#3](https://github.com/kineticsystem/stepit-speech/pull/3) Run Bonsai on llama.cpp from the project, started with the bridge |
| [004-summary-off.md](004-summary-off.md) | [#4](https://github.com/kineticsystem/stepit-speech/pull/4) No summaries of older turns: the proxy writes them, without the model |
| [005-todo-hands-free.md](005-todo-hands-free.md) | [#5](https://github.com/kineticsystem/stepit-speech/pull/5) TODO: hands-free control from a phone in a pocket |
| [006-mdns-hosts.md](006-mdns-hosts.md) | [#6](https://github.com/kineticsystem/stepit-speech/pull/6) Resolve .local names on the host for the bridge's container |
| [007-hands-free.md](007-hands-free.md) | [#7](https://github.com/kineticsystem/stepit-speech/pull/7) Hands-free: the Android app, sleep mode and the whole voice in serve |
| [008-loudspeaker.md](008-loudspeaker.md) | [#8](https://github.com/kineticsystem/stepit-speech/pull/8) Loudspeaker, a clip-on microphone and shorter read-backs |

## How to Write One

- One file per pull request: `<number>-<branch>.md`, e.g. `002-new-command.md`. Before it has a number, use the branch name.
- Sections: **Goal**, **Decisions**, **Left Out**, **Open Items**. Skip the ones that do not apply.
- Short sentences. One idea per paragraph. A diagram when it explains faster.
- Write it while the branch is open. Do not rewrite it after the merge.
