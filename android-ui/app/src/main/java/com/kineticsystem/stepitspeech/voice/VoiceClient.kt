// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.voice

import com.kineticsystem.stepitspeech.protocol.Realtime
import com.kineticsystem.stepitspeech.protocol.ServerEvent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/**
 * One voice connection to the bridge: the microphone goes up, the voice comes down.
 *
 * It opens the WebSocket, sends the session and the opening message, streams
 * the microphone while connected, plays the voice, and stops the voice as soon
 * as we start speaking. When the connection drops while we want it, it logs
 * the drop and tries again, after the delays of [retryDelaysMillis], the last
 * one repeated. Every reconnection is a new session of the bridge, which
 * cancels the goals of the old one: the drop log is what the pocket test is for.
 *
 * Every change of state happens under [lock]; the WebSocket's callbacks of an
 * old connection are ignored.
 */
class VoiceClient(
    private val http: OkHttpClient,
    private val microphone: Microphone,
    private val speaker: Speaker,
    private val scheduler: ScheduledExecutorService,
    private val clock: () -> Long = System::currentTimeMillis,
    private val retryDelaysMillis: List<Long> = listOf(500, 1_000, 2_000, 5_000),
    private val maxLines: Int = 20,
    /** Where the state is published: the service passes one the screen already watches. */
    private val published: MutableStateFlow<VoiceState> = MutableStateFlow(VoiceState()),
) {
    val state: StateFlow<VoiceState> = published

    private val lock = Any()
    private var url: String? = null
    private var socket: WebSocket? = null
    private var retry: ScheduledFuture<*>? = null

    /** Connects to the bridge, e.g. `ws://192.168.1.10:8766/v1/realtime`, and stays connected until [disconnect]. */
    fun connect(url: String) = synchronized(lock) {
        disconnectLocked()
        this.url = url
        published.value = VoiceState(connection = Connection.CONNECTING)
        open()
    }

    fun disconnect() = synchronized(lock) {
        disconnectLocked()
        published.update { it.copy(connection = Connection.DISCONNECTED, attempt = 0) }
    }

    private fun disconnectLocked() {
        url = null
        retry?.cancel(false)
        retry = null
        val old = socket
        socket = null
        old?.close(1000, "Disconnected")
        microphone.stop()
        speaker.stop()
    }

    private fun open() {
        val target = url ?: return
        val request = Request.Builder().url(target).header("Sec-WebSocket-Protocol", "realtime").build()
        socket = http.newWebSocket(request, Listener())
    }

    private inner class Listener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) = synchronized(lock) {
            if (webSocket !== socket) return
            webSocket.send(Realtime.sessionUpdate())
            Realtime.greeting().forEach(webSocket::send)
            speaker.start()
            microphone.start { chunk -> send(webSocket, chunk) }
            val now = clock()
            published.update { state ->
                state.copy(
                    connection = Connection.CONNECTED,
                    attempt = 0,
                    error = null,
                    drops = state.drops.map { if (it.downMillis == null) it.copy(downMillis = now - it.atMillis) else it },
                )
            }
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (synchronized(lock) { webSocket !== socket }) return
            when (val event = Realtime.parse(text)) {
                is ServerEvent.Audio -> speaker.play(event.pcm)
                ServerEvent.SpeechStarted -> speaker.interrupt()
                is ServerEvent.Heard -> addLine(Who.US, event.text)
                is ServerEvent.Said -> addLine(Who.VOICE, event.text)
                is ServerEvent.State -> published.update {
                    it.copy(asleep = event.asleep, phrases = event.phrases ?: it.phrases)
                }
                is ServerEvent.Error -> published.update { it.copy(error = event.message) }
                is ServerEvent.Other -> Unit
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
            lost(webSocket, reason.ifEmpty { "Closed by the bridge ($code)" })
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) =
            lost(webSocket, reason.ifEmpty { "Closed ($code)" })

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) =
            lost(webSocket, t.message ?: t.javaClass.simpleName)
    }

    private fun send(webSocket: WebSocket, chunk: ByteArray) {
        // OkHttp queues it; a socket that is closed refuses it.
        webSocket.send(Realtime.append(chunk))
    }

    private fun addLine(who: Who, text: String) {
        if (text.isEmpty()) return
        published.update { it.copy(lines = (it.lines + Line(who, text)).takeLast(maxLines)) }
    }

    private fun lost(webSocket: WebSocket, reason: String) = synchronized(lock) {
        if (webSocket !== socket) return
        socket = null
        microphone.stop()
        speaker.stop()
        if (url == null) return
        val state = published.value
        val attempt = state.attempt
        val drops = if (state.connection == Connection.CONNECTED) state.drops + Drop(clock(), reason) else state.drops
        published.value = state.copy(connection = Connection.RECONNECTING, attempt = attempt + 1, drops = drops,
            error = reason)
        val delay = retryDelaysMillis[minOf(attempt, retryDelaysMillis.lastIndex)]
        retry = scheduler.schedule({ synchronized(lock) { if (socket == null) open() } }, delay, TimeUnit.MILLISECONDS)
    }
}
