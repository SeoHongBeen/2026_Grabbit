"""연속 알림 스트레스 테스트 스크립트 (mock_rpi.py 기반).

폰 앱으로 알림을 연속으로 쏴서 다음을 검증한다:
  1. 연속 수신 시 유실 없는지 (전송 성공 카운트 vs 워치 표시)
  2. 자동 해제 타이머가 새 알림마다 리셋되는지
  3. 진동 겹침 체감 (긴급 진동 중 낮은 알림이 끊는지)
  4. 폰 화면 꺼진 상태에서도 전부 전달되는지

사용법 (노트북에서, 폰과 같은 네트워크):
  python tools/stress_test.py --host <폰IP>              # 기본: 2초 간격 5발
  python tools/stress_test.py --host <폰IP> --fast       # 0.5초 간격 5발 (빡센 버전)
  python tools/stress_test.py --host <폰IP> --scenario   # 실전 시나리오 (긴급→낮음 섞어서)
  python tools/stress_test.py --host <폰IP> --doze       # 화면 꺼짐 장기 테스트 (1분 간격 10발)

검증 방법:
  - 전송 후 마지막에 "전송 성공 N발" 출력됨
  - 워치에서 받은 개수와 비교 (others는 워치에 안 가는 게 정상이므로 제외하고 셈)
  - 폰 히스토리 화면에는 others 포함 전부 기록돼야 함
"""
import argparse
import json
import time
import urllib.request

# (class, direction, 설명) — others 제외, 워치까지 가는 클래스만 기본 사용
BURST_SEQUENCE = [
    ("siren",            90,  "긴급/오른쪽"),
    ("door_wood_knock",  0,   "중간/앞"),
    ("glass_breaking",   180, "긴급/뒤"),
    ("door_wood_creaks", 270, "낮음/왼쪽"),
    ("doorbell",         45,  "중간/오른쪽"),
]

# 실전 시나리오: 긴급 진동 중에 낮은 알림이 끼어드는 상황 재현
SCENARIO_SEQUENCE = [
    ("siren",            0,   "긴급 시작 (긴 진동)"),
    ("door_wood_creaks", 90,  "1.5초 뒤 낮은 알림 - 긴급 진동을 끊는지 체감"),
    ("siren",            180, "다시 긴급"),
    ("others",           -1,  "others - 워치에 안 가고 폰 기록만 남아야 함"),
    ("doorbell",         270, "초인종 - 새로 추가한 매핑 확인"),
]

DANGER_MAP = {
    "crackling_fire": 3, "glass_breaking": 3, "siren": 3,
    "door_wood_knock": 2, "doorbell": 2, "door_wood_creaks": 1, "others": 0,
}


def send(host, port, cls, direction):
    alert = {
        "class": cls,
        "direction": direction,
        "danger": DANGER_MAP.get(cls, 0),
        "timestamp": int(time.time()),
    }
    url = f"http://{host}:{port}/alert"
    req = urllib.request.Request(
        url, data=json.dumps(alert).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as res:
            return res.status == 200
    except Exception as e:
        print(f"  전송 실패: {e}")
        return False


def run(host, port, sequence, interval, label):
    print(f"=== {label} (간격 {interval}초) ===")
    ok = 0
    watch_expected = 0
    for i, (cls, direction, desc) in enumerate(sequence):
        success = send(host, port, cls, direction)
        mark = "O" if success else "X"
        print(f"  [{i+1}/{len(sequence)}] {mark} {cls} ({desc})")
        if success:
            ok += 1
            if cls != "others":
                watch_expected += 1
        if i < len(sequence) - 1:
            time.sleep(interval)
    print(f"\n전송 성공 {ok}/{len(sequence)}발")
    print(f"워치에 떠야 하는 개수: {watch_expected}개 (others 제외)")
    print(f"폰 히스토리에 기록돼야 하는 개수: {ok}개 (others 포함)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="폰(수신 서버) IP")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--fast", action="store_true", help="0.5초 간격 (빡센 연속 테스트)")
    parser.add_argument("--scenario", action="store_true", help="실전 시나리오 (진동 겹침/others/doorbell)")
    parser.add_argument("--doze", action="store_true", help="화면 꺼짐 장기 테스트 (60초 간격 10발)")
    args = parser.parse_args()

    if args.doze:
        print("폰 화면을 끄고 그대로 두세요. 60초 간격으로 10발 쏩니다 (약 10분).")
        print("중간에 수신이 끊기면 몇 발째부터 끊겼는지가 중요합니다 (배터리 절전 개입 시점).\n")
        seq = [BURST_SEQUENCE[i % len(BURST_SEQUENCE)] for i in range(10)]
        run(args.host, args.port, seq, 60, "화면 꺼짐 장기(Doze) 테스트")
    elif args.scenario:
        run(args.host, args.port, SCENARIO_SEQUENCE, 1.5, "실전 시나리오")
    elif args.fast:
        run(args.host, args.port, BURST_SEQUENCE, 0.5, "고속 연속 테스트")
    else:
        run(args.host, args.port, BURST_SEQUENCE, 2.0, "기본 연속 테스트")
