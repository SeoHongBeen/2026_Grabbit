// VibrationTypeMap.kt
package com.toi.grabbit.model

object VibrationTypeMap {
    private val map: Map<String, LongArray> = mapOf(
        "urgent" to longArrayOf(0, 500, 200, 500, 200, 500),  // 길게 반복 (긴급)
        "normal" to longArrayOf(0, 150, 100, 150),             // 짧게 2회
        "soft" to longArrayOf(0, 100),                         // 짧고 약하게 1회
        "none" to longArrayOf(0)                               // 진동 없음
    )

    /** 정의되지 않은 타입이 오면 진동 없음으로 안전 처리 */
    fun patternFor(vibrationType: String): LongArray =
        map[vibrationType] ?: map["none"]!!
}