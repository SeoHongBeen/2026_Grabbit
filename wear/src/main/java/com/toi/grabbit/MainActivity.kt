package com.toi.grabbit

import android.content.Context
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Text
import com.toi.grabbit.model.AlertListenerService
import com.toi.grabbit.model.DirectionMap
import com.toi.grabbit.model.LabelMap
import com.toi.grabbit.model.SoundAlert
import com.toi.grabbit.model.SoundAlertParser
import com.toi.grabbit.model.VibrationTypeMap

private const val TAG = "Grabbit"

// 마지막으로 처리한 eventId를 기억 (앱 프로세스가 살아있는 동안 유지, 중복 알림 방지용)
private var lastProcessedEventId: String? = null

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            GrabbitWatchScreen()
        }
    }
}

/** vibration이 "none"이면 진동 자체를 실행하지 않음 */
fun triggerVibration(context: Context, vibration: String) {
    if (vibration == "none") {
        Log.d(TAG, "진동 스킵 (vibration=none)")
        return
    }
    val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
    val pattern = VibrationTypeMap.patternFor(vibration)
    vibrator.vibrate(VibrationEffect.createWaveform(pattern, -1))
    Log.d(TAG, "진동 실행: vibration=$vibration")
}

fun handleIncomingJson(json: String, onSuccess: (SoundAlert) -> Unit) {
    Log.d(TAG, "수신 JSON: $json")
    val alert = SoundAlertParser.parse(json)
    if (alert == null) {
        Log.w(TAG, "파싱 실패 또는 유효하지 않은 값 - 무시함")
        return
    }

    if (alert.eventId == lastProcessedEventId) {
        Log.d(TAG, "중복 eventId 감지 (${alert.eventId}) - 무시함")
        return
    }
    lastProcessedEventId = alert.eventId

    Log.d(TAG, "파싱 성공: eventId=${alert.eventId}, label=${alert.label}, color=${alert.color}, vibration=${alert.vibration}, direction=${alert.direction}")
    onSuccess(alert)
}

@Composable
fun GrabbitWatchScreen() {
    val context = LocalContext.current

    // "others"는 알림 자체를 표시하지 않으므로, 화면에 보여줄 현재 알림이 없을 수도 있음 (nullable)
    var currentAlert by remember { mutableStateOf<SoundAlert?>(null) }

    fun applyAlert(json: String) {
        handleIncomingJson(json) { alert ->
            if (alert.label == "others") {
                // others는 화면 표시/진동 없이 조용히 무시 (currentAlert 갱신 안 함)
                Log.d(TAG, "others 클래스 - 알림 표시 생략")
                return@handleIncomingJson
            }
            currentAlert = alert
            triggerVibration(context, alert.vibration)
        }
    }

    // MessageClient(폰 relay)로 수신된 alert를 화면에 반영
    DisposableEffect(Unit) {
        AlertListenerService.onAlertReceived = { json ->
            applyAlert(json)
        }
        onDispose {
            AlertListenerService.onAlertReceived = null
        }
    }

    val alert = currentAlert
    val baseColor = alert?.let { Color(android.graphics.Color.parseColor(it.color)) } ?: Color.DarkGray

    // vibration이 urgent일 때만 점멸
    val infiniteTransition = rememberInfiniteTransition(label = "blink")
    val blinkAlpha by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 0.2f,
        animationSpec = infiniteRepeatable(
            animation = tween(400, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "blinkAlpha"
    )
    val isUrgent = alert?.vibration == "urgent"
    val shapeColor = if (isUrgent) baseColor.copy(alpha = blinkAlpha) else baseColor

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black),
        contentAlignment = Alignment.Center
    ) {
        // 방향 도형 표시 (알림이 있을 때만)
        if (alert != null) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val cx = size.width / 2
                val cy = size.height / 2
                val r = size.width * 0.22f
                val shapeSize = size.width * 0.12f

                val sector = DirectionMap.sectorFor(alert.direction)
                val (x, y) = when (sector) {
                    "front" -> Pair(cx, cy - r)
                    "rear"  -> Pair(cx, cy + r)
                    "left"  -> Pair(cx - r, cy)
                    "right" -> Pair(cx + r, cy)
                    else    -> Pair(cx, cy)
                }

                // urgent면 세모(경고 느낌), 그 외엔 원
                if (!isUrgent) {
                    drawCircle(color = shapeColor, radius = shapeSize, center = Offset(x, y))
                } else {
                    val path = Path().apply {
                        moveTo(x, y - shapeSize)
                        lineTo(x + shapeSize, y + shapeSize)
                        lineTo(x - shapeSize, y + shapeSize)
                        close()
                    }
                    drawPath(path = path, color = shapeColor, style = Fill)
                }
            }
        }

        // 알림 텍스트 — 상단 고정. 알림 없으면 "대기 중" 표시
        Column(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = alert?.let { LabelMap.displayTextFor(it.label) } ?: "대기 중",
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                color = Color.White
            )
            if (alert != null) {
                Text(
                    text = DirectionMap.displayNameFor(alert.direction),
                    fontSize = 9.sp,
                    color = Color.LightGray
                )
            }
        }

        // Mock 테스트 버튼들 (실제 데이터는 MessageClient로도 수신됨)
        Column(
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                listOf(
                    Triple("crackling_fire", "#FF3B30", "urgent"),
                    Triple("glass_breaking", "#FF3B30", "urgent"),
                    Triple("siren", "#FF3B30", "urgent")
                ).forEach { (label, color, vib) ->
                    Button(
                        onClick = {
                            val mockJson = """
                                {"eventId":"evt_${System.currentTimeMillis()}",
                                 "label":"$label",
                                 "color":"$color",
                                 "vibration":"$vib",
                                 "direction":${alert?.direction ?: 0},
                                 "rpiTimestamp":${System.currentTimeMillis()},
                                 "phoneTimestamp":${System.currentTimeMillis()}}
                            """.trimIndent()
                            applyAlert(mockJson)
                        },
                        modifier = Modifier.size(28.dp),
                        colors = ButtonDefaults.buttonColors(
                            backgroundColor = Color(android.graphics.Color.parseColor(color))
                        )
                    ) {
                        Text(label.take(2), fontSize = 8.sp, color = Color.White)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                listOf(
                    Triple("door_wood_knock", "#FF9500", "normal"),
                    Triple("door_wood_creaks", "#007AFF", "soft"),
                    Triple("others", "#8E8E93", "none")
                ).forEach { (label, color, vib) ->
                    Button(
                        onClick = {
                            val mockJson = """
                                {"eventId":"evt_${System.currentTimeMillis()}",
                                 "label":"$label",
                                 "color":"$color",
                                 "vibration":"$vib",
                                 "direction":${alert?.direction ?: 0},
                                 "rpiTimestamp":${System.currentTimeMillis()},
                                 "phoneTimestamp":${System.currentTimeMillis()}}
                            """.trimIndent()
                            applyAlert(mockJson)
                        },
                        modifier = Modifier.size(28.dp),
                        colors = ButtonDefaults.buttonColors(
                            backgroundColor = Color(android.graphics.Color.parseColor(color))
                        )
                    ) {
                        Text(label.take(2), fontSize = 8.sp, color = Color.White)
                    }
                }
            }
            // 각도 테스트 버튼 (0/90/180/270도)
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf(0, 90, 180, 270).forEach { angle ->
                    Button(
                        onClick = {
                            val label = alert?.label ?: "siren"
                            val color = alert?.color ?: "#FF3B30"
                            val vib = alert?.vibration ?: "urgent"
                            val mockJson = """
                                {"eventId":"evt_${System.currentTimeMillis()}",
                                 "label":"$label",
                                 "color":"$color",
                                 "vibration":"$vib",
                                 "direction":$angle,
                                 "rpiTimestamp":${System.currentTimeMillis()},
                                 "phoneTimestamp":${System.currentTimeMillis()}}
                            """.trimIndent()
                            applyAlert(mockJson)
                        },
                        modifier = Modifier.size(28.dp),
                        colors = ButtonDefaults.buttonColors(backgroundColor = Color.DarkGray)
                    ) {
                        Text("${angle}°", fontSize = 8.sp, color = Color.White)
                    }
                }
            }
        }
    }
}