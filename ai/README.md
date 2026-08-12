# Grabbit 소리 분류

집 안의 소리를 듣고 **유리 깨짐 · 사이렌 · 노크 · 초인종**을 감지합니다.

처음 보는 사람은 **[docs/GUIDE.md](docs/GUIDE.md)** 부터 읽으세요.
파일 설명, 수정 방법, 설계 이유가 정리되어 있습니다.

---

## 폴더 구조

| 폴더 | 무엇 |
|---|---|
| **`core/`** | 공용 모듈. 전처리·모델 구조·설정·라벨 정의 |
| **`data/`** | 데이터 준비 (오디오 → 특징) |
| **`training/`** | 학습 · 평가 · 임계값 결정 |
| **`export/`** | **RPi에 넘길 것** |
| **`record/`** | RPi에서 실환경 녹음하는 도구 |
| `tools/` | 개발 보조 도구 |
| `model/` | 학습된 가중치 |
| `dataset/` | 원본 오디오와 특징 파일 |
| `docs/` | 문서 |

### core/ — 여기가 기준점

| 파일 | 역할 |
|---|---|
| `features.py` | **전처리의 유일한 정답.** 클래스 정의, 오디오→특징, 음량 정규화, 알림 규칙 |
| `config.py` | 경로와 하이퍼파라미터 (경로는 이 파일 위치 기준으로 자동 계산) |
| `cnn.py` | 모델 구조 (`YamnetHead` 사용, `CNN`은 비교용) |
| `utils.py` | 클래스 이름 → 숫자 라벨 |

**새 코드를 쓸 때 전처리를 복사하지 말고 `features.py` 를 import 하세요.**
두 곳에 두면 언젠가 어긋나고, 그 사실은 실제 기기 성능이 무너질 때까지
드러나지 않습니다. 실제로 겪었던 문제입니다.

---

## 실행 순서

데이터를 바꿨다면 **전부 순서대로** 다시 돌려야 합니다.

```bash
python data/relabel_doorbell.py       # 초인종 데이터 (구성 바꿀 때만)
python data/build_dataset.py          # 오디오 → MFCC + 그룹 정보     (약 3분)
python data/build_embeddings.py       # → YAMNet 임베딩               (약 12분)
python training/train.py              # 학습 + 임계값 선정             (약 8분)
python training/eval_stream.py        # 연속 오디오 오알림 측정        (약 8분)
python training/deploy_config.py      # 출시 설정 확정                 (수초)
python export/export_model.py         # RPi 배포 파일 생성            (수초)
```

- 하이퍼파라미터만 바꿨다면 `train.py` 부터
- 임계값·후처리만 바꿨다면 `deploy_config.py` 만

어느 폴더에서 실행해도 됩니다. 경로는 자동으로 잡힙니다.

**파일을 옮기거나 import를 바꿨다면** 아래를 먼저 돌려보세요.

```bash
python tools/check_imports.py
```

구문 검사로는 "모듈을 못 찾는" 문제가 안 잡힙니다.
이 도구는 각 스크립트의 import 구간만 실제로 실행해 확인합니다.

---

## RPi에 넘길 것

`export/` 안의 4개 파일 (총 27MB):

```
grabbit.py  run_rpi.py  grabbit_model.npz  yamnet.tflite
```

자세한 내용은 **[export/HANDOFF.md](export/HANDOFF.md)** 를 RPi 팀에 전달하세요.

---

## 현재 성능

실환경 2시간 녹음 기준 (RPi 마이크)

| 클래스 | recall | precision |
|---|---|---|
| glass_breaking | 0.96 | 0.91 |
| siren | 0.90 | 0.77 |
| door_wood_knock | 0.89 | 0.88 |
| doorbell | 0.74 | 0.91 |

오알림 시간당 약 1.5회.

**recall은 데이터셋(깨끗한 녹음) 기준입니다.** 마이크에서 멀리 떨어진 소리는
이보다 낮을 수 있으며 아직 측정하지 않았습니다.
