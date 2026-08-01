package com.toi.grabbit

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// RPi가 보내는 JSON 형식 (docs/json-schema.md 참고)
data class SoundAlert(
    val `class`: String,
    val direction: Int,
    val danger: Int,
    val timestamp: Long
)

class MainActivity : AppCompatActivity() {

    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.KOREA)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val statusView = TextView(this).apply {
            text = "Grabbit 수신 대기중... (포트 ${GrabbitRelayService.PORT})"
            textSize = 18f
        }

        val testButton = Button(this).apply {
            text = "테스트 알림 보내기"
            setOnClickListener {
                val classes = listOf(
                    "crackling_fire", "glass_breaking", "siren",
                    "door_wood_knock", "door_wood_creaks", "others"
                )
                // 전방(315~44) 제외 — 좌/우/후방만
                val dir = listOf(
                    (45..134).random(),
                    (135..224).random(),
                    (225..314).random()
                ).random()
                val fake = SoundAlert(
                    `class` = classes.random(),
                    direction = dir,
                    danger = (0..2).random(),
                    timestamp = System.currentTimeMillis() / 1000
                )
                GrabbitRelayService.handleAlert(this@MainActivity, fake)
            }
        }

        val clearButton = Button(this).apply {
            text = "기록 전체 삭제"
            setOnClickListener { AlertBus.clear(this@MainActivity) }
        }

        val historyTitle = TextView(this).apply {
            text = "알림 기록"
            textSize = 16f
            setPadding(0, 48, 0, 12)
        }

        val historyList = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }

        val scroll = ScrollView(this).apply {
            addView(historyList)
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(40, 80, 40, 40)
            addView(statusView)
            addView(testButton)
            addView(clearButton)
            addView(historyTitle)
            addView(scroll)
        }
        setContentView(root)

        // 저장된 이력 복원
        AlertBus.restore(this)

        // 알림 권한 요청 (Android 13+)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
        }

        // HTTP 서버는 Foreground Service가 담당
        ContextCompat.startForegroundService(
            this, Intent(this, GrabbitRelayService::class.java)
        )

        // 최신 알림 → 상단 상태 표시
        lifecycleScope.launch {
            AlertBus.latest.collect { alert ->
                alert ?: return@collect
                statusView.text =
                    "소리: ${alert.`class`}\n방향: ${dirLabel(alert.direction)}\n위험도: ${alert.danger}"
            }
        }

        // 히스토리 → 리스트 갱신
        lifecycleScope.launch {
            AlertBus.history.collect { list ->
                historyList.removeAllViews()
                if (list.isEmpty()) {
                    historyList.addView(TextView(this@MainActivity).apply {
                        text = "아직 감지된 소리가 없어요"
                        setTextColor(Color.GRAY)
                    })
                    return@collect
                }
                list.forEach { alert ->
                    historyList.addView(buildRow(alert))
                }
            }
        }
    }

    /** 각도 → 좌/우/후방 (전방은 사용 안 함) */
    private fun dirLabel(deg: Int): String = when (deg) {
        in 45..134 -> "오른쪽"
        in 135..224 -> "뒤쪽"
        in 225..314 -> "왼쪽"
        else -> "${deg}°"
    }

    private fun buildRow(alert: SoundAlert): TextView {
        val spec = alertMap[alert.`class`]
        val label = spec?.label ?: alert.`class`
        val color = spec?.let { Color.parseColor(it.color) } ?: Color.LTGRAY
        val time = timeFormat.format(Date(alert.timestamp * 1000))

        return TextView(this).apply {
            text = "$time   $label   ${dirLabel(alert.direction)}   위험도 ${alert.danger}"
            textSize = 15f
            setPadding(28, 24, 28, 24)
            setBackgroundColor(color)
            setTextColor(Color.WHITE)
            val lp = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
            lp.setMargins(0, 0, 0, 12)
            layoutParams = lp
        }
    }
}