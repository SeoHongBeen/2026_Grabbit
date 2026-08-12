import numpy as np
from scipy.signal import correlate
import joblib
import time
import pyaudio

# 1. v5 모델과 스케일러 로드
MODEL_PATH = "doa_knn_model_v5.pkl"
SCALER_PATH = "doa_scaler.pkl"
try:
    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    print("성공: DoA v5 모델 + 스케일러 로드 완료")
except FileNotFoundError as e:
    print(f"에러: 파일이 없습니다 - {e}")
    exit()

FS = 16000
CHANNELS = 4
CHUNK = 1024 * 4
FORMAT = pyaudio.paInt16

VOLUME_THRESHOLD = 3000
COOLDOWN_SEC = 0.5


def get_real_microphone_input(stream):
    data = stream.read(CHUNK, exception_on_overflow=False)
    audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)

    ch0 = audio[0::4]
    ch1 = audio[1::4]
    ch2 = audio[2::4]
    ch3 = audio[3::4]

    volume = np.max(np.abs(audio))
    return ch0, ch1, ch2, ch3, volume


def extract_features(ch0, ch1, ch2, ch3):
    corr_x = correlate(ch0, ch2, mode='full')
    delay_x = np.argmax(corr_x) - (len(ch0) - 1)

    corr_y = correlate(ch1, ch3, mode='full')
    delay_y = np.argmax(corr_y) - (len(ch1) - 1)

    rms0 = np.sqrt(np.mean(ch0.astype(np.float64)**2))
    rms1 = np.sqrt(np.mean(ch1.astype(np.float64)**2))
    rms2 = np.sqrt(np.mean(ch2.astype(np.float64)**2))
    rms3 = np.sqrt(np.mean(ch3.astype(np.float64)**2))

    return delay_x, delay_y, rms0, rms1, rms2, rms3


def get_doa_direction(delay_x, delay_y, rms0, rms1, rms2, rms3):
    """
    주하 v5 스펙 그대로: RMS 비율 변환 -> 스케일러 -> KNN 예측
    """
    rms_sum = rms0 + rms1 + rms2 + rms3 + 1e-5

    rms0_ratio = rms0 / rms_sum
    rms1_ratio = rms1 / rms_sum
    rms2_ratio = rms2 / rms_sum
    rms3_ratio = rms3 / rms_sum

    raw_features = np.array([[delay_x, delay_y,
                              rms0_ratio, rms1_ratio, rms2_ratio, rms3_ratio]])

    scaled_features = scaler.transform(raw_features)
    predicted_direction = model.predict(scaled_features)[0]

    return predicted_direction


if __name__ == "__main__":
    print("==== 라즈베리파이 실시간 DoA 예측 테스트 (v5: 6차원 피처 + 스케일러) ====")
    print(f"볼륨 임계값: {VOLUME_THRESHOLD}")
    print("마이크 앞에서 40cm~1m 거리 두고 방향 바꿔가며 소리내보세요.")
    print("종료: Ctrl+C\n")

    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                     channels=CHANNELS,
                     rate=FS,
                     input=True,
                     input_device_index=1,
                     frames_per_buffer=CHUNK)

    # 스트림 안정화: 초기 청크 버림
    for _ in range(5):
        stream.read(CHUNK, exception_on_overflow=False)

    last_trigger_time = 0

    try:
        while True:
            ch0, ch1, ch2, ch3, volume = get_real_microphone_input(stream)

            now = time.time()
            if volume > VOLUME_THRESHOLD and (now - last_trigger_time) > COOLDOWN_SEC:
                dx, dy, r0, r1, r2, r3 = extract_features(ch0, ch1, ch2, ch3)
                direction = get_doa_direction(dx, dy, r0, r1, r2, r3)

                print(f"[감지! vol={volume:.0f}] dX={dx:3d} dY={dy:3d} "
                      f"RMS=[{r0:.0f},{r1:.0f},{r2:.0f},{r3:.0f}]  ->  방향: {direction}")
                last_trigger_time = now

    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()