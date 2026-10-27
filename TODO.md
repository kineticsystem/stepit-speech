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
- **Keep a short history, without summaries.** The speech server keeps the last `chat_size` turns, 30 by default, and with `compact_history`, on by default, asks the LLM to summarise the older ones. The summary request has no tools, so the proxy passes it to the model, which then retells the bridge's read-backs and outcomes in its own words: "The assistant rotated the stage". The proxy cannot remove a paraphrase, and the model sees itself acting again, which makes it pretend. Our commands stand alone, so a few turns are enough.
  - Start the speech server with summaries off and a short history, probably `--compact_history false --chat_size 8`: check the names with `uv run speech-to-speech serve --help`, then add them to the README.
  - Make the proxy handle the summary request on its own, e.g. answer it with empty summaries, and test it in `test_llmproxy.py`.
- **"Stop it" stops twice**: the bridge stops the rig, and the sentence also goes to the LLM, which calls `stop` again. Harmless; "it" could become a filler.
