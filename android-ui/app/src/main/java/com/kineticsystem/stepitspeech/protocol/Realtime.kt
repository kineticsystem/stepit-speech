// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import java.util.Base64

/**
 * The events of the OpenAI Realtime API that the app sends and reads, as the
 * speech server's browser demo does. Pure functions on JSON text, with no I/O.
 *
 * The app decides nothing about the robot: it sends the microphone, plays the
 * voice and shows what was said. The bridge adds the robot's tools to our
 * session.update and handles every command.
 */
object Realtime {
    /** The rate of the audio both ways: 16-bit mono PCM. */
    const val SAMPLE_RATE = 24_000

    /** The opening message: the bridge answers it with the robot's greeting, word for word. */
    const val GREETING_REQUEST = "Start the conversation with a short greeting."

    private val json = Json { ignoreUnknownKeys = true }

    /** The session: audio both ways at 24 kHz, transcripts of what we say, the server's voice detection. */
    fun sessionUpdate(): String = buildJsonObject {
        put("type", "session.update")
        putJsonObject("session") {
            put("type", "realtime")
            putJsonArray("output_modalities") { add(JsonPrimitive("audio")) }
            putJsonObject("audio") {
                putJsonObject("input") {
                    putJsonObject("format") {
                        put("type", "audio/pcm")
                        put("rate", SAMPLE_RATE)
                    }
                    putJsonObject("transcription") { put("model", "whisper-1") }
                    putJsonObject("turn_detection") {
                        put("type", "server_vad")
                        put("interrupt_response", true)
                    }
                }
                putJsonObject("output") {
                    putJsonObject("format") {
                        put("type", "audio/pcm")
                        put("rate", SAMPLE_RATE)
                    }
                }
            }
        }
    }.toString()

    /** The opening message and the request for its answer. */
    fun greeting(): List<String> = listOf(
        buildJsonObject {
            put("type", "conversation.item.create")
            putJsonObject("item") {
                put("type", "message")
                put("role", "user")
                put("content", buildJsonArray {
                    add(buildJsonObject {
                        put("type", "input_text")
                        put("text", GREETING_REQUEST)
                    })
                })
            }
        }.toString(),
        buildJsonObject { put("type", "response.create") }.toString(),
    )

    /** A chunk of the microphone, 16-bit little-endian PCM at [SAMPLE_RATE]. */
    fun append(pcm: ByteArray): String = buildJsonObject {
        put("type", "input_audio_buffer.append")
        put("audio", Base64.getEncoder().encodeToString(pcm))
    }.toString()

    /** What an event from the bridge means to the app; [ServerEvent.Other] for the rest. */
    fun parse(text: String): ServerEvent {
        val event = try {
            json.parseToJsonElement(text) as? JsonObject
        } catch (e: IllegalArgumentException) {
            null
        } ?: return ServerEvent.Other("")
        val type = event.string("type") ?: return ServerEvent.Other("")
        return when (type) {
            "response.output_audio.delta", "response.audio.delta" ->
                event.string("delta")?.let { delta ->
                    try {
                        ServerEvent.Audio(Base64.getDecoder().decode(delta))
                    } catch (e: IllegalArgumentException) {
                        null
                    }
                } ?: ServerEvent.Other(type)
            "input_audio_buffer.speech_started" -> ServerEvent.SpeechStarted
            "conversation.item.input_audio_transcription.completed" ->
                ServerEvent.Heard(event.string("transcript").orEmpty().trim())
            "response.output_audio_transcript.done", "response.audio_transcript.done" ->
                ServerEvent.Said(event.string("transcript").orEmpty().trim())
            "voicebridge.state" -> {
                val phrases = event.string("wake")?.let { Phrases(wake = it, sleep = event.string("sleep")) }
                when (event.string("state")) {
                    "asleep" -> ServerEvent.State(asleep = true, phrases)
                    "awake" -> ServerEvent.State(asleep = false, phrases)
                    else -> ServerEvent.Other(type)
                }
            }
            "error" -> ServerEvent.Error(
                (event["error"] as? JsonObject)?.string("message") ?: "Unknown error",
            )
            else -> ServerEvent.Other(type)
        }
    }

    private fun JsonObject.string(key: String): String? =
        (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
}

/**
 * What wakes the voice and what puts it to sleep, from the robot file. The
 * wake phrase is exact, matched by the bridge; the sleep phrase is an example,
 * as going to sleep is a command in our own words, read back and confirmed.
 */
data class Phrases(val wake: String, val sleep: String?)

/** An event of the bridge, as the app reads it. */
sealed interface ServerEvent {
    /** A piece of the voice, 16-bit PCM at [Realtime.SAMPLE_RATE]. */
    class Audio(val pcm: ByteArray) : ServerEvent

    /** We started speaking: the voice must stop at once, so that "stop" is heard. */
    data object SpeechStarted : ServerEvent

    /** What speech-to-text heard us say. */
    data class Heard(val text: String) : ServerEvent

    /** What the voice said. */
    data class Said(val text: String) : ServerEvent

    /** The bridge's sleep mode, from `voicebridge.state`, with the phrases of the robot file when it gives them. */
    data class State(val asleep: Boolean, val phrases: Phrases? = null) : ServerEvent

    data class Error(val message: String) : ServerEvent

    data class Other(val type: String) : ServerEvent
}
