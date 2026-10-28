// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.util.Log
import com.kineticsystem.stepitspeech.protocol.Realtime
import com.kineticsystem.stepitspeech.voice.Microphone

/**
 * The phone's microphone, or the headset's, through `AudioRecord`.
 *
 * `VOICE_COMMUNICATION` is the source of a phone call: Android cancels the
 * echo of the voice and picks the headset's microphone when one is plugged
 * in. The echo canceller is also switched on explicitly, where the phone has
 * one. The service checks the microphone permission before starting it.
 */
class AndroidMicrophone : Microphone {
    private var record: AudioRecord? = null
    private var echoCanceller: AcousticEchoCanceler? = null
    private var thread: Thread? = null

    @Volatile
    private var running = false

    @SuppressLint("MissingPermission")
    @Synchronized
    override fun start(onChunk: (ByteArray) -> Unit) {
        if (running) return
        val minimum = AudioRecord.getMinBufferSize(Realtime.SAMPLE_RATE, CHANNEL, ENCODING)
        val record = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, Realtime.SAMPLE_RATE, CHANNEL,
            ENCODING, maxOf(minimum, CHUNK_BYTES * 4))
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            Log.e(TAG, "The microphone cannot be opened")
            return
        }
        if (AcousticEchoCanceler.isAvailable()) {
            echoCanceller = AcousticEchoCanceler.create(record.audioSessionId)?.apply { enabled = true }
        }
        this.record = record
        running = true
        record.startRecording()
        thread = Thread({
            val buffer = ByteArray(CHUNK_BYTES)
            while (running) {
                val read = record.read(buffer, 0, buffer.size)
                if (read > 0) onChunk(buffer.copyOf(read))
                else if (read < 0) {
                    Log.e(TAG, "The microphone failed: $read")
                    break
                }
            }
        }, "microphone").apply { start() }
    }

    @Synchronized
    override fun stop() {
        if (!running) return
        running = false
        record?.stop()
        thread?.join(500)
        echoCanceller?.release()
        record?.release()
        echoCanceller = null
        record = null
        thread = null
    }

    private companion object {
        const val TAG = "AndroidMicrophone"
        const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        const val ENCODING = AudioFormat.ENCODING_PCM_16BIT

        /** 40 ms of 16-bit mono at 24 kHz, as the browser demo sends. */
        const val CHUNK_BYTES = Realtime.SAMPLE_RATE / 25 * 2
    }
}
