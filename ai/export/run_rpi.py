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
import collections
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

HERE = os.path.dirname(os.path.abspath(__file__))

# 임계값·연속 조건을 정할 때 쓴 판정 간격 (training/deploy_config.py 의 DEPLOY_HOP).
# "연속 N회"는 결국 "N × hop 초 동안 지속"이라는 뜻이라, 이 값이 달라지면
# 같은 npz 를 써도 요구 지속시간과 알림 지연이 통째로 바뀐다.
#
# 0.48초로 낮췄더니 RPi4가 못 따라가 오디오가 밀렸다. 간격을 좁히는 대신
# 연속 조건을 줄여(사이렌 4→2, 노크 2→1) 지연을 절반으로 만들었고,
# 그렇게 해도 임계값·recall·오알림은 그대로였다.
TUNE_HOP = 1.0

# ===== 방향 추정 (DoA) =====
# 주하 v5 모델: 6차원 피처 [delay_x, delay_y, rms0~3 비율] -> StandardScaler -> KNN
#
# rpi/live_test.py 와 **같은 조건**으로 계산해야 한다. 학습 데이터를 모은
# collect_direction_data.py 가 16kHz / 4096샘플(0.256초) 청크를 썼기 때문에,
# 더 긴 구간에서 상관 argmax 를 잡으면 학습에 없던 delay 가 나온다.
# direction_training_data_v2.csv 의 실제 범위는 delay_x -32~3, delay_y -9~3 이다.
DOA_WIN = 4096                  # 학습과 같은 청크 길이 (0.256초 @16kHz)
DOA_MAX_LAG = 64                # 상관 피크를 찾을 범위 (학습 최대치 32의 2배)
DOA_VOLUME_THRESHOLD = 3000     # 이보다 조용하면 방향 추정을 하지 않는다

# 라벨 -> 각도. docs/json-schema.md 기준 (0=정면, 90=우, 180=후, 270=좌)
DIRECTION_ANGLE = {
    "front": 0,
    "right": 90,
    "rear": 180,
    "left": 270,
}

_doa_model = None
_doa_scaler = None
_correlate = None
_doa_unknown_labels = set()

# 클래스 → 위험도. docs/json-schema.md 의 확정 목록과 같은 값이어야 함
# (1=낮음, 2=중간, 3=긴급). 여기 없는 클래스는 전송하지 않는다.
DANGER = {
    "crackling_fire": 3,
    "glass_breaking": 3,
    "siren": 3,
    "door_wood_knock": 2,
    "door_wood_creaks": 1,
    "doorbell": 2,          # 스키마 확정 목록에는 없음 — 아래 주석 참고
}


def _find_doa_file(name, explicit):
    """DoA 파일을 찾는다. 배포 패키지(export/)만 복사한 경우도 있어 여러 곳을 본다"""
    if explicit:
        return explicit if os.path.exists(explicit) else None

    for p in (os.path.join(HERE, name),                          # export/ 에 같이 복사
              os.path.join(HERE, "..", "..", "rpi", name),       # 저장소 배치
              os.path.join(os.getcwd(), name)):
        if os.path.exists(p):
            return os.path.normpath(p)
    return None


def load_doa(model_path=None, scaler_path=None):
    """
    DoA 모델을 읽는다. 성공하면 쓴 모델 경로, 실패하면 None

    import 시점이 아니라 main() 에서 부른다 — --help 만 봐도 모델을 읽거나
    배너보다 먼저 오류가 찍히는 걸 막기 위해서
    """
    global _doa_model, _doa_scaler, _correlate

    m = _find_doa_file("doa_knn_model_v5.pkl", model_path)
    s = _find_doa_file("doa_scaler.pkl", scaler_path)
    if m is None or s is None:
        missing = " / ".join(n for n, p in (("doa_knn_model_v5.pkl", m),
                                            ("doa_scaler.pkl", s)) if p is None)
        print("[DoA] 파일을 찾지 못함 (%s) — 방향은 -1(unknown)로 나갑니다" % missing)
        return None

    try:
        import joblib
        from scipy.signal import correlate
    except ImportError as e:
        print("[DoA] %s — 방향은 -1(unknown). pip install joblib scipy" % e)
        return None

    try:
        _doa_model = joblib.load(m)
        _doa_scaler = joblib.load(s)
    except Exception as e:
        # sklearn 버전이 다르면 여기서 깨진다. 감지는 계속돼야 하므로 죽이지 않는다
        print("[DoA] 모델 로드 실패 — 방향은 -1(unknown): %s: %s" % (type(e).__name__, e))
        _doa_model = _doa_scaler = None
        return None

    _correlate = correlate
    return m


def _delay(a, b):
    """a, b 사이 지연(샘플). live_test.py 와 같은 정의이되 탐색 범위만 제한

    범위를 두는 이유: 5초 버퍼처럼 긴 구간에서는 잔향·무관한 소리 때문에
    엉뚱한 위치에 피크가 생기고, 그 값은 학습 분포(-32~3) 밖이라
    스케일러를 거치면 KNN 이 아무 방향이나 내놓는다
    """
    c = _correlate(a, b, mode="full")
    mid = len(a) - 1
    lo = max(0, mid - DOA_MAX_LAG)
    hi = min(len(c), mid + DOA_MAX_LAG + 1)
    return int(np.argmax(c[lo:hi]) + lo - mid)


def estimate_direction(frames):
    """
    소리 방향(도, 0~359). 추정 실패면 -1

    frames: (N, 4) int16 원본 (5초 버퍼 전체). 가장 큰 소리가 난 0.256초
    구간을 골라서 추정한다 — 알림은 연속 조건 때문에 소리가 난 뒤 1~2창
    지나서 울리므로, 마지막 청크에는 정작 그 소리가 없을 수 있다
    """
    if _doa_model is None or frames is None:
        return -1
    if frames.ndim != 2 or frames.shape[1] != 4 or len(frames) < DOA_WIN:
        return -1

    # 4096샘플 블록으로 잘라 가장 시끄러운 블록을 고른다 (뒤쪽 기준으로 정렬)
    n_blocks = len(frames) // DOA_WIN
    blocks = frames[-n_blocks * DOA_WIN:].reshape(n_blocks, DOA_WIN, 4)
    peaks = np.abs(blocks.astype(np.int32)).max(axis=(1, 2))

    b = int(np.argmax(peaks))
    if peaks[b] < DOA_VOLUME_THRESHOLD:
        return -1

    seg = blocks[b].astype(np.float32)
    ch0, ch1, ch2, ch3 = seg[:, 0], seg[:, 1], seg[:, 2], seg[:, 3]

    delay_x = _delay(ch0, ch2)
    delay_y = _delay(ch1, ch3)

    rms = np.sqrt(np.mean(seg.astype(np.float64) ** 2, axis=0))
    rms_sum = rms.sum() + 1e-5

    features = np.array([[delay_x, delay_y,
                          rms[0] / rms_sum, rms[1] / rms_sum,
                          rms[2] / rms_sum, rms[3] / rms_sum]])

    try:
        label = _doa_model.predict(_doa_scaler.transform(features))[0]
    except Exception as e:
        print("  [DoA] 예측 실패: %s: %s" % (type(e).__name__, e), flush=True)
        return -1

    if label not in DIRECTION_ANGLE:
        if label not in _doa_unknown_labels:      # 같은 경고를 반복하지 않는다
            _doa_unknown_labels.add(label)
            print("  [DoA] 모르는 라벨 '%s' — DIRECTION_ANGLE 에 추가가 필요합니다"
                  % label, flush=True)
        return -1

    return DIRECTION_ANGLE[label]


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


def drain_stderr(proc, keep=50, show=3):
    """
    arecord 의 stderr 를 계속 비운다. 반환값은 마지막 몇 줄을 담은 deque

    비우지 않으면 파이프(64KB)가 차는 순간 arecord 가 stderr 쓰기에서 막히고,
    그러면 오디오도 더 안 나와서 판정 루프가 통째로 얼어붙는다. 화면에는
    "듣는 중..." 만 남고 아무 일도 일어나지 않는다.

    RPi 가 판정을 못 따라가면 arecord 가 overrun 경고를 계속 뱉으므로
    이건 가정이 아니라 실제로 도달하는 상태다. 앞 몇 줄은 화면에도 보여준다
    — 느려서 밀리는 중이라는 가장 빠른 신호이기 때문
    """
    lines = collections.deque(maxlen=keep)

    def run():
        buf = b""
        while True:
            try:
                chunk = proc.stderr.read(4096)
            except Exception:
                return
            if not chunk:
                break
            buf += chunk
            parts = buf.replace(b"\r", b"\n").split(b"\n")
            buf = parts.pop()
            for p in parts:
                s = p.decode("utf-8", "replace").strip()
                if not s:
                    continue
                if len(lines) < show:
                    print("  [arecord] %s" % s, flush=True)
                lines.append(s)

        if buf.strip():
            lines.append(buf.decode("utf-8", "replace").strip())

    threading.Thread(target=run, daemon=True).start()
    return lines


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
    ap.add_argument("--hop", type=float, default=TUNE_HOP,
                    help="판정 간격(초). 기본값은 임계값을 정할 때 쓴 %.2f초 — "
                         "바꾸면 연속 조건이 요구하는 지속시간도 같이 바뀐다" % TUNE_HOP)
    ap.add_argument("--cooldown", type=float, default=30.0,
                    help="같은 알림을 다시 울리기까지 최소 간격(초)")
    ap.add_argument("--verbose", action="store_true", help="판정마다 결과 출력")
    ap.add_argument("--host", default="127.0.0.1",
                    help="알림을 받을 폰의 IP (핫스팟 주소). 예: 192.168.137.42")
    ap.add_argument("--port", type=int, default=8080, help="폰 Ktor 서버 포트")
    ap.add_argument("--timeout", type=float, default=2.0, help="전송 타임아웃(초)")
    ap.add_argument("--no-send", action="store_true",
                    help="전송하지 않고 화면 출력만 (마이크·모델 점검용)")
    ap.add_argument("--doa-model", default=None, help="doa_knn_model_v5.pkl 경로")
    ap.add_argument("--doa-scaler", default=None, help="doa_scaler.pkl 경로")
    ap.add_argument("--no-doa", action="store_true", help="방향 추정을 끄고 -1로 보냄")
    args = ap.parse_args()

    det = Detector()

    # 방향 추정은 4채널 어레이에서만 의미가 있다 (v5 피처가 4채널 전제)
    doa_path = None
    if not args.no_doa and args.channels == 4:
        doa_path = load_doa(args.doa_model, args.doa_scaler)
    elif not args.no_doa and args.channels != 4:
        print("[DoA] --channels 가 4가 아니라 방향 추정을 건너뜁니다 (-1로 전송)")

    # 모델이 내는 클래스인데 위험도 표에 없으면 조용히 안 나가므로 미리 알린다
    missing = [det.name(c) for c in sorted(det.minority) if det.name(c) not in DANGER]
    if missing:
        print("경고: 위험도 미지정 클래스 → 알림이 전송되지 않습니다: %s" % ", ".join(missing))

    if abs(args.hop - TUNE_HOP) > 1e-6:
        print("경고: --hop %.2f 는 임계값을 정할 때 쓴 %.2f 초와 다릅니다."
              % (args.hop, TUNE_HOP))
        print("      연속 조건이 요구하는 지속시간이 %.2f배가 되어 알림이 그만큼 늦어집니다."
              % (args.hop / TUNE_HOP))

    print("=" * 62)
    print(" Grabbit 소리 감지")
    print("=" * 62)
    print(" 클래스 : %s" % ", ".join(det.name(c) for c in sorted(det.minority)))
    print(" 임계값 : %s" % ", ".join(
        "%s %.2f" % (det.name(c), det.thresholds[c]) for c in sorted(det.minority)))
    print(" 연속   : %s" % ", ".join(
        "%s %d회" % (det.name(c), det.consecutive[c]) for c in sorted(det.minority)))
    # "연속 N회"가 실제로 요구하는 지속시간 — hop 에 따라 달라지므로 같이 보여준다
    print(" 지속   : %s" % ", ".join(
        "%s %.2f초" % (det.name(c), det.consecutive[c] * args.hop)
        for c in sorted(det.minority)))
    print(" 오디오 : %dHz / %d초 창 / %.2f초 간격 / %d채널"
          % (det.sr, det.clip_len // det.sr, args.hop, args.channels))
    print(" 방향   : %s" % ("v5 모델 (%s)" % doa_path if doa_path
                           else "사용 안 함 (-1로 전송)"))
    print(" 전송   : %s" % ("(안 함 — --no-send)" if args.no_send
                           else "http://%s:%d/alert" % (args.host, args.port)))
    print("\n 듣는 중... (Ctrl+C 로 종료)\n")

    sender = None if args.no_send else AlertSender(args.host, args.port, args.timeout)
    mic = open_mic(args.device, det.sr, args.channels)
    mic_err = drain_stderr(mic)

    buf = np.zeros(det.clip_len, dtype=np.float32)
    hop_frames = int(args.hop * det.sr)
    bytes_per_frame = 2 * args.channels
    need = hop_frames * bytes_per_frame

    # 방향 추정용: 분류와 같은 5초 구간의 채널별 원본(int16)을 그대로 들고 있는다.
    # 분류 버퍼는 모노로 평균내고 음량 정규화까지 거쳐서 채널 간 차이가 사라진다
    raw_buf = (np.zeros((det.clip_len, args.channels), dtype=np.int16)
               if args.channels > 1 else None)

    n_alert, n_win, t_start = 0, 0, time.time()
    n_slow, t_proc = 0, 0.0

    try:
        while True:
            raw = read_exact(mic.stdout, need)
            if raw is None:
                mic.terminate()
                try:                          # 마지막 stderr 가 도착할 짬을 준다
                    mic.wait(timeout=1.0)
                except Exception:
                    pass
                sys.exit("녹음이 끊겼습니다.\n%s\n장치 이름을 확인하세요 (arecord -l)"
                         % "\n".join(mic_err))

            samples = np.frombuffer(raw, dtype=np.int16)

            if args.channels > 1:
                frames = samples.reshape(-1, args.channels)
                raw_buf = np.concatenate([raw_buf[len(frames):], frames])
                chunk = frames.astype(np.float32).mean(axis=1) / 32768.0
            else:
                chunk = samples.astype(np.float32) / 32768.0

            # 5초 버퍼를 굴린다
            buf = np.concatenate([buf[len(chunk):], chunk])

            t0 = time.perf_counter()
            cls, conf, probs = det.predict(buf)
            proc = time.perf_counter() - t0

            now = time.time()
            n_win += 1
            t_proc += proc

            # 처리가 간격보다 오래 걸리면 파이프에 오디오가 쌓여 판정이 실시간에서
            # 점점 뒤처진다. 조용히 늦어지는 게 제일 나쁘므로 눈에 보이게 알린다
            if proc > args.hop:
                n_slow += 1
                if n_slow in (1, 10, 100) or n_slow % 1000 == 0:
                    print("  [경고] 처리 %.0fms > 간격 %.0fms — 오디오가 밀립니다 "
                          "(%d회째). --hop 을 늘리세요"
                          % (proc * 1000, args.hop * 1000, n_slow), flush=True)

            if args.verbose:
                print("  %s  %-16s %.3f   [%s]" % (
                    time.strftime("%H:%M:%S"), det.name(cls), conf,
                    " ".join("%s %.2f" % (det.name(i)[:5], p)
                             for i, p in enumerate(probs))), flush=True)

            if det.should_alert(cls, conf, now, args.cooldown):
                n_alert += 1
                on_alert(det.name(cls), conf, now, sender,
                         estimate_direction(raw_buf))

    except KeyboardInterrupt:
        el = (time.time() - t_start) / 3600
        print("\n\n종료. %.2f시간 동안 판정 %d회 / 알림 %d회 (시간당 %.1f회)"
              % (el, n_win, n_alert, n_alert / el if el > 0 else 0))
        if n_win:
            print("처리 시간 평균 %.0fms (간격 %.0fms) / 간격 초과 %d회"
                  % (t_proc / n_win * 1000, args.hop * 1000, n_slow))
        if sender is not None:
            print("전송 성공 %d회 / 실패 %d회" % (sender.n_ok, sender.n_fail))
    finally:
        mic.terminate()
        if sender is not None:
            sender.close()


if __name__ == "__main__":
    main()
