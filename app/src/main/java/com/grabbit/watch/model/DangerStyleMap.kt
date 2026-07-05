// DangerStyleMap.kt
package com.grabbit.watch.model

data class AlertStyle(
    val colorHex: String,
    val vibrationPattern: LongArray,
    val isBlinking: Boolean = false
)

object DangerStyleMap {
    val map: Map<Int, AlertStyle> = mapOf(
        1 to AlertStyle("#4CAF50", longArrayOf(0, 200)),
        2 to AlertStyle("#FFEB3B", longArrayOf(0, 150, 100, 150)),
        3 to AlertStyle("#FF9800", longArrayOf(0, 500)),
        4 to AlertStyle("#F44336", longArrayOf(0, 500, 200, 500, 200, 500), isBlinking = true)
    )

    fun styleFor(danger: Int): AlertStyle = map[danger] ?: map[1]!!
}