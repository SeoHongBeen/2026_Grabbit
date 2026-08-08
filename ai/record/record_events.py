"""
!/usr/bin/env python3
위험음을 거리별로 녹음한다 (감지율 측정용)

클래스와 거리를 물어보고, 카운트다운 후 녹음하고, 파일명을 규칙에 맞게 저장
이름 규칙이 어긋나면 나중에 분석 스크립트가 라벨을 못 읽으므로 직접 짓지 말 것

사용법:
    python3 record_events.py                 기본 장치
    python3 record_events.py plughw:1,0      장치 지정

표준 라이브러리만 쓴다 (RPi에 추가 설치 필요 없음)
"""
import os
import subprocess
import sys
import time

RATE = 44100
DURATION = 8            # 한 번에 녹음할 길이(초)
DISTANCES = ["1m", "3m", "5m"]
TAKES = 5               # 클래스 x 거리 당 반복 횟수

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "dataset", "realworld", "events")

CLASSES = {
    "1": ("siren", "사이렌 — 스피커로 재생"),
    "2": ("knock", "노크 — 실제로 문을 두드리세요 (재생보다 정확합니다)"),
    "3": ("glass", "유리 깨짐 — 스피커로 재생"),
    "4": ("fire", "불 타는 소리 — 스피커로 재생 (저음이 잘 안 나와 결과가 나쁠 수 있음)"),
}


def record(device, path, seconds):
    cmd = ["arecord", "-f", "S16_LE", "-r", str(RATE), "-c", "1",
           "-d", str(seconds), "-t", "wav", path]
    if device:
        cmd[1:1] = ["-D", device]
    return subprocess.run(cmd, capture_output=True, text=True).returncode == 0


def next_index(cls, dist):
    i = 1
    while os.path.exists(os.path.join(OUT, "%s_%s_%02d.wav" % (cls, dist, i))):
        i += 1
    return i


def countdown(n=3):
    for i in range(n, 0, -1):
        print("  %d..." % i, end="", flush=True)
        time.sleep(1)
    print(" 녹음 시작!", flush=True)


def session(device, cls, label, dist):
    print()
    print("-" * 62)
    print(" %s / 거리 %s" % (label, dist))
    print("-" * 62)
    print(" 소리를 %s 거리에서 내주세요. 볼륨은 실제 상황에서 들릴 법한 크기로." % dist)
    print(" 한 번에 %d초씩 %d회 녹음합니다.\n" % (DURATION, TAKES))

    done = 0
    while done < TAKES:
        idx = next_index(cls, dist)
        name = "%s_%s_%02d.wav" % (cls, dist, idx)
        path = os.path.join(OUT, name)

        ans = input(" [%d/%d] Enter=녹음  s=이 거리 건너뛰기  q=메뉴로 : "
                    % (done + 1, TAKES)).strip().lower()
        if ans == "s":
            return
        if ans == "q":
            raise KeyboardInterrupt

        countdown()
        if not record(device, path, DURATION):
            print("  녹음 실패 — 장치를 확인하세요 (arecord -l)")
            return

        print("  저장: %s" % name)
        again = input("  소리가 제대로 들어갔나요? Enter=다음  r=다시찍기 : ").strip().lower()
        if again == "r":
            os.remove(path)
            print("  삭제했습니다. 다시 찍습니다.")
            continue

        done += 1


def summary():
    if not os.path.isdir(OUT):
        return
    files = [f for f in os.listdir(OUT) if f.endswith(".wav")]
    if not files:
        return

    print("\n" + "=" * 62)
    print(" 지금까지 녹음한 파일")
    print("=" * 62)
    print(" %-10s %6s %6s %6s" % ("클래스", "1m", "3m", "5m"))
    for cls, _ in CLASSES.values():
        row = [sum(1 for f in files if f.startswith("%s_%s_" % (cls, d))) for d in DISTANCES]
        print(" %-10s %6d %6d %6d" % (cls, row[0], row[1], row[2]))
    print("\n 총 %d개  →  %s" % (len(files), os.path.normpath(OUT)))


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else None
    os.makedirs(OUT, exist_ok=True)

    print("=" * 62)
    print(" 위험음 녹음 (감지율 측정용)")
    print("=" * 62)
    print(" 장치: %s" % (device or "기본"))
    print(" 저장: %s" % os.path.normpath(OUT))
    print("\n 거리를 나눠 찍는 게 핵심입니다. 실제로는 다른 방에서 나는 소리도")
    print(" 잡아야 하는데, 가까이서만 녹음하면 그 성능을 알 수 없습니다.")

    try:
        while True:
            summary()
            print("\n" + "=" * 62)
            for k, (_, label) in CLASSES.items():
                print(" %s. %s" % (k, label))
            print(" q. 종료")

            c = input("\n 번호 선택: ").strip().lower()
            if c == "q":
                break
            if c not in CLASSES:
                continue

            cls, label = CLASSES[c]
            for dist in DISTANCES:
                session(device, cls, label, dist)

    except KeyboardInterrupt:
        pass

    summary()
    print("\n 이 폴더를 PC의 2026_Grabbit/ai/dataset/realworld/events/ 로 옮기세요.")


if __name__ == "__main__":
    main()
