# Loudspeaker, a Clip-On Microphone and Shorter Read-Backs

## Goal

Show the rig to people, with the voice out loud. The phone plays the voice on its loudspeaker, and we speak into a DJI Mic Mini 2 on the shirt, whose receiver plugs into the phone. On the way, the voice got calmer, the speech detector stopped losing a short "yes", and the read-backs got shorter.

## Decisions

### The Loudspeaker

**Without a headset, the voice plays on the loudspeaker.** In call mode, Android plays the voice in the earpiece, which nobody hears from a table. The app picks the loudspeaker, as the speaker button of a call does: `setCommunicationDevice` on Android 12 and newer, `isSpeakerphoneOn` on Android 11, e.g. the Moto G9 Play.

**Call mode stays, for its echo canceller.** The phone's microphone sits next to the loudspeaker: without the canceller, the robot hears itself, answers itself, and once took its own "yes" for ours.

### The Clip-On Microphone

**With a USB microphone, the app leaves call mode.** On Android 11, call mode with the loudspeaker on records from the phone's own microphone, whatever the app asks for: our first fix, `setPreferredDevice` inside call mode, worked only some of the time. Out of call mode, the app records from the USB microphone with the `MIC` source, and plays the voice as media on the loudspeaker. The phone's log shows it: "Recording from USB-Audio - Wireless Mic Rx (type 11)".

**We lose the echo canceller there, and do not need it.** The microphone is on the shirt, far from the loudspeaker, and points at our mouth. In our test, about 22 of 24 transcripts were right, no "yes" was lost, and the robot never heard itself.

**A USB headset stays in call mode.** It has its own earphones, so nothing leaks into its microphone. `UsbMicrophone.find` returns nothing when a wired or USB headset is plugged in.

### The Voice

**One calm voice, in English.** Without an instruction, Qwen3-TTS changed its tone from sentence to sentence, at times breathy or whispered. It now gets `--qwen3_tts_instruct`, a calm and neutral assistant at a normal volume, and `--qwen3_tts_language english`: guessing the language of each sentence gave a short one the wrong intonation.

**A short "yes" counts.** A "yes" through the phone measured 96 to 160 ms of voice. The speech detector threw away anything under 384 ms by default, and still about one in five at 192 ms. `--min_speech_ms` is 96.

**A pause does not end the turn.** At the default `--smart_turn_threshold` of 0.5, "Can you" or "move it uh one" went off on their own. At 0.7, the turn waits through the pause.

### Shorter Read-Backs

**A read-back says what changes, nothing more.** The rig has one stage and one rail, so "Rotating the stage 30 degrees clockwise" becomes "Rotating 30 degrees clockwise", and "Moving the camera 10 millimetres closer" becomes "Moving closer 10 millimetres". Every read-back keeps the direction, the amount and, for a stack, the number of pictures: those are what the user checks before the yes. The list is in [`robots/stepit-macro/commands.md`](../../robots/stepit-macro/commands.md).

**"Confirm?" stays a sentence of its own.** The bridge adds it the same way for every robot, and the proxy's guard looks for it.

**Millimetres are said in full.** "10mm" could be read aloud as "ten em em".

## Left Out

**The rail's direction on the rig.** Voice commands moved the camera the wrong way: the rig's `rig.yaml` inverted the rail's joint, and the sliders of StepIt UI made up for it with a negative scale. The fix belongs to stepit-macro, in its own pull request.

**An echo filter in the bridge.** With the clip-on microphone, or a headset, there is no echo. Without either, outside call mode, the robot could still hear itself; a filter that drops what the voice has just said would close that gap.

## Open Items

- Bonsai fills in a value from an earlier turn: "Move closer." became 20 millimetres, copied from the move before. The read-back caught it.
- Bonsai calls a command that needs no confirmation on a fragment: "Three centimeter.", after a read-back was dropped, called `stop`.
- Parakeet TDT 0.6B v3 sometimes writes an English word in Russian or Spanish ("Ротейт", "Ni cierto"). Parakeet v2 is English only.
- Nothing is said while a long move runs, about 10 seconds for 30 millimetres, so we say "yes" again. A `started` sentence for the moves would answer it.
