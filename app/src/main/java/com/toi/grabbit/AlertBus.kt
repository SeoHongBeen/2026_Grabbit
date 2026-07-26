package com.toi.grabbit

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

object AlertBus {
    private val _latest = MutableStateFlow<SoundAlert?>(null)
    val latest: StateFlow<SoundAlert?> = _latest

    private val _history = MutableStateFlow<List<SoundAlert>>(emptyList())
    val history: StateFlow<List<SoundAlert>> = _history

    fun publish(alert: SoundAlert) {
        _latest.value = alert
        _history.value = (listOf(alert) + _history.value).take(50)
    }
}