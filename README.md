# Grabbit 🐰

> 청각장애인을 위한 실시간 환경음 인식 및 위험 알림 시스템  
> AI융합학부 IT경진대회 2026

---

## 프로젝트 개요

스마트폰 또는 라즈베리파이의 마이크 배열로 주변 소리를 수집·분류하고,  
위험도와 방향 정보를 Galaxy Watch(Wear OS)의 진동 패턴과 색상으로 전달하는 AIoT 보조 시스템.

| 항목 | 내용 |
|------|------|
| 대회명 | 2026 AI융합학부 IT경진대회 |
| 팀명 | Grabbit |
| 구분 | 고학년부 |
| 제출일 | 2026. 05. 15. |

---

## 시스템 구조

```
[ReSpeaker 4-Mic Array]
        ↓
[Raspberry Pi - 소리 캡처 + AI 추론]
  ├─ 소리 분류 (PyTorch / TFLite)
  ├─ 방향 추정 (GCC-PHAT DOA)
  └─ 위험도 판단 + 실내/실외 모드
        ↓
[Galaxy Watch - Wear OS]
  ├─ 위험도별 색상 표시
  ├─ 진동 패턴 알림
  └─ 방향 파동 애니메이션
```

---

## 폴더 구조

```
2026_Grabbit/
├── rpi/                  # 라즈베리파이 (소리 캡처 + 추론)
│   ├── audio/            # 오디오 캡처 모듈
│   ├── doa/              # 방향 추정 (GCC-PHAT)
│   └── transmit/         # Watch로 데이터 전송
├── ai/                   # AI 모델 학습 및 전처리
│   ├── dataset/          # 데이터셋 관련 스크립트
│   ├── model/            # PyTorch 모델 정의
│   ├── train/            # 학습 스크립트
│   └── export/           # TFLite/ONNX 변환
├── watch/                # Galaxy Watch Wear OS 앱
│   ├── app/
│   └── ...               # Android Studio 프로젝트 구조
├── backend/              # 로그 서버 (Django or Node.js)
│   └── logs/
├── docs/                 # 문서, 발표 자료
│   ├── ppt/
│   └── images/
└── README.md
```

---

## 기술 스택

**Hardware**
- Raspberry Pi 4B
- ReSpeaker 4-Mic Array HAT
- Samsung Galaxy Watch (Wear OS)

**AI / 신호처리**
- Python 3.10+
- PyTorch, Librosa
- GCC-PHAT (방향 추정)
- TFLite (RPi 엣지 추론)

**앱 / 통신**
- Android Studio, Kotlin
- Jetpack Compose for Wear OS
- Wearable Data Layer API / BLE

**서버**
- Django or Node.js
- Firebase (로그)

---

## 브랜치 전략

| 브랜치 | 설명 |
|--------|------|
| `main` | 최종 배포 브랜치 (직접 push 금지) |
| `dev` | 통합 개발 브랜치 (PR 후 merge) |
| `feat/rpi-audio` | RPi 오디오 캡처 |
| `feat/ai-model` | AI 소리 분류 모델 |
| `feat/doa` | 방향 추정 알고리즘 |
| `feat/watch-ui` | Wear OS 워치 UI |
| `feat/backend` | 로그 서버 |
| `feat/context` | 실내/실외 판단 |

> PR은 반드시 `dev` 브랜치로, 리뷰 1명 이상 후 merge

---

## 팀원 역할

| 역할 | 담당 파트 | 브랜치 |
|------|-----------|--------|
| 팀장 (IoT) | RPi 하드웨어 총괄, 오디오 캡처 | `feat/rpi-audio` |
| IoT 팀원 A | Galaxy Watch UI, 통신 연동 | `feat/watch-ui` |
| AI 팀원 A | 소리 분류 모델, 데이터셋 | `feat/ai-model` |
| AI 팀원 B | 방향 추정, 위험도 로직 | `feat/doa` |
| IoT 팀원 B | 실내/실외 판단, 로그 서버 | `feat/context`, `feat/backend` |

---

## 개발 환경 세팅

### RPi 세팅
```bash
# ReSpeaker 드라이버 설치
git clone https://github.com/respeaker/seeed-voicecard
cd seeed-voicecard && sudo ./install.sh

# Python 패키지
pip install pyaudio numpy librosa
```

### AI 환경 (로컬/Colab)
```bash
pip install torch torchaudio librosa
```

### Watch 앱
Android Studio 최신버전 설치 후 `watch/` 폴더 열기

---

## 커밋 컨벤션

```
feat: 새 기능 추가
fix: 버그 수정
docs: 문서 수정
test: 테스트 추가
refactor: 리팩토링
chore: 기타 (패키지, 설정 등)
```

예시: `feat: GCC-PHAT 4채널 방향 추정 구현`

---

## 진행 현황

- [ ] 1단계: 개발 환경 세팅 (6/20 ~ 6/26)
- [ ] 2단계: AI 모델 v1 + RPi 추론 (6/27 ~ 7/7)
- [ ] 3단계: 전체 파이프라인 1차 통합 (7/8 ~ 7/18)
- [ ] 4단계: 정확도 개선 + UX 고도화 (7/19 ~ 7/28)
- [ ] 5단계: 실환경 테스트 (7/29 ~ 8/4)
- [ ] 6단계: 시연 준비 (8/5 ~ 8/9)
- [ ] 최종 제출 (8/10 ~ 8/12)
