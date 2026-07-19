package com.toi.grabbit.model

/** label(영문 클래스명) → 화면에 표시할 한글 문구 매핑 */
object LabelMap {
    private val map = mapOf(
        "crackling_fire" to "화재 소리!",
        "glass_breaking" to "유리 깨짐!",
        "siren" to "사이렌!",
        "door_wood_knock" to "노크 소리",
        "door_wood_creaks" to "문 소리",
        "others" to "알 수 없는 소리"
    )

    fun displayTextFor(label: String): String = map[label] ?: label
}