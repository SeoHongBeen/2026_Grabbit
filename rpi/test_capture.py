import pyaudio
import numpy as np

CHANNELS = 4
RATE = 16000
CHUNK = 1024

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=3,
                frames_per_buffer=CHUNK)

print("녹음 시작...")
for i in range(10):
    data = stream.read(CHUNK)
    audio = np.frombuffer(data, dtype=np.int16)
    print(f"청크 {i}: shape={audio.shape}, max={audio.max()}")

stream.stop_stream()
stream.close()
p.terminate()
print("완료!")
