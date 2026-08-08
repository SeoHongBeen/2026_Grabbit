"""
!/usr/bin/env python3
녹음 시작 전에 마이크가 제대로 잡히는지 확인

표준 라이브러리만 사용 (RPi에 추가 설치 필요 없음)
"""
import array
import os
import subprocess
import sys
import tempfile
import wave

DURATION = 5
RATE = 44100


def list_devices():
    print("=" * 60)
    print("녹음 장치 목록")
    print("=" * 60)
    try:
        out = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
        print(out.strip() or "  (장치를 찾지 못함)")
    except FileNotFoundError:
        print("  arecord가 없음 → sudo apt install alsa-utils")
        sys.exit(1)
    print()


def record(device, path):
    cmd = ["arecord", "-f", "S16_LE", "-r", str(RATE), "-c", "1",
           "-d", str(DURATION), "-t", "wav", path]
    if device:
        cmd[1:1] = ["-D", device]

    print("%d초간 녹음합니다. 평소 말하는 크기로 아무 말이나 해보세요..." % DURATION)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("\n녹음 실패:")
        print(r.stderr.strip())
        print("\n장치 이름이 맞는지 확인하세요 (예: plughw:1,0)")
        sys.exit(1)


def analyse(path):
    with wave.open(path, "rb") as w:
        n, width, rate = w.getnframes(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)

    if width != 2:
        print("16bit 녹음이 아님 — 설정 확인 필요")
        return

    samples = array.array("h")
    samples.frombytes(raw)

    peak = max(abs(s) for s in samples) if samples else 0
    rms = (sum(float(s) * s for s in samples) / len(samples)) ** 0.5 if samples else 0.0

    # 16bit 최대값 32768 기준 비율
    peak_pct = 100.0 * peak / 32768
    rms_pct = 100.0 * rms / 32768
    clipped = sum(1 for s in samples if abs(s) >= 32700)

    print()
    print("=" * 60)
    print("결과")
    print("=" * 60)
    print("  샘플레이트 : %d Hz" % rate)
    print("  길이       : %.1f초" % (n / rate))
    print("  최대 음량  : %.1f%%" % peak_pct)
    print("  평균 음량  : %.1f%%" % rms_pct)
    print("  찌그러짐   : %d 샘플" % clipped)
    print()

    if peak_pct < 1:
        print("  [문제] 거의 무음입니다. 마이크가 연결되지 않았거나 음소거 상태입니다.")
        print("         alsamixer 로 Capture 볼륨을 올리고 M 키로 음소거를 해제하세요.")
    elif peak_pct < 10:
        print("  [주의] 음량이 너무 작습니다. alsamixer 에서 Capture 게인을 올리세요.")
    elif clipped > len(samples) * 0.001:
        print("  [주의] 소리가 찌그러집니다. alsamixer 에서 Capture 게인을 낮추세요.")
    else:
        print("  [정상] 이 설정으로 녹음을 진행하세요.")
        print()
        print("  다음 단계:")
        print("    ./record_ambient.sh %s      (일상 소음 — 오알림 측정용)"
              % (device_arg or "plughw:1,0"))
        print("    python3 record_events.py %s (위험음 — 감지율 측정용)"
              % (device_arg or "plughw:1,0"))


if __name__ == "__main__":
    device_arg = sys.argv[1] if len(sys.argv) > 1 else None

    list_devices()
    if not device_arg:
        print("장치를 지정하지 않았습니다. 기본 장치로 시도합니다.")
        print("실패하면 위 목록을 보고: python3 check_mic.py plughw:1,0\n")

    tmp = os.path.join(tempfile.gettempdir(), "grabbit_mic_check.wav")
    record(device_arg, tmp)
    analyse(tmp)
    os.remove(tmp)
