package com.toi.grabbit

import android.content.Context
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** 알림 이력을 앱 내부 저장소에 JSON 파일로 보관 */
object AlertStore {
    private const val FILE_NAME = "alert_history.json"
    private const val MAX = 200

    private fun file(context: Context) = File(context.filesDir, FILE_NAME)

    fun load(context: Context): List<SoundAlert> = try {
        val f = file(context)
        if (!f.exists()) emptyList()
        else {
            val arr = JSONArray(f.readText())
            (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                SoundAlert(
                    `class` = o.getString("class"),
                    direction = o.getInt("direction"),
                    danger = o.getInt("danger"),
                    timestamp = o.getLong("timestamp")
                )
            }
        }
    } catch (e: Exception) {
        Log.e("Grabbit", "이력 불러오기 실패", e)
        emptyList()
    }

    fun save(context: Context, list: List<SoundAlert>) {
        try {
            val arr = JSONArray()
            list.take(MAX).forEach { a ->
                arr.put(JSONObject().apply {
                    put("class", a.`class`)
                    put("direction", a.direction)
                    put("danger", a.danger)
                    put("timestamp", a.timestamp)
                })
            }
            file(context).writeText(arr.toString())
        } catch (e: Exception) {
            Log.e("Grabbit", "이력 저장 실패", e)
        }
    }

    fun clear(context: Context) {
        file(context).delete()
    }
}
