// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.voice

/** Where our voice comes from: 16-bit mono PCM at 24 kHz, in chunks of about 40 ms. */
interface Microphone {
    /** Starts capturing; [onChunk] is called on the microphone's own thread. */
    fun start(onChunk: (ByteArray) -> Unit)

    fun stop()
}

/** Where the bridge's voice goes: 16-bit mono PCM at 24 kHz. */
interface Speaker {
    fun start()

    /** Queues a piece of the voice; it returns at once. */
    fun play(pcm: ByteArray)

    /** Drops what is queued and stops at once: we started speaking, e.g. to say "stop". */
    fun interrupt()

    fun stop()
}
