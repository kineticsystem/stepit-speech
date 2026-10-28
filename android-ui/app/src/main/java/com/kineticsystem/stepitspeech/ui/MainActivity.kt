// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.ui

import android.Manifest
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.kineticsystem.stepitspeech.R
import com.kineticsystem.stepitspeech.protocol.Phrases
import com.kineticsystem.stepitspeech.service.VoiceService
import com.kineticsystem.stepitspeech.voice.Connection
import com.kineticsystem.stepitspeech.voice.Drop
import com.kineticsystem.stepitspeech.voice.VoiceState
import com.kineticsystem.stepitspeech.voice.Who
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * The one screen: the bridge's address, Start and Stop, and what the voice is
 * doing. It decides nothing; the service holds the voice, the bridge the robot.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val preferences = getSharedPreferences("voice", Context.MODE_PRIVATE)
        setContent {
            MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()) {
                val state by VoiceService.state.collectAsStateWithLifecycle()
                val headset by VoiceService.headset.collectAsStateWithLifecycle()
                var url by remember { mutableStateOf(preferences.getString(KEY_URL, DEFAULT_URL) ?: DEFAULT_URL) }
                var phrases by remember { mutableStateOf(savedPhrases(preferences)) }
                // The bridge's phrases, kept for the next start, when the app has not connected yet.
                LaunchedEffect(state.phrases) {
                    state.phrases?.let { given ->
                        phrases = given
                        preferences.edit().putString(KEY_WAKE, given.wake).putString(KEY_SLEEP, given.sleep).apply()
                    }
                }
                val permissions = rememberLauncherForActivityResult(
                    ActivityResultContracts.RequestMultiplePermissions(),
                ) { granted ->
                    if (granted[Manifest.permission.RECORD_AUDIO] == true) VoiceService.start(this, url)
                }
                Screen(
                    state = state,
                    phrases = phrases,
                    headset = headset,
                    url = url,
                    onUrl = { url = it },
                    onStart = {
                        preferences.edit().putString(KEY_URL, url).apply()
                        if (hasMicrophone()) VoiceService.start(this, url) else permissions.launch(wanted())
                    },
                    onStop = { VoiceService.stop(this) },
                )
            }
        }
    }

    /** The phrases the last bridge gave, or those of the plan until a bridge has given any. */
    private fun savedPhrases(preferences: SharedPreferences) = Phrases(
        wake = preferences.getString(KEY_WAKE, null) ?: getString(R.string.default_wake),
        sleep = preferences.getString(KEY_SLEEP, null) ?: getString(R.string.default_sleep),
    )

    private fun hasMicrophone() =
        ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    /** The microphone, and on Android 13 and newer the notification of the service. */
    private fun wanted(): Array<String> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS)
        } else {
            arrayOf(Manifest.permission.RECORD_AUDIO)
        }

    private companion object {
        const val KEY_URL = "url"
        const val KEY_WAKE = "wake"
        const val KEY_SLEEP = "sleep"

        /** The host computer, as the emulator sees it; on a phone, the computer's address on the Wi-Fi. */
        const val DEFAULT_URL = "ws://10.0.2.2:8766/v1/realtime"
    }
}

@Composable
private fun Screen(
    state: VoiceState,
    phrases: Phrases,
    headset: String?,
    url: String,
    onUrl: (String) -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
) {
    val running = state.connection != Connection.DISCONNECTED
    Scaffold { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("StepIt Speech", style = MaterialTheme.typography.headlineSmall)
            PhrasesCard(phrases)
            OutlinedTextField(
                value = url,
                onValueChange = onUrl,
                label = { Text("Bridge") },
                singleLine = true,
                enabled = !running,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onStart, enabled = !running) { Text("Start") }
                Button(onClick = onStop, enabled = running) { Text("Stop") }
            }
            Text(status(state), fontWeight = FontWeight.Bold)
            if (headset != null) Text("Audio: $headset")
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            HorizontalDivider()
            Text("Drops: ${state.drops.size}", fontWeight = FontWeight.Bold)
            state.drops.takeLast(5).forEach { Text(describe(it), style = MaterialTheme.typography.bodySmall) }
            HorizontalDivider()
            LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                items(state.lines.reversed()) { line ->
                    Text(
                        (if (line.speaker == Who.US) "You: " else "Voice: ") + line.text,
                        fontWeight = if (line.speaker == Who.US) FontWeight.Normal else FontWeight.Medium,
                    )
                }
            }
        }
    }
}

/** What to say to wake the voice, exactly, and to put it to sleep, in our own words. */
@Composable
private fun PhrasesCard(phrases: Phrases) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("To wake it, say exactly", style = MaterialTheme.typography.labelMedium)
            Text("“${phrases.wake}”", style = MaterialTheme.typography.titleLarge)
            phrases.sleep?.let { sleep ->
                Spacer(Modifier.height(8.dp))
                Text("To put it to sleep, say something like", style = MaterialTheme.typography.labelMedium)
                Text("“$sleep”", style = MaterialTheme.typography.titleMedium)
                Text("and confirm with “yes”.", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

private fun status(state: VoiceState): String {
    val connection = when (state.connection) {
        Connection.DISCONNECTED -> "Stopped"
        Connection.CONNECTING -> "Connecting…"
        Connection.CONNECTED -> "Connected"
        Connection.RECONNECTING -> "Reconnecting, attempt ${state.attempt}…"
    }
    return when (state.asleep) {
        true -> "$connection, asleep"
        false -> "$connection, awake"
        null -> connection
    }
}

private fun describe(drop: Drop): String {
    val at = SimpleDateFormat("HH:mm:ss", Locale.ROOT).format(Date(drop.atMillis))
    val down = drop.downMillis?.let { "down %.1f s".format(Locale.ROOT, it / 1000.0) } ?: "still down"
    return "$at, $down: ${drop.reason}"
}
