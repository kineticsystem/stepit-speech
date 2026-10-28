// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import com.kineticsystem.stepitspeech.protocol.Realtime
import com.kineticsystem.stepitspeech.voice.Speaker
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * The voice, through `AudioTrack`, as the audio of a call: it goes to the
 * headset when one is plugged in, and the echo canceller knows it.
 *
 * The voice arrives in pieces faster than it plays: a thread of its own writes
 * them, in slices of 20 ms, so that [interrupt] cuts it within 20 ms, not at the
 * end of a piece of a second or more.
 */
class AndroidSpeaker : Speaker {
    private val queue = LinkedBlockingQueue<ByteArray>()
    private var track: AudioTrack? = null
    private var thread: Thread? = null

    @Volatile
    private var running = false

    /** Raised by every interrupt: the writer drops what it was writing when it changes. */
    @Volatile
    private var generation = 0

    @Synchronized
    override fun start() {
        if (running) return
        val format = AudioFormat.Builder()
            .setSampleRate(Realtime.SAMPLE_RATE)
            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .build()
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
        val minimum = AudioTrack.getMinBufferSize(Realtime.SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT)
        val track = AudioTrack.Builder()
            .setAudioAttributes(attributes)
            .setAudioFormat(format)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .setBufferSizeInBytes(minimum * 2)
            .build()
        this.track = track
        running = true
        track.play()
        thread = Thread({ write(track) }, "speaker").apply { start() }
    }

    private fun write(track: AudioTrack) {
        while (running) {
            val piece = queue.poll(100, TimeUnit.MILLISECONDS) ?: continue
            val mine = generation
            var offset = 0
            while (offset < piece.size && running && mine == generation) {
                val length = minOf(SLICE_BYTES, piece.size - offset)
                val written = track.write(piece, offset, length)
                if (written <= 0) break
                offset += written
            }
        }
    }

    override fun play(pcm: ByteArray) {
        if (running) queue.add(pcm)
    }

    @Synchronized
    override fun interrupt() {
        generation++
        queue.clear()
        track?.run {
            pause()
            flush()
            play()
        }
    }

    @Synchronized
    override fun stop() {
        if (!running) return
        running = false
        generation++
        queue.clear()
        thread?.join(500)
        track?.run {
            stop()
            release()
        }
        track = null
        thread = null
    }

    private companion object {
        /** 20 ms of 16-bit mono at 24 kHz. */
        const val SLICE_BYTES = Realtime.SAMPLE_RATE / 50 * 2
    }
}
