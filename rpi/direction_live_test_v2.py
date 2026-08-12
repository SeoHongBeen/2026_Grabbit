import pyaudio
import numpy as np
from scipy.signal import correlate
import time

FS = 16000
CHANNELS = 4
CHUNK = 1024 * 4
FORMAT = pyaudio.paInt16

VOLUME_THRESHOLD = 1500
COOLDOWN_SEC = 0.3

# 진단 모드: True면 채널별 볼륨만 출력 (마이크 매핑 확인용)
# False면 기존처럼 방향 판정 로직 실행
DIAGNOSTIC_MODE = True


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

    if DIAGNOSTIC_MODE:
        print("[채널-마이크 매핑 진단 모드]")
        print("마이크 하나씩 가까이 대고 톡톡 두드려보세요 (mic2 -> mic3 -> mic1 -> mic4 순서 추천)")
        print("어느 ch가 제일 크게 뜨는지 확인하세요. 종료: Ctrl+C\n")
    else:
        print("[방향 추정 실시간 테스트 - 임계값 적용]")
        print(f"볼륨 임계값: {VOLUME_THRESHOLD}")
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

            volume = np.max(np.abs(audio))
            now = time.time()

            if volume > VOLUME_THRESHOLD and (now - last_trigger_time) > COOLDOWN_SEC:
                last_trigger_time = now

                if DIAGNOSTIC_MODE:
                    v0 = np.max(np.abs(ch0))
                    v1 = np.max(np.abs(ch1))
                    v2 = np.max(np.abs(ch2))
                    v3 = np.max(np.abs(ch3))
                    volumes = [v0, v1, v2, v3]
                    loudest = volumes.index(max(volumes))
                    print(f"ch0={v0:6.0f}  ch1={v1:6.0f}  ch2={v2:6.0f}  ch3={v3:6.0f}   ->  가장 큰 채널: ch{loudest}")
                else:
                    direction, dx, dy = estimate_direction(ch0, ch1, ch2, ch3)
                    print(f"[소리 감지! volume={volume:.0f}] delay_x={dx:4d}  delay_y={dy:4d}  ->  방향 판정: {direction}")

    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


if __name__ == "__main__":
    main()