# TODO

## Later

- **Start the speech server from this project too**, so that one command starts the whole voice: the speech server, llama-server and the bridge, as `docker/compose.yaml` already starts the last two.
- **Check the LLM on the GPU computer** after each new release of the submodule: `voicebridge eval` must still score 35 of 35.
- **Remove the dependency on StepIt Macro**: its robot file moves into the stepit-macro repository, and this project becomes a module of the rig.
- **Check whether [Pydantic AI](https://pydantic.dev/docs/ai/) helps.** It could replace the call of the proxy to the LLM, not the safety gate. First findings, from its documentation (version 2.60):
  - It needs Python 3.11; we support 3.10.
  - `NativeOutput([Command, Reply])` asks for a JSON schema through `response_format`, as `llmproxy.structured` does. Our commands come from the robot file, so their models would be built at run time. Check that llama.cpp gets a strict schema from it.
  - An output validator raising `ModelRetry` could replace our second ask when the LLM pretends (`commands_only`).
  - Its approvals (`requires_approval`, `DeferredToolRequests`) need a tool call, which llama.cpp does not enforce with our model, and after the approval the model speaks again. Both break our rules: the gate stays ours.
  - It is a client. The proxy still serves the speech server's OpenAI API and turns the decision back into a tool call.
  - It brings opentelemetry, pydantic-graph and httpx with it.

  Try it on a branch, on `_ask` of `llmproxy/proxy.py` only: keep it if it removes code and `voicebridge eval` still scores 35 of 35; otherwise note why here and drop it.
- **Try a shorter history on the GPU computer.** The speech server keeps the last 30 turns. Our commands stand alone, so `--chat_size 8` might be enough, with shorter prompts and fewer old turns to imitate: keep it if `voicebridge eval` still scores 35 of 35 and a voice session of more than 8 turns still works.
- **"Stop it" stops twice**: the bridge stops the rig, and the sentence also goes to the LLM, which calls `stop` again. Harmless; "it" could become a filler.
