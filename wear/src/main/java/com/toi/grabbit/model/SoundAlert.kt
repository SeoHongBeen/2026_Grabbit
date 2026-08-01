package com.toi.grabbit.model

import com.google.gson.Gson
import com.google.gson.JsonSyntaxException

data class SoundAlert(
    val eventId: String,
    val label: String,
    val color: String,
    val vibration: String,
    val direction: Int,       // 각도 0~360, -1이면 unknown
    val rpiTimestamp: Long,
    val phoneTimestamp: Long
)

object SoundAlertParser {
    private val gson = Gson()
    private val validVibrations = setOf("urgent", "normal", "soft", "none")

    fun parse(json: String): SoundAlert? {
        return try {
            val alert = gson.fromJson(json, SoundAlert::class.java) ?: return null

            if (alert.eventId.isNullOrBlank() || alert.label.isNullOrBlank() || alert.color.isNullOrBlank()) {
                return null
            }
            if (alert.vibration !in validVibrations) {
                return null
            }
            if (alert.direction != -1 && alert.direction !in 0..360) {
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