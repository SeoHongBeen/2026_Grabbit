import pyaudio
import numpy as np
from scipy.signal import correlate
import time

FS = 16000
CHANNELS = 4
CHUNK = 1024 * 4
FORMAT = pyaudio.paInt16

# 이 값보다 큰 소리(박수 등)가 났을 때만 방향 계산
# 너무 자주 찍히면 숫자를 올리고, 박수쳐도 반응 없으면 낮추기
VOLUME_THRESHOLD = 3000

# 같은 박수 소리가 여러 청크에 걸쳐 중복 출력되는 것 방지 (초 단위)
COOLDOWN_SEC = 0.5


def estimate_direction(ch0, ch1, ch2, ch3, threshold=1):
    corr_x = correlate(ch0, ch2, mode='full')
    delay_x = np.argmax(corr_x) - (len(ch0) - 1)

    corr_y = correlate(ch1, ch3, mode='full')
    delay_y = np.argmax(corr_y) - (len(ch1) - 1)

    if np.abs(delay_x) <= threshold and np.abs(delay_y) <= threshold:
        return "unknown", delay_x, delay_y

    if np.abs(delay_x) > np.abs(delay_y):
        direction = "left" if delay_x < 0 else "right"
    else:
        direction = "front" if delay_y < 0 else "rear"

    return direction, delay_x, delay_y


def main():
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                     channels=CHANNELS,
                     rate=FS,
                     input=True,
                     input_device_index=1,
                     frames_per_buffer=CHUNK)

    print("[방향 추정 실시간 테스트 - 임계값 적용]")
    print(f"볼륨 임계값: {VOLUME_THRESHOLD} (박수 등 큰 소리에만 반응)")
    print("종료하려면 Ctrl+C\n")

    last_trigger_time = 0

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)

            ch0 = audio[0::4]
            ch1 = audio[1::4]
            ch2 = audio[2::4]
            ch3 = audio[3::4]

            # 전체 볼륨 크기 (RMS 대신 최대 절댓값으로 간단히 체크)
            volume = np.max(np.abs(audio))

            now = time.time()
            if volume > VOLUME_THRESHOLD and (now - last_trigger_time) > COOLDOWN_SEC:
                direction, dx, dy = estimate_direction(ch0, ch1, ch2, ch3)
                print(f"[소리 감지! volume={volume:.0f}] delay_x={dx:4d}  delay_y={dy:4d}  ->  방향 판정: {direction}")
                last_trigger_time = now

    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


if __name__ == "__main__":
    main()

