# RPi 팀 전달 문서

AI 파트에서 넘기는 것과, RPi 쪽에서 해야 할 일을 정리했습니다.

---

## 1. 넘기는 파일

`export/` 폴더에서 **아래 4개만** 복사하면 됩니다 (총 27MB).

| 파일 | 크기 | 무엇 |
|---|---|---|
| `grabbit.py` | 7KB | 추론 코드 |
| `run_rpi.py` | 4KB | 실시간 실행 |
| `grabbit_model.npz` | 11MB | 분류기 가중치 + 임계값 + 전처리 설정 |
| `yamnet.tflite` | 16MB | 특징 추출기 (구글 YAMNet) |

`export_model.py` 는 PC에서 모델을 내보낼 때 쓰는 도구라 안 보내도 됩니다.

**PyTorch·TensorFlow 불필요**합니다. numpy + tflite-runtime 만 있으면 됩니다.

### yamnet.tflite 는 저장소에 없습니다

16MB라 git에 넣지 않았습니다. 파일 전달(드라이브·USB)로 받거나,
아래 명령으로 직접 받으세요. 구글이 배포하는 원본 그대로라 어느 쪽이든 같습니다.

```bash
curl -L -o yam.tar.gz \
  'https://www.kaggle.com/api/v1/models/google/yamnet/tfLite/tflite/1/download'
tar xzf yam.tar.gz && mv 1.tflite yamnet.tflite
```

받은 파일을 `grabbit.py` 와 **같은 폴더**에 두면 됩니다.

**반드시 16MB 버전이어야 합니다.** MediaPipe판(4MB)은 클래스 점수 521개만 내놓고
우리가 쓰는 1024차원 임베딩이 없어서, 실행하면 바로 오류가 납니다.

---

## 2. 설치

```bash
pip install numpy tflite-runtime
sudo apt install alsa-utils
```

`tflite-runtime` 이 안 깔리면 `pip install tensorflow` 로도 되지만 훨씬 무겁습니다.

---

## 3. 실행

```bash
arecord -l                                          # 마이크 확인
python3 run_rpi.py --device plughw:1,0 --channels 4 --host 192.168.137.42
```

`--channels` 는 마이크 채널 수입니다. 테스트에 쓴 마이크 어레이가 4채널이라
그 값을 넣었습니다. 일반 USB 마이크면 `1` 입니다.

`--host` 는 **알림을 받을 폰의 IP** 입니다 (핫스팟 주소). 폰 앱을 아직 안 띄웠으면
`--no-send` 로 전송 없이 마이크·모델만 점검할 수 있습니다.

**`--verbose` 를 붙이면** 판정마다 클래스와 확신도가 출력되어,
소리를 내면서 반응을 눈으로 확인할 수 있습니다.

---

## 4. 알림 전송 — 이미 구현되어 있습니다

`on_alert()` 안이 채워져 있습니다. `docs/json-schema.md` 스키마 그대로 폰에 POST 합니다.

```
POST http://<폰IP>:8080/alert     Content-Type: application/json
{"class": "siren", "direction": -1, "danger": 3, "timestamp": 1752894000}
```

**이 함수는 "울려야 할 때"만 호출됩니다.** 임계값·연속 조건·쿨다운 판정은
이미 안에서 끝난 상태입니다. RPi 쪽에서 다시 필터링할 필요 없습니다.

- 같은 소리가 계속 나도 30초에 한 번만 호출됩니다
- 사이렌이 30초 울려도 알림은 1번입니다

전송은 **별도 스레드**에서 합니다. 5초 창을 1초마다 굴리는 구조라 전송이 블로킹되면
그 사이 오디오가 밀리기 때문입니다. 네트워크가 죽어도 감지는 멈추지 않고,
실패는 세기만 해서 종료할 때 성공/실패 횟수를 출력합니다.

### RPi 쪽에서 아직 채워야 할 것: `direction`

DoA(GCC-PHAT)가 아직 없어서 **`direction` 은 `-1`(unknown) 로 나갑니다.**
붙일 때 `run_rpi.py` 의 `estimate_direction()` 한 곳만 바꾸면 됩니다.

```python
def estimate_direction():
    """소리 방향(도, 0~359). 추정 실패면 -1."""
    return -1
```

`danger` 는 `run_rpi.py` 상단 `DANGER` 표에서 붙입니다 — 스키마 확정 목록과 같은 값입니다.

### 앱 파트에 확인 필요: `doorbell`

모델이 내는 클래스는 `glass_breaking, siren, door_wood_knock, doorbell` 인데
`docs/json-schema.md` 확정 목록(2026-07-19)에는 `doorbell` 이 없습니다.
폰의 `AlertSpec.kt` 매핑에도 없어서 **초인종은 POST는 되지만 워치로 안 넘어갑니다**
(미등록 클래스는 이력만 남기고 스킵). 반대로 확정 목록의 `crackling_fire` 와
`door_wood_creaks` 는 모델이 내지 않습니다.

일단 `danger 2` 로 보내고 있으니, 앱 파트에서 `alertMap` 에 `doorbell` 을 추가하거나
클래스 목록을 맞추는 결정이 필요합니다.

---

## 5. 알아둘 동작

### 판정 주기

기본 1초마다 최근 5초를 듣고 판정합니다 (`--hop` 으로 변경 가능).

**체감 지연 = hop + 처리시간.** 소리가 난 뒤 알림까지 약 1.3~1.6초 예상입니다.

### 연속 조건

같은 소리가 연속으로 나와야 알림이 울립니다.

| 클래스 | 임계값 | 연속 조건 |
|---|---|---|
| `glass_breaking` | 0.30 | 2회 |
| `siren` | 0.30 | 4회 |
| `door_wood_knock` | 0.54 | 2회 |
| `doorbell` | 0.30 | 2회 |

사이렌은 오래 울리므로 4회를 요구해도 놓치지 않지만,
유리·노크·초인종은 1~2초짜리라 조건을 높이면 아예 안 울립니다.
이 값들은 실환경 녹음 2시간을 분석해 정한 것입니다.

### 설정 변경

임계값이나 연속 조건을 바꾸고 싶으면 **RPi 코드가 아니라 AI 파트에 요청**하세요.
`grabbit_model.npz` 안에 들어 있고, PC에서 다시 내보내야 합니다.

코드에 직접 적으면 학습·평가·배포가 서로 다른 값을 쓰게 되고,
그 사실은 성능이 무너질 때까지 드러나지 않습니다.

---

## 6. 성능

**실환경 2시간 녹음 기준** (RPi 마이크로 직접 녹음한 것)

| 클래스 | recall | precision |
|---|---|---|
| `glass_breaking` | 0.96 | 0.91 |
| `siren` | 0.90 | 0.77 |
| `door_wood_knock` | 0.89 | 0.88 |
| `doorbell` | 0.74 | 0.91 |

오알림 **시간당 약 1.5회**.

**주의 두 가지:**

1. **recall은 데이터셋(깨끗한 녹음) 기준입니다.** 마이크에서 5m 떨어진 소리는
   이보다 낮을 수 있으며 아직 측정하지 않았습니다.
2. **"시간당 1.5회"는 2시간 관측 결과입니다.** 통계적으로 하루 몇 회인지
   확정하려면 더 긴 녹음이 필요합니다.

---

## 7. RPi 팀에 부탁하는 것

### (1) 추론 속도 측정 — 우선

```bash
python3 bench_latency.py      # record/ 폴더에 있음
```

PC에서 5초 오디오 처리에 31~42ms 나왔습니다. RPi4에서 10~20배 느려도
300~600ms라 여유가 있을 것으로 보이지만 **실측한 적이 없습니다.**
1.5초 목표를 지킬 수 있는지 확인이 필요합니다.

결과에 따라 `--hop` 값을 조정합니다.

### (2) CPU·메모리 사용률

24시간 상시 동작이라 발열·전력도 봐야 합니다.
`top` 이나 `htop` 으로 확인해 주세요.

### (3) 장시간 안정성

몇 시간 돌렸을 때 메모리가 계속 늘거나 arecord가 끊기는지 확인이 필요합니다.
`run_rpi.py` 는 종료 시 "몇 시간 동안 알림 몇 회"를 출력하니 참고하세요.

### (4) 마이크 위치

같은 소리라도 마이크 위치에 따라 성능이 크게 달라집니다.
실제 설치할 위치를 정하면 알려주세요 — 그 조건으로 다시 평가하겠습니다.

---

## 8. 문제가 생기면

| 증상 | 확인 |
|---|---|
| `arecord: command not found` | `sudo apt install alsa-utils` |
| 녹음이 끊김 | `arecord -l` 로 장치 이름 확인 후 `--device` 지정 |
| 아무 알림도 안 울림 | `--verbose` 로 확신도 확인. `alsamixer` 에서 마이크 음량 조정 |
| 헛알림이 너무 잦음 | 어떤 클래스인지 알려주세요. 임계값 조정은 AI 파트에서 합니다 |
| `1024차원 임베딩 출력이 없습니다` | MediaPipe판(4MB)을 받은 경우입니다. 1번 항목의 안내대로 16MB 버전을 다시 받으세요 |

**헛알림이나 놓친 소리가 있으면 그때의 오디오를 저장해서 보내주세요.**
그게 모델을 개선하는 가장 확실한 재료입니다.
