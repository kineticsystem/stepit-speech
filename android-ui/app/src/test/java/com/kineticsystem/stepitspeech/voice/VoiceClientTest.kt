// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.voice

import com.kineticsystem.stepitspeech.protocol.Phrases
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.Base64
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** The client against a fake bridge: OkHttp's MockWebServer, which answers each connection with a WebSocket. */
class VoiceClientTest {
    private val server = MockWebServer()
    private val scheduler = Executors.newSingleThreadScheduledExecutor()
    private val http = OkHttpClient()
    private val microphone = FakeMicrophone()
    private val speaker = FakeSpeaker()
    private lateinit var client: VoiceClient

    /** One connection of the app, as the bridge sees it. */
    private class Bridge : WebSocketListener() {
        val received = LinkedBlockingQueue<String>()
        val opened = LinkedBlockingQueue<WebSocket>()

        override fun onOpen(webSocket: WebSocket, response: Response) {
            opened.add(webSocket)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            received.add(text)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
        }

        fun next(): String = received.poll(5, TimeUnit.SECONDS) ?: error("Nothing received")

        fun socket(): WebSocket = opened.poll(5, TimeUnit.SECONDS) ?: error("Not connected")
    }

    private fun accept(): Bridge {
        val bridge = Bridge()
        server.enqueue(MockResponse().withWebSocketUpgrade(bridge))
        return bridge
    }

    private fun type(text: String) = Json.parseToJsonElement(text).jsonObject["type"]!!.jsonPrimitive.content

    private fun waitFor(what: String, condition: (VoiceState) -> Boolean): VoiceState {
        val deadline = System.currentTimeMillis() + 5_000
        while (System.currentTimeMillis() < deadline) {
            val state = client.state.value
            if (condition(state)) return state
            Thread.sleep(10)
        }
        error("Timed out waiting for $what: ${client.state.value}")
    }

    private val url get() = server.url("/v1/realtime").toString().replace("http", "ws")

    @Before
    fun setUp() {
        server.start()
        client = VoiceClient(http, microphone, speaker, scheduler, retryDelaysMillis = listOf(50))
    }

    @After
    fun tearDown() {
        client.disconnect()
        scheduler.shutdownNow()
        server.shutdown()
    }

    @Test
    fun `on connecting it sends the session, then the opening message, then the microphone`() {
        val bridge = accept()
        client.connect(url)
        assertEquals("session.update", type(bridge.next()))
        assertEquals("conversation.item.create", type(bridge.next()))
        assertEquals("response.create", type(bridge.next()))
        waitFor("connected") { it.connection == Connection.CONNECTED }

        microphone.speak(byteArrayOf(5, 6, 7, 8))
        val append = bridge.next()
        assertEquals("input_audio_buffer.append", type(append))
        val audio = Json.parseToJsonElement(append).jsonObject["audio"]!!.jsonPrimitive.content
        assertArrayEquals(byteArrayOf(5, 6, 7, 8), Base64.getDecoder().decode(audio))
    }

    @Test
    fun `it offers the realtime subprotocol, as the bridge expects`() {
        accept()
        client.connect(url)
        val request = server.takeRequest(5, TimeUnit.SECONDS)
        assertEquals("realtime", request?.getHeader("Sec-WebSocket-Protocol"))
    }

    @Test
    fun `the voice is played, and stops as soon as we speak`() {
        val bridge = accept()
        client.connect(url)
        val socket = bridge.socket()
        waitFor("connected") { it.connection == Connection.CONNECTED }

        val pcm = byteArrayOf(1, 2, 3, 4)
        socket.send("""{"type":"response.output_audio.delta","delta":"${Base64.getEncoder().encodeToString(pcm)}"}""")
        speaker.awaitPlayed(1)
        assertArrayEquals(pcm, speaker.played[0])

        socket.send("""{"type":"input_audio_buffer.speech_started"}""")
        speaker.awaitInterrupts(1)
    }

    @Test
    fun `what we said and what the voice said are shown, and the sleep mode`() {
        val bridge = accept()
        client.connect(url)
        val socket = bridge.socket()
        socket.send("""{"type":"conversation.item.input_audio_transcription.completed","transcript":"Stop."}""")
        socket.send("""{"type":"response.output_audio_transcript.done","transcript":"Stopped."}""")
        socket.send("""{"type":"voicebridge.state","state":"asleep"}""")
        val state = waitFor("the lines") { it.lines.size == 2 && it.asleep == true }
        assertEquals(listOf(Line(Who.US, "Stop."), Line(Who.VOICE, "Stopped.")), state.lines)
    }

    @Test
    fun `the phrases are kept from the state that gave them`() {
        val bridge = accept()
        client.connect(url)
        val socket = bridge.socket()
        socket.send("""{"type":"voicebridge.state","state":"awake","wake":"Wake up, StepIt","sleep":"Go to sleep"}""")
        socket.send("""{"type":"voicebridge.state","state":"asleep"}""")
        val state = waitFor("asleep") { it.asleep == true }
        assertEquals(Phrases(wake = "Wake up, StepIt", sleep = "Go to sleep"), state.phrases)
    }

    @Test
    fun `a dropped connection is logged, and it reconnects with a new session`() {
        val first = accept()
        val second = accept()
        client.connect(url)
        val socket = first.socket()
        waitFor("connected") { it.connection == Connection.CONNECTED }

        socket.close(1011, "The speech-to-speech server cannot be reached")
        val back = waitFor("reconnected") { it.connection == Connection.CONNECTED && it.drops.isNotEmpty() }
        assertEquals("session.update", type(second.next()))
        assertEquals(1, back.drops.size)
        assertEquals("The speech-to-speech server cannot be reached", back.drops[0].reason)
        assertNotNull(back.drops[0].downMillis)
        assertTrue(microphone.stops >= 1)
    }

    @Test
    fun `a bridge that is not there is tried again, without counting a drop`() {
        client.connect(url)
        server.shutdown()
        val state = waitFor("retrying") { it.attempt >= 2 }
        assertEquals(Connection.RECONNECTING, state.connection)
        assertTrue(state.drops.isEmpty())
    }

    @Test
    fun `after disconnecting it stays disconnected`() {
        val bridge = accept()
        accept()
        client.connect(url)
        bridge.socket()
        waitFor("connected") { it.connection == Connection.CONNECTED }

        client.disconnect()
        Thread.sleep(200)
        val state = client.state.value
        assertEquals(Connection.DISCONNECTED, state.connection)
        assertTrue(state.drops.isEmpty())
        assertNull(microphone.listener)
        assertEquals(1, server.requestCount)
    }

    private class FakeMicrophone : Microphone {
        @Volatile var listener: ((ByteArray) -> Unit)? = null
        @Volatile var stops = 0

        override fun start(onChunk: (ByteArray) -> Unit) {
            listener = onChunk
        }

        override fun stop() {
            listener = null
            stops++
        }

        fun speak(pcm: ByteArray) = listener?.invoke(pcm) ?: error("The microphone is off")
    }

    private class FakeSpeaker : Speaker {
        val played = CopyOnWriteArrayList<ByteArray>()
        @Volatile var interrupts = 0

        override fun start() = Unit

        override fun play(pcm: ByteArray) {
            played.add(pcm)
        }

        override fun interrupt() {
            interrupts++
        }

        override fun stop() = Unit

        fun awaitPlayed(count: Int) = await { played.size >= count }

        fun awaitInterrupts(count: Int) = await { interrupts >= count }

        private fun await(condition: () -> Boolean) {
            val deadline = System.currentTimeMillis() + 5_000
            while (!condition()) {
                check(System.currentTimeMillis() < deadline) { "Timed out" }
                Thread.sleep(10)
            }
        }
    }
}
