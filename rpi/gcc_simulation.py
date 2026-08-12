import numpy as np
from scipy.signal import correlate
import time

# 🎛️ 기본 설정 (우리 파이프라인 스펙)
FS = 16000      # 샘플링 레이트 (16kHz)
CHUNK = 1024    # 청크 크기

def generate_mock_audio(direction="left"):
    """
    하드웨어 없이 가상으로 2채널 오디오 데이터를 만들어주는 함수
    """
    # 1. 가상의 소리 신호 (싸인파 노이즈 소스) 생성
    t = np.linspace(0, CHUNK/FS, CHUNK, endpoint=False)
    signal = np.sin(2 * np.pi * 440 * t)  # 440Hz 삐- 소리
    
    # 2. 방향에 따라 마이크 도달 시간 차이(Delay) 주기
    # 16kHz 환경에서 2샘플 정도 차이가 난다고 가정
    delay_samples = 3 
    
    if direction == "left":
        # 왼쪽에 먼저 도달 -> 오른쪽 채널에 딜레이(0을 패딩) 줌
        mic_left = signal
        mic_right = np.concatenate([np.zeros(delay_samples), signal[:-delay_samples]])
    elif direction == "right":
        # 오른쪽에 먼저 도달 -> 왼쪽 채널에 딜레이 줌
        mic_left = np.concatenate([np.zeros(delay_samples), signal[:-delay_samples]])
        mic_right = signal
    else:
        # 정면 -> 두 마이크에 동시에 도달
        mic_left = signal
        mic_right = signal
        
    return mic_left, mic_right

# 🚀 가상 실험 루프 시작
print("🤖 [시뮬레이션 시작] 3초마다 가상의 소리 방향을 변경하며 알고리즘을 검증합니다.")
print("종료하려면 Ctrl+C를 누르세요.\n")

directions = ["left", "center", "right", "center"]
dir_index = 0

try:
    while True:
        current_dir = directions[dir_index]
        print(f"\n📢 [가상 환경 설정] 현재 소리가 발생하는 방향: **{current_dir.upper()}**")
        
        # 1. 라즈베리파이 마이크 대신 가상 소리 가져오기
        mic_left, mic_right = generate_mock_audio(current_dir)
        
        # -------------------------------------------------------------
        # 🌟 여기서부터는 나중에 RPi에 그대로 들어갈 실제 GCC-PHAT 로직이야!
        # -------------------------------------------------------------
        # 2. GCC-PHAT 연산 (두 신호의 상호연관성 계산)
        correlation = correlate(mic_left, mic_right, mode='full')
        center = len(mic_left) - 1
        peak_index = np.argmax(correlation)
        
        # 시간 차이(Delay) 계산
        delay = peak_index - center
        
        # 3. 계산된 delay 값으로 알고리즘이 방향을 맞추는지 판단
        if delay < 0:
            print(f"   🎯 알고리즘 판단 결과 ➡️ 👈 [왼쪽] 소리 감지! (Delay 샘플 수: {delay})")
        elif delay > 0:
            print(f"   🎯 알고리즘 판단 결과 ➡️ 👉 [오른쪽] 소리 감지! (Delay 샘플 수: {delay})")
        else:
            print(f"   🎯 알고리즘 판단 결과 ➡️ ⚪ [정면/중앙] 소리 감지! (Delay 샘플 수: {delay})")
        # -------------------------------------------------------------
        
        # 방향 변경을 위해 index 순환
        dir_index = (dir_index + 1) % len(directions)
        time.sleep(3)  # 3초 대기

except KeyboardInterrupt:
    print("\n🛑 시뮬레이션을 종료합니다.")