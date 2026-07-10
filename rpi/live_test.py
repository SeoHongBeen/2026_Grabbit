import numpy as np
from scipy.signal import correlate
import joblib
import json
import time

# 1. 코랩에서 학습시켜 가져온 KNN 모델 로드
MODEL_PATH = "doa_knn_model.pkl"
try:
    model = joblib.load(MODEL_PATH)
    print("성공: DoA 머신러닝 모델 로드 완료")
except FileNotFoundError:
    print(f"에러: {MODEL_PATH} 파일이 같은 폴더에 없습니다.")
    exit()

# 라즈베리파이 오디오 설정 (마이크 사양에 맞게 조정)
FS = 16000
CHUNK = 1024

def get_real_microphone_input():
    """
    라즈베리파이에 연결된 4채널 마이크로부터 실제 오디오 스트림을 받는 함수입니다.
    (실제 오디오 라이브러리인 PyAudio 또는 SoundDevice 코드가 이 자리에 매핑됩니다)
    지금은 하드웨어 연동 전 테스트를 위해 임시 0번 패딩 데이터를 리턴합니다.
    """
    # 실제 구현 시 마이크에서 들어오는 4개 채널 스트림 데이터를 언팩해야 합니다.
    ch0 = np.zeros(CHUNK)
    ch1 = np.zeros(CHUNK)
    ch2 = np.zeros(CHUNK)
    ch3 = np.zeros(CHUNK)
    return ch0, ch1, ch2, ch3

def extract_features(ch0, ch1, ch2, ch3):
    """
    실시간 입력된 4채널 데이터에서 모델 입력용 크로스 코릴레이션 딜레이 피처를 추출합니다.
    """
    corr_x = correlate(ch0, ch2, mode='full')
    delay_x = np.argmax(corr_x) - (len(ch0) - 1)
    
    corr_y = correlate(ch1, ch3, mode='full')
    delay_y = np.argmax(corr_y) - (len(ch1) - 1)
    
    return [delay_x, delay_y]

if __name__ == "__main__":
    print("==== 라즈베리파이 실시간 DoA 예측 테스트 시작 ====")
    
    try:
        while True:
            # 1. 마이크에서 실제 4채널 소리 데이터 수신
            ch0, ch1, ch2, ch3 = get_real_microphone_input()
            
            # 2. 실시간 피처 추출
            features = extract_features(ch0, ch1, ch2, ch3)
            
            # 3. 모델 기반 방향 추정 (Inference)
            input_vector = np.array([features])
            predicted_direction = model.predict(input_vector)[0]
            
            # 4. 결과 출력 테스트
            print(f"추출된 딜레이 값: X축={features[0]}, Y축={features[1]} -> 추정된 방향: {predicted_direction}")
            
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\n실시간 테스트를 종료합니다.")