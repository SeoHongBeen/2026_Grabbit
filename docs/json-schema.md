# Grabbit JSON 스키마 (RPi → 폰)

RPi가 소리를 감지하면 아래 형식의 JSON을 폰으로 HTTP POST 한다.

## 형식

```json
{
  "class": "siren",
  "direction": 90,
  "danger": 3,
  "timestamp": 1752894000
}
```

## 필드 정의

| 필드 | 타입 | 설명 | 값 예시 |
|------|------|------|---------|
| class | string | 감지된 소리 종류 | siren, horn, doorbell, fire_alarm, baby_cry, dog_bark |
| direction | int | 소리 방향 (도 단위, 0~359) | 0=정면, 90=오른쪽, 180=뒤, 270=왼쪽 |
| danger | int | 위험도 (1~3) | 1=낮음, 2=중간, 3=긴급 |
| timestamp | int | 유닉스 타임스탬프 (초) | 1752894000 |

## 참고

- 전송 방식: HTTP POST, Content-Type: application/json
- 폰은 실내/실외 모드에 따라 알림 여부를 필터링한 뒤 워치로 전달
- direction 값이 없으면(추정 실패) -1로 보낸다
