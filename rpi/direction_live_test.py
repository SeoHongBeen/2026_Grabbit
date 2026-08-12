import pyaudio
import numpy as np
from scipy.signal import correlate

# 시스템 스펙
FS = 16000
CHANNELS = 4
CHUNK = 1024 * 4
FORMAT = pyaudio.paInt16

def estimate_direction(ch0, ch1, ch2, ch3, threshold=1):
    """
    주하 로직 그대로: Ch0 vs Ch2 -> left/right, Ch1 vs Ch3 -> front/rear
    """
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

    print("[방향 추정 실시간 테스트] 마이크 앞에서 방향 바꿔가며 소리 내보세요 (박수 등).")
    print("종료하려면 Ctrl+C\n")

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)

            # 4채널 분리 (인터리브 되어 있음: ch0,ch1,ch2,ch3,ch0,ch1,...)
            ch0 = audio[0::4]
            ch1 = audio[1::4]
            ch2 = audio[2::4]
            ch3 = audio[3::4]

            direction, dx, dy = estimate_direction(ch0, ch1, ch2, ch3)
            print(f"delay_x={dx:4d}  delay_y={dy:4d}  ->  방향 판정: {direction}")

    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


if __name__ == "__main__":
    main()
