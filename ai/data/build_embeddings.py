"""
samples.csv의 모든 오디오에서 YAMNet 임베딩을 뽑아 저장

YAMNet: AudioSet 521개 클래스로 사전학습된 모델
Fire / Glass / Shatter / Siren / Knock 포함
마지막 분류층 대신 1024차원 임베딩을 꺼내 쓰면, 클래스당 수백 개짜리 데이터로도 학습 가능

5초 오디오 하나 → (10, 1024), 프레임을 평균내지 않고 그대로 저장
집계 방식은 학습 단계에서 선택

출력 순서는 samples.csv의 index와 정확히 일치
"""
import os
import sys
import warnings

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
warnings.filterwarnings("ignore")

import csv
import time

import numpy as np
from tqdm import tqdm

# core/ 의 공용 모듈(features, config, cnn, utils)을 찾기 위한 경로 설정
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "core"))

import config
import features as F

if sys.platform == "win32":
    os.system("chcp 65001 > nul")

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import tensorflow as tf
import tensorflow_hub as hub

YAMNET_URL = "https://tfhub.dev/google/yamnet/1"
SAMPLES_CSV = os.path.join(config.MFCC_PATH, "samples.csv")
OUT_PATH = os.path.join(config.MFCC_PATH, "yamnet_frames.npy")
AUG_PATH = os.path.join(config.MFCC_PATH, "yamnet_frames_aug.npz")

# 클래스별 파형 증강 배수. 데이터가 부족한 클래스만 늘린다.
#
# 왜 파형 단계인가:
#   train.py의 증강은 이미 뽑은 임베딩에 잡음을 더하는 방식인데, 임베딩은
#   추상화된 벡터라 "3m 떨어져서 들리면 어떤 값이 되는지"를 만들어낼 수 없다.
#   파형을 바꾼 뒤 YAMNet을 다시 통과시켜야 진짜 다양성이 생긴다.
# 실험 결과: doorbell 4배 증강은 역효과였다.
#   recall은 0.741 그대로인데 precision이 0.909 → 0.690으로 무너졌고,
#   증강하지 않은 유리·노크의 precision까지 같이 떨어졌다 (전체 오탐율 0.035 → 0.059).
#
# 원인 둘:
#   1. SNR 5~20dB는 너무 가혹하다. 5dB면 소음이 신호의 절반 크기인데
#      음량 정규화까지 걸리면 '소음 덩어리'가 doorbell로 학습된다.
#   2. 133 → 557개로 4배가 되며 클래스 균형이 틀어져,
#      모델이 소리 클래스 전반을 더 적극적으로 예측하게 됐다.
#
# 다시 시도한다면 SNR을 15~30dB로 낮추고 배수도 2배부터 시작할 것.
AUG_PER_CLASS = {}

# 배경 소음으로 섞을 실환경 녹음. 학습 데이터는 전부 조용한 스튜디오 녹음인데
# 실제로는 에어컨·냉장고 소리에 묻혀 들리므로, 그 조건을 만들어준다.
AMBIENT_DIR = os.path.join(_ROOT,
                           "dataset", "realworld", "ambient")


def load_ambient_pool(max_sec=600):
    """실환경 녹음을 16kHz 모노로 이어붙인 배경 소음 풀."""
    import glob
    import librosa
    import soundfile as sf

    files = sorted(glob.glob(os.path.join(AMBIENT_DIR, "*.wav")))
    if not files:
        print("[안내] 실환경 녹음이 없어 배경 소음 섞기는 건너뜁니다")
        return None

    out, total = [], 0
    for f in files:
        y, sr = sf.read(f)
        if y.ndim > 1:
            y = y.mean(axis=1)
        if sr != F.YAMNET_SR:
            y = librosa.resample(y.astype(np.float32), orig_sr=sr, target_sr=F.YAMNET_SR)
        out.append(y.astype(np.float32))
        total += len(y)
        if total >= max_sec * F.YAMNET_SR:
            break

    pool = np.concatenate(out)
    print("배경 소음 풀 %.1f분" % (len(pool) / F.YAMNET_SR / 60))
    return pool


def augment_wave(y, rng, ambient=None):
    """5초 파형에 실제로 일어날 법한 변형을 준다.

    - 배경 소음 섞기: 실환경에서는 소리가 항상 잡음에 묻혀 들린다
    - 시간 이동:     소리가 5초 창의 어디에 놓일지는 매번 다르다
    - 음높이 변경:   초인종 기종마다 음이 다르다
    """
    import librosa

    y = y.copy()

    # 시간 이동 (원형 회전 — 소리가 잘리지 않음)
    y = np.roll(y, rng.integers(-len(y) // 4, len(y) // 4))

    # 음높이 ±2 반음
    st = float(rng.uniform(-2, 2))
    if abs(st) > 0.2:
        y = librosa.effects.pitch_shift(y, sr=F.YAMNET_SR, n_steps=st)

    # 배경 소음을 SNR 5~20dB로 섞기
    if ambient is not None and len(ambient) > len(y):
        s = int(rng.integers(0, len(ambient) - len(y)))
        noise = ambient[s:s + len(y)]

        sig_rms = float(np.sqrt(np.mean(y ** 2)))
        noise_rms = float(np.sqrt(np.mean(noise ** 2)))
        if noise_rms > 1e-8 and sig_rms > 1e-8:
            snr_db = float(rng.uniform(5, 20))
            target_noise = sig_rms / (10 ** (snr_db / 20))
            y = y + noise * (target_noise / noise_rms)

    return np.clip(y, -1.0, 1.0).astype(np.float32)


def build_augmented(rows, model, ambient):
    """증강 대상 클래스만 추가 임베딩 생성.

    그룹 키를 원본과 똑같이 유지한다. 그래야 train.py가 '이 증강본이 어느
    원본에서 나왔는지' 알고, 원본이 test로 가면 증강본도 학습에서 빠진다.
    """
    if not AUG_PER_CLASS:
        return None

    targets = [r for r in rows if r["category"] in AUG_PER_CLASS]
    if not targets:
        return None

    total = sum(AUG_PER_CLASS[r["category"]] for r in targets)
    print("\n파형 증강: %d개 원본 → %d개 추가 생성" % (len(targets), total))

    rng = np.random.default_rng(42)
    embs, labels, groups, sources = [], [], [], []

    for r in tqdm(targets, ncols=88, ascii=True):
        base = F.load_5sec(r["path"], target_sr=F.YAMNET_SR)
        if base is None:
            continue

        for _ in range(AUG_PER_CLASS[r["category"]]):
            try:
                y = augment_wave(base, rng, ambient)
                y = F.normalize_gain(y) if F.GAIN_NORMALIZE else y
                _, e, _ = model(y)
                embs.append(np.asarray(e, dtype=np.float32))
                labels.append(r["category"])
                groups.append(r["group"])
                sources.append(r["source"])
            except Exception:
                continue

    if not embs:
        return None

    return (np.stack(embs), np.array(labels), np.array(groups), np.array(sources))


def main():
    rows = list(csv.DictReader(open(SAMPLES_CSV, encoding="utf-8")))
    print("샘플 %d개" % len(rows))

    print("YAMNet 로드 중...")
    t0 = time.time()
    model = hub.load(YAMNET_URL)
    print("  %.1f초" % (time.time() - t0))

    embeddings = []
    failed = []

    for r in tqdm(rows, ncols=88, ascii=True):
        try:
            wave = F.load_for_yamnet(r["path"])
            if wave is None:
                raise ValueError("너무 짧음")
            _, emb, _ = model(wave)
            embeddings.append(np.asarray(emb, dtype=np.float32))
        except Exception as e:
            # samples.csv는 build_dataset.py가 이미 걸러낸 목록이라 여기서 실패하면 이상 신호.
            # 순서를 유지해야 하므로 0으로 채우고 나중에 보고한다.
            failed.append((r["index"], r["path"], str(e)))
            embeddings.append(None)

    # 프레임 수가 다르면 이후 처리가 어긋나므로 확인
    shapes = {e.shape for e in embeddings if e is not None}
    print("\n임베딩 형태:", shapes)
    if len(shapes) != 1:
        print("[경고] 프레임 수가 일정하지 않음 — 5초 고정이 깨졌는지 확인 필요")

    ref = next(e.shape for e in embeddings if e is not None)
    X = np.stack([e if e is not None else np.zeros(ref, np.float32) for e in embeddings])

    np.save(OUT_PATH, X)
    print("저장:", OUT_PATH, X.shape, "(%.0f MB)" % (X.nbytes / 1e6))

    if failed:
        print("\n실패 %d개:" % len(failed))
        for idx, path, err in failed[:10]:
            print("  %s  %s  (%s)" % (idx, os.path.basename(path), err))
    else:
        print("실패 없음")

    # 파형 증강본은 따로 저장한다.
    # 본 데이터에 섞으면 홀드아웃에도 들어가서 성능이 부풀려진다
    # (증강본은 학습에만 쓰여야 한다 — train.py가 그렇게 처리한다).
    ambient = load_ambient_pool()
    aug = build_augmented(rows, model, ambient)

    if aug is not None:
        Xa, ya, ga, sa = aug
        np.savez(AUG_PATH, X=Xa, y=ya, groups=ga, sources=sa)
        print("증강 저장:", AUG_PATH, Xa.shape, "(%.0f MB)" % (Xa.nbytes / 1e6))
        import collections
        print("  구성:", dict(collections.Counter(ya.tolist())))
    elif os.path.exists(AUG_PATH):
        os.remove(AUG_PATH)
        print("증강 대상이 없어 기존 증강 파일을 삭제했습니다")


if __name__ == "__main__":
    main()
