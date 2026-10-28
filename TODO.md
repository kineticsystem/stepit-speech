# TODO

## Next: Hands-Free, From a Phone in a Pocket

The goal: control the robot by voice with our hands busy. An Android phone in a pocket, with a headset, always listening; "Wake up StepIt" switches the voice on, "Go to sleep StepIt" switches it off. Today the voice starts with the button of the speech server's browser demo, and listens until the page closes.

Three steps, in this order. Decide the open questions first.

### 1. Sleep Mode in the Bridge

Done: the robot file's `sleep` section, described in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#sleeping-and-waking). Going to sleep is a command, read back and confirmed, that runs nothing on the robot; waking up is a wake phrase said alone; a session starts awake; stop always works; the phone is told the state with `voicebridge.state`.

Still open:

- Fall asleep after a quiet spell, e.g. 5 minutes, or only when told?
- An outcome that comes while asleep, e.g. the end of a focus stack, is said at once: or kept for the wake?

The speech server still transcribes everything while asleep, on our own GPU: nothing leaves the computer, but the microphone is live. A wake word recognised on the phone, before any audio leaves it, would avoid that, at the price of a wake-word model of our own: openWakeWord needs one trained for the phrase, and Porcupine's free tier excludes commercial use.

### 2. Test a Phone in a Pocket

Before writing the app, find out what the phone does with its screen off. A minimal page, or a minimal app, streams the microphone to the bridge and plays the voice; we wear it for 30 minutes, with the headset, while the robot runs a focus stack.

- **Does the microphone keep going with the screen locked?** Chrome on Android throttles or freezes a page in the background, and may stop its microphone. A native app keeps it with a foreground service of type `microphone`, behind a permanent notification.
- **Does the connection hold?** A session that ends cancels its goals: the rule that no robot moves for a voice that is gone. A Wi-Fi drop, or Android pausing the app, would stop a focus stack half way. If drops happen, decide whether the bridge gives a session a short grace period to reconnect before it cancels.
- **Which headset?** Wired or USB-C keeps the full audio quality and no echo of the voice. A Bluetooth headset switches the phone's microphone to the hands-free profile, often 8 or 16 kHz, and speech-to-text gets worse: fine for "yes" and "stop", riskier for "rotate the stage 12.5 degrees".
- **The battery**, over an hour.

The voice stop takes about a second. In a pocket, with our hands busy, it still does not replace the stop of the gamepad or of StepIt UI.

### 3. The App

What the app does is the same in every form: capture the microphone at 24 kHz, 16-bit mono, with echo cancellation, and send it as `input_audio_buffer.append`; play the voice's `response.output_audio.delta`, and cut it as soon as we speak, so that "stop" interrupts it; reconnect after a drop; show asleep or awake, what was heard and the last read-back. It decides nothing about the robot. Three ways to write it:

| | Web page (React, Vite, TypeScript, pnpm) | Capacitor app | Native Android app (Kotlin) |
|---|---|---|---|
| What it is | A page in Chrome, or installed as a PWA | The same React app, packaged as an Android app by [Capacitor](https://capacitorjs.com/), an MIT-licensed tool from the makers of Ionic, with a small native plugin | An app written for Android: Jetpack Compose for the screen, a foreground service for the microphone |
| Listening in a pocket | Uncertain: step 2 tells | Reliable, through the plugin's foreground service | Reliable |
| Control of the audio | What Chrome offers | What Chrome offers, or the plugin's own | Full: `AudioRecord` with `VOICE_COMMUNICATION`, `AudioTrack`, the headset chosen with `AudioManager.setCommunicationDevice` |
| Reaching the bridge | HTTPS and WSS only: browsers allow the microphone only on secure pages, and a phone reaching `192.168.x.x` is not `localhost`. A certificate from `mkcert` installed on the phone, or Tailscale's | `ws://` on the local network, allowed by its network configuration | Same as Capacitor |
| Code | About 600 to 900 lines of TypeScript | The same, plus about 100 lines of Kotlin, more if the plugin does the audio | About 1,000 to 1,500 lines of Kotlin |
| iPhone later | Partly | Yes, with an iOS plugin | A second app, in Swift |
| Build | Node and pnpm, in `web/` | Also the Android SDK | The Android SDK and Gradle, in `android/` |

The speech server's demo, `demo/` of speech-to-speech (Apache 2.0), has working audio worklets for capture and playback to learn from. Whichever form, the app lives in this repository, builds in Docker like the rest (e.g. `./docker/dock.sh build-android`), and is tested against a fake bridge without a phone.

Chosen: the native app, as the audio is the heart of it. Its first version is in [`android-ui`](android-ui/README.md): it streams the microphone, plays the voice, keeps going with the screen locked, reconnects and logs the drops, and shows the sleep mode. Capacitor stays the way to an iPhone, if we want one.

Open questions:

- Which headset: wired, USB-C or Bluetooth? The phone is a Moto G9, Android 11.
- An iPhone one day?

## Later

- **Download Bonsai from its release repository.** We download `Ternary-Bonsai-2-27B-Q2_0-prism-fork-required.gguf` from `prism-ml/Ternary-Bonsai-2-27B-gguf-dev`, Prism ML's development repository. Its release repository, `prism-ml/Ternary-Bonsai-2-27B-gguf`, has `Ternary-Bonsai-2-27B-PQ2_0.gguf`, 7.2 GB, under the same Apache 2.0 licence. For a product, switch to it once `llama-server` of the submodule loads it and `voicebridge eval` still scores 35 of 35 on the GPU computer.
- **Credit the models in a product.** Bonsai and Qwen3.8-27B are Apache 2.0: ship their `LICENSE` and `NOTICE.txt` with the model file, and Prism ML asks for "Created using Bonsai by Prism ML.". The speech server's default speech-to-text, NVIDIA's Parakeet TDT 0.6B v3, is CC BY 4.0, which requires credit.
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
