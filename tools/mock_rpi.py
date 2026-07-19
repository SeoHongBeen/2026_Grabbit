"""RPi 흉내내는 테스트 스크립트.
폰 앱(HTTP 서버)으로 가짜 소리 감지 JSON을 쏜다.

사용법:
  python3 tools/mock_rpi.py                     # 랜덤 소리 1개 전송
  python3 tools/mock_rpi.py --loop              # 5초마다 계속 전송
  python3 tools/mock_rpi.py --host 192.168.0.5  # 폰 IP 지정
"""
import argparse
import json
import random
import time
import urllib.request

SOUND_CLASSES = ["crackling_fire", "glass_breaking", "siren", "door_wood_knock", "door_wood_creaks", "others"]
DANGER_MAP = {"crackling_fire": 3, "glass_breaking": 3, "siren": 3, "door_wood_knock": 2, "door_wood_creaks": 1, "others": 0}


def make_alert():
    cls = random.choice(SOUND_CLASSES)
    return {
        "class": cls,
        "direction": random.choice([0, 45, 90, 135, 180, 225, 270, 315, -1]),
        "danger": DANGER_MAP[cls],
        "timestamp": int(time.time()),
    }


def send(host, port, alert):
    url = f"http://{host}:{port}/alert"
    data = json.dumps(alert).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as res:
            print(f"보냄 -> {alert} | 응답: {res.status}")
    except Exception as e:
        print(f"전송 실패 ({url}): {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", help="폰(수신 서버) IP")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--loop", action="store_true", help="5초마다 반복 전송")
    args = parser.parse_args()

    if args.loop:
        while True:
            send(args.host, args.port, make_alert())
            time.sleep(5)
    else:
        send(args.host, args.port, make_alert())
