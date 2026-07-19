package com.toi.grabbit

import android.content.Context
import android.util.Log
import com.google.android.gms.wearable.Wearable
import org.json.JSONObject

object WatchSender {
    private const val ALERT_PATH = "/grabbit/alert"

    /** RPi JSON을 받아 매핑 후 워치로 전송. others/미등록이면 false 반환(이력에만 기록용) */
    fun sendAlert(context: Context, rpiJson: JSONObject): Boolean {
        val cls = rpiJson.optString("class")
        val spec = alertMap[cls] ?: return false  // others/미등록 → 워치 전송 스킵

        val payload = JSONObject().apply {
            put("label", spec.label)
            put("color", spec.color)
            put("vibration", spec.vibration)
            put("direction", rpiJson.optInt("direction", -1))
            put("rpiTimestamp", rpiJson.optLong("timestamp"))
            put("phoneTimestamp", System.currentTimeMillis() / 1000.0)
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

