package com.toi.grabbit

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Text
import com.toi.grabbit.model.AlertEffects
import com.toi.grabbit.model.AlertListenerService
import com.toi.grabbit.model.AlertProcessor
import com.toi.grabbit.model.DirectionMap
import com.toi.grabbit.model.LabelMap
import com.toi.grabbit.model.SoundAlert
import com.toi.grabbit.model.SoundAlertParser
import kotlinx.coroutines.delay

private const val TAG = "Grabbit"

// 알림 자동 해제까지의 시간 (ms)
private const val AUTO_DISMISS_MS = 8_000L
private const val URGENT_DISMISS_MS = 12_000L

class MainActivity : ComponentActivity() {

    // 화면에 표시할 현재 알림. 액티비티에서 hoisting해서
    // 서비스 콜백 / 인텐트 extra / mock 버튼 어디서 와도 여기로 모임.
    private val alertState = mutableStateOf<SoundAlert?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 워치 화면이 꺼져 있거나 잠금 상태여도 알림 수신 시 화면을 켜고 위에 표시
        setShowWhenLocked(true)
        setTurnScreenOn(true)

        requestNotificationPermissionIfNeeded()
        handleAlertIntent(intent)

        setContent {
            GrabbitWatchScreen(alertState)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // launchMode="singleTop"이라 백그라운드 수신으로 재실행되면 여기로 들어옴
        handleAlertIntent(intent)
    }

    /**
     * 백그라운드 수신 시 AlertListenerService가 넘겨준 alert JSON 처리.
     * 서비스에서 이미 파싱 검증/중복 제거/진동까지 끝낸 상태이므로
     * 여기서는 표시용 파싱만 다시 해서 화면에 반영.
     */
    private fun handleAlertIntent(intent: Intent?) {
        val json = intent?.getStringExtra(EXTRA_ALERT_JSON) ?: return
        intent.removeExtra(EXTRA_ALERT_JSON) // 회전/재생성 시 중복 처리 방지
        val alert = SoundAlertParser.parse(json) ?: return
        if (alert.label == "others") return
        Log.d(TAG, "인텐트로 alert 수신: ${alert.label}")
        alertState.value = alert
    }

    /** 백그라운드 수신 안전망(시스템 알림)을 위해 알림 권한 요청 (Wear OS 4 / API 33+) */
    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    companion object {
        const val EXTRA_ALERT_JSON = "extra_alert_json"
    }
}

@Composable
fun GrabbitWatchScreen(alertState: MutableState<SoundAlert?>) {
    val context = LocalContext.current

    // "others"는 알림 자체를 표시하지 않으므로, 화면에 보여줄 현재 알림이 없을 수도 있음 (nullable)
    var currentAlert by alertState

    // [ADD] mock 테스트 버튼 표시 여부. 기본은 숨김(깔끔한 실제 화면),
    // 상단 "대기 중" 영역을 길게 누르면 토글됨 — 개발/디버깅용.
    var showTestPanel by remember { mutableStateOf(false) }

    /** mock 버튼용: 파싱/중복제거 후 진동 + 화면 갱신 (실수신과 동일 경로인 AlertProcessor 사용) */
    fun applyMockAlert(json: String) {
        val alert = AlertProcessor.process(json) ?: return
        if (alert.label == "others") {
            // others는 화면 표시/진동 없이 조용히 무시 (currentAlert 갱신 안 함)
            Log.d(TAG, "others 클래스 - 알림 표시 생략")
            return
        }
        AlertEffects.vibrate(context, alert.vibration)
        currentAlert = alert
    }

    // MessageClient(폰 relay)로 수신된 alert를 화면에 반영
    // (진동/중복제거는 서비스에서 이미 처리됨 - 여기선 화면 갱신만)
    DisposableEffect(Unit) {
        AlertListenerService.onAlertReceived = { alert ->
            currentAlert = alert
        }
        onDispose {
            AlertListenerService.onAlertReceived = null
        }
    }

    val alert = currentAlert

    // 알림 자동 해제: 일정 시간이 지나면 "대기 중"으로 복귀
    // (urgent는 조금 더 길게 유지)
    LaunchedEffect(alert?.eventId) {
        if (alert != null) {
            delay(if (alert.vibration == "urgent") URGENT_DISMISS_MS else AUTO_DISMISS_MS)
            currentAlert = null
            Log.d(TAG, "알림 자동 해제 → 대기 중 복귀")
        }
    }

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

    // 파동(ripple) 애니메이션 — 방향이 있을 때 도형 주변으로 원이 퍼져나감
    val rippleTransition = rememberInfiniteTransition(label = "ripple")
    val rippleProgress by rippleTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1200, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "rippleProgress"
    )

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

                // 파동: unknown이 아닐 때만 방향 쪽으로 퍼져나가는 원 표시
                if (sector != "unknown") {
                    val rippleRadius = shapeSize + (shapeSize * 1.8f * rippleProgress)
                    val rippleAlpha = (1f - rippleProgress) * 0.6f
                    drawCircle(
                        color = baseColor.copy(alpha = rippleAlpha),
                        radius = rippleRadius,
                        center = Offset(x, y),
                        style = Stroke(width = 3f)
                    )
                }
            }
        }

        // 알림 텍스트 — 상단 고정. 알림 없으면 "대기 중" 표시
        // [ADD] 길게 누르면 하단 mock 테스트 패널 표시/숨김 토글 (개발자용, 화면 안 가림)
        Column(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 28.dp)
                .pointerInput(Unit) {
                    detectTapGestures(
                        onLongPress = { showTestPanel = !showTestPanel }
                    )
                },
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
        // [CHANGE] 기본 숨김. "대기 중" 텍스트 길게 눌러야 나타남 → 평소 화면 안 가림.
        if (showTestPanel) {
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
                                applyMockAlert(mockJson)
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
                                applyMockAlert(mockJson)
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
                // 각도 테스트 버튼 (0/90/180/270도 + unknown)
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    listOf(0, 90, 180, 270, -1).forEach { angle ->
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
                                applyMockAlert(mockJson)
                            },
                            modifier = Modifier.size(28.dp),
                            colors = ButtonDefaults.buttonColors(backgroundColor = Color.DarkGray)
                        ) {
                            Text(if (angle == -1) "?" else "${angle}°", fontSize = 8.sp, color = Color.White)
                        }
                    }
                }
            }
        }
    }
}