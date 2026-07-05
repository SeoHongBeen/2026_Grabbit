package com.grabbit.watch

import android.content.Context
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
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
import com.grabbit.watch.model.DangerStyleMap
import com.grabbit.watch.model.SoundAlertParser

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            GrabbitWatchScreen()
        }
    }
}

fun triggerVibration(context: Context, danger: Int) {
    val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
    val pattern = DangerStyleMap.styleFor(danger).vibrationPattern
    vibrator.vibrate(VibrationEffect.createWaveform(pattern, -1))
}

@Composable
fun GrabbitWatchScreen() {
    val context = LocalContext.current
    var dangerLevel by remember { mutableStateOf(1) }
    var direction by remember { mutableStateOf("right") }

    // JSON 문자열을 받아서 파싱 후 상태 반영 + 진동까지 처리하는 함수
    fun applyAlert(json: String) {
        val alert = SoundAlertParser.parse(json)
        if (alert != null) {
            dangerLevel = alert.danger
            direction = alert.direction
            triggerVibration(context, alert.danger)
        }
        // 파싱 실패 시 조용히 무시 (추후 로그 추가 고려)
    }

    val style = DangerStyleMap.styleFor(dangerLevel)
    val baseColor = Color(android.graphics.Color.parseColor(style.colorHex))

    // 레벨 4일 때만 점멸 (알파값 반복)
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
    val shapeColor = if (style.isBlinking) baseColor.copy(alpha = blinkAlpha) else baseColor

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black),
        contentAlignment = Alignment.Center
    ) {
        // 방향 도형 표시
        Canvas(modifier = Modifier.fillMaxSize()) {
            val cx = size.width / 2
            val cy = size.height / 2
            val r = size.width * 0.28f
            val shapeSize = size.width * 0.13f

            if (direction != "unknown") {
                val (x, y) = when (direction) {
                    "front" -> Pair(cx, cy - r)
                    "rear"  -> Pair(cx, cy + r)
                    "left"  -> Pair(cx - r, cy)
                    "right" -> Pair(cx + r, cy)
                    else    -> Pair(cx, cy)
                }

                if (dangerLevel <= 2) {
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

        // 위험도 텍스트 — direction이 unknown일 때만 중앙, 아니면 살짝 위로 오프셋
        Column(
            modifier = Modifier.offset(y = if (direction == "unknown") 0.dp else (-4).dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = when (dangerLevel) {
                    1 -> "낮음"; 2 -> "중간"; 3 -> "높음"; 4 -> "매우 높음"; else -> ""
                },
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                color = Color.White
            )
        }

        // 더미 테스트 버튼 (하단) — 이제 JSON 파싱 경로를 거쳐서 상태 반영
        Column(
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf(1, 2, 3, 4).forEach { level ->
                    Button(
                        onClick = {
                            val mockJson = """
                                {"eventId":"evt_${System.currentTimeMillis()}",
                                 "timestamp":${System.currentTimeMillis()},
                                 "label":"test_sound",
                                 "danger":$level,
                                 "direction":"$direction"}
                            """.trimIndent()
                            applyAlert(mockJson)
                        },
                        modifier = Modifier.size(30.dp),
                        colors = ButtonDefaults.buttonColors(
                            backgroundColor = Color(
                                android.graphics.Color.parseColor(DangerStyleMap.styleFor(level).colorHex)
                            )
                        )
                    ) {
                        Text("$level", fontSize = 10.sp, color = Color.White)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf("front", "left", "right", "rear", "?").forEach { dir ->
                    Button(
                        onClick = {
                            val newDir = if (dir == "?") "unknown" else dir
                            val mockJson = """
                                {"eventId":"evt_${System.currentTimeMillis()}",
                                 "timestamp":${System.currentTimeMillis()},
                                 "label":"test_sound",
                                 "danger":$dangerLevel,
                                 "direction":"$newDir"}
                            """.trimIndent()
                            applyAlert(mockJson)
                        },
                        modifier = Modifier.size(30.dp),
                        colors = ButtonDefaults.buttonColors(backgroundColor = Color.DarkGray)
                    ) {
                        Text(
                            text = when (dir) {
                                "front" -> "↑"; "left" -> "←"; "right" -> "→"; "rear" -> "↓"; else -> "?"
                            },
                            fontSize = 10.sp,
                            color = Color.White
                        )
                    }
                }
            }
        }
    }
}