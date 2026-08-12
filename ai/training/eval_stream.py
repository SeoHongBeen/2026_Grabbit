"""
연속 오디오에서 '시간당 오알림 수'와 '감지율'을 측정
"""
import os
import sys
import warnings

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
warnings.filterwarnings("ignore")

import csv
import numpy as np
import torch

# core/ 의 공용 모듈(features, config, cnn, utils)을 찾기 위한 경로 설정
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "core"))

import config
import features as F
from cnn import YamnetHead
from utils import map_label

if sys.platform == "win32":
    os.system("chcp 65001 > nul")

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


# ======================
# 설정
# ======================

MODEL_DIR = config.MODEL_PATH
FEATURES = "yamnet"
N_ENSEMBLE = 5

FRAME_HOP = 0.48          # YAMNet 내부 프레임 간격(초)
WIN_FRAMES = 10           # 5초 = 프레임 10개 (학습 때와 동일)
COOLDOWN_SEC = 30.0       # 알림 한 번 울리면 이 시간 동안 같은 클래스는 안 울림

STREAM_MINUTES = 60       # 합성 스트림 길이 (홀드아웃 others가 허용하는 만큼)

# 실환경 녹음 폴더. 파일이 있으면 합성 스트림 대신 이걸 쓴다.
# 합성 스트림은 후처리 튜닝용 대체물이고, 진짜 지표는 여기서 나온다.
REALWORLD_DIR = os.path.join(_ROOT,
                             "dataset", "realworld", "ambient")

# 음량 정규화는 features.py의 GAIN_NORMALIZE 하나로만 제어한다.
# 여기 따로 두면 학습과 다른 설정으로 평가하게 될 수 있다.


# ======================
# 모델
# ======================

def load_models():
    models = []
    for i in range(N_ENSEMBLE):
        p = os.path.join(MODEL_DIR, "best_model_%s_%d.pth" % (FEATURES, i))
        if not os.path.exists(p):
            break
        m = YamnetHead(num_classes=config.NUM_CLASSES)
        m.load_state_dict(torch.load(p, map_location="cpu"))
        m.eval()
        models.append(m)

    if not models:   # 앙상블 없이 단일 모델만 있는 경우
        m = YamnetHead(num_classes=config.NUM_CLASSES)
        m.load_state_dict(torch.load(
            os.path.join(MODEL_DIR, "best_model_%s.pth" % FEATURES), map_location="cpu"))
        m.eval()
        models.append(m)

    return models


# ======================
# 스트림 만들기
# ======================

def build_stream(paths, minutes):
    """오디오들을 이어붙여 연속 파형 하나로 (16kHz)."""
    target = int(minutes * 60 * F.YAMNET_SR)
    chunks, total = [], 0

    for p in paths:
        y = F.load_for_yamnet(p)
        if y is None:
            continue
        chunks.append(y)
        total += len(y)
        if total >= target:
            break

    return np.concatenate(chunks)[:target] if chunks else np.zeros(0, np.float32)


def load_realworld():
    """실환경 녹음을 하나의 연속 파형으로 (16kHz 모노).

    마이크 어레이라 채널이 여러 개면 평균내어 모노로 만든다
    (학습 데이터 처리와 동일).
    """
    import glob
    import librosa
    import soundfile as sf

    files = sorted(glob.glob(os.path.join(REALWORLD_DIR, "*.wav")))
    if not files:
        return None

    print("실환경 녹음 %d개" % len(files))
    out = []
    for f in files:
        y, sr = sf.read(f)
        if y.ndim > 1:
            y = y.mean(axis=1)
        if sr != F.YAMNET_SR:
            y = librosa.resample(y.astype(np.float32), orig_sr=sr, target_sr=F.YAMNET_SR)
        out.append(y.astype(np.float32))
        print("  %-38s %5.1f분  RMS %.4f"
              % (os.path.basename(f), len(y) / F.YAMNET_SR / 60,
                 float(np.sqrt(np.mean(y ** 2)))), flush=True)

    # 음량 정규화는 여기서 하지 않는다.
    # 스트림 전체를 한 번에 맞추면 RPi 동작(5초 버퍼마다 정규화)과 달라지므로,
    # window_probs_normalized()가 윈도우 단위로 처리한다.
    return np.concatenate(out)


def frame_embeddings(wave, chunk_sec=300):
    """긴 파형을 YAMNet에 통과시켜 프레임별 임베딩 (T, 1024).

    한 번에 넣으면 메모리를 많이 쓰므로 나눠서 처리한다.
    """
    import tensorflow_hub as hub
    model = hub.load(F.YAMNET_URL)

    out = []
    step = int(chunk_sec * F.YAMNET_SR)
    for s in range(0, len(wave), step):
        piece = wave[s:s + step]
        if len(piece) < F.YAMNET_SR:      # 1초 미만 자투리는 버림
            break
        _, emb, _ = model(piece)
        out.append(np.asarray(emb, dtype=np.float32))
        print("  임베딩 %.0f분 / %.0f분" % ((s + len(piece)) / F.YAMNET_SR / 60,
                                            len(wave) / F.YAMNET_SR / 60), flush=True)

    return np.concatenate(out) if out else np.zeros((0, 1024), np.float32)


def window_probs_normalized(wave, models, mean, std, hop_sec=FRAME_HOP):
    """윈도우마다 따로 음량 정규화 → YAMNet → 분류기.

    RPi는 5초 버퍼를 받아 정규화하고 추론한다. 스트림 전체를 한 번에 정규화하면
    그 동작과 달라지므로, 느리더라도 윈도우 단위로 처리해 배포와 일치시킨다.
    """
    import tensorflow_hub as hub
    yam = hub.load(F.YAMNET_URL)

    win = int(F.CLIP_SEC * F.YAMNET_SR)
    hop = int(hop_sec * F.YAMNET_SR)
    starts = range(0, max(0, len(wave) - win + 1), hop)

    embs = []
    for n, s in enumerate(starts):
        piece = F.normalize_gain(wave[s:s + win]) if F.GAIN_NORMALIZE else wave[s:s + win]
        _, e, _ = yam(piece)
        embs.append(np.asarray(e, dtype=np.float32)[:WIN_FRAMES])
        if n % 500 == 0:
            print("  윈도우 %d / %d" % (n, len(starts)), flush=True)

    if not embs:
        return np.zeros((0, config.NUM_CLASSES))

    x = torch.tensor((np.stack(embs) - mean) / std, dtype=torch.float32)
    out = []
    with torch.no_grad():
        for i in range(0, len(x), 512):
            b = x[i:i + 512]
            out.append(np.mean([torch.softmax(m(b), dim=1).numpy() for m in models], axis=0))

    return np.concatenate(out)


def window_probs(frames, models, mean, std):
    """프레임 열 → 5초 윈도우별 확률. 윈도우는 프레임 1개씩 밀며 만든다."""
    if len(frames) < WIN_FRAMES:
        return np.zeros((0, config.NUM_CLASSES))

    # (T-9, 10, 1024) 슬라이딩 뷰
    wins = np.lib.stride_tricks.sliding_window_view(frames, WIN_FRAMES, axis=0)
    wins = np.transpose(wins, (0, 2, 1))
    wins = (wins - mean) / std

    x = torch.tensor(wins, dtype=torch.float32)
    probs = []
    with torch.no_grad():
        for i in range(0, len(x), 512):
            batch = x[i:i + 512]
            p = np.mean([torch.softmax(m(batch), dim=1).numpy() for m in models], axis=0)
            probs.append(p)

    return np.concatenate(probs)


# ======================
# 후처리 규칙 → 알림 사건
# ======================

def to_events(probs, thresholds, consecutive, cooldown_sec, hop=FRAME_HOP):
    """윈도우 확률 → 알림 사건 목록 [(시각초, 클래스)].

    consecutive: 같은 클래스가 몇 번 연속 나와야 알림을 울릴지.
      사이렌처럼 오래 지속되는 소리는 높여도 감지가 거의 안 줄지만,
      유리 깨짐·노크·초인종은 1~2윈도우만 나타나므로 높이면 recall이 무너진다.
      그래서 클래스별로 다르게 준다 (배열).
    """
    pred = probs.argmax(1)
    conf = probs.max(1)

    # 임계값 미달인 소리 예측은 others로 강등
    thr = np.array([thresholds[p] for p in pred])
    fired = np.isin(pred, F.MINORITY) & (conf >= thr)
    cls = np.where(fired, pred, F.OTHERS)

    need = np.asarray(consecutive)
    run_cls, run_len = -1, 0
    last_alert = {}
    events = []

    for i, c in enumerate(cls):
        if c == run_cls:
            run_len += 1
        else:
            run_cls, run_len = c, 1

        if c == F.OTHERS or run_len < need[c]:
            continue

        t = i * hop
        if t - last_alert.get(c, -1e9) < cooldown_sec:
            continue

        last_alert[c] = t
        events.append((t, int(c)))

    return events


# ======================
# 실행
# ======================

def main():
    rows = list(csv.DictReader(open(os.path.join(config.MFCC_PATH, "samples.csv"),
                                    encoding="utf-8")))
    test_idx = set(np.load(os.path.join(config.MFCC_PATH, "test_indices.npy")).tolist())

    # 홀드아웃 others만 사용 (학습에 안 쓴 데이터)
    others = [r["path"] for r in rows
              if int(r["index"]) in test_idx and r["category"] == "others"]
    rng = np.random.default_rng(42)
    rng.shuffle(others)
    print("홀드아웃 others %d개로 스트림 구성" % len(others))

    models = load_models()
    mean, std = F.load_norm(config.MFCC_PATH, FEATURES)
    thresholds = F.load_thresholds(config.MFCC_PATH, FEATURES)

    # 윈도우 확률을 캐시한다. YAMNet을 1시간치 돌리는 게 제일 오래 걸리는데,
    # 임계값·규칙만 바꿔가며 볼 때는 매번 다시 할 필요가 없다.
    real = load_realworld()
    tag = "real" if real is not None else "synth"
    if F.GAIN_NORMALIZE:
        tag += "_gain"

    cache = os.path.join(config.MFCC_PATH, "stream_probs_%s_%s.npz" % (FEATURES, tag))
    if os.path.exists(cache):
        z = np.load(cache)
        probs, dur_hr = z["probs"], float(z["dur_hr"])
        print("캐시 사용: %s (%.2f시간)\n" % (os.path.basename(cache), dur_hr))
    else:
        wave = real if real is not None else build_stream(others, STREAM_MINUTES)
        dur_hr = len(wave) / F.YAMNET_SR / 3600
        print("\n%s 스트림 %.2f시간\n" % ("실환경" if real is not None else "합성", dur_hr))

        if F.GAIN_NORMALIZE:
            # 윈도우마다 정규화해야 하므로 YAMNet을 윈도우 단위로 돌린다 (느림)
            print("윈도우별 정규화 + 추론 중...")
            probs = window_probs_normalized(wave, models, mean, std)
        else:
            print("YAMNet 임베딩 추출 중...")
            frames = frame_embeddings(wave)
            print("프레임 %d개\n" % len(frames))
            probs = window_probs(frames, models, mean, std)

        np.savez(cache, probs=probs, dur_hr=dur_hr)
        print("윈도우 확률 캐시 저장: %s" % cache)

    print("모델 %d개 / 임계값 %s" % (len(models), np.round(thresholds[:len(F.MINORITY)], 2)))
    print("윈도우 %d개 (%.2f초 간격)\n" % (len(probs), FRAME_HOP))

    # 후처리 없이 = 윈도우마다 바로 알림
    raw = to_events(probs, thresholds, [1] * config.NUM_CLASSES, cooldown_sec=0.0)
    print("=" * 74)
    print("후처리 없음: 오알림 %d회 → 시간당 %.0f회" % (len(raw), len(raw) / dur_hr))
    print("=" * 74)

    print("\n연속 조건별 시간당 오알림 (쿨다운 %.0f초 적용)" % COOLDOWN_SEC)
    print("%-30s %10s %14s" % ("규칙", "총 오알림", "시간당"))

    rules = {
        "전 클래스 1회 (쿨다운만)":      [1, 1, 1, 1, 1],
        "전 클래스 2회 연속":            [2, 2, 2, 2, 1],
        "전 클래스 3회 연속":            [3, 3, 3, 3, 1],
        "사이렌만 3회, 나머지 1회":      [1, 3, 1, 1, 1],
        "사이렌만 4회, 나머지 2회":      [2, 4, 2, 2, 1],
        "사이렌만 6회, 나머지 2회":      [2, 6, 2, 2, 1],
    }

    for name, need in rules.items():
        ev = to_events(probs, thresholds, need, COOLDOWN_SEC)
        print("%-30s %10d %14.1f" % (name, len(ev), len(ev) / dur_hr))

    # 어떤 클래스가 헛울리는지
    ev = to_events(probs, thresholds, [3, 1, 3, 1, 1], COOLDOWN_SEC)
    if ev:
        import collections
        c = collections.Counter(F.CLASS_NAMES[k] for _, k in ev)
        print("\n오알림 클래스 분포 (사이렌 3회 규칙):", dict(c))

    # ======================
    # 임계값을 '시간당 오알림' 기준으로 다시 잡기
    # ======================
    # 지금 임계값은 클립 단위 오탐 2% 예산으로 정해졌다. 그 기준으로는
    # 유리·사이렌·노크가 예산 안에 들어와 임계값 0이 됐지만,
    # 시간당으로 환산하면 전혀 다른 얘기가 된다. 사용자가 체감하는 단위로 다시 잡는다.
    print("\n" + "=" * 74)
    print("임계값별 [시간당 오알림] vs [클립 단위 소리 recall]")
    print("=" * 74)

    # 클립 단위 recall은 홀드아웃에서 계산 (같은 앙상블 사용)
    Xc = np.load(os.path.join(config.MFCC_PATH, "yamnet_frames.npy"))
    yc = np.array([map_label(v) for v in
                   np.load(os.path.join(config.MFCC_PATH, "labels.npy"))])
    idx = np.load(os.path.join(config.MFCC_PATH, "test_indices.npy"))
    xc = torch.tensor((Xc[idx] - mean) / std, dtype=torch.float32)

    with torch.no_grad():
        clip_prob = np.mean([torch.softmax(m(xc), dim=1).numpy() for m in models], axis=0)
    y_clip = yc[idx]

    from sklearn.metrics import recall_score

    RULE = [2, 4, 2, 2, 1]   # 사이렌 4회, 유리·노크·초인종 2회
    print("규칙: 사이렌 %d회 연속, 유리·노크·초인종 %d회 연속, 쿨다운 %.0f초\n"
          % (RULE[1], RULE[0], COOLDOWN_SEC))
    print("%8s %14s %16s %s" % ("임계값", "시간당 오알림", "소리recall", "클래스별 recall"))

    for thr in [0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99]:
        t = np.full(config.NUM_CLASSES, thr)
        t[F.OTHERS] = 0.0
        ev = to_events(probs, t, RULE, COOLDOWN_SEC)

        cp = clip_prob.argmax(1)
        cc = cp.copy()
        cc[np.isin(cp, F.MINORITY) & (clip_prob.max(1) < thr)] = F.OTHERS
        rec = recall_score(y_clip, cc, labels=F.MINORITY, average="macro", zero_division=0)
        per = [recall_score(y_clip, cc, labels=[c], average="macro", zero_division=0)
               for c in F.MINORITY]

        print("%8.2f %14.1f %16.3f  %s" % (
            thr, len(ev) / dur_hr, rec,
            " ".join("%s %.2f" % (F.CLASS_NAMES[c][:5], per[i]) for i, c in enumerate(F.MINORITY))))

    # ======================
    # 클래스별로 '시간당 예산'을 나눠서 임계값 선정
    # ======================
    # 클래스마다 난이도가 크게 다르다. 사이렌은 임계값을 아무리 올려도 recall이
    # 잘 안 떨어지지만 불은 금방 무너진다. 하나의 임계값을 공유하면 사이렌의
    # 여유를 쓰지 못한다. 클래스마다 따로 "이 예산 안에 드는 가장 낮은 임계값"을 찾는다.
    print("\n" + "=" * 74)
    print("클래스별 시간당 예산으로 임계값 선정")
    print("=" * 74)

    for budget in [0.5, 1.0, 2.0]:
        grid = np.round(np.arange(0.30, 0.999, 0.01), 3)
        chosen = np.zeros(config.NUM_CLASSES)
        lines = []

        for c in F.MINORITY:
            pick, rate = 0.999, 0.0
            for thr in grid:
                # 이 클래스만 켜고 나머지는 절대 안 울리게 해서 따로 측정
                t = np.full(config.NUM_CLASSES, 1.1)
                t[c] = thr
                ev = to_events(probs, t, RULE, COOLDOWN_SEC)
                r = len(ev) / dur_hr
                if r <= budget:
                    pick, rate = float(thr), r
                    break

            chosen[c] = pick
            cp = clip_prob.argmax(1)
            cc = cp.copy()
            cc[np.isin(cp, F.MINORITY) & (clip_prob.max(1) < pick)] = F.OTHERS
            rec_c = recall_score(y_clip, cc, labels=[c], average="macro", zero_division=0)
            lines.append((F.CLASS_NAMES[c], pick, rate, rec_c))

        ev_all = to_events(probs, chosen, RULE, COOLDOWN_SEC)
        cp = clip_prob.argmax(1)
        cc = cp.copy()
        thr_of = np.array([chosen[p] if p in F.MINORITY else 0.0 for p in cp])
        cc[np.isin(cp, F.MINORITY) & (clip_prob.max(1) < thr_of)] = F.OTHERS
        rec_all = recall_score(y_clip, cc, labels=F.MINORITY, average="macro", zero_division=0)

        print("\n[클래스당 시간당 %.1f회 예산]  → 전체 시간당 %.1f회 / 소리recall %.3f"
              % (budget, len(ev_all) / dur_hr, rec_all))
        print("  %-16s %8s %12s %10s" % ("클래스", "임계값", "시간당", "recall"))
        for name, thr, rate, rec_c in lines:
            print("  %-16s %8.2f %12.1f %10.3f" % (name, thr, rate, rec_c))

        np.save(os.path.join(config.MFCC_PATH, "thresholds_stream_%.1f.npy" % budget), chosen)


if __name__ == "__main__":
    main()
