package com.toi.grabbit

data class AlertSpec(
    val label: String,
    val color: String,
    val vibration: String
)

val alertMap = mapOf(
    "crackling_fire"   to AlertSpec("화재 소리!", "#FF3B30", "urgent"),
    "glass_breaking"   to AlertSpec("유리 깨짐!", "#FF3B30", "urgent"),
    "siren"            to AlertSpec("사이렌!",   "#FF3B30", "urgent"),
    "door_wood_knock"  to AlertSpec("노크 소리", "#FF9500", "normal"),
    "door_wood_creaks" to AlertSpec("문 소리",   "#007AFF", "soft")
)
// alertMap[클래스명]이 null이면 → others/미등록 → 워치 전송 스킵, 이력에만 저장

