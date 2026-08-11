"""
스피커 재생용 위험음 클립을 골라 realworld/playback/ 에 모은다

record_events.py 로 실환경 감지율을 잴 때, 노크를 뺀 나머지는 스피커로 소리를
틀어야 한다. 이때 아무 클립이나 쓰면 "모델이 못 잡은 건지, 원본이 애매한
소리였는지" 구분이 안 된다. 그래서 **배포 모델이 이미 확실하게 맞히는 클립**만
고른다. 이러면 실환경에서 놓쳤을 때 원인이 마이크·거리·잡음이라고 말할 수 있다.

고르는 기준
  1. 배포 모델(export/grabbit_model.npz) 확신도가 높은 순
  2. 클래스당 group(원본 녹음/업로더)이 겹치지 않게 → 5개가 서로 다른 소리
     같은 업로더의 비슷한 클립 5개를 쓰면 5회 측정이 1회나 마찬가지가 된다
  3. 실제로 '틀 수 있는' 클립만 (아래 MAX_SEC / MIN_RMS)

선행 조건: build_dataset.py → build_embeddings.py → export_model.py 순으로 실행되어
samples.csv / yamnet_frames.npy / grabbit_model.npz 가 있어야 한다.

    python data/build_playback.py
"""
import csv
import os
import shutil
import sys

import numpy as np
import soundfile as sf

# core/ 의 공용 모듈(features, config, cnn, utils)을 찾기 위한 경로 설정
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "core"))

import config
import features as F

sys.stdout.reconfigure(encoding="utf-8")

SAMPLES_CSV = os.path.join(config.MFCC_PATH, "samples.csv")
FRAMES_NPY = os.path.join(config.MFCC_PATH, "yamnet_frames.npy")
MODEL_NPZ = os.path.join(_ROOT, "export", "grabbit_model.npz")
OUT_DIR = os.path.join(config.REALWORLD_PATH, "playback")
LIST_CSV = os.path.join(OUT_DIR, "목록.csv")

PER_CLASS = 5      # 클래스당 클립 수 (record_events.py 가 거리별 5회씩 안내)

# record_events.py 의 DURATION(8초) 안에 소리가 다 들어가야 한다.
# 20초짜리를 틀면 녹음이 끊긴 뒤에도 소리가 계속돼 몇 번째 소리를 잰 건지 모르게 된다.
MAX_SEC = 8.0

# 너무 조용한 원본은 제외. 모델은 음량을 정규화해서 듣지만 스피커는 아니라,
# rms 0.005 짜리를 5m에서 틀면 사람 귀에도 안 들린다.
# 그런 클립으로 잰 감지율은 모델이 아니라 스피커를 잰 것이다.
MIN_RMS = 0.02

# 파일명에 쓸 짧은 이름. record_events.py 의 메뉴 이름과 같아야 한다
# (녹음 파일명이 `siren_3m_01.wav` 형식이라 분석 스크립트가 여기서 클래스를 읽는다).
SHORT_NAME = {
    "glass_breaking": "glass",
    "siren": "siren",
    "door_wood_knock": "knock",
    "doorbell": "doorbell",
}


def load_rows():
    with open(SAMPLES_CSV, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def classify(emb, z):
    """임베딩 (T,1024) → 클래스 확률. export/grabbit.py 의 classify 와 동일한 계산."""
    x = (emb - z["emb_mean"]) / z["emb_std"]

    # YamnetHead 와 동일: 프레임 평균과 최댓값을 이어붙임
    feat = np.concatenate([x.mean(axis=0), x.max(axis=0)])

    n = int(z["n_models"])
    eps = float(z["bn_eps"])
    probs = np.zeros(len(z["class_names"]), dtype=np.float64)

    for i in range(n):
        h = feat
        # BatchNorm1d (추론 모드)
        h = (h - z["m%d_bn_mean" % i]) / np.sqrt(z["m%d_bn_var" % i] + eps)
        h = h * z["m%d_bn_w" % i] + z["m%d_bn_b" % i]

        h = z["m%d_fc1_w" % i] @ h + z["m%d_fc1_b" % i]
        h = np.maximum(h, 0.0)                  # ReLU (Dropout 은 추론 시 없음)
        h = z["m%d_fc2_w" % i] @ h + z["m%d_fc2_b" % i]

        e = np.exp(h - h.max())
        probs += e / e.sum()

    return probs / n


def origin_id(path):
    """세 데이터셋을 관통하는 Freesound 원본 ID.

    samples.csv 의 group 은 데이터셋 안에서만 유효해서, 같은 Freesound 녹음이
    ESC-50 과 UrbanSound8K 에 각각 들어있으면 서로 다른 클립으로 보인다
    (`4-111671-B-42.wav` 와 `111671-8-0-6.wav` 는 같은 소리다).
    파일명 맨 앞 숫자가 세 데이터셋 모두 Freesound ID 라 이걸 키로 쓴다.
      ESC-50       {fold}-{ID}-{take}-{target}.wav → 두 번째 칸
      UrbanSound8K {ID}-{class}-{occ}-{slice}.wav  → 첫 칸
      FSD50K       {ID}.wav                        → 파일명 그대로
    """
    stem = os.path.splitext(os.path.basename(path.replace("\\", "/")))[0]
    parts = stem.split("-")
    if len(parts) == 4 and parts[0].isdigit() and parts[2].isalpha():
        return parts[1]          # ESC-50
    return parts[0]              # UrbanSound8K / FSD50K


def playable(path):
    """스피커로 틀 수 있는 클립인지 (길이·음량)."""
    try:
        info = sf.info(path)
    except RuntimeError:
        return False
    if info.duration > MAX_SEC:
        return False

    y, _ = sf.read(path, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    return float(np.sqrt(np.mean(y ** 2))) >= MIN_RMS


def pick(rows, frames, z, cls, cls_idx):
    """cls 클래스에서 확신도 높은 순으로, group 이 겹치지 않게 PER_CLASS 개."""
    scored = []
    for i, r in enumerate(rows):
        if r["category"] != cls:
            continue
        if not os.path.exists(r["path"]):
            continue
        if not playable(r["path"]):
            continue
        p = classify(np.asarray(frames[i], dtype=np.float64), z)
        # 다른 클래스로 새는 클립은 재생해도 의미가 없으니 argmax 도 확인한다
        if int(np.argmax(p)) != cls_idx:
            continue
        scored.append((float(p[cls_idx]), i, r))

    scored.sort(key=lambda t: -t[0])

    chosen, seen = [], set()
    for conf, i, r in scored:
        keys = {r["group"], "origin:%s" % origin_id(r["path"])}
        if keys & seen:
            continue
        seen |= keys
        chosen.append((conf, r))
        if len(chosen) == PER_CLASS:
            break

    if len(chosen) < PER_CLASS:
        print("  [경고] %s: group 이 겹치지 않는 클립이 %d개뿐" % (cls, len(chosen)))
    return chosen


def main():
    for path in (SAMPLES_CSV, FRAMES_NPY, MODEL_NPZ):
        if not os.path.exists(path):
            print("[중단] %s 가 없습니다. GUIDE.md 의 실행 순서를 확인하세요." % path)
            return

    rows = load_rows()
    frames = np.load(FRAMES_NPY, mmap_mode="r")
    if len(frames) != len(rows):
        print("[중단] samples.csv(%d) 와 yamnet_frames.npy(%d) 개수가 다릅니다. "
              "build_embeddings.py 를 다시 실행하세요." % (len(rows), len(frames)))
        return

    z = np.load(MODEL_NPZ, allow_pickle=True)
    class_names = [str(s) for s in z["class_names"]]
    if class_names != F.CLASS_NAMES:
        print("[중단] 모델 클래스 %s 가 features.CLASS_NAMES 와 다릅니다. "
              "export_model.py 를 다시 실행하세요." % class_names)
        return

    os.makedirs(OUT_DIR, exist_ok=True)

    # 클래스가 바뀌면 예전 클립(crackling_fire 등)이 남아 실측을 오염시킨다.
    # 이 스크립트가 만든 wav 만 지우고 새로 채운다.
    for name in os.listdir(OUT_DIR):
        if name.endswith(".wav"):
            os.remove(os.path.join(OUT_DIR, name))

    records = []
    for cls in F.CLASS_NAMES:
        if cls == "others":
            continue
        cls_idx = F.CLASS_NAMES.index(cls)
        short = SHORT_NAME[cls]
        print("[%s]" % cls)

        for n, (conf, r) in enumerate(pick(rows, frames, z, cls, cls_idx), start=1):
            out_name = "%s_%02d.wav" % (short, n)
            shutil.copyfile(r["path"], os.path.join(OUT_DIR, out_name))
            records.append({
                "재생파일": out_name,
                "클래스": short,
                "번호": n,
                "원본확신도": "%.3f" % conf,
                "출처": r["source"],
                "원본파일": os.path.basename(r["path"].replace("\\", "/")),
            })
            print("  %s  확신도 %.3f  %s  %s"
                  % (out_name, conf, r["source"], records[-1]["원본파일"]))

    with open(LIST_CSV, "w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=["재생파일", "클래스", "번호",
                                           "원본확신도", "출처", "원본파일"])
        w.writeheader()
        w.writerows(records)

    print("\n총 %d개 → %s" % (len(records), OUT_DIR))


if __name__ == "__main__":
    main()
