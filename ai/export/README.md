# RPi 배포 패키지

라즈베리파이에서 마이크를 듣고 위험음을 감지하고, 소리가 난 방향을 추정합니다.
**PyTorch·TensorFlow 없이** numpy + tflite-runtime 만으로 돌아갑니다.

## RPi에 복사할 파일

```
export/
  grabbit.py           추론 코드
  run_rpi.py           실시간 실행
  grabbit_model.npz    학습된 분류기 + 임계값 + 전처리 설정  (11 MB)
  yamnet.tflite        YAMNet 특징 추출기                    (16 MB)

rpi/                   ← 방향 추정(DoA). 4채널 어레이를 쓸 때만 필요
  doa_knn_model_v5.pkl (18 KB)
  doa_scaler.pkl       (1 KB)
```

`export_model.py` 는 PC에서만 쓰는 도구라 복사하지 않아도 됩니다.

DoA 파일 두 개는 `run_rpi.py` 와 같은 폴더에 둬도 되고, 저장소 배치
(`<repo>/rpi/`)를 그대로 유지해도 됩니다. 둘 다 아니면 `--doa-model`,
`--doa-scaler` 로 경로를 지정하세요.

## 설치

```bash
pip install numpy tflite-runtime
sudo apt install alsa-utils                     # arecord

# 방향 추정을 쓸 때만
pip install joblib scipy "scikit-learn==1.6.1"
```

`tflite-runtime` 설치가 안 되면 `pip install tensorflow` 도 됩니다(무겁습니다).

**scikit-learn 버전을 맞추세요.** pkl 은 1.6.1 에서 만들어졌고, 다른 버전에서
풀면 sklearn 이 `InconsistentVersionWarning` 을 내면서도 그냥 로드합니다 —
경고만 뜨고 방향이 조용히 틀릴 수 있습니다.

## 실행

```bash
# 마이크 확인
arecord -l

# 실행 (마이크 어레이면 --channels 4, --host 는 폰 IP)
python3 run_rpi.py --device plughw:0,0 --channels 4 --host 192.168.137.42

# 전송 없이 마이크·모델만 점검
python3 run_rpi.py --device plughw:0,0 --channels 4 --no-send --verbose
```

옵션:

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--device` | 기본 장치 | `arecord -l` 로 확인한 이름 |
| `--channels` | 1 | 마이크 어레이면 채널 수. 분류는 평균내어 모노로 씀 |
| `--hop` | 1.0 | 몇 초마다 판정할지. **바꾸기 전에 아래 설명을 읽으세요** |
| `--cooldown` | 30.0 | 같은 알림을 다시 울리기까지 최소 간격(초) |
| `--host` | 127.0.0.1 | 알림을 받을 폰의 IP |
| `--port` | 8080 | 폰 Ktor 서버 포트 |
| `--timeout` | 2.0 | 전송 타임아웃(초) |
| `--no-send` | 꺼짐 | 전송하지 않고 화면 출력만 |
| `--doa-model` | 자동 탐색 | `doa_knn_model_v5.pkl` 경로 |
| `--doa-scaler` | 자동 탐색 | `doa_scaler.pkl` 경로 |
| `--no-doa` | 꺼짐 | 방향 추정을 끄고 `-1` 로 보냄 |

## 알림 전송

`on_alert()` 에 이미 들어 있습니다. `docs/json-schema.md` 그대로 폰에 POST 합니다.

```
POST http://<폰IP>:8080/alert     Content-Type: application/json
{"class": "siren", "direction": 90, "danger": 3, "timestamp": 1752894000}
```

전송은 별도 스레드라 판정 루프를 막지 않고, 네트워크가 죽어도 감지는 계속됩니다
(실패는 세기만 하고 종료 시 성공/실패 횟수를 출력).

## 알림이 울리는 기준

관문 여섯 개를 **순서대로 전부** 통과해야 알림이 나갑니다.

1. 그 창에서 해당 클래스가 **1등(argmax)** 일 것
2. 1등 확률이 **클래스별 임계값** 이상일 것
3. 1·2를 **연속 N회** 통과할 것 (한 창이라도 끊기면 1로 리셋)
4. 같은 클래스의 마지막 알림에서 **쿨다운(30초)** 이 지났을 것
5. `run_rpi.py` 의 `DANGER` 표에 있는 클래스일 것
6. 폰 `AlertSpec.kt` 의 `alertMap` 에 있는 클래스일 것

**1번을 자주 놓칩니다.** 임계값은 "그 클래스의 확률"이 아니라 "1등 확률"에
걸립니다. siren 0.45 / others 0.50 이면 siren 이 0.30 을 넘었어도 1등이 아니라
세지 않습니다. `--verbose` 로 확인할 수 있습니다.

## 감지하는 소리

| 클래스 | 임계값 | 연속 | 요구 지속시간 | recall | precision |
|---|---|---|---|---|---|
| `glass_breaking` | 0.30 | 2회 | 2.0초 | 0.96 | 0.91 |
| `siren` | 0.30 | 2회 | 2.0초 | 0.90 | 0.77 |
| `door_wood_knock` | 0.55 | 1회 | 1.0초 | 0.89 | 0.88 |
| `doorbell` | 0.30 | 2회 | 2.0초 | 0.74 | 0.91 |

**연속 조건**은 결국 "그만큼 지속돼야 한다"는 뜻입니다. 유리·노크·초인종은
1~2초짜리라 조건을 높이면 아예 안 울립니다. 오알림은 실환경 2시간 녹음 기준
**하루 1회 이하**입니다.

**주의**: recall은 데이터셋(깨끗한 녹음) 기준입니다. 마이크에서 멀리 떨어진
소리는 이보다 낮게 나올 수 있으며, 아직 측정하지 않았습니다.
`record/record_events.py` 로 거리별 녹음을 하면 확인할 수 있습니다.

## `--hop` 을 함부로 바꾸지 마세요

임계값과 연속 조건은 **판정 간격 1초**를 전제로 정해진 값입니다
(`training/deploy_config.py` 의 `DEPLOY_HOP`). hop 을 바꾸면 같은 "연속 N회"가
요구하는 **지속시간이 통째로 바뀝니다.**

간격을 0.48초로 좁혀봤지만 RPi4가 따라오지 못해 오디오가 밀렸습니다.
대신 **연속 조건을 줄여** 지연을 절반으로 만들었고, 실환경 2시간 녹음으로
재보니 그래도 임계값·recall·오알림이 그대로였습니다.

| 연속 조건 | siren 지연 | knock 지연 | 임계값 | 전체 recall |
|---|---|---|---|---|
| 예전 (siren 4, knock 2) | 4.0초 | 2.0초 | 0.30 | 0.874 |
| **현행 (siren 2, knock 1)** | **2.0초** | **1.0초** | 0.30 | **0.874** |
| 전부 1회까지 | 2.0초 | 1.0초 | glass 0.70 | 0.845 |

사이렌은 오래 울리므로 4회를 요구할 이유가 없었습니다. 반대로 유리·초인종을
1회로 줄이면 오알림 예산을 지키느라 임계값이 0.30 → 0.70/0.61 로 올라가
`glass_breaking` recall 이 0.96 → 0.88 로 떨어져서 2회를 유지했습니다.

기본값과 다른 hop 으로 실행하면 시작할 때 경고가 나옵니다.

## 속도

hop 1초는 **한 창 처리가 1000ms 안에 끝나야** 밀리지 않습니다.
PC에서 5초 오디오 1회 처리에 31ms 였고, RPi4 실측은 아직 없습니다
(0.48초로 좁혔을 때 밀린 것으로 보아 480ms는 넘습니다).
`record/bench_latency.py` 로 재주세요.

넘으면 `run_rpi.py` 가 실행 중에 경고를 찍고, 종료할 때 평균 처리 시간과
초과 횟수를 출력합니다. 그때는 `--hop` 을 늘리는 대신 **AI 파트에 연락**해서
연속 조건과 임계값을 함께 다시 잡는 편이 낫습니다 (위 표의 세 번째 줄).

체감 지연 = 요구 지속시간 + 처리 시간입니다. 노크는 약 1.5초,
유리 깨짐과 사이렌은 약 2.5초입니다.

## 방향 추정 (DoA)

4채널 어레이 + `doa_knn_model_v5.pkl` 이 있을 때만 동작하고, 아니면 `-1`
(unknown)로 나갑니다. 폰은 `-1` 을 unknown 으로 처리합니다.

- 피처: `[delay_x, delay_y, rms0~3 비율]` 6차원 → StandardScaler → KNN
- 라벨 → 각도: `front 0 / right 90 / rear 180 / left 270`
- **0.256초(4096샘플) 구간**에서 계산합니다. 학습 데이터를 모을 때 쓴 길이와
  같아야 하기 때문입니다 — 더 긴 구간에서 상관 피크를 찾으면 학습에 없던
  delay 값이 나와 예측이 무너집니다
- 알림이 울린 시점의 **5초 버퍼 안에서 가장 시끄러운 0.256초**를 골라 씁니다.
  연속 조건 때문에 알림은 소리가 난 뒤 1~2창 지나서 울리므로, 마지막 청크만
  보면 정작 그 소리가 없을 수 있습니다
- 최대 음량이 3000(int16) 미만이면 추정하지 않고 `-1` 을 보냅니다

## 모델을 다시 내보낼 때

PC에서 재학습했다면:

```bash
python deploy_config.py      # 실환경 기준 임계값 결정
python export/export_model.py
```

`grabbit_model.npz` 만 RPi로 다시 복사하면 됩니다.

임계값·연속 조건은 `grabbit_model.npz` 안에 들어 있습니다.
**코드에 직접 적지 마세요** — 학습·평가·배포가 다른 값을 쓰게 됩니다.

## 문제 해결

| 증상 | 해결 |
|---|---|
| `arecord: command not found` | `sudo apt install alsa-utils` |
| 녹음이 끊김 / 장치 오류 | `arecord -l` 로 이름 확인 후 `--device plughw:카드,장치` |
| 아무 알림도 안 울림 | `--verbose` 로 확신도 확인. 마이크 음량은 `alsamixer` 에서 조정 |
| `1024차원 임베딩 출력이 없습니다` | MediaPipe판 yamnet.tflite(4MB)를 받았을 때 발생. 아래 안내대로 다시 받으세요 |
| `[DoA] 파일을 찾지 못함` | pkl 두 개를 `run_rpi.py` 옆에 두거나 `--doa-model`/`--doa-scaler` 지정 |
| `[DoA] 모델 로드 실패` | scikit-learn 버전 불일치가 대부분. `pip install "scikit-learn==1.6.1"` |
| 방향이 늘 `-1` | `--channels 4` 인지, 소리가 3000(int16) 이상 큰지 확인 |
| `[경고] 처리 ...ms > 간격 ...ms` | RPi가 못 따라가는 중. `bench_latency.py` 결과와 함께 AI 파트에 알려주세요 |

### yamnet.tflite 다시 받기

```bash
curl -L -o yam.tar.gz \
  'https://www.kaggle.com/api/v1/models/google/yamnet/tfLite/tflite/1/download'
tar xzf yam.tar.gz && mv 1.tflite yamnet.tflite
```

16MB 버전이어야 합니다. MediaPipe의 4MB 버전은 클래스 점수만 내놓고
우리가 필요한 임베딩이 없습니다.
