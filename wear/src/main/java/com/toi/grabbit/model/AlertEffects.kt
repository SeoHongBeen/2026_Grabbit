package com.toi.grabbit.model

import android.content.Context
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Log

/**
 * 진동 실행 유틸.
 * 서비스(백그라운드 수신)와 액티비티(mock 버튼) 양쪽에서 사용하므로
 * MainActivity에서 분리함.
 */
object AlertEffects {
    private const val TAG = "Grabbit"

    /** vibration이 "none"이면 진동 자체를 실행하지 않음 */
    fun vibrate(context: Context, vibration: String) {
        if (vibration == "none") {
            Log.d(TAG, "진동 스킵 (vibration=none)")
            return
        }
        val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        val pattern = VibrationTypeMap.patternFor(vibration)
        vibrator.vibrate(VibrationEffect.createWaveform(pattern, -1))
        Log.d(TAG, "진동 실행: vibration=$vibration")
    }
}
