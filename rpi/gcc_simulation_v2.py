import numpy as np
from scipy.signal import correlate
import time
import json

# 시스템 스펙 설정
FS = 16000
CHUNK = 1024

# 6단계: ESC-50 기반 커스텀 클래스 및 위험도 매핑 테이블
DANGER_TABLE = {
    "crackling_fire":   {"danger": "매우 높음", "color": "red",    "vibration": "urgent"},
    "glass_breaking":   {"danger": "매우 높음", "color": "red",    "vibration": "urgent"},
    "crying_baby":      {"danger": "높음",      "color": "orange", "vibration": "long_1"},
    "door_wood_knock":  {"danger": "중간",      "color": "yellow", "vibration": "short_2"},
    "door_wood_creaks": {"danger": "중간",      "color": "yellow", "vibration": "short_2"},
    "siren":            {"danger": "매우 높음", "color": "red",    "vibration": "urgent"},
    "others":           {"danger": "낮음",      "color": "green",  "vibration": "none"}
}

def generate_mock_4channel_audio(direction="left"):
    """
    사각형 4-Mic 배열에 도달하는 가상 소리 신호 생성
    Ch0-Ch2 (좌/우 쌍), Ch1-Ch3 (전/후 쌍)
    """
    t = np.linspace(0, CHUNK/FS, CHUNK, endpoint=False)
    signal = np.sin(2 * np.pi * 440 * t)  # 440Hz 가상 오디오 소스
    
    # 딜레이 샘플 수
    d = 3 
    
    # 기본 채널 초기화
    ch0, ch1, ch2, ch3 = signal.copy(), signal.copy(), signal.copy(), signal.copy()
    
    if direction == "left":
        ch2 = np.concatenate([np.zeros(d), signal[:-d]])
    elif direction == "right":
        ch0 = np.concatenate([np.zeros(d), signal[:-d]])
    elif direction == "front":
        ch3 = np.concatenate([np.zeros(d), signal[:-d]])
    elif direction == "rear":
        ch1 = np.concatenate([np.zeros(d), signal[:-d]])
        
    return ch0, ch1, ch2, ch3

def estimate_direction(ch0, ch1, ch2, ch3):
    """
    4단계 디벨롭: 지정된 표준 라벨(left, right, front, rear, unknown)로 반환
    """
    # 1. X축 (Ch0 vs Ch2) 상호연관성 연산 -> left / right 판별
    corr_x = correlate(ch0, ch2, mode='full')
    delay_x = np.argmax(corr_x) - (len(ch0) - 1)
    
    # 2. Y축 (Ch1 vs Ch3) 상호연관성 연산 -> front / rear 판별
    corr_y = correlate(ch1, ch3, mode='full')
    delay_y = np.argmax(corr_y) - (len(ch1) - 1)
    
    # 3. 임계값 설정 (노이즈로 인한 미세한 튀는 값 방지)
    threshold = 1
    
    if np.abs(delay_x) <= threshold and np.abs(delay_y) <= threshold:
        return "unknown"
        
    # 두 축 중 딜레이 절대값이 더 큰 축을 기준 방향으로 신뢰함
    if np.abs(delay_x) > np.abs(delay_y):
        return "left" if delay_x < 0 else "right"
    else:
        return "front" if delay_y < 0 else "rear"

def package_json(label, direction):
    """
    7단계: AI 결과와 표준화된 방향 라벨을 융합하여 최종 JSON 패키징
    """
    meta = DANGER_TABLE.get(label, DANGER_TABLE["others"])
    
    return {
        "label": label,
        "danger": meta["danger"],
        "direction": direction,  # left, right, front, rear, unknown 중 하나가 매핑됨
        "color": meta["color"],
        "vibration": meta["vibration"]
    }

if __name__ == "__main__":
    print("[Grabbit DoA-AI 통합 시스템 시뮬레이터 v2_1] 구동")
    
    # 테스트 시나리오 구성 (가상 방향 라벨 일치 여부 검증)
    scenarios = [
        ("left", "siren"),
        ("rear", "crackling_fire"),
        ("right", "crying_baby"),
        ("front", "door_wood_knock")
    ]
    
    for test_dir, ai_label in scenarios:
        print(f"\n[상황 발생] 위치: {test_dir.upper()} / AI 분류: {ai_label}")
        
        ch0, ch1, ch2, ch3 = generate_mock_4channel_audio(test_dir)
        calculated_dir = estimate_direction(ch0, ch1, ch2, ch3)
        final_packet = package_json(ai_label, calculated_dir)
        
        print("최종 출력 JSON 패키지:")
        print(json.dumps(final_packet, ensure_ascii=False, indent=2))
        
        time.sleep(1)