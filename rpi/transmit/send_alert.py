"""RPi -> 폰 알림 전송 모듈 (Grabbit).

docs/json-schema.md 스키마 그대로 폰 앱(포트 8080)에 HTTP POST 한다.
표준 라이브러리만 사용 (requests 설치 불필요).

[다른 스크립트에서 쓰는 법 - 감지 루프에 두 줄]

    from transmit.send_alert import AlertSender
    sender = AlertSender("192.168.43.1")   # 폰 IP (실행 인자로 받는 걸 권장)

    # 감지됐을 때:
    sender.send(cls="siren", direction=90)

[단독 실행으로 전송 테스트]

    python3 transmit/send_alert.py --host 192.168.43.1 --cls siren --direction 90
"""
import argparse
import json
import time
import urllib.request

# docs/json-schema.md 확정 표와 동일하게 유지할 것
DANGER_MAP = {
    "crackling_fire": 3,
    "glass_breaking": 3,
    "siren": 3,
    "door_wood_knock": 2,
    "doorbell": 2,
    "door_wood_creaks": 1,
    "others": 0,
}


class AlertSender:
    def __init__(self, host, port=8080, timeout=3, cooldown_sec=2.0):
        """
        cooldown_sec: 같은 클래스가 연속 감지될 때 최소 전송 간격.
                      (마이크가 한 소리를 여러 청크로 잡아 중복 전송되는 것 방지)
        """
        self.url = f"http://{host}:{port}/alert"
        self.timeout = timeout
        self.cooldown_sec = cooldown_sec
        self._last_sent = {}  # cls -> timestamp

    def send(self, cls, direction=-1):
        """감지 결과를 폰으로 전송. 성공 여부 반환.

        cls: 분류 클래스명 (DANGER_MAP의 키. 미등록이면 danger=0 = others 취급)
        direction: 방향 각도 0~359, 추정 실패면 -1
        """
        now = time.time()
        last = self._last_sent.get(cls, 0)
        if now - last < self.cooldown_sec:
            print(f"[send_alert] 쿨다운 스킵: {cls} ({now - last:.1f}s < {self.cooldown_sec}s)")
            return False
        self._last_sent[cls] = now

        alert = {
            "class": cls,
            "direction": int(direction),
            "danger": DANGER_MAP.get(cls, 0),
            "timestamp": int(now),
        }
        req = urllib.request.Request(
            self.url,
            data=json.dumps(alert).encode(),
            headers={"Content-Type": "application/json"},
        )
        # 폰이 Wi-Fi 절전 중이면 첫 패킷이 씹힐 수 있어 최대 3회 재시도
        # (첫 시도가 폰의 Wi-Fi를 깨우는 역할을 하는 경우가 실측으로 확인됨)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as res:
                    print(f"[send_alert] 전송 OK: {alert}")
                    return res.status == 200
            except Exception as e:
                if attempt < 2:
                    print(f"[send_alert] 재시도 {attempt + 1}/2 ({e})")
                    time.sleep(1.0)
                else:
                    # 폰이 잠깐 안 잡혀도 감지 루프는 계속 돌아야 하므로 예외는 삼킨다
                    print(f"[send_alert] 전송 실패 ({self.url}): {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RPi -> 폰 알림 전송 테스트")
    parser.add_argument("--host", required=True, help="폰 IP (예: 192.168.43.1)")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cls", default="siren", help=f"클래스명 {list(DANGER_MAP)}")
    parser.add_argument("--direction", type=int, default=90, help="방향 각도 0~359, 모름=-1")
    args = parser.parse_args()

    sender = AlertSender(args.host, args.port)
    ok = sender.send(args.cls, args.direction)
    print("성공! 폰/워치 확인하세요." if ok else "실패 - 폰 IP, 같은 네트워크인지, 앱 실행 중인지 확인.")
