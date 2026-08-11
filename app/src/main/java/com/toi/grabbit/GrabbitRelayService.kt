package com.toi.grabbit

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.app.PendingIntent
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
        const val ALERT_CHANNEL_ID = "grabbit_phone_alerts"
        const val ALERT_NOTI_ID = 2
        const val PORT = 8080
        const val TAG = "Grabbit"

        /** 수신 알림 공통 처리 — HTTP 수신부와 테스트 버튼 양쪽에서 사용 */
        fun handleAlert(context: Context, alert: SoundAlert) {
            Log.d(TAG, "수신: $alert")
            AlertBus.publish(context, alert)

            val rpiJson = JSONObject().apply {
                put("class", alert.`class`)
                put("direction", alert.direction)
                put("timestamp", alert.timestamp)
            }
            val sent = WatchSender.sendAlert(context, rpiJson)
            LogUploader.upload(alert)   // 백엔드 로그 서버로 전송 (실패해도 무시)
            Log.d(
                TAG,
                if (sent) "워치 전송 시도: ${alert.`class`}"
                else "워치 스킵(others/미등록): ${alert.`class`}"
            )

            // others가 아니면 폰 화면 깨우기 + full-screen 알림
            // (화면 꺼진 상태에서도 폰이 켜지면서 알림 화면 표시)
            if (sent) {
                wakePhoneScreen(context)
                postPhoneAlertNotification(context, alert)
            }
        }

        /** 화면 꺼진 상태에서 알림 수신 시 폰 화면을 깨움 (5초 후 자동 해제) */
        @Suppress("DEPRECATION")
        private fun wakePhoneScreen(context: Context) {
            try {
                val pm = context.getSystemService(PowerManager::class.java)
                pm.newWakeLock(
                    PowerManager.SCREEN_BRIGHT_WAKE_LOCK or
                        PowerManager.ACQUIRE_CAUSES_WAKEUP or
                        PowerManager.ON_AFTER_RELEASE,
                    "grabbit:phone_alert_wake"
                ).acquire(5_000L)
                Log.d(TAG, "폰 화면 깨우기 WakeLock 획득")
            } catch (e: Exception) {
                Log.w(TAG, "폰 화면 깨우기 실패: ${e.message}")
            }
        }

        /** full-screen intent 알림: 잠금/꺼짐 상태에서 시스템이 화면을 켜며 앱을 띄움 */
        private fun postPhoneAlertNotification(context: Context, alert: SoundAlert) {
            val nm = context.getSystemService(NotificationManager::class.java)
            if (nm.getNotificationChannel(ALERT_CHANNEL_ID) == null) {
                nm.createNotificationChannel(
                    NotificationChannel(
                        ALERT_CHANNEL_ID, "Grabbit 위험 알림",
                        NotificationManager.IMPORTANCE_HIGH
                    ).apply { description = "감지된 위험 소리 알림" }
                )
            }
            val spec = alertMap[alert.`class`]
            val fullScreenPi = PendingIntent.getActivity(
                context, 1,
                Intent(context, MainActivity::class.java).addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP
                ),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val noti = NotificationCompat.Builder(context, ALERT_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setContentTitle(spec?.label ?: alert.`class`)
                .setContentText("방향: ${alert.direction}도 / 위험도 ${alert.danger}")
                .setContentIntent(fullScreenPi)
                .setFullScreenIntent(fullScreenPi, true)
                .setCategory(NotificationCompat.CATEGORY_ALARM)
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setAutoCancel(true)
                .build()
            nm.notify(ALERT_NOTI_ID, noti)
            Log.d(TAG, "폰 full-screen 알림 게시: ${alert.`class`}")
        }
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
                        handleAlert(this@GrabbitRelayService, alert)
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