package com.toi.grabbit.model

import android.util.Log

/**
 * JSON 파싱 + eventId 중복 제거를 한 곳에서 처리.
 *
 * 기존에는 MainActivity 파일의 전역 변수로 dedup을 관리했지만,
 * 백그라운드 수신(AlertListenerService)과 화면(mock 버튼) 양쪽에서
 * 같은 기록을 공유해야 하므로 object로 분리함.
 */
object AlertProcessor {
    private const val TAG = "Grabbit"
    private const val MAX_RECENT_EVENTS = 20

    // 최근 처리한 eventId들 (최대 20개 유지 - 중복 알림 방지용)
    private val recentEventIds = ArrayDeque<String>()

    /**
     * 파싱 실패 / 유효하지 않은 값 / 중복 eventId면 null 반환.
     * 성공 시 dedup 기록에 등록 후 SoundAlert 반환.
     */
    @Synchronized
    fun process(json: String): SoundAlert? {
        Log.d(TAG, "수신 JSON: $json")

        val alert = SoundAlertParser.parse(json)
        if (alert == null) {
            Log.w(TAG, "파싱 실패 또는 유효하지 않은 값 - 무시함")
            return null
        }

        if (recentEventIds.contains(alert.eventId)) {
            Log.d(TAG, "중복 eventId 감지 (${alert.eventId}) - 무시함")
            return null
        }
        recentEventIds.addLast(alert.eventId)
        if (recentEventIds.size > MAX_RECENT_EVENTS) {
            recentEventIds.removeFirst()
        }

        Log.d(TAG, "파싱 성공: eventId=${alert.eventId}, label=${alert.label}, color=${alert.color}, vibration=${alert.vibration}, direction=${alert.direction}")
        return alert
    }
}
