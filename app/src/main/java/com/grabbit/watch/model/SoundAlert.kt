// SoundAlert.kt
package com.grabbit.watch.model

import com.google.gson.Gson
import com.google.gson.JsonSyntaxException

data class SoundAlert(
    val eventId: String,
    val timestamp: Long,
    val label: String,
    val danger: Int,
    val direction: String
)

object SoundAlertParser {
    private val gson = Gson()

    /**
     * JSON 문자열을 SoundAlert로 파싱.
     * 실패하면 null 반환 (호출부에서 null 체크해서 무시하거나 기본값 처리)
     */
    fun parse(json: String): SoundAlert? {
        return try {
            val alert = gson.fromJson(json, SoundAlert::class.java)
            // 필수 필드 누락 체크 (Gson은 없는 필드를 null로 채워서 통과시킴)
            if (alert.eventId.isNullOrBlank() || alert.label.isNullOrBlank()) {
                null
            } else {
                alert
            }
        } catch (e: JsonSyntaxException) {
            null
        }
    }
}