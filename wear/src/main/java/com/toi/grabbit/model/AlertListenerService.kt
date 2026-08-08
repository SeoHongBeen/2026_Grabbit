package com.toi.grabbit.model

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.util.Log
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.WearableListenerService
import com.toi.grabbit.MainActivity

private const val TAG = "Grabbit"
private const val ALERT_PATH = "/grabbit/alert"

/**
 * 폰(relay 앱)이 MessageClient로 보내는 메시지를 수신하는 서비스.
 *
 * [변경] 기존에는 콜백으로 MainActivity에 전달만 했기 때문에,
 * 앱이 백그라운드/종료 상태면 알림이 통째로 유실됐음 (진동도 안 울림).
 * 이제 진동은 액티비티 유무와 무관하게 서비스에서 직접 실행하고,
 * 액티비티가 없으면 화면을 깨우면서 실행 시도 + 시스템 알림 게시(이중 안전망).
 */
class AlertListenerService : WearableListenerService() {

    override fun onMessageReceived(event: MessageEvent) {
        Log.d(TAG, "메시지 수신: path=${event.path}")

        if (event.path != ALERT_PATH) {
            Log.d(TAG, "다른 경로 메시지 - 무시함 (${event.path})")
            return
        }

        val json = String(event.data, Charsets.UTF_8)

        // 파싱 + 중복 제거 (AlertProcessor가 dedup 기록을 전역 관리)
        val alert = AlertProcessor.process(json) ?: return

        if (alert.label == "others") {
            Log.d(TAG, "others 클래스 - 알림 생략")
            return
        }

        // 1) 진동: 앱 화면 유무와 무관하게 서비스에서 바로 실행
        //    → 워치 화면 꺼짐 / 앱 종료 상태에서도 진동 보장
        AlertEffects.vibrate(this, alert.vibration)

        // 2) 액티비티가 떠 있으면 콜백으로 화면만 갱신 (진동은 위에서 이미 실행됨)
        val callback = onAlertReceived
        if (callback != null) {
            callback(alert)
            return
        }

        // 3) 액티비티가 없으면: 실행 시도 + 시스템 알림 게시
        //    (Wear OS 백그라운드 액티비티 실행 제한에 걸릴 수 있어 알림을 안전망으로 병행)
        try {
            startActivity(Intent(this, MainActivity::class.java).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP
                )
                putExtra(MainActivity.EXTRA_ALERT_JSON, json)
            })
            Log.d(TAG, "백그라운드 수신 → 액티비티 실행 시도")
        } catch (e: Exception) {
            Log.w(TAG, "액티비티 실행 실패: ${e.message}")
        }
        postAlertNotification(alert, json)
    }

    private fun postAlertNotification(alert: SoundAlert, json: String) {
        val nm = getSystemService(NotificationManager::class.java)

        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Grabbit 위험 알림",
                    NotificationManager.IMPORTANCE_HIGH
                ).apply { description = "감지된 위험 소리 알림" }
            )
        }

        val contentIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP
                )
                putExtra(MainActivity.EXTRA_ALERT_JSON, json)
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(LabelMap.displayTextFor(alert.label))
            .setContentText(DirectionMap.displayNameFor(alert.direction))
            .setContentIntent(contentIntent)
            .setAutoCancel(true)
            .build()

        nm.notify(NOTIFICATION_ID, notification)
        Log.d(TAG, "시스템 알림 게시: ${alert.label}")
    }

    companion object {
        /**
         * MainActivity가 등록하는 콜백.
         * 서비스에서 파싱/중복제거/진동까지 끝낸 SoundAlert를 전달하므로,
         * 액티비티 쪽에서는 화면 갱신만 하면 됨.
         */
        var onAlertReceived: ((SoundAlert) -> Unit)? = null

        private const val CHANNEL_ID = "grabbit_alerts"
        private const val NOTIFICATION_ID = 1001
    }
}
