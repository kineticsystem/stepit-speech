// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.audio

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.util.Log
import com.kineticsystem.stepitspeech.protocol.Realtime
import com.kineticsystem.stepitspeech.voice.Microphone

/**
 * The phone's microphone, the headset's, or a USB microphone, through `AudioRecord`.
 *
 * `VOICE_COMMUNICATION` is the source of a phone call: Android cancels the
 * echo of the voice and picks the headset's microphone when one is plugged
 * in. The echo canceller is also switched on explicitly, where the phone has
 * one. The service checks the microphone permission before starting it.
 *
 * A USB microphone ([UsbMicrophone]) is recorded from by name, with the plain
 * microphone source and `setPreferredDevice`: the phone is not in call mode then.
 */
class AndroidMicrophone(context: Context) : Microphone {
    private val audio = context.getSystemService(AudioManager::class.java)
    private var record: AudioRecord? = null
    private var echoCanceller: AcousticEchoCanceler? = null
    private var thread: Thread? = null

    @Volatile
    private var running = false

    @SuppressLint("MissingPermission")
    @Synchronized
    override fun start(onChunk: (ByteArray) -> Unit) {
        if (running) return
        val usb = UsbMicrophone.find(audio)
        val source = if (usb != null) MediaRecorder.AudioSource.MIC else MediaRecorder.AudioSource.VOICE_COMMUNICATION
        val record = open(source, usb) ?: return
        Log.i(TAG, "Recording from ${record.routedDevice?.productName} (type ${record.routedDevice?.type})")
        if (AcousticEchoCanceler.isAvailable()) {
            echoCanceller = AcousticEchoCanceler.create(record.audioSessionId)?.apply { enabled = true }
        }
        this.record = record
        running = true
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

    /** A recording, already started so that it is routed, from [source] and, if it is not null, [device]. */
    @SuppressLint("MissingPermission")
    private fun open(source: Int, device: AudioDeviceInfo?): AudioRecord? {
        val minimum = AudioRecord.getMinBufferSize(Realtime.SAMPLE_RATE, CHANNEL, ENCODING)
        val record = AudioRecord(source, Realtime.SAMPLE_RATE, CHANNEL, ENCODING, maxOf(minimum, CHUNK_BYTES * 4))
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            Log.e(TAG, "The microphone cannot be opened")
            return null
        }
        if (device != null) record.preferredDevice = device
        record.startRecording()
        return record
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
