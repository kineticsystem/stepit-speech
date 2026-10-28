// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.audio

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build

/**
 * Puts the phone in call mode while the voice runs, and sends the audio to
 * the headset.
 *
 * In call mode a wired or USB-C headset is chosen on its own. A Bluetooth
 * headset needs its hands-free link, SCO, which switches its microphone to 8
 * or 16 kHz: fine for "yes" and "stop", worse for numbers. Android 12 and newer
 * choose the device with `setCommunicationDevice`; Android 11, e.g. the Moto
 * G9, with `startBluetoothSco`.
 */
class HeadsetRoute(context: Context) {
    private val audio = context.getSystemService(AudioManager::class.java)
    private var previousMode = AudioManager.MODE_NORMAL
    private var sco = false

    /** The headset in use, for the screen; "phone" without one. */
    var device: String = "phone"
        private set

    fun start() {
        previousMode = audio.mode
        audio.mode = AudioManager.MODE_IN_COMMUNICATION
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val available = audio.availableCommunicationDevices
            val chosen = PREFERENCE.firstNotNullOfOrNull { type -> available.firstOrNull { it.type == type } }
            if (chosen != null) {
                audio.setCommunicationDevice(chosen)
                device = name(chosen.type)
            }
        } else {
            val outputs = audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS).map { it.type }
            val wired = PREFERENCE.take(3).firstOrNull { it in outputs }
            if (wired != null) {
                device = name(wired)
            } else if (AudioDeviceInfo.TYPE_BLUETOOTH_SCO in outputs) {
                @Suppress("DEPRECATION")
                audio.startBluetoothSco()
                @Suppress("DEPRECATION")
                audio.isBluetoothScoOn = true
                sco = true
                device = name(AudioDeviceInfo.TYPE_BLUETOOTH_SCO)
            }
        }
    }

    fun stop() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            audio.clearCommunicationDevice()
        } else if (sco) {
            @Suppress("DEPRECATION")
            audio.isBluetoothScoOn = false
            @Suppress("DEPRECATION")
            audio.stopBluetoothSco()
            sco = false
        }
        audio.mode = previousMode
        device = "phone"
    }

    private fun name(type: Int) = when (type) {
        AudioDeviceInfo.TYPE_WIRED_HEADSET -> "wired headset"
        AudioDeviceInfo.TYPE_USB_HEADSET -> "USB headset"
        AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> "wired headphones"
        AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "Bluetooth headset"
        else -> "phone"
    }

    private companion object {
        /** Wired first: full quality and no radio to drop. */
        val PREFERENCE = listOf(
            AudioDeviceInfo.TYPE_WIRED_HEADSET,
            AudioDeviceInfo.TYPE_USB_HEADSET,
            AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
            AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
        )
    }
}
