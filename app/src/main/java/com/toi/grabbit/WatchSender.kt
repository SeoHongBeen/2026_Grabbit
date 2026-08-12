package com.toi.grabbit

import android.content.Context
import android.util.Log
import com.google.android.gms.wearable.Wearable
import org.json.JSONObject
import java.util.UUID

object WatchSender {
    private const val ALERT_PATH = "/grabbit/alert"

    /** RPi JSON을 받아 매핑 후 워치로 전송. others/미등록이면 false 반환(이력에만 기록용) */
    fun sendAlert(context: Context, rpiJson: JSONObject): Boolean {
        val cls = rpiJson.optString("class")
        val spec = alertMap[cls] ?: return false  // others/미등록 → 워치 전송 스킵

        val payload = JSONObject().apply {
            // [FIX] eventId가 빠져 있어서 워치 쪽 SoundAlertParser가
            // "eventId.isNullOrBlank()" 체크에 걸려 모든 실제 알림을 조용히 버리고 있었음.
            // 워치 mock 버튼은 자체적으로 eventId를 만들어 보내서 정상 동작했던 것.
            put("eventId", "evt_${System.currentTimeMillis()}_${UUID.randomUUID().toString().take(8)}")
            put("label", spec.label)
            put("color", spec.color)
            put("vibration", spec.vibration)
            put("direction", rpiJson.optInt("direction", -1))
            put("rpiTimestamp", rpiJson.optLong("timestamp"))
            // [FIX] 기존엔 / 1000.0 (Double)이라 "1754640000.123"처럼 소수점이 붙었음.
            // SoundAlert.phoneTimestamp는 Long 타입이라 워치 쪽 Gson 파싱이
            // JsonSyntaxException으로 실패 → 역시 조용히 무시되고 있었음.
            put("phoneTimestamp", System.currentTimeMillis() / 1000L)
        }.toString().toByteArray()

        Wearable.getNodeClient(context).connectedNodes
            .addOnSuccessListener { nodes ->
                if (nodes.isEmpty()) Log.w("WatchSender", "연결된 워치 없음")
                nodes.forEach { node ->
                    Wearable.getMessageClient(context)
                        .sendMessage(node.id, ALERT_PATH, payload)
                        .addOnSuccessListener { Log.d("WatchSender", "워치 전송 성공: $cls") }
                        .addOnFailureListener { e -> Log.e("WatchSender", "워치 전송 실패", e) }
                }
            }
        return true
    }
}
