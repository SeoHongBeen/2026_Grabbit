"""
!/usr/bin/env python3

RPi에서 마이크를 계속 듣다가 위험음이 나면 알림

arecord 로 raw 오디오를 받아 5초 버퍼를 굴리며 HOP초마다 판정
소리 분류(YAMNet + 앙상블)와 방향 추정(GCC delay + RMS 비율 KNN)을 함께 수행

알림은 폰(Android)이 띄운 Ktor 서버로 HTTP POST 한다.

    POST http://<폰IP>:8080/alert
    {"class": "siren", "direction": 90, "danger": 3, "timestamp": 1752894000}

사용법:
    python3 run_rpi.py --host 192.168.137.42          폰 IP 지정
    python3 run_rpi.py --device plughw:0,0 --channels 4 --host 192.168.137.42
    python3 run_rpi.py --hop 1.0 --verbose            매 판정 결과를 보고 싶을 때
    python3 run_rpi.py --no-send                      전송 없이 화면 출력만
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import numpy as np

from grabbit import Detector

# ===== 방향 추정 (DoA) =====
# 주하 v5 모델: 6차원 피처 [delay_x, delay_y, rms0~3 비율] -> StandardScaler -> KNN
try:
    import joblib
    from scipy.signal import correlate

    _DOA_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "rpi")
    _doa_model = joblib.load(os.path.join(_DOA_DIR, "doa_knn_model_v5.pkl"))
    _doa_scaler = joblib.load(os.path.join(_DOA_DIR, "doa_scaler.pkl"))
    DOA_READY = True
except Exception as e:
    print("[DoA] 모델 로드 실패 — 방향은 -1(unknown)로 나갑니다: %s" % e)
    _doa_model = None
    _doa_scaler = None
    DOA_READY = False

# 라벨 -> 각도. docs/json-schema.md 기준 (0=정면, 90=우, 180=후, 270=좌)
DIRECTION_ANGLE = {
    "front": 0,
    "right": 90,
    "rear": 180,
    "left": 270,
}

# 이 값보다 조용하면 방향 추정을 하지 않는다 (잡음으로 엉뚱한 방향이 나오는 걸 막음)
DOA_VOLUME_THRESHOLD = 3000

# 클래스 → 위험도. docs/json-schema.md 의 확정 목록(2026-08-11 개정)과 같은
# 값이어야 함 (1=낮음, 2=중간, 3=긴급). 여기 없는 클래스는 전송하지 않는다.
DANGER = {
    "glass_breaking": 3,
    "siren": 3,
    "door_wood_knock": 2,
    "doorbell": 2,
}


def estimate_direction(frames):
    """
    소리 방향(도, 0~359). 추정 실패면 -1

    frames: (N, channels) int16 원본. 4채널이 아니거나 모델이 없으면 -1
    """
    if not DOA_READY or frames is None or frames.ndim != 2 or frames.shape[1] != 4:
        return -1

    audio = frames.astype(np.float32)
    if np.max(np.abs(audio)) < DOA_VOLUME_THRESHOLD:
        return -1

    ch0, ch1, ch2, ch3 = audio[:, 0], audio[:, 1], audio[:, 2], audio[:, 3]

    corr_x = correlate(ch0, ch2, mode="full")
    delay_x = np.argmax(corr_x) - (len(ch0) - 1)

    corr_y = correlate(ch1, ch3, mode="full")
    delay_y = np.argmax(corr_y) - (len(ch1) - 1)

    rms0 = np.sqrt(np.mean(ch0.astype(np.float64) ** 2))
    rms1 = np.sqrt(np.mean(ch1.astype(np.float64) ** 2))
    rms2 = np.sqrt(np.mean(ch2.astype(np.float64) ** 2))
    rms3 = np.sqrt(np.mean(ch3.astype(np.float64) ** 2))
    rms_sum = rms0 + rms1 + rms2 + rms3 + 1e-5

    features = np.array([[delay_x, delay_y,
                          rms0 / rms_sum, rms1 / rms_sum,
                          rms2 / rms_sum, rms3 / rms_sum]])

    try:
        label = _doa_model.predict(_doa_scaler.transform(features))[0]
    except Exception:
        return -1

    return DIRECTION_ANGLE.get(label, -1)


def warm_up(det, channels):
    """
    분류·방향 추정을 시작 전에 한 번씩 돌려둔다

    scipy FFT 준비와 tflite 첫 invoke 는 RPi에서 몇 초씩 걸린다. 루프 안에서
    처음 만나면 그 사이 arecord 가 뱉는 오디오가 통째로 밀려 알림이 늦어진다
    """
    t = time.time()
    det.predict(np.zeros(det.clip_len, dtype=np.float32))
    if DOA_READY and channels == 4:
        dummy = np.full((det.sr, 4), 8000, dtype=np.int16)
        dummy[::2] = -8000
        estimate_direction(dummy)
    print(" 준비 완료 (%.1f초)" % (time.time() - t))


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


def on_alert(name, conf, when, sender, direction):
    """알림이 울려야 할 때 호출, 임계값·연속·쿨다운 판정은 이미 끝난 상태"""
    dir_txt = "unknown" if direction < 0 else "%d도" % direction
    print("\n[알림] %s  (확신도 %.2f)  방향 %s  %s"
          % (name, conf, dir_txt,
             time.strftime("%H:%M:%S", time.localtime(when))), flush=True)

    danger = DANGER.get(name)
    if danger is None:
        print("  [전송 안 함] '%s' 는 위험도 표에 없는 클래스" % name, flush=True)
        return

    payload = {
        "class": name,
        "direction": direction,
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


def read_exact(stream, n):
    """
    파이프에서 정확히 n바이트를 모아 돌려준다. 녹음이 끝났으면 None

    파이프는 한 번의 read 로 요청한 만큼 주지 않는다 — 그 순간 도착해 있는
    만큼만 준다. 파이프 버퍼가 64KB라 4채널 1초(128KB)는 애초에 한 번에
    올 수 없으므로, 다 찰 때까지 이어 붙여야 한다
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:                        # arecord 종료 = EOF
            return None
        buf += chunk
    return bytes(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=None, help="예: plughw:0,0")
    ap.add_argument("--channels", type=int, default=1,
                    help="마이크 어레이면 채널 수 (예: 4). 분류는 평균내어 모노로 씀")
    ap.add_argument("--hop", type=float, default=1.0, help="판정 간격(초)")
    ap.add_argument("--cooldown", type=float, default=10.0,
                    help="같은 알림을 다시 울리기까지 최소 간격(초). "
                         "소리가 계속 나면 이 간격마다 다시 울린다")
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
    print(" 방향   : %s" % ("v5 모델 사용" if DOA_READY and args.channels == 4
                           else "사용 안 함 (-1로 전송)"))
    print(" 전송   : %s" % ("(안 함 — --no-send)" if args.no_send
                           else "http://%s:%d/alert" % (args.host, args.port)))
    warm_up(det, args.channels)
    print("\n 듣는 중... (Ctrl+C 로 종료)\n")

    sender = None if args.no_send else AlertSender(args.host, args.port, args.timeout)
    mic = open_mic(args.device, det.sr, args.channels)

    buf = np.zeros(det.clip_len, dtype=np.float32)
    hop_frames = int(args.hop * det.sr)
    bytes_per_frame = 2 * args.channels
    need = hop_frames * bytes_per_frame

    # 방향 추정용: 최근 hop 구간의 채널별 원본(int16)을 그대로 들고 있는다
    last_frames = None

    n_alert, n_win, t_start = 0, 0, time.time()
    t_infer_sum, t_infer_max = 0.0, 0.0          # hop 을 더 줄여도 되는지 판단용

    try:
        while True:
            raw = read_exact(mic.stdout, need)
            if raw is None:
                # arecord 를 먼저 죽여야 stderr 가 EOF 로 닫힌다 (안 그러면 read 가 멈춤)
                mic.terminate()
                try:
                    err = mic.stderr.read().decode("utf-8", "replace").strip()
                except Exception:
                    err = ""
                sys.exit("녹음이 끊겼습니다.\n%s\n장치 이름을 확인하세요 (arecord -l)" % err)

            samples = np.frombuffer(raw, dtype=np.int16)

            if args.channels > 1:
                frames = samples.reshape(-1, args.channels)
                last_frames = frames                       # 방향 추정용 원본 보관
                chunk = frames.astype(np.float32).mean(axis=1) / 32768.0
            else:
                last_frames = None
                chunk = samples.astype(np.float32) / 32768.0

            # 5초 버퍼를 굴린다
            buf = np.concatenate([buf[len(chunk):], chunk])

            t0 = time.time()
            cls, conf, probs = det.predict(buf)
            now = time.time()
            infer = now - t0
            t_infer_max = max(t_infer_max, infer)
            t_infer_sum += infer
            n_win += 1

            if args.verbose:
                print("  %s  %-16s %.3f   [%s]  %.2fs" % (
                    time.strftime("%H:%M:%S"), det.name(cls), conf,
                    " ".join("%s %.2f" % (det.name(i)[:5], p)
                             for i, p in enumerate(probs)), infer), flush=True)

            hit = det.should_alert(probs, now, args.cooldown)
            if hit is not None:
                alert_cls, alert_conf = hit
                n_alert += 1
                direction = estimate_direction(last_frames)
                on_alert(det.name(alert_cls), alert_conf, now, sender, direction)

    except KeyboardInterrupt:
        el = (time.time() - t_start) / 3600
        print("\n\n종료. %.2f시간 동안 판정 %d회 / 알림 %d회 (시간당 %.1f회)"
              % (el, n_win, n_alert, n_alert / el if el > 0 else 0))
        if n_win:
            print("추론 시간 평균 %.2f초 / 최대 %.2f초 (--hop %.1f초)"
                  % (t_infer_sum / n_win, t_infer_max, args.hop))
        if sender is not None:
            print("전송 성공 %d회 / 실패 %d회" % (sender.n_ok, sender.n_fail))
    finally:
        mic.terminate()
        if sender is not None:
            sender.close()


if __name__ == "__main__":
    main()