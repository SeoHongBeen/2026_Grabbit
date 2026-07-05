"""
GPS 모듈

현재는 테스트용 코드입니다.
실제 GPS 모듈이 연결되면 get_gps() 함수만 수정하면 됩니다.
"""

def get_gps():
    return {
        "latitude": 37.5665,
        "longitude": 126.9780,
        "accuracy": 15
    }


if __name__ == "__main__":
    gps = get_gps()

    print("Latitude :", gps["latitude"])
    print("Longitude:", gps["longitude"])
    print("Accuracy :", gps["accuracy"], "m")
