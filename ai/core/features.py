"""
오디오 → 모델 입력(MFCC) 변환

학습(build_dataset.py) / 평가(test.py) / 배포(export/predict.py)가 모두 여기를 사용
전처리가 한 곳이라도 어긋나면 모델은 학습 때와 다른 입력을 받게 되고,
그 사실이 실제 기기에서 성능이 무너질 때까지 드러나지 않음
"""
import os

os.environ.setdefault("NUMBA_CACHE_DISABLE", "1")
os.environ.setdefault("LIBROSA_CACHE_DIR", "")

import librosa
import numpy as np
import soundfile as sf

# ======================
# 클래스 정의
# ======================

# crackling_fire는 제외했다.
#   - FSD50K의 'Fire' 라벨이 가스레인지·토치·담배까지 포함하는 넓은 범주라
#     "타닥거리는 화재"만 골라낼 방법이 없었다 (라벨·제목·오디오 지표 모두 시도)
#   - 불 소리가 광대역 잡음이라 조용한 방의 배경음과 스펙트럼이 겹친다.
#     실환경 2시간 측정에서 오알림의 99%가 불이었다
#   - 화재는 연기감지기가 주 수단이므로, 그 경보음을 잡는 방향이 더 실용적이다
CLASS_NAMES = [
    "glass_breaking",
    "siren",
    "door_wood_knock",
    "doorbell",
    "others",
]

MINORITY = [0, 1, 2, 3]      # 알림을 보내야 하는 소리 4개
OTHERS = 4                   # 그 외 (알림 없음)


# ======================
# 오디오 규격 (학습 데이터와 반드시 일치해야 함)
# ======================

SR = 44100                # MFCC 경로 (직접 만든 CNN)
YAMNET_SR = 16000         # YAMNet이 요구하는 샘플레이트

# 음량 정규화.
#
# 학습 데이터(Freesound 녹음)는 RMS 중앙 0.065인데 실제 RPi 마이크 녹음은 0.002로
# 약 29배 작다. 같은 소리라도 음량이 이만큼 다르면 모델이 전혀 다른 조건에 놓인다.
# 학습·추론 양쪽에 똑같이 적용해야 하므로 여기 한 곳에서 처리한다.
#
# MAX_GAIN을 두는 이유: 완전한 무음 구간을 증폭하면 잡음만 키워서
# 오히려 오탐이 늘어난다. 증폭 배수에 상한을 둬서 그걸 막는다.
GAIN_NORMALIZE = True
TARGET_RMS = 0.06
MAX_GAIN = 30.0
CLIP_SEC = 5
CLIP_LEN = SR * CLIP_SEC
MIN_SEC = 1.0             # 이보다 짧으면 사용하지 않음
N_MFCC = 40
N_FRAMES = 431            # librosa 기본 hop(512) 기준 5초


def load_5sec(path_or_wave, sr=None, target_sr=SR):
    """오디오를 5초 파형으로 맞춰서 반환. 너무 짧으면 None.

    path_or_wave: 파일 경로, 또는 이미 읽은 1차원 파형(이 경우 sr 필수)
    target_sr:    출력 샘플레이트 (MFCC는 44100, YAMNet은 16000)
      - MIN_SEC 미만        → None (대부분이 0 패딩이라 학습·추론에 방해)
      - MIN_SEC ~ CLIP_SEC  → 뒤를 0으로 패딩
      - CLIP_SEC 초과       → RMS 에너지가 가장 높은 5초 구간 선택
        (앞 5초를 그냥 자르면 도입부 정적만 담길 수 있음)

    어느 샘플레이트로 뽑든 '어느 5초를 고르는가'는 동일하게 유지된다.
    """
    if isinstance(path_or_wave, (str, os.PathLike)):
        y, sr = sf.read(path_or_wave)
    else:
        y = np.asarray(path_or_wave)
        if sr is None:
            raise ValueError("파형을 직접 넘길 때는 sr을 함께 줘야 함")

    if y.ndim > 1:                      # 스테레오 → 모노
        y = np.mean(y, axis=1)

    if len(y) < sr * MIN_SEC:
        return None

    if sr != target_sr:
        y = librosa.resample(y, orig_sr=sr, target_sr=target_sr)

    clip_len = int(target_sr * CLIP_SEC)

    if len(y) < clip_len:
        y = np.pad(y, (0, clip_len - len(y)))

    elif len(y) > clip_len:
        step = target_sr // 2           # 0.5초 간격으로 탐색
        best_start, best_rms = 0, -1.0
        for s in range(0, len(y) - clip_len + 1, step):
            rms = float(np.sqrt(np.mean(y[s:s + clip_len] ** 2)))
            if rms > best_rms:
                best_rms, best_start = rms, s
        y = y[best_start:best_start + clip_len]

    return y


def normalize_gain(y, target_rms=TARGET_RMS, max_gain=MAX_GAIN):
    """파형의 음량을 목표 RMS로 맞춘다 (증폭 배수에 상한).

    마이크·거리에 따라 입력 음량이 크게 달라지는데, 모델은 학습 때 본
    음량 범위에서만 제대로 동작한다. 상한을 두는 건 무음에 가까운 구간을
    과도하게 증폭해 잡음만 키우는 걸 막기 위해서다.
    """
    y = np.asarray(y, dtype=np.float32)
    rms = float(np.sqrt(np.mean(y ** 2)))

    if rms <= 1e-8:
        return y

    gain = min(target_rms / rms, max_gain)
    return np.clip(y * gain, -1.0, 1.0).astype(np.float32)


def load_for_yamnet(path_or_wave, sr=None):
    """YAMNet 입력용 16kHz 5초 파형 (float32, -1~1)."""
    y = load_5sec(path_or_wave, sr, target_sr=YAMNET_SR)
    if y is None:
        return None

    if GAIN_NORMALIZE:
        y = normalize_gain(y)

    return y.astype(np.float32)


YAMNET_URL = "https://tfhub.dev/google/yamnet/1"
_yamnet = None


def yamnet_embed(path_or_wave, sr=None):
    """오디오 → YAMNet 임베딩 (10, 1024). 너무 짧으면 None.

    TensorFlow는 실제로 쓸 때만 불러온다 (MFCC 경로만 쓰는 코드에 부담 주지 않도록).
    """
    global _yamnet

    wave = load_for_yamnet(path_or_wave, sr)
    if wave is None:
        return None

    if _yamnet is None:
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        import tensorflow_hub as hub
        _yamnet = hub.load(YAMNET_URL)

    _, emb, _ = _yamnet(wave)
    return np.asarray(emb, dtype=np.float32)


def sustainedness(y):
    """소리가 5초 내내 이어지는 정도 (median RMS / max RMS).

    1에 가까우면 지속적(타닥거리는 불, 사이렌), 0에 가까우면 순간적(성냥 긋기, 충격음).

    FSD50K의 'Fire' 라벨에는 성냥·라이터 켜는 소리가 대량 섞여 있는데,
    제목이나 동시 라벨로는 걸러지지 않는다(다국어 제목, 66%가 Fire 단독 라벨).
    소리 자체를 재는 이 지표가 유일하게 신뢰할 수 있는 구분선이었다.
    """
    r = librosa.feature.rms(y=np.asarray(y, dtype=np.float32),
                            frame_length=2048, hop_length=1024)[0]
    return 0.0 if r.max() <= 0 else float(np.median(r) / r.max())


def to_mfcc(y):
    """5초 파형 → (N_MFCC, N_FRAMES) MFCC."""
    mfcc = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=N_MFCC)

    if mfcc.shape[1] < N_FRAMES:
        mfcc = np.pad(mfcc, ((0, 0), (0, N_FRAMES - mfcc.shape[1])))
    else:
        mfcc = mfcc[:, :N_FRAMES]

    return mfcc


def extract(path_or_wave, sr=None):
    """오디오 → MFCC 한 장. 너무 짧으면 None."""
    y = load_5sec(path_or_wave, sr)
    return None if y is None else to_mfcc(y)


# ======================
# 정규화 (train.py가 저장한 통계를 사용)
# ======================

def load_norm(mfcc_dir, feature_kind="mfcc"):
    """train.py가 저장한 특징 차원별 평균/표준편차.

    train.py의 USE_NORM이 꺼져 있으면 항등값(0, 1)이 저장돼 있어
    호출하는 쪽은 켜짐/꺼짐을 신경 쓸 필요가 없다.
    """
    mean_path = os.path.join(mfcc_dir, "norm_mean_%s.npy" % feature_kind)
    std_path = os.path.join(mfcc_dir, "norm_std_%s.npy" % feature_kind)

    if not (os.path.exists(mean_path) and os.path.exists(std_path)):
        raise FileNotFoundError(
            "%s 정규화 통계가 없음 — train.py를 FEATURES='%s'로 먼저 돌려야 함"
            % (feature_kind, feature_kind))

    return np.load(mean_path), np.load(std_path)


def apply_norm(mfcc, mean, std):
    return (mfcc - mean) / std


# ======================
# 알림 규칙
# ======================

def decide(probs, threshold):
    """확률 벡터 → (최종 클래스, 원래 예측, 확신도, 강등 여부).

    소리 클래스로 예측돼도 확신도가 임계값 미만이면 others로 강등한다(= 알림 안 함).
    학습·평가·배포가 같은 규칙을 쓰도록 여기 한 곳에 둔다.

    threshold: 숫자 하나(모든 클래스 공통) 또는 클래스별 배열.
      오탐이 몰리는 정도가 클래스마다 크게 다르므로, 하나로 맞추면
      오탐 많은 클래스에 끌려가 멀쩡한 클래스의 recall까지 깎인다.
    """
    raw = int(np.argmax(probs))
    conf = float(probs[raw])

    thr = float(threshold[raw]) if np.ndim(threshold) > 0 else float(threshold)

    if raw in MINORITY and conf < thr:
        return OTHERS, raw, conf, True

    return raw, raw, conf, False


def load_thresholds(mfcc_dir, feature_kind, fallback=0.5):
    """train.py가 고른 클래스별 임계값. 없으면 fallback 하나를 모든 클래스에 적용."""
    path = os.path.join(mfcc_dir, "thresholds_%s.npy" % feature_kind)
    if os.path.exists(path):
        return np.load(path)
    return np.full(len(CLASS_NAMES), fallback)
