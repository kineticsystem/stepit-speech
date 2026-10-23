# TODO

## Next Iteration: A Self-Contained Project

Today the LLM of the voice, Bonsai 2 27B, is served by llama-swap from another repository, `qwen-4090-bench`, entry `stepit-macro-bonsai`. StepIt Speech must run on its own: one repository, its own model, its own LLM server, no llama-swap.

- **Build llama.cpp in the image.** Add upstream [llama.cpp](https://github.com/ggml-org/llama.cpp) as a Git submodule, e.g. `engines/llama.cpp`, pinned to a release of b11555 or newer (Bonsai's Q2_0 needs it; b11840 is tested). Compile `llama-server` with CUDA in a CUDA image (`-DGGML_CUDA=ON`, the GPU's architecture, e.g. `-DCMAKE_CUDA_ARCHITECTURES=89` for the RTX 4090). The image needs the NVIDIA Container Toolkit to reach the GPU.
- **Download the model into `models/`.** A script, e.g. `./docker/dock.sh models`, downloads `Ternary-Bonsai-2-27B-Q2_0-prism-fork-required.gguf`, 7.6 GB, from [prism-ml/Ternary-Bonsai-2-27B-gguf-dev](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf-dev), pinned to revision `2a263ef827a2e215f3ddd14c9871a5bd1800fcbc`, checks its SHA-256, `4f99aed01b8a877e153f9aa6569a4440fe17c59701cc0953e36d7f460549e70e`, and resumes an interrupted download. `models/` is git-ignored.
- **Start llama-server with the bridge.** `./docker/dock.sh serve` starts `llama-server` on the model, with `--jinja`, `--ctx-size 8192`, `--flash-attn on`, `--n-gpu-layers 999`, the model card's sampling (`--temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.05`) and thinking off (`--chat-template-kwargs '{"enable_thinking":false}'`), then the bridge, pointed at it. No llama-swap: one model, always loaded, so nothing swaps it out.
- **Keep the tests free of the GPU.** CI keeps running the tests with the fake LLM; building llama.cpp with CUDA stays out of the test image, or in a stage of its own.
- **Update the README and the architecture document**: the LLM is part of the project, the prerequisites (an NVIDIA GPU, the NVIDIA Container Toolkit, about 8 GB of GPU memory for the model), and how to use another model.

## Later

- **Start the speech server from this project too**, so that one command starts the whole voice: the speech server, llama-server and the bridge.
- **Remove the dependency on StepIt Macro**: its robot file moves into the stepit-macro repository, and this project becomes a module of the rig.
- **Check whether [Pydantic AI](https://pydantic.dev/docs/ai/) helps.** It could replace the call of the proxy to the LLM, not the safety gate. First findings, from its documentation (version 2.60):
  - It needs Python 3.11; we support 3.10.
  - `NativeOutput([Command, Reply])` asks for a JSON schema through `response_format`, as `llmproxy.structured` does. Our commands come from the robot file, so their models would be built at run time. Check that llama.cpp gets a strict schema from it.
  - An output validator raising `ModelRetry` could replace our second ask when the LLM pretends (`commands_only`).
  - Its approvals (`requires_approval`, `DeferredToolRequests`) need a tool call, which llama.cpp does not enforce with our model, and after the approval the model speaks again. Both break our rules: the gate stays ours.
  - It is a client. The proxy still serves the speech server's OpenAI API and turns the decision back into a tool call.
  - It brings opentelemetry, pydantic-graph and httpx with it.

  Try it on a branch, on `_ask` of `llmproxy.py` only: keep it if it removes code and `voicebridge eval` still scores 35 of 35; otherwise note why here and drop it.
- **Keep a short history, without summaries.** The speech server keeps the last `chat_size` turns, 30 by default, and with `compact_history`, on by default, asks the LLM to summarise the older ones. The summary request has no tools, so the proxy passes it to the model, which then retells the bridge's read-backs and outcomes in its own words: "The assistant rotated the stage". The proxy cannot remove a paraphrase, and the model sees itself acting again, which makes it pretend. Our commands stand alone, so a few turns are enough.
  - Start the speech server with summaries off and a short history, probably `--compact_history false --chat_size 8`: check the names with `uv run speech-to-speech serve --help`, then add them to the README.
  - Make the proxy handle the summary request on its own, e.g. answer it with empty summaries, and test it in `test_llmproxy.py`.
- **"Stop it" stops twice**: the bridge stops the rig, and the sentence also goes to the LLM, which calls `stop` again. Harmless; "it" could become a filler.
