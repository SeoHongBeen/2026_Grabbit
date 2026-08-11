package com.toi.grabbit

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

// RPi가 보내는 JSON 형식 (docs/json-schema.md 참고)
data class SoundAlert(
    val `class`: String,
    val direction: Int,
    val danger: Int,
    val timestamp: Long
)

class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private var pageReady = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 잠금/화면 꺼짐 상태에서 알림으로 실행될 때 화면을 켜고 잠금 위에 표시
        setShowWhenLocked(true)
        setTurnScreenOn(true)

        // 저장된 이력 복원 (WebView 로드 전에)
        AlertBus.restore(this)

        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            addJavascriptInterface(JsBridge(), "Android")
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    pageReady = true
                    pushHistory()
                }
            }
            loadUrl("file:///android_asset/grabbit_ui.html")
        }
        setContentView(web)

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

        // 새 알림 → 홈 화면 알림 카드 (drop(1): 복원된 옛 알림으로 시작하자마자 울리지 않게)
        lifecycleScope.launch {
            AlertBus.latest.drop(1).collect { alert ->
                alert ?: return@collect
                if (!pageReady) return@collect
                web.evaluateJavascript(
                    "onAlert('${alert.`class`}', ${alert.direction}, ${alert.danger}, ${alert.timestamp})",
                    null
                )
            }
        }

        // 히스토리 변경 → 목록/최근 감지 갱신
        lifecycleScope.launch {
            AlertBus.history.collect {
                if (pageReady) pushHistory()
            }
        }
    }

    /** 현재 히스토리 전체를 JSON으로 만들어 WebView에 전달 */
    private fun pushHistory() {
        val arr = JSONArray()
        AlertBus.history.value.forEach { a ->
            arr.put(JSONObject().apply {
                put("cls", a.`class`)
                put("deg", a.direction)
                put("danger", a.danger)
                put("ts", a.timestamp)
            })
        }
        web.evaluateJavascript("setHistory(${JSONObject.quote(arr.toString())})", null)
    }

    /** HTML 쪽에서 Android.○○○() 로 호출하는 다리 */
    inner class JsBridge {

        /** 설정 화면의 '테스트 알림 보내기' — 전체 파이프라인(워치·서버 포함) 테스트 */
        @JavascriptInterface
        fun sendTestAlert() {
            val classes = listOf(
                "glass_breaking", "siren", "doorbell",
                "door_wood_knock", "door_wood_creaks", "others"
            )
            // 4방향(앞/오른쪽/뒤/왼쪽) 균등 랜덤
            val dir = listOf(
                ((315..359) + (0..44)),   // 앞
                (45..134).toList(),       // 오른쪽
                (135..224).toList(),      // 뒤
                (225..314).toList()       // 왼쪽
            ).random().random()
            val fake = SoundAlert(
                `class` = classes.random(),
                direction = dir,
                danger = (0..3).random(),
                timestamp = System.currentTimeMillis() / 1000
            )
            GrabbitRelayService.handleAlert(this@MainActivity, fake)
        }

        /** 설정 화면의 '기록 전체 삭제' */
        @JavascriptInterface
        fun clearHistory() {
            AlertBus.clear(this@MainActivity)
        }
    }
}