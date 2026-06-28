package com.grabbit.watch

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Text

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            GrabbitWatchScreen()
        }
    }
}

@Composable
fun GrabbitWatchScreen() {
    // 더미 상태 (나중에 실제 데이터로 교체)
    var dangerLevel by remember { mutableStateOf(1) }
    var direction by remember { mutableStateOf("right") }

    val shapeColor = when (dangerLevel) {
        1 -> Color(0xFF4CAF50)  // 초록
        2 -> Color(0xFFFFEB3B)  // 노랑
        3 -> Color(0xFFFF9800)  // 주황
        4 -> Color(0xFFF44336)  // 빨강
        else -> Color.Gray
    }

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
            val r = size.width * 0.28f  // 도형이 놓일 반지름
            val shapeSize = size.width * 0.13f

            val (x, y) = when (direction) {
                "front" -> Pair(cx, cy - r)
                "rear"  -> Pair(cx, cy + r)
                "left"  -> Pair(cx - r, cy)
                "right" -> Pair(cx + r, cy)
                else    -> Pair(cx, cy)  // unknown → 가운데
            }

            if (dangerLevel <= 2) {
                // 원
                drawCircle(
                    color = shapeColor,
                    radius = shapeSize,
                    center = Offset(x, y)
                )
            } else {
                // 삼각형 ▲
                val path = Path().apply {
                    moveTo(x, y - shapeSize)
                    lineTo(x + shapeSize, y + shapeSize)
                    lineTo(x - shapeSize, y + shapeSize)
                    close()
                }
                drawPath(path = path, color = shapeColor, style = Fill)
            }
        }

        // 위험도 텍스트 (중앙)
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = when (dangerLevel) {
                    1 -> "낮음"
                    2 -> "중간"
                    3 -> "높음"
                    4 -> "매우 높음"
                    else -> ""
                },
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                color = Color.White
            )
        }

        // 더미 테스트 버튼 (하단)
        Column(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf(1, 2, 3, 4).forEach { level ->
                    Button(
                        onClick = { dangerLevel = level },
                        modifier = Modifier.size(30.dp),
                        colors = ButtonDefaults.buttonColors(
                            backgroundColor = when (level) {
                                1 -> Color(0xFF4CAF50)
                                2 -> Color(0xFFFFEB3B)
                                3 -> Color(0xFFFF9800)
                                4 -> Color(0xFFF44336)
                                else -> Color.Gray
                            }
                        )
                    ) {
                        Text("$level", fontSize = 10.sp, color = Color.White)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf("front", "left", "right", "rear", "?").forEach { dir ->
                    Button(
                        onClick = { direction = if (dir == "?") "unknown" else dir },
                        modifier = Modifier.size(30.dp),
                        colors = ButtonDefaults.buttonColors(backgroundColor = Color.DarkGray)
                    ) {
                        Text(
                            text = when (dir) {
                                "front" -> "↑"
                                "left"  -> "←"
                                "right" -> "→"
                                "rear"  -> "↓"
                                else    -> "?"
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