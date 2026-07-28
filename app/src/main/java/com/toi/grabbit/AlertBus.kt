package com.toi.grabbit

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

object AlertBus {
    private val _latest = MutableStateFlow<SoundAlert?>(null)
    val latest: StateFlow<SoundAlert?> = _latest

    private val _history = MutableStateFlow<List<SoundAlert>>(emptyList())
    val history: StateFlow<List<SoundAlert>> = _history

    private var loaded = false

    /** 저장된 이력을 메모리로 복원 (앱/서비스 시작 시 1회) */
    fun restore(context: Context) {
        if (loaded) return
        _history.value = AlertStore.load(context)
        _latest.value = _history.value.firstOrNull()
        loaded = true
    }

    fun publish(context: Context, alert: SoundAlert) {
        restore(context)
        _latest.value = alert
        _history.value = (listOf(alert) + _history.value).take(200)
        AlertStore.save(context, _history.value)
    }

    fun clear(context: Context) {
        _history.value = emptyList()
        _latest.value = null
        AlertStore.clear(context)
    }
}