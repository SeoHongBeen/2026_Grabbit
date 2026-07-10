import pyaudio
import numpy as np
import librosa

CHANNELS = 4
RATE = 16000
CHUNK = 1024 * 4  # 약 0.25초

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=1,
                frames_per_buffer=CHUNK)

print("MFCC 테스트 시작...")
for i in range(5):
    data = stream.read(CHUNK, exception_on_overflow=False)
    audio = np.frombuffer(data, dtype=np.int16)
    
    # 4채널 → 채널 0만 뽑기
    ch0 = audio[0::4].astype(np.float32) / 32768.0
    
    # MFCC 추출
    mfcc = librosa.feature.mfcc(y=ch0, sr=RATE, n_mfcc=40)
    print(f"청크 {i}: MFCC shape={mfcc.shape}, mean={mfcc.mean():.2f}")

stream.stop_stream()
stream.close()
p.terminate()
print("완료!")
