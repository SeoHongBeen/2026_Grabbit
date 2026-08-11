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
| class | string | 감지된 소리 종류 |crackling_fire, glass_breaking, siren, door_wood_knock, doorbell, door_wood_creaks, others |
| direction | int | 소리 방향 (도 단위, 0~359) | 0=정면, 90=오른쪽, 180=뒤, 270=왼쪽 |
| danger | int | 위험도 (1~3) | 1=낮음, 2=중간, 3=긴급 |
| timestamp | int | 유닉스 타임스탬프 (초) | 1752894000 |

## 참고

- 전송 방식: HTTP POST, Content-Type: application/json
- 폰은 클래스 매핑 후 워치로 전달
- others/미등록 클래스는 RPi에서 아예 전송하지 않음 (2026-08-11 확정 - 알림 자체 없음). 폰/워치의 others 처리 코드는 방어용으로만 유지
- direction 값이 없으면(추정 실패) -1로 보낸다

## class 확정 목록 (2026-08-08 업데이트, 실내 전용)

| class | danger | 색상 | 진동 | 워치 문구 |
|------|------|------|------|------|
| crackling_fire | 3 | #FF3B30 | urgent | 화재 소리! |
| glass_breaking | 3 | #FF3B30 | urgent | 유리 깨짐! |
| siren | 3 | #FF3B30 | urgent | 사이렌! |
| door_wood_knock | 2 | #FF9500 | normal | 노크 소리 |
| doorbell | 2 | #FF9500 | normal | 초인종 |
| door_wood_creaks | 1 | #007AFF | soft | 문 소리 |
| others | 0 | - | - | RPi에서 전송 안 함 (알림 없음) |

※ 미등록 class는 others와 동일 처리
※ doorbell 추가 (2026-08-08): RPi 모델이 door_wood_knock과 별개로 doorbell을 내는데 앱 매핑에 누락돼 있어 추가함. danger=2는 기존 확정값 유지.

## 폰 → 워치 (Data Layer, path: /grabbit/alert)

폰이 위 표대로 가공해서 label/color/vibration/direction/rpiTimestamp/phoneTimestamp를 전달한다.

## direction
- 타입: Int (0~359, 각도)
- 4분할 표시 (2026.08.02 확정 — v5 모델부터 전방 포함)
    - 앞: 315~359, 0~44
    - 오른쪽: 45~134
    - 뒤: 135~224
    - 왼쪽: 225~314

## 남은 이슈 (2026-08-11 갱신)
- crackling_fire / door_wood_creaks: 스키마엔 있지만 AI 모델이 실제로 내지 않는 클래스 (모델 클래스: glass_breaking, siren, door_wood_knock, doorbell + others). 발표/시연 자료는 실제 4클래스 기준으로 작성할 것.
- 화재음(crackling_fire)은 오알림 문제로 모델에서 제외됨 (실측: 오알림 99%가 화재 오탐). 향후 화재경보기 '경보음' 감지 방향으로 재검토.
- [확정 2026-08-11] others는 RPi가 전송하지 않음 → 폰 히스토리에도 남지 않음. 시연에서 "기타 소리 무시" 장면이 필요하면 mock_rpi로 재현.
