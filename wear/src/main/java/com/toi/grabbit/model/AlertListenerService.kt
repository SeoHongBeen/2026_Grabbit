package com.toi.grabbit.model

import android.util.Log
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.WearableListenerService

private const val TAG = "Grabbit"
private const val ALERT_PATH = "/grabbit/alert"

/**
 * 폰(서현 relay 앱)이 MessageClient로 보내는 메시지를 수신하는 서비스.
 * /grabbit/alert 경로로 온 메시지의 payload(JSON 바이트)를 콜백으로 전달.
 */
class AlertListenerService : WearableListenerService() {

    override fun onMessageReceived(event: MessageEvent) {
        Log.d(TAG, "메시지 수신: path=${event.path}")

        if (event.path != ALERT_PATH) {
            Log.d(TAG, "다른 경로 메시지 - 무시함 (${event.path})")
            return
        }

        val json = String(event.data, Charsets.UTF_8)
        Log.d(TAG, "alert 페이로드: $json")

        // 전역 콜백으로 MainActivity에 전달
        onAlertReceived?.invoke(json)
    }

    companion object {
        // MainActivity가 등록하는 콜백. Compose 쪽에서 currentAlert 갱신용.
        var onAlertReceived: ((String) -> Unit)? = null
    }
}