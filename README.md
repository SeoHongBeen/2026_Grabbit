# Grabbit 🐰

> 청각장애인을 위한 실시간 환경음 인식 · 방향 알림 시스템
> 2026 AI융합학부 IT경진대회 · 고학년부 \

주변의 위험 소리를 실시간으로 감지·분류하고, **발생 방향과 위험도**를 함께 판단해
Galaxy Watch의 **색상·진동**으로 즉각 전달하는 AIoT 보조 시스템입니다.

---

## 시스템 구조

[ReSpeaker 4-Mic Array]
↓
[Raspberry Pi 4 — 엣지 AI 추론]
├─ 소리 분류 (YAMNet 임베딩 + 자체 분류기, TFLite)
├─ 방향 추정 DoA (TDOA 2차원 + RMS 에너지 비율 4차원 → KNN)
└─ 위험도 판단 (danger 0~3) → JSON 생성
↓ HTTP POST (Wi-Fi)
[Android 중계 앱]
├─ 실시간 수신 · 알림 히스토리
└─ MessageClient(Bluetooth)로 워치 전달
↓
[Galaxy Watch — Wear OS]
├─ 위험도별 색상 화면 + 파동 애니메이션
├─ 진동 패턴 알림 (soft / normal / urgent)
└─ eventId 중복 제거 · 방어적 파싱


## 주요 성과

- 소리 분류: 4종(유리 깨짐·사이렌·노크·초인종) + others, 전체 정확도 **95.4%** (test 1,228개)
- 방향 추정: 6차원 피처 KNN으로 전·후·좌·우 4방향 분류, 실측 테스트 전 방향 정답
- End-to-End: RPi 감지 → 워치 알림까지 실시간 동작 (실기기 SM-R920 검증 완료)

## 폴더 구조

2026_Grabbit/
├── rpi/ # DoA 모델(v5), 데이터 수집, 실시간 테스트
├── ai/export/ # 분류 모델 + 통합 추론 파이프라인 (run_rpi.py)
├── app/ # Android 중계 앱
├── wear/ # Galaxy Watch 앱 (Wear OS)
├── tools/ # mock_rpi.py 등 테스트 도구
└── docs/ # JSON 스키마 등 문서


## 실행 방법

### RPi (감지·추론)
```bash
source ~/grabbit-env/bin/activate
python ai/export/run_rpi.py
```

### RPi 없이 전 구간 테스트
```bash
python tools/mock_rpi.py
```

### 앱 빌드
Android Studio에서 프로젝트 열기 → `app`(폰) / `wear`(워치) 모듈 각각 실행

## 기술 스택

- **Hardware**: Raspberry Pi 4B · ReSpeaker 4-Mic Array HAT · Galaxy Watch SM-R920
- **AI/신호처리**: Python, TFLite(YAMNet), scikit-learn(KNN), librosa, PyAudio
- **앱/통신**: Kotlin, Jetpack Compose for Wear OS, Wearable Data Layer(MessageClient), HTTP

## 팀

| 이름 | 역할 | 주요 브랜치 |
|------|------|------|
| 서홍빈 (팀장) | RPi 하드웨어 · DoA · 시스템 통합 | `feat/rpi-audio` |
| 강수아 | Galaxy Watch 앱 · 알림 UI/진동 | `feat/phone-relay` |
| 김주하 | 방향 추정 로직 · 위험도 판단 · 발표 | `feat/rpi-audio` |
| 김혜정 | 소리 분류 AI 모델 | `ai-sound` |
| 최서현 | Android 중계 앱 · 발표 | `feat/phone-relay` |

## 커밋 컨벤션

`feat:` 새 기능 · `fix:` 버그 수정 · `docs:` 문서 · `chore:` 설정/기타
