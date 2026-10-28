// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.voice

import com.kineticsystem.stepitspeech.protocol.Phrases

/** What the screen shows: the connection, the bridge's sleep mode, the conversation and the drops. */
data class VoiceState(
    val connection: Connection = Connection.DISCONNECTED,
    /** Reconnections tried since the last drop. */
    val attempt: Int = 0,
    /** The bridge's sleep mode; null until it says, as a bridge without sleep mode never does. */
    val asleep: Boolean? = null,
    /** The bridge's wake and sleep phrases; null until it says. */
    val phrases: Phrases? = null,
    /** The last lines of the conversation, oldest first. */
    val lines: List<Line> = emptyList(),
    /** Every time the connection was lost while we wanted it, oldest first. */
    val drops: List<Drop> = emptyList(),
    val error: String? = null,
)

enum class Connection { DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING }

data class Line(val speaker: Who, val text: String)

enum class Who { US, VOICE }

/** A lost connection: when, why, and how long until it came back, null while it is still down. */
data class Drop(val atMillis: Long, val reason: String, val downMillis: Long? = null)
