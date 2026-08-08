# Grabbit 소리 분류 — 파일 가이드

수정하거나 이어서 작업할 때 보는 문서입니다.
"무엇을 하고 싶은가"에서 시작해 어느 파일을 건드릴지 찾도록 정리했습니다.

---

## 1. 지금 뭘 하고 있나

집 안의 소리를 듣고 **4가지 위험음·알림음**을 감지해 사용자에게 알립니다.

| 클래스 | 무엇 |
|---|---|
| `glass_breaking` | 유리 깨지는 소리 |
| `siren` | 사이렌 (구급차·소방차·경찰) |
| `door_wood_knock` | 문 두드리는 소리 |
| `doorbell` | 초인종 |
| `others` | 그 외 전부 (알림 안 함) |

모델은 **YAMNet**(구글이 AudioSet 200만 클립으로 학습한 오디오 모델)에서
1024차원 특징을 뽑고, 그 위에 작은 분류기만 학습하는 구조입니다.
직접 CNN을 처음부터 학습하는 것보다 훨씬 잘 됩니다.

---

## 2. 파일 지도

### `core/` — 기준점

| 파일 | 역할 |
|---|---|
| **`core/features.py`** | **전처리의 유일한 정답.** 클래스 정의, 오디오→특징, 음량 정규화, 알림 규칙 |
| `core/config.py` | 경로, 클래스 개수, 배치 크기, 학습률 (경로는 자동 계산) |
| `core/cnn.py` | 모델 구조 (`YamnetHead`가 실제로 쓰는 것, `CNN`은 비교용) |
| `core/utils.py` | 클래스 이름 → 숫자 라벨 |

### `data/` — 데이터 준비

| 파일 | 역할 |
|---|---|
| `data/build_dataset.py` | 3개 데이터셋을 합쳐 5초 단위로 통일 |
| `data/build_embeddings.py` | 위 결과를 YAMNet에 통과시켜 임베딩 생성 |
| `data/relabel_doorbell.py` | FSD50K에서 초인종 클립을 받아와 manifest에 반영 |

### `training/` — 학습·평가

| 파일 | 역할 |
|---|---|
| `training/train.py` | 학습 + 평가. 하이퍼파라미터가 파일 위쪽에 모여 있음 |
| `training/test.py` | 홀드아웃에서 몇 개 뽑아 눈으로 확인 |
| `training/eval_stream.py` | **연속 오디오에서 시간당 오알림 측정** (실제 서비스 지표) |
| `training/deploy_config.py` | 출시용 임계값 결정 |

### 그 외

| 폴더 | 역할 |
|---|---|
| `export/` | RPi 배포 패키지 (`HANDOFF.md` 를 RPi 팀에 전달) |
| `record/` | RPi에서 실환경 녹음하는 스크립트 |
| `tools/` | 개발 보조 (`check_imports.py`) |
| `model/` | 학습된 가중치 |
| `dataset/` | 원본 오디오와 특징 파일 |

---

## 3. 실행 순서

데이터를 바꿨다면 **반드시 이 순서 전부**를 다시 돌려야 합니다.
중간부터 돌리면 앞 단계의 옛 결과가 남아 조용히 틀린 값이 나옵니다.

```
1. data/relabel_doorbell.py    초인종 데이터 (구성 바꿀 때만)
2. data/build_dataset.py       오디오 → MFCC + 그룹 정보     (약 3분)
3. data/build_embeddings.py    → YAMNet 임베딩               (약 12분)
4. training/train.py           학습 + 임계값 선정             (약 8분)
5. training/eval_stream.py     연속 오디오 오알림 측정        (약 8분)
6. training/deploy_config.py   출시 설정 확정                 (수초)
7. export/export_model.py      RPi 배포 파일 생성             (수초)
```

어느 폴더에서 실행해도 됩니다 (`python data/build_dataset.py` 처럼).

**하이퍼파라미터만 바꿨다면** 4번부터.
**임계값·후처리 규칙만 바꿨다면** 6번만 (5번이 만든 캐시를 재사용).

---

## 4. 하고 싶은 일별 안내

### 클래스를 추가·삭제하고 싶다

건드릴 곳이 여러 개라 순서대로:

1. `core/features.py` → `CLASS_NAMES`, `MINORITY`, `OTHERS`
2. `core/utils.py` → `CLASS_MAP` (인덱스가 `CLASS_NAMES` 순서와 같아야 함)
3. `core/config.py` → `NUM_CLASSES`
4. `data/build_dataset.py` → `ESC50_MAP` 또는 `DROP_CATEGORIES`
5. `training/deploy_config.py` → `BUDGET_PER_DAY`, `CONSECUTIVE`
6. **기존 모델·캐시 삭제** — 클래스 개수가 바뀌면 형태가 안 맞습니다
   ```
   rm dataset/mfcc/stream_probs_*.npz dataset/mfcc/thresholds_*.npy
   rm model/best_model_yamnet*.pth
   ```
7. 3절의 실행 순서 전부

### 특정 클래스를 더 잘 잡고 싶다

`training/train.py` 의 `CLASS_WEIGHT_OVERRIDE` 를 올립니다.

```python
CLASS_WEIGHT_OVERRIDE = {3: 5.0}   # 3번(doorbell)을 더 중요하게
```

기본 가중치는 `SOUND_WEIGHT = 3.0` 입니다. 올리면 그 클래스를 적극적으로
예측하게 되어 recall이 오르고 대신 오탐이 늘어납니다.

### 오알림을 줄이고 싶다

`training/deploy_config.py` 의 `BUDGET_PER_DAY` 를 낮춥니다.

```python
BUDGET_PER_DAY = {
    0: 1.0,   # glass_breaking — 하루 1회까지 허용
    ...
}
```

숫자를 낮추면 임계값이 자동으로 올라가고, 대신 recall이 떨어집니다.
**이건 성능 문제가 아니라 제품 판단입니다** — 놓치는 것과 헛울리는 것 중
무엇이 더 나쁜지에 따라 정하세요.

### 데이터를 더 넣고 싶다

`dataset/FSD50K/manifest.csv` 에 `파일명,클래스` 행을 추가하고
오디오를 `dataset/FSD50K/audio/` 에 두면 됩니다.
`data/relabel_doorbell.py` 가 그 작업을 자동화한 예입니다.

---

## 5. 반드시 알아야 할 설계 결정

이 프로젝트에서 시행착오로 알아낸 것들입니다.
**모르고 바꾸면 성능이 조용히 무너지는** 부분이라 이유까지 적었습니다.

### 그룹 단위 분리 (가장 중요)

`training/train.py` 는 train/test를 무작위가 아니라 **그룹 단위**로 나눕니다.

- ESC-50: 클립 2000개가 원본 녹음 1524개에서 나옴 (한 녹음에서 최대 8조각)
- FSD50K: 클립이 업로더 1386명에게서 나옴 (한 명이 48개 올린 경우도)
- UrbanSound8K: 사이렌 929개가 원본 74개에서 나옴 (한 녹음에서 100조각!)

무작위로 나누면 **같은 녹음에서 잘라낸 조각이 train과 test 양쪽에** 들어갑니다.
모델이 사실상 본 적 있는 소리를 맞히는 셈이라 점수가 부풀려집니다.

`groups.npy` 가 이 정보를 담고, `StratifiedGroupKFold` 가 그룹을 쪼개지 않습니다.
**이걸 일반 `train_test_split` 으로 되돌리면 점수가 올라가지만 전부 거짓입니다.**

### 음량 정규화

`core/features.py` 의 `GAIN_NORMALIZE`. 학습 데이터(Freesound 녹음)는 RMS 0.065인데
실제 RPi 마이크 녹음은 0.002로 **29배 작습니다.**

이걸 맞추지 않았을 때 실환경 오알림이 **시간당 77.5회**였고,
맞추자 **6.5회**로 줄었습니다. 12배 차이입니다.

학습과 추론 양쪽에 똑같이 적용되어야 하므로 `core/features.py` 한 곳에만 둡니다.
**여기 값을 바꾸면 반드시 재학습해야 합니다.**

### 전처리는 features.py에만

예전에 `training/test.py` 가 자체 MFCC 코드를 갖고 있었는데, 리샘플링과 구간 선택이
빠져 있어서 **학습과 다른 입력을 모델에 넣고 있었습니다.**
그 사실이 한참 뒤에야 드러났습니다.

새 추론 코드(RPi 등)를 쓸 때도 반드시 `core/features.py` 를 import 하세요.
복사해서 쓰면 언젠가 어긋납니다.

### 클립 단위 vs 시간당

`training/train.py` 가 내는 "오탐율 3.8%"는 **클립 하나당** 비율입니다.
RPi가 5초마다 판정하면 시간당 720번이라 오알림이 시간당 27회가 됩니다.

사용자가 체감하는 건 시간당 횟수이므로, **출시 판단은 `training/eval_stream.py` 와
`training/deploy_config.py` 의 수치로** 해야 합니다.

### 알림은 사건 단위로

사이렌이 30초 울리면 윈도우로는 수십 번이지만 사용자에겐 알림 1번입니다.
`training/eval_stream.py` 의 `COOLDOWN_SEC` 이 이걸 처리합니다.

### 연속 조건은 클래스마다 다르게

`training/deploy_config.py` 의 `CONSECUTIVE`:

- 사이렌은 오래 울리므로 4회 연속을 요구해도 놓치지 않음
- **유리·노크·초인종은 1~2초짜리라 연속 조건을 높이면 아예 안 울립니다**

전 클래스에 같은 값을 주는 건 흔한 실수입니다.

---

## 6. 자주 하는 실수

| 증상 | 원인 |
|---|---|
| 성능이 이상하게 좋음 | 그룹 분리가 깨졌거나 test 데이터가 학습에 섞임 |
| 학습은 잘 되는데 실환경에서 안 됨 | 음량 정규화 불일치, 또는 전처리가 학습과 다름 |
| 클래스 바꾼 뒤 shape 에러 | 옛 모델·캐시 삭제 안 함 (4절 6번) |
| `training/test.py` 가 엉뚱한 파일을 읽음 | `data/build_dataset.py` 를 다시 안 돌려 `samples.csv` 가 옛것 |
| 한글이 깨짐 | 스크립트 시작 부분의 `chcp 65001` 이 빠짐 |
| `ModuleNotFoundError` | 파일을 옮긴 뒤 경로 설정이 빠짐 → `python tools/check_imports.py` 로 확인 |

파일을 옮기거나 import를 바꿨다면 항상 아래를 먼저 돌리세요.
구문 검사(`py_compile`)로는 "모듈을 못 찾는" 문제가 안 잡힙니다.

```bash
python tools/check_imports.py
```

---

## 7. 현재 성능

**데이터셋 홀드아웃** (학습에 안 쓴 1228개, 그룹 분리)

| 클래스 | recall | precision | f1 |
|---|---|---|---|
| glass_breaking | 0.96 | 0.91 | 0.94 |
| siren | 0.90 | 0.77 | 0.83 |
| door_wood_knock | 0.91 | 0.85 | 0.88 |
| doorbell | 0.74 | 0.91 | 0.82 |

정확도 0.95 / 소리 macro recall 0.878 / 오탐율 0.035

**실환경** (RPi 마이크 2시간 녹음, `training/deploy_config.py` 설정)

| 클래스 | 임계값 | 연속 | recall | 관측 오알림 |
|---|---|---|---|---|
| glass_breaking | 0.30 | 2회 | 0.961 | 0회 |
| siren | 0.30 | 4회 | 0.901 | 0회 |
| door_wood_knock | 0.54 | 2회 | 0.893 | 0회 |
| doorbell | 0.30 | 2회 | 0.741 | 0회 |

후처리 없이는 시간당 10회 → **2회 연속 조건으로 시간당 1.5회**,
3회 연속이면 시간당 1.0회.

**"오알림 0회"를 "하루 0회"로 읽으면 안 됩니다.** 2시간 관측으로는 통계적으로
하루 36회 미만까지만 보장됩니다 (Poisson 95%). 하루 1~2회를 실제로 검증하려면
36시간 연속 녹음이 필요합니다.

### 여기까지 온 과정

| 단계 | 정확도 | 소리 recall | 오탐율 |
|---|---|---|---|
| 직접 만든 CNN (ESC-50만, 2000개) | 0.85 | 0.694 | 0.110 |
| YAMNet 전이학습 | 0.86 | 0.871 | 0.151 |
| others 보강 + 사이렌 중복 제거 | 0.90 | 0.864 | 0.091 |
| epoch 선택 수정 + 앙상블 | 0.92 | 0.849 | 0.056 |
| 음량 정규화 | 0.92 | 0.879 | 0.059 |
| crackling_fire 제외 + doorbell 추가 | **0.95** | **0.878** | **0.035** |

실환경 오알림은 음량 정규화에서 시간당 77.5 → 6.5회,
crackling_fire 제외에서 6.5 → 1.5회로 줄었습니다.

### 시도했다가 되돌린 것

- **doorbell 파형 증강 (4배)** — recall은 0.741 그대로인데 precision이
  0.909 → 0.690으로 무너지고, 증강하지 않은 유리·노크 precision까지
  떨어졌습니다. 원인과 재시도 설정은 `data/build_embeddings.py` 의
  `AUG_PER_CLASS` 주석 참고.
- **dropout 0.5/0.7, weight decay** — 과적합이 보여 강화했으나 오히려 나빠졌습니다.
  실제 문제는 정규화가 아니라 학습을 멈추는 시점이었습니다.
- **MFCC 계수 정규화 (ESC-50 단독 시절)** — 그땐 성능이 떨어졌는데
  데이터가 3배가 된 뒤 재실험하니 개선됐습니다. 데이터가 바뀌면
  이전 실험 결론이 뒤집힐 수 있습니다.

---

## 8. 아직 안 된 것

1. **위험음 실환경 녹음** — 지금 recall은 전부 데이터셋 기준입니다.
   5m 떨어진 사이렌을 실제로 잡는지는 아직 모릅니다.
   `record/record_events.py` 로 거리별 녹음이 필요합니다.

2. **장시간 ambient 녹음** — 2시간으로는 "하루 1~2회"를 검증할 수 없습니다.
   0회를 관측해도 통계적으로는 하루 36회 미만까지만 보장됩니다.
   36시간 정도가 필요합니다.

3. **RPi 추론 속도 실측** — 배포 패키지(`export/`)는 완성했고 PC에서 42ms가
   나왔지만, RPi4에서는 재본 적이 없습니다. `record/bench_latency.py` 로
   확인해야 1.5초 목표를 지킬 수 있는지 알 수 있습니다.

4. **화재 감지** — `crackling_fire` 는 뺐습니다. 이유는 `core/features.py` 주석 참고.
   다시 넣는다면 "불 타는 소리"가 아니라 **연기감지기 경보음**을 잡는 방향이
   성능·실용성 모두 유리합니다.

5. **데이터 증강** (noise·gain·reverb) — 거리·마이크 강건성용.
   실환경 데이터가 있어야 효과 검증이 됩니다.
