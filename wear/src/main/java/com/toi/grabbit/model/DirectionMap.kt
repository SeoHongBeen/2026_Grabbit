package com.toi.grabbit.model

/**
 * 각도(0~360, 0=정면 기준 시계방향 가정) → 4방향 섹터 변환
 * ⚠️ 이 기준(0=front, 시계방향)은 주하(방향 추정) 쪽과 반드시 확인 필요
 */
object DirectionMap {

    /** 각도를 4방향 중 하나로 분류: front / right / rear / left */
    fun sectorFor(angle: Int): String {
        val a = ((angle % 360) + 360) % 360  // 음수 방지
        return when {
            a >= 315 || a < 45 -> "front"
            a in 45..134 -> "right"
            a in 135..224 -> "rear"
            else -> "left"
        }
    }

    /** 화면 하단에 표시할 한글 방향 텍스트 */
    fun displayNameFor(angle: Int): String {
        return when (sectorFor(angle)) {
            "front" -> "정면"
            "right" -> "오른쪽"
            "rear" -> "후방"
            "left" -> "왼쪽"
            else -> "알 수 없음"
        }
    }
}