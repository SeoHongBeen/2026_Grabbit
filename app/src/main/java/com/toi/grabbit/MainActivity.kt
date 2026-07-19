package com.toi.grabbit

import android.os.Bundle
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import io.ktor.serialization.gson.gson
import io.ktor.server.application.call
import io.ktor.server.application.install
import io.ktor.server.engine.embeddedServer
import io.ktor.server.netty.Netty
import io.ktor.server.plugins.contentnegotiation.ContentNegotiation
import io.ktor.server.request.receive
import io.ktor.server.response.respond
import io.ktor.server.routing.post
import io.ktor.server.routing.routing
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

// RPi가 보내는 JSON 형식 (docs/json-schema.md 참고)
data class SoundAlert(
    val `class`: String,
    val direction: Int,
    val danger: Int,
    val timestamp: Long
)

class MainActivity : AppCompatActivity() {

    private val serverPort = 8080

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 화면에 상태 표시용 텍스트뷰 (레이아웃 파일 없이 코드로 간단히)
        val statusView = TextView(this).apply {
            text = "Grabbit 수신 대기중... (포트 $serverPort)"
            textSize = 18f
            setPadding(40, 80, 40, 0)
        }
        setContentView(statusView)

        // HTTP 서버를 백그라운드에서 시작
        CoroutineScope(Dispatchers.IO).launch {
            embeddedServer(Netty, port = serverPort) {
                install(ContentNegotiation) { gson() }
                routing {
                    post("/alert") {
                        val alert = call.receive<SoundAlert>()
                        Log.d("Grabbit", "수신: $alert")

                        // 화면 갱신은 메인 스레드에서
                        runOnUiThread {
                            statusView.text =
                                "소리: ${alert.`class`}\n방향: ${alert.direction}도\n위험도: ${alert.danger}"
                        }

                        // TODO: 실내/실외 모드 필터링 → 워치 전달 (수아 언니 파트랑 연결)
                        call.respond(mapOf("status" to "ok"))
                    }
                }
            }.start(wait = true)
        }
    }
}