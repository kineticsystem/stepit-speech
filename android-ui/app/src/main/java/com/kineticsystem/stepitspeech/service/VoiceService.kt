// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.IBinder
import android.os.PowerManager
import com.kineticsystem.stepitspeech.R
import com.kineticsystem.stepitspeech.audio.AndroidMicrophone
import com.kineticsystem.stepitspeech.audio.AndroidSpeaker
import com.kineticsystem.stepitspeech.audio.HeadsetRoute
import com.kineticsystem.stepitspeech.ui.MainActivity
import com.kineticsystem.stepitspeech.voice.Connection
import com.kineticsystem.stepitspeech.voice.VoiceClient
import com.kineticsystem.stepitspeech.voice.VoiceState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import okhttp3.OkHttpClient
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Keeps the voice going with the screen off, in a pocket.
 *
 * A foreground service of type `microphone`, behind a permanent notification,
 * is how Android lets an app use the microphone with its screen locked. It
 * holds a partial wake lock, so that the CPU keeps streaming, and a Wi-Fi lock,
 * so that the radio does not doze between packets. The screen starts it, and
 * stops it with [stop] or the notification's Stop.
 */
class VoiceService : Service() {
    private lateinit var client: VoiceClient
    private lateinit var route: HeadsetRoute
    private val scheduler = Executors.newSingleThreadScheduledExecutor()
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    override fun onCreate() {
        super.onCreate()
        // Pings find a dead Wi-Fi in seconds; without them a socket can stay open on nothing for minutes.
        val http = OkHttpClient.Builder().pingInterval(10, TimeUnit.SECONDS).build()
        client = VoiceClient(http, AndroidMicrophone(), AndroidSpeaker(), scheduler, published = mutableState)
        route = HeadsetRoute(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        val url = intent?.getStringExtra(EXTRA_URL) ?: return START_NOT_STICKY
        startForeground(NOTIFICATION_ID, notification(url), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        acquireLocks()
        route.start()
        mutableHeadset.value = route.device
        client.connect(url)
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        client.disconnect()
        route.stop()
        mutableHeadset.value = null
        releaseLocks()
        scheduler.shutdownNow()
        mutableState.update { it.copy(connection = Connection.DISCONNECTED) }
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun acquireLocks() {
        if (wakeLock == null) {
            // No timeout: it is held as long as the service runs, and released in onDestroy.
            @Suppress("WakelockTimeout")
            wakeLock = getSystemService(PowerManager::class.java)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "StepItSpeech:voice")
                .apply { acquire() }
        }
        if (wifiLock == null) {
            // HIGH_PERF keeps the radio awake with the screen off; LOW_LATENCY, its successor, only with it on.
            @Suppress("DEPRECATION")
            wifiLock = getSystemService(WifiManager::class.java)
                .createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "StepItSpeech:voice")
                .apply { acquire() }
        }
    }

    private fun releaseLocks() {
        wakeLock?.takeIf { it.isHeld }?.release()
        wifiLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
        wifiLock = null
    }

    private fun notification(url: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW),
        )
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, VoiceService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_mic)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(url)
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, getString(R.string.stop), stop).build())
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "voice"
        private const val NOTIFICATION_ID = 1
        private const val ACTION_STOP = "com.kineticsystem.stepitspeech.STOP"
        private const val EXTRA_URL = "url"

        private val mutableState = MutableStateFlow(VoiceState())
        private val mutableHeadset = MutableStateFlow<String?>(null)

        /** The voice's state, for the screen; it outlives the service, so the last drops stay visible. */
        val state: StateFlow<VoiceState> = mutableState

        /** Where the audio goes while the service runs; null when it does not. */
        val headset: StateFlow<String?> = mutableHeadset

        fun start(context: Context, url: String) {
            context.startForegroundService(Intent(context, VoiceService::class.java).putExtra(EXTRA_URL, url))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, VoiceService::class.java))
        }
    }
}
