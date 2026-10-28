// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class RealtimeTest {
    private fun field(text: String, vararg path: String): String? {
        var current: JsonElement = Json.parseToJsonElement(text)
        for (key in path) current = current.jsonObject[key] ?: return null
        return current.jsonPrimitive.contentOrNull
    }

    @Test
    fun `the session asks for audio at 24 kHz both ways, with transcripts and voice detection`() {
        val update = Realtime.sessionUpdate()
        assertEquals("session.update", field(update, "type"))
        assertEquals("realtime", field(update, "session", "type"))
        assertEquals("24000", field(update, "session", "audio", "input", "format", "rate"))
        assertEquals("24000", field(update, "session", "audio", "output", "format", "rate"))
        assertEquals("server_vad", field(update, "session", "audio", "input", "turn_detection", "type"))
        assertEquals("true", field(update, "session", "audio", "input", "turn_detection", "interrupt_response"))
        assertEquals("whisper-1", field(update, "session", "audio", "input", "transcription", "model"))
    }

    @Test
    fun `the greeting is a user message, then a request for its answer`() {
        val (message, create) = Realtime.greeting()
        assertEquals("conversation.item.create", field(message, "type"))
        assertEquals("user", field(message, "item", "role"))
        val content = Json.parseToJsonElement(message).jsonObject["item"]!!.jsonObject["content"]!!.jsonArray
        assertEquals(Realtime.GREETING_REQUEST, content[0].jsonObject["text"]!!.jsonPrimitive.content)
        assertEquals("response.create", field(create, "type"))
    }

    @Test
    fun `a chunk of the microphone goes up in base64`() {
        val pcm = byteArrayOf(1, 2, 3, -1)
        val append = Realtime.append(pcm)
        assertEquals("input_audio_buffer.append", field(append, "type"))
        assertArrayEquals(pcm, Base64.getDecoder().decode(field(append, "audio")))
    }

    @Test
    fun `the voice comes down as audio`() {
        val pcm = byteArrayOf(10, 20, 30, 40)
        val event = Realtime.parse(
            """{"type":"response.output_audio.delta","response_id":"r1","delta":"${Base64.getEncoder().encodeToString(pcm)}"}""",
        )
        assertTrue(event is ServerEvent.Audio)
        assertArrayEquals(pcm, (event as ServerEvent.Audio).pcm)
    }

    @Test
    fun `the events the screen shows are read`() {
        assertEquals(ServerEvent.SpeechStarted, Realtime.parse("""{"type":"input_audio_buffer.speech_started"}"""))
        assertEquals(
            ServerEvent.Heard("Move the camera 2 millimetres closer."),
            Realtime.parse(
                """{"type":"conversation.item.input_audio_transcription.completed",
                   "transcript":" Move the camera 2 millimetres closer. "}""",
            ),
        )
        assertEquals(
            ServerEvent.Said("Confirm?"),
            Realtime.parse("""{"type":"response.output_audio_transcript.done","transcript":"Confirm?"}"""),
        )
        assertEquals(ServerEvent.State(asleep = true), Realtime.parse("""{"type":"voicebridge.state","state":"asleep"}"""))
        assertEquals(ServerEvent.State(asleep = false), Realtime.parse("""{"type":"voicebridge.state","state":"awake"}"""))
        assertEquals(
            ServerEvent.State(asleep = true, Phrases(wake = "Wake up, StepIt", sleep = "Go to sleep")),
            Realtime.parse("""{"type":"voicebridge.state","state":"asleep","wake":"Wake up, StepIt","sleep":"Go to sleep"}"""),
        )
        assertEquals(
            ServerEvent.State(asleep = false, Phrases(wake = "Wake up, StepIt", sleep = null)),
            Realtime.parse("""{"type":"voicebridge.state","state":"awake","wake":"Wake up, StepIt"}"""),
        )
        assertEquals(ServerEvent.Error("Busy"), Realtime.parse("""{"type":"error","error":{"message":"Busy"}}"""))
    }

    @Test
    fun `anything else is ignored, even text that is not JSON`() {
        assertEquals(ServerEvent.Other("session.created"), Realtime.parse("""{"type":"session.created"}"""))
        assertEquals(ServerEvent.Other("voicebridge.state"), Realtime.parse("""{"type":"voicebridge.state"}"""))
        assertEquals(ServerEvent.Other(""), Realtime.parse("not json"))
        assertEquals(ServerEvent.Other(""), Realtime.parse("[1, 2]"))
        assertEquals(
            ServerEvent.Other("response.output_audio.delta"),
            Realtime.parse("""{"type":"response.output_audio.delta","delta":"%%%"}"""),
        )
    }
}
