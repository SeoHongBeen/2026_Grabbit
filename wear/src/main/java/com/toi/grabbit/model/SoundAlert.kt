package com.toi.grabbit.model

import com.google.gson.Gson
import com.google.gson.JsonSyntaxException

data class SoundAlert(
    val eventId: String,
    val label: String,
    val color: String,        // 폰이 계산해서 보냄, 예: "#FF3B30"
    val vibration: String,    // "urgent" | "normal" | "soft" | "none"
    val direction: Int,       // 각도 0~360
    val rpiTimestamp: Long,
    val phoneTimestamp: Long
)

object SoundAlertParser {
    private val gson = Gson()
    private val validVibrations = setOf("urgent", "normal", "soft", "none")

    /**
     * JSON 문자열을 SoundAlert로 파싱.
     * 필수 필드 누락, vibration 값 이상, direction 범위(0~360) 벗어남 시 null 반환.
     */
    fun parse(json: String): SoundAlert? {
        return try {
            val alert = gson.fromJson(json, SoundAlert::class.java) ?: return null

            if (alert.eventId.isNullOrBlank() || alert.label.isNullOrBlank() || alert.color.isNullOrBlank()) {
                return null
            }
            if (alert.vibration !in validVibrations) {
                return null
            }
            if (alert.direction !in 0..360) {
                return null
            }
            alert
        } catch (e: JsonSyntaxException) {
            null
        } catch (e: Exception) {
            null
        }
    }
}