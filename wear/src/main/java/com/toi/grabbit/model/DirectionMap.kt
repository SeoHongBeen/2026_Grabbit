package com.toi.grabbit.model

object DirectionMap {

    fun sectorFor(angle: Int): String {
        if (angle == -1) return "unknown"
        val a = ((angle % 360) + 360) % 360
        return when {
            a >= 315 || a < 45 -> "front"
            a in 45..134 -> "right"
            a in 135..224 -> "rear"
            else -> "left"
        }
    }

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