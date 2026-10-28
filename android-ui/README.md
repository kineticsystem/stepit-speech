# StepIt Speech for Android

## Table of Contents <!-- omit in toc -->

- [Introduction](#introduction)
- [Prerequisites](#prerequisites)
- [Build the App](#build-the-app)
- [Install It on the Phone](#install-it-on-the-phone)
- [Running the App](#running-the-app)
  - [On the Phone](#on-the-phone)
  - [In the Emulator](#in-the-emulator)
- [The Pocket Test](#the-pocket-test)
- [How It Is Built](#how-it-is-built)
- [Tests](#tests)

## Introduction

An Android app that talks to the bridge with the phone in a pocket and a headset on: the same job as the speech server's browser demo, without a screen. It is the first version of step 3 of [`TODO.md`](../TODO.md), and the tool of its step 2, the pocket test.

- It streams the microphone to the bridge, 24 kHz 16-bit mono, with the echo canceller of a phone call.
- It plays the voice, and stops it as soon as we speak, so that "stop" is heard.
- It keeps going with the screen locked: a foreground service of type `microphone`, behind a permanent notification.
- It reconnects after a drop, and logs every drop with how long the connection was down.
- It shows what was heard, what the voice said, and whether the voice is asleep or awake.
- It shows the phrase that wakes the voice, and one that puts it to sleep, as the bridge's `voicebridge.state` gives them; it remembers them for the next start, before it connects.

It decides nothing about the robot. The bridge reads every command back, hears the yes and runs it: a bug of the app cannot move the rig.

## Prerequisites

- Android 11 or newer, e.g. a Moto G9.
- Docker, to build. No Android Studio is needed.
- `adb` on the computer, to install the app over USB:

  ```
  sudo apt install adb
  ```

- The bridge and the speech server running, as the [README](../README.md) explains. The phone reaches the bridge on port 8766, over the Wi-Fi.

## Build the App

Build the image with the Android SDK, once:

```
./docker/dock.sh build-android
```

Then run the unit tests and build the debug APK:

```
./docker/dock.sh android
```

The APK is `android-ui/app/build/outputs/apk/debug/app-debug.apk`, about 24 MB. Any other Gradle tasks can be given, e.g. `./docker/dock.sh android lintDebug`. Gradle's downloads and the debug signing key stay in `android-ui/.cache`, outside git: with the same key, a new APK replaces the old one on the phone.

## Install It on the Phone

On the phone, open **Settings**, **About phone**, tap **Build number** seven times, then turn on **Settings**, **System**, **Developer options**, **USB debugging**. Connect it by USB, allow the computer when it asks, and install:

```
adb install -r android-ui/app/build/outputs/apk/debug/app-debug.apk
```

Without a cable, copy the APK to the phone and open it: Android asks once to allow installs from that app.

## Running the App

### On the Phone

The phone reaches the bridge at the computer's address on the Wi-Fi. Find it with `ip -4 addr` on the computer, e.g. `192.168.100.26`. In the app, set **Bridge** to that address, with port 8766:

```
ws://192.168.100.26:8766/v1/realtime
```

Press **Start** and allow the microphone and the notifications. The voice says "Ready.", the greeting of the robot file, and the screen shows **Connected**. Then talk to the rig as in the browser demo. **Stop**, on the screen or on the notification, ends the session.

> [!IMPORTANT]
> A session that ends cancels its goals: the bridge stops the rig for a voice that is gone. A drop of the Wi-Fi stops a focus stack half way, and the app reconnects with a new session.

### In the Emulator

The emulator runs the whole app on the computer, with the bridge at `ws://10.0.2.2:8766/v1/realtime`, the app's default: `10.0.2.2` is the emulator's name for the host. It needs the Android SDK's emulator on the host, e.g. from Android Studio, with a system image of Android 11 or newer. In the emulator's **Extended controls**, **Microphone**, turn on **Virtual microphone uses host audio input**, so that we speak through the computer's headset.

The emulator shows everything but the pocket: the locked screen, the Bluetooth headset and the battery need the phone.

## The Pocket Test

Step 2 of [`TODO.md`](../TODO.md): wear the phone for 30 minutes, with the headset, while the robot runs a focus stack, and note:

- **Drops**: the screen lists each one, with its time, how long it was down, and why.
- **The microphone with the screen locked**: the voice still answers "yes" and "stop".
- **The headset**: the screen shows where the audio goes, e.g. `wired headset` or `Bluetooth headset`.
- **The battery**, before and after.

Motorola's battery saving can stop a foreground service: if the app stops in the pocket, set **Settings**, **Apps**, **StepIt Speech**, **Battery** to **Unrestricted**.

## How It Is Built

One module, `app`, in Kotlin, by job:

| Package | Role |
|---|---|
| `protocol` | The Realtime events the app sends and reads, as pure functions on JSON text. |
| `voice` | `VoiceClient`: the WebSocket to the bridge, the session, reconnection and the drop log. The microphone and the speaker are interfaces. |
| `audio` | The microphone (`AudioRecord`, `VOICE_COMMUNICATION`), the speaker (`AudioTrack`) and the headset route. |
| `service` | `VoiceService`: the foreground service, its wake lock and Wi-Fi lock, and the state the screen shows. |
| `ui` | `MainActivity`: the one screen, in Jetpack Compose. |

On connecting, the app sends a `session.update` and an opening message, as the browser demo does: the bridge adds the robot's tools to the first and answers the second with the robot's greeting. The voice is written to `AudioTrack` in slices of 20 ms, so that we cut it within 20 ms when we start speaking. The service pings the bridge every 10 seconds: a dead Wi-Fi is found in seconds, not minutes.

## Tests

The unit tests run on the JVM, in Docker, without a phone: `./docker/dock.sh android`.

| Test | What it covers |
|---|---|
| `RealtimeTest` | The session, the opening message and the microphone's chunks; reading the voice, the transcripts, the sleep mode and the errors; ignoring the rest. |
| `VoiceClientTest` | Against a fake bridge, OkHttp's `MockWebServer`: the order of the first events, the `realtime` subprotocol, the voice played and cut, the lines shown, a drop logged and reconnected, a bridge that is not there, and staying disconnected. |

The audio, the service and the screen need a phone or the emulator: check them by hand with the bridge running, as [Running the App](#running-the-app) explains.
