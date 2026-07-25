import numpy as np
from scipy.signal import correlate
import joblib
import time
import pyaudio

# 1. 실측 데이터로 재학습된 v2 KNN 모델 로드
MODEL_PATH = "doa_knn_model_v2.pkl"
try:
    model = joblib.load(MODEL_PATH)
    print("성공: DoA 머신러닝 모델(v2) 로드 완료")
except FileNotFoundError:
    print(f"에러: {MODEL_PATH} 파일이 같은 폴더에 없습니다.")
    exit()

# 라즈베리파이 오디오 설정
FS = 16000
CHANNELS = 4
CHUNK = 1024 * 4
FORMAT = pyaudio.paInt16

# 클리핑 방지 + 조용할 때 무시하기 위한 볼륨 임계값
VOLUME_THRESHOLD = 3000
COOLDOWN_SEC = 0.5


def get_real_microphone_input(stream):
    """
    라즈베리파이 4채널 마이크에서 실제 오디오 청크를 읽어 채널별로 분리한다.
    """
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


if __name__ == "__main__":
    print("==== 라즈베리파이 실시간 DoA 예측 테스트 시작 (v2 모델) ====")
    print(f"볼륨 임계값: {VOLUME_THRESHOLD} (박수 등 큰 소리에만 반응)")
    print("마이크 앞에서 40cm~1m 거리 두고 방향 바꿔가며 소리내보세요.")
    print("종료: Ctrl+C\n")

    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                     channels=CHANNELS,
                     rate=FS,
                     input=True,
                     input_device_index=1,
                     frames_per_buffer=CHUNK)

    last_trigger_time = 0

    try:
        while True:
            ch0, ch1, ch2, ch3, volume = get_real_microphone_input(stream)

            now = time.time()
            if volume > VOLUME_THRESHOLD and (now - last_trigger_time) > COOLDOWN_SEC:
                features = extract_features(ch0, ch1, ch2, ch3)
                input_vector = np.array([features])
                predicted_direction = model.predict(input_vector)[0]

                print(f"[감지! volume={volume:.0f}] 딜레이: X={features[0]:4d}, Y={features[1]:4d}  ->  추정된 방향: {predicted_direction}")
                last_trigger_time = now

    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
