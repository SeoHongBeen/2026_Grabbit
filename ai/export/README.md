# RPi 배포 패키지

라즈베리파이에서 마이크를 듣고 위험음을 감지합니다.
**PyTorch·TensorFlow 없이** numpy + tflite-runtime 만으로 돌아갑니다.

## RPi에 복사할 파일

```
export/
  grabbit.py           추론 코드
  run_rpi.py           실시간 실행
  grabbit_model.npz    학습된 분류기 + 임계값 + 전처리 설정  (11 MB)
  yamnet.tflite        YAMNet 특징 추출기                    (16 MB)
```

`export_model.py` 는 PC에서만 쓰는 도구라 복사하지 않아도 됩니다.

## 설치

```bash
pip install numpy tflite-runtime
sudo apt install alsa-utils          # arecord
```

`tflite-runtime` 설치가 안 되면 `pip install tensorflow` 도 됩니다(무겁습니다).

## 실행

```bash
# 마이크 확인
arecord -l

# 실행 (마이크 어레이면 --channels 4, --host 는 폰 IP)
python3 run_rpi.py --device plughw:1,0 --channels 4 --host 192.168.137.42

# 전송 없이 마이크·모델만 점검
python3 run_rpi.py --device plughw:1,0 --channels 4 --no-send --verbose
```

옵션:

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--device` | 기본 장치 | `arecord -l` 로 확인한 이름 |
| `--channels` | 1 | 마이크 어레이면 채널 수 (평균내어 모노로 씀) |
| `--hop` | 1.0 | 몇 초마다 판정할지 |
| `--cooldown` | 30.0 | 같은 알림을 다시 울리기까지 최소 간격(초) |
| `--host` | 127.0.0.1 | 알림을 받을 폰의 IP |
| `--port` | 8080 | 폰 Ktor 서버 포트 |
| `--timeout` | 2.0 | 전송 타임아웃(초) |
| `--no-send` | 꺼짐 | 전송하지 않고 화면 출력만 |

## 알림 전송

`on_alert()` 에 이미 들어 있습니다. 앱 파트와 합의한 형식 그대로 폰에 POST 합니다.

```
POST http://<폰IP>:8080/alert     Content-Type: application/json
{"class": "siren", "direction": 90, "danger": 3, "timestamp": 1752894000}
```

전송은 별도 스레드라 판정 루프를 막지 않고, 네트워크가 죽어도 감지는 계속됩니다
(실패는 세기만 하고 종료 시 성공/실패 횟수를 출력).

`direction` 은 DoA 파트가 붙기 전까지 `-1`(unknown) 입니다.
붙일 때 `estimate_direction()` 한 곳만 바꾸면 됩니다.

## 감지하는 소리

| 클래스 | 임계값 | 연속 조건 |
|---|---|---|
| `glass_breaking` | 0.30 | 2회 |
| `siren` | 0.30 | 4회 |
| `door_wood_knock` | 0.54 | 2회 |
| `doorbell` | 0.30 | 2회 |

**연속 조건**: 같은 소리가 연속으로 그만큼 나와야 알림이 울립니다.
사이렌은 오래 울리므로 4회를 요구해도 놓치지 않지만,
유리·노크·초인종은 1~2초짜리라 조건을 높이면 아예 안 울립니다.

**쿨다운**: 사이렌이 30초 울려도 사용자에겐 알림 1번이어야 합니다.

이 값들은 `grabbit_model.npz` 안에 들어 있습니다. 바꾸려면 PC에서
`deploy_config.py` 로 다시 정한 뒤 `export_model.py` 를 실행하세요.
**코드에 직접 적지 마세요** — 학습·평가·배포가 다른 값을 쓰게 됩니다.

## 성능

**실환경 2시간 녹음 기준** (같은 RPi 마이크)

| 클래스 | recall | precision |
|---|---|---|
| glass_breaking | 0.96 | 0.91 |
| siren | 0.90 | 0.77 |
| door_wood_knock | 0.89 | 0.88 |
| doorbell | 0.74 | 0.91 |

오알림 시간당 약 1.5회 (연속 조건 2회 기준).

**주의**: recall은 데이터셋(깨끗한 녹음) 기준입니다. 마이크에서 멀리 떨어진
소리는 이보다 낮게 나올 수 있으며, 아직 측정하지 않았습니다.
`record/record_events.py` 로 거리별 녹음을 하면 확인할 수 있습니다.

## 속도

PC에서 5초 오디오 1회 처리에 31ms. RPi4에서는 10~20배 느려도
300~600ms 수준이라 실시간 처리에 여유가 있습니다.
실제 측정은 `record/bench_latency.py` 로 하세요.

체감 지연 = `--hop` 값 + 처리 시간. 기본 1초 간격이면 약 1.3~1.6초입니다.

## 모델을 다시 내보낼 때

PC에서 재학습했다면:

```bash
python deploy_config.py      # 실환경 기준 임계값 결정
python export/export_model.py
```

`grabbit_model.npz` 만 RPi로 다시 복사하면 됩니다.

## 문제 해결

| 증상 | 해결 |
|---|---|
| `arecord: command not found` | `sudo apt install alsa-utils` |
| 녹음이 끊김 / 장치 오류 | `arecord -l` 로 이름 확인 후 `--device plughw:카드,장치` |
| 아무 알림도 안 울림 | `--verbose` 로 확신도 확인. 마이크 음량은 `alsamixer` 에서 조정 |
| `1024차원 임베딩 출력이 없습니다` | MediaPipe판 yamnet.tflite(4MB)를 받았을 때 발생. 아래 안내대로 다시 받으세요 |

### yamnet.tflite 다시 받기

```bash
curl -L -o yam.tar.gz \
  'https://www.kaggle.com/api/v1/models/google/yamnet/tfLite/tflite/1/download'
tar xzf yam.tar.gz && mv 1.tflite yamnet.tflite
```

16MB 버전이어야 합니다. MediaPipe의 4MB 버전은 클래스 점수만 내놓고
우리가 필요한 임베딩이 없습니다.
