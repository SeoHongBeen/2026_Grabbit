package com.toi.grabbit

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * 알림 1건을 노트북의 Django 로그 서버로 전송 (fire-and-forget).
 *
 * - 서버가 꺼져 있거나 IP가 틀려도 알림 경로에는 아무 영향 없음 (로그만 남김)
 * - 지금은 에뮬레이터 테스트용 주소(10.0.2.2 = 내 맥북)
 * - 데모 날 실기기로 갈 땐: 맥 터미널에서 `ipconfig getifaddr en0` 으로
 *   맥북 IP 확인 후 그 주소로 SERVER_URL 변경 (예: http://192.168.0.5:8000/logs)
 */
object LogUploader {

    /** ★ 에뮬레이터용. 데모 날 실기기 테스트 시 맥북 IP로 변경 */
    private const val SERVER_URL = "http://10.0.2.2:8000/logs"

    private const val TAG = "Grabbit"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    fun upload(alert: SoundAlert) {
        scope.launch {
            try {
                val body = JSONObject().apply {
                    put("class", alert.`class`)
                    put("direction", alert.direction)
                    put("danger", alert.danger)
                    put("timestamp", alert.timestamp)
                }.toString()

                Log.d(TAG, "로그 서버 전송 시도 → $SERVER_URL")
                val conn = URL(SERVER_URL).openConnection() as HttpURLConnection
                conn.requestMethod = "POST"
                conn.connectTimeout = 5_000
                conn.readTimeout = 5_000
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toByteArray()) }

                val code = conn.responseCode
                conn.disconnect()
                Log.d(TAG, "로그 서버 전송: ${alert.`class`} → HTTP $code")
            } catch (e: Exception) {
                // 서버 미실행/IP 오류 등 — 조용히 스킵 (알림 경로 보호)
                Log.d(TAG, "로그 서버 전송 스킵: ${e.javaClass.simpleName} / ${e.message}")
            }
        }
    }
}