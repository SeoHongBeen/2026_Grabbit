package com.toi.grabbit

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
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
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject

class GrabbitRelayService : Service() {

    companion object {
        const val CHANNEL_ID = "grabbit_relay"
        const val NOTI_ID = 1
        const val PORT = 8080
        private const val TAG = "Grabbit"
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var stopServer: (() -> Unit)? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTI_ID,
                buildNotification(),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            )
        } else {
            startForeground(NOTI_ID, buildNotification())
        }
        startKtor()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    private fun startKtor() {
        if (stopServer != null) return
        scope.launch {
            val server = embeddedServer(Netty, port = PORT) {
                install(ContentNegotiation) { gson() }
                routing {
                    post("/alert") {
                        val alert = call.receive<SoundAlert>()
                        Log.d(TAG, "수신: $alert")

                        AlertBus.publish(alert)

                        val rpiJson = JSONObject().apply {
                            put("class", alert.`class`)
                            put("direction", alert.direction)
                            put("timestamp", alert.timestamp)
                        }
                        val sent = WatchSender.sendAlert(this@GrabbitRelayService, rpiJson)
                        Log.d(
                            TAG,
                            if (sent) "워치 전송 시도: ${alert.`class`}"
                            else "워치 스킵(others/미등록): ${alert.`class`}"
                        )

                        call.respond(mapOf("status" to "ok"))
                    }
                }
            }
            server.start(wait = false)
            stopServer = { server.stop(1_000, 2_000) }
            Log.d(TAG, "Ktor 서버 시작 (포트 $PORT)")
        }
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(
                CHANNEL_ID, "Grabbit 감지",
                NotificationManager.IMPORTANCE_LOW
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
        }
    }

    private fun buildNotification() =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Grabbit 감지 중")
            .setContentText("주변 소리를 워치로 전달하고 있어요")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setOngoing(true)
            .build()

    override fun onDestroy() {
        stopServer?.invoke()
        scope.cancel()
        super.onDestroy()
        Log.d(TAG, "서비스 종료")
    }

    override fun onBind(intent: Intent?): IBinder? = null
}