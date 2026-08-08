"""
!/usr/bin/env python3

RPi에서 마이크를 계속 듣다가 위험음이 나면 알림

arecord 로 raw 오디오를 받아 5초 버퍼를 굴리며 HOP초마다 판정
PyAudio 같은 추가 패키지 없이 numpy + tflite-runtime 만 있으면 됨

알림은 폰(Android)이 띄운 Ktor 서버로 HTTP POST 한다.
스키마는 앱 파트와 합의한 형식 그대로:

    POST http://<폰IP>:8080/alert
    {"class": "siren", "direction": 90, "danger": 3, "timestamp": 1752894000}

사용법:
    python3 run_rpi.py --host 192.168.137.42          폰 IP 지정
    python3 run_rpi.py --device plughw:1,0 --channels 4 --host 192.168.137.42
    python3 run_rpi.py --hop 1.0 --verbose            매 판정 결과를 보고 싶을 때
    python3 run_rpi.py --no-send                      전송 없이 화면 출력만
"""
import argparse
import json
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import numpy as np

from grabbit import Detector

# 클래스 → 위험도. 앱 파트 확정 목록(2026-07-19)과 같은 값이어야 함
# (1=낮음, 2=중간, 3=긴급). 여기 없는 클래스는 전송하지 않는다.
DANGER = {
    "crackling_fire": 3,
    "glass_breaking": 3,
    "siren": 3,
    "door_wood_knock": 2,
    "door_wood_creaks": 1,
    "doorbell": 2,          # 스키마 확정 목록에는 없음 — 아래 주석 참고
}


def estimate_direction():
    """
    소리 방향(도, 0~359). 추정 실패면 -1

    DoA(GCC-PHAT)는 rpi/doa 파트에서 구현 중이라 아직 -1을 보냄
    붙일 때 이 함수만 바꾸면 됨 — 폰은 -1을 'unknown'으로 처리
    """
    return -1


class AlertSender:
    """
    알림을 폰으로 POST, 별도 스레드에서 보내 판정 루프를 막지 않음

    5초 창을 1초마다 굴리는 구조라 전송이 블로킹되면 그 사이 오디오가 밀림
    네트워크가 죽어도 감지는 계속돼야 하므로, 큐가 차면 버리고 실패는 세기만 함
    """

    def __init__(self, host, port, timeout=2.0, retries=1):
        self.url = "http://%s:%d/alert" % (host, port)
        self.timeout = timeout
        self.retries = retries
        self.n_ok = 0
        self.n_fail = 0

        self._q = queue.Queue(maxsize=32)
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def send(self, payload):
        try:
            self._q.put_nowait(payload)
        except queue.Full:
            self.n_fail += 1
            print("  [전송] 큐가 가득 참 — 버림", flush=True)

    def _run(self):
        while True:
            payload = self._q.get()
            if payload is None:
                return
            self._deliver(payload)

    def _deliver(self, payload):
        body = json.dumps(payload).encode("utf-8")
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(
                    self.url, data=body,
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as res:
                    res.read()
                    if 200 <= res.status < 300:
                        self.n_ok += 1
                        return
                    reason = "HTTP %d" % res.status
            except urllib.error.HTTPError as e:
                reason = "HTTP %d" % e.code
            except urllib.error.URLError as e:
                reason = str(e.reason)
            except Exception as e:                      # 소켓·타임아웃 등
                reason = "%s: %s" % (type(e).__name__, e)

            if attempt < self.retries:
                time.sleep(0.3)

        self.n_fail += 1
        print("  [전송 실패] %s → %s" % (self.url, reason), flush=True)

    def close(self):
        self._q.put(None)
        self._worker.join(timeout=3.0)


def on_alert(name, conf, when, sender):
    """알림이 울려야 할 때 호출, 임계값·연속·쿨다운 판정은 이미 끝난 상태"""
    print("\n[알림] %s  (확신도 %.2f)  %s"
          % (name, conf, time.strftime("%H:%M:%S", time.localtime(when))), flush=True)

    danger = DANGER.get(name)
    if danger is None:
        print("  [전송 안 함] '%s' 는 위험도 표에 없는 클래스" % name, flush=True)
        return

    payload = {
        "class": name,
        "direction": estimate_direction(),
        "danger": danger,
        "timestamp": int(when),          # 스키마상 유닉스 '초'
    }

    if sender is None:                   # --no-send
        print("  [전송 생략] %s" % json.dumps(payload, ensure_ascii=False), flush=True)
        return

    sender.send(payload)


def open_mic(device, sr, channels):
    cmd = ["arecord", "-f", "S16_LE", "-r", str(sr), "-c", str(channels),
           "-t", "raw", "-q", "-"]
    if device:
        cmd[1:1] = ["-D", device]

    try:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0)
    except FileNotFoundError:
        sys.exit("arecord 가 없습니다 → sudo apt install alsa-utils")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=None, help="예: plughw:1,0")
    ap.add_argument("--channels", type=int, default=1,
                    help="마이크 어레이면 채널 수 (예: 4). 평균내어 모노로 씀")
    ap.add_argument("--hop", type=float, default=1.0, help="판정 간격(초)")
    ap.add_argument("--cooldown", type=float, default=30.0,
                    help="같은 알림을 다시 울리기까지 최소 간격(초)")
    ap.add_argument("--verbose", action="store_true", help="판정마다 결과 출력")
    ap.add_argument("--host", default="127.0.0.1",
                    help="알림을 받을 폰의 IP (핫스팟 주소). 예: 192.168.137.42")
    ap.add_argument("--port", type=int, default=8080, help="폰 Ktor 서버 포트")
    ap.add_argument("--timeout", type=float, default=2.0, help="전송 타임아웃(초)")
    ap.add_argument("--no-send", action="store_true",
                    help="전송하지 않고 화면 출력만 (마이크·모델 점검용)")
    args = ap.parse_args()

    det = Detector()

    # 모델이 내는 클래스인데 위험도 표에 없으면 조용히 안 나가므로 미리 알린다
    missing = [det.name(c) for c in sorted(det.minority) if det.name(c) not in DANGER]
    if missing:
        print("경고: 위험도 미지정 클래스 → 알림이 전송되지 않습니다: %s" % ", ".join(missing))

    print("=" * 62)
    print(" Grabbit 소리 감지")
    print("=" * 62)
    print(" 클래스 : %s" % ", ".join(det.name(c) for c in sorted(det.minority)))
    print(" 임계값 : %s" % ", ".join(
        "%s %.2f" % (det.name(c), det.thresholds[c]) for c in sorted(det.minority)))
    print(" 연속   : %s" % ", ".join(
        "%s %d회" % (det.name(c), det.consecutive[c]) for c in sorted(det.minority)))
    print(" 오디오 : %dHz / %d초 창 / %.1f초 간격 / %d채널"
          % (det.sr, det.clip_len // det.sr, args.hop, args.channels))
    print(" 전송   : %s" % ("(안 함 — --no-send)" if args.no_send
                           else "http://%s:%d/alert" % (args.host, args.port)))
    print("\n 듣는 중... (Ctrl+C 로 종료)\n")

    sender = None if args.no_send else AlertSender(args.host, args.port, args.timeout)
    mic = open_mic(args.device, det.sr, args.channels)

    buf = np.zeros(det.clip_len, dtype=np.float32)
    hop_frames = int(args.hop * det.sr)
    bytes_per_frame = 2 * args.channels
    need = hop_frames * bytes_per_frame

    n_alert, n_win, t_start = 0, 0, time.time()

    try:
        while True:
            raw = mic.stdout.read(need)
            if not raw or len(raw) < need:
                err = mic.stderr.read().decode("utf-8", "replace").strip()
                sys.exit("녹음이 끊겼습니다.\n%s\n장치 이름을 확인하세요 (arecord -l)" % err)

            chunk = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if args.channels > 1:
                chunk = chunk.reshape(-1, args.channels).mean(axis=1)

            # 5초 버퍼를 굴린다
            buf = np.concatenate([buf[len(chunk):], chunk])

            cls, conf, probs = det.predict(buf)
            now = time.time()
            n_win += 1

            if args.verbose:
                print("  %s  %-16s %.3f   [%s]" % (
                    time.strftime("%H:%M:%S"), det.name(cls), conf,
                    " ".join("%s %.2f" % (det.name(i)[:5], p)
                             for i, p in enumerate(probs))), flush=True)

            if det.should_alert(cls, conf, now, args.cooldown):
                n_alert += 1
                on_alert(det.name(cls), conf, now, sender)

    except KeyboardInterrupt:
        el = (time.time() - t_start) / 3600
        print("\n\n종료. %.2f시간 동안 판정 %d회 / 알림 %d회 (시간당 %.1f회)"
              % (el, n_win, n_alert, n_alert / el if el > 0 else 0))
        if sender is not None:
            print("전송 성공 %d회 / 실패 %d회" % (sender.n_ok, sender.n_fail))
    finally:
        mic.terminate()
        if sender is not None:
            sender.close()


if __name__ == "__main__":
    main()
