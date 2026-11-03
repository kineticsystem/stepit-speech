// Copyright (c) 2026 Giovanni Remigi
// SPDX-License-Identifier: MIT

package com.kineticsystem.stepitspeech.audio

import android.media.AudioDeviceInfo
import android.media.AudioManager

/**
 * A USB microphone with no headset around it, e.g. the receiver of a wireless
 * clip-on microphone.
 *
 * With one plugged in the voice leaves call mode: in call mode with the
 * loudspeaker on, Android records from the phone's own microphone, next to the
 * loudspeaker, whatever the app asks for. Out of it, the microphone records
 * from the USB one and the voice plays as media on the loudspeaker; the call's
 * echo canceller is lost, but the clip-on microphone is far from the loudspeaker.
 * A USB headset, with its own earphones, stays in call mode, as before.
 */
object UsbMicrophone {
    private val INPUTS = setOf(AudioDeviceInfo.TYPE_USB_DEVICE, AudioDeviceInfo.TYPE_USB_HEADSET)
    private val HEADSETS = setOf(
        AudioDeviceInfo.TYPE_WIRED_HEADSET,
        AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
        AudioDeviceInfo.TYPE_USB_HEADSET,
    )

    /** The USB microphone to record from, or null: none, or a headset is plugged in. */
    fun find(audio: AudioManager): AudioDeviceInfo? {
        if (audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any { it.type in HEADSETS }) return null
        return audio.getDevices(AudioManager.GET_DEVICES_INPUTS).firstOrNull { it.type in INPUTS }
    }
}
