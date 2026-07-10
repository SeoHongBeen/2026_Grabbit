import pyaudio
import numpy as np
from scipy.signal import correlate
import time
import csv
import os
import sys

FS = 16000
CHANNELS = 4
CHUNK = 1024 * 4
FORMAT = pyaudio.paInt16

VOLUME_THRESHOLD = 3000
COOLDOWN_SEC = 0.5

CSV_PATH = "direction_training_data.csv"


def compute_delays(ch0, ch1, ch2, ch3):
    corr_x = correlate(ch0, ch2, mode='full')
    delay_x = np.argmax(corr_x) - (len(ch0) - 1)

    corr_y = correlate(ch1, ch3, mode='full')
    delay_y = np.argmax(corr_y) - (len(ch1) - 1)

    return delay_x, delay_y


def ensure_csv_header():
    file_exists = os.path.isfile(CSV_PATH)
    if not file_exists:
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "delay_x", "delay_y", "label"])


def append_row(delay_x, delay_y, label):
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), delay_x, delay_y, label])


def main():
    if len(sys.argv) < 2:
        print("사용법: python3 collect_direction_data.py <label>")
        print("예시:   python3 collect_direction_data.py left")
        print("       (label은 left / right / front / rear 중 하나)")
        sys.exit(1)

    label = sys.argv[1]
    valid_labels = ["left", "right", "front", "rear"]
    if label not in valid_labels:
        print(f"경고: label '{label}' 은 표준 라벨({valid_labels})이 아닙니다. 그래도 계속 진행합니다.")

    ensure_csv_header()

    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                     channels=CHANNELS,
                     rate=FS,
                     input=True,
                     input_device_index=1,
                     frames_per_buffer=CHUNK)

    print(f"[데이터 수집 시작] 라벨: {label}")
    print(f"저장 파일: {CSV_PATH}")
    print("이 방향에서 박수를 20~30번 정도 쳐주세요. 종료: Ctrl+C\n")

    last_trigger_time = 0
    count = 0

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
                delay_x, delay_y = compute_delays(ch0, ch1, ch2, ch3)
                append_row(delay_x, delay_y, label)
                count += 1
                print(f"[{count}번째 기록] volume={volume:.0f}  delay_x={delay_x:4d}  delay_y={delay_y:4d}  label={label}")
                last_trigger_time = now

    except KeyboardInterrupt:
        print(f"\n종료합니다. 이번 세션에서 {count}개 기록됨.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


if __name__ == "__main__":
    main()