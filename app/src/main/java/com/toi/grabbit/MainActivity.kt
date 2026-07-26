package com.toi.grabbit

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

// RPi가 보내는 JSON 형식 (docs/json-schema.md 참고)
data class SoundAlert(
    val `class`: String,
    val direction: Int,
    val danger: Int,
    val timestamp: Long
)

class MainActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val statusView = TextView(this).apply {
            text = "Grabbit 수신 대기중... (포트 ${GrabbitRelayService.PORT})"
            textSize = 18f
            setPadding(40, 80, 40, 0)
        }
        setContentView(statusView)

        // 알림 권한 요청 (Android 13+)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
        }

        // HTTP 서버는 이제 Foreground Service가 담당
        ContextCompat.startForegroundService(
            this, Intent(this, GrabbitRelayService::class.java)
        )

        // 서비스가 받은 알림을 화면에 반영
        lifecycleScope.launch {
            AlertBus.latest.collect { alert ->
                alert ?: return@collect
                statusView.text =
                    "소리: ${alert.`class`}\n방향: ${alert.direction}도\n위험도: ${alert.danger}"
            }
        }
    }
}