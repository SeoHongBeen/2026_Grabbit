import numpy as np
from scipy.signal import correlate
import joblib
import time
import pyaudio

# v3 모델 사용 (4클래스: left/right/front/rear 그대로 살아있는 버전)
MODEL_PATH = "doa_knn_model_v3.pkl"
try:
    model = joblib.load(MODEL_PATH)
    print("성공: DoA 머신러닝 모델(v3) 로드 완료")
except FileNotFoundError:
    print(f"에러: {MODEL_PATH} 파일이 같은 폴더에 없습니다.")
    exit()

FS = 16000
CHANNELS = 4
CHUNK = 1024 * 4
FORMAT = pyaudio.paInt16

VOLUME_THRESHOLD = 3000
COOLDOWN_SEC = 0.5

# 확신도 임계값: 이 값보다 낮으면 unknown 처리
CONFIDENCE_THRESHOLD = 0.6


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

    return [delay_x, delay_y]


def predict_with_confidence(features):
    """
    확신도가 낮으면 unknown으로 강제 처리하는 예측 함수
    """
    input_vector = np.array([features])
    proba = model.predict_proba(input_vector)[0]
    max_proba = np.max(proba)
    predicted_class = model.classes_[np.argmax(proba)]

    if max_proba < CONFIDENCE_THRESHOLD:
        return "unknown", max_proba, predicted_class
    else:
        return predicted_class, max_proba, predicted_class


if __name__ == "__main__":
    print("==== 라즈베리파이 실시간 DoA 예측 테스트 (v3 + 확신도 필터) ====")
    print(f"볼륨 임계값: {VOLUME_THRESHOLD}, 확신도 임계값: {CONFIDENCE_THRESHOLD}")
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
                features = extract_features(ch0, ch1, ch2, ch3)
                direction, confidence, raw_class = predict_with_confidence(features)

                print(f"[감지! volume={volume:.0f}] 딜레이: X={features[0]:4d}, Y={features[1]:4d}  ->  "
                      f"최종: {direction:8s} (확신도={confidence:.2f}, 원래예측={raw_class})")
                last_trigger_time = now

    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()