"""
홀드아웃 test 샘플에서 클래스별로 랜덤 추출해 예측을 확인

전처리·클래스 정의·알림 규칙은 전부 features.py를 사용(학습과 동일 보장)
어떤 샘플이 어느 파일인지는 build_dataset.py가 만든 samples.csv로 역추적
"""
import os
import sys

import numpy as np
import pandas as pd
import torch

# core/ 의 공용 모듈(features, config, cnn, utils)을 찾기 위한 경로 설정
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "core"))

import config
import features as F
from cnn import CNN, YamnetHead
from utils import map_label

if sys.platform == "win32":
    os.system("chcp 65001 > nul")

sys.stdout.reconfigure(encoding="utf-8")


# ======================
# 설정
# ======================

# train.py의 FEATURES와 반드시 같아야 함 ("mfcc" 또는 "yamnet")
FEATURES = "yamnet"

MODEL_DIR = config.MODEL_PATH
SAMPLES_CSV = os.path.join(config.MFCC_PATH, "samples.csv")
TEST_INDICES_PATH = os.path.join(config.MFCC_PATH, "test_indices.npy")

N_PER_CLASS = 3     # 클래스마다 매번 랜덤으로 뽑을 오디오 개수
SEED = None         # 고정하고 싶으면 숫자, 매번 다르게 하려면 None

# 알림 규칙: 소리 클래스로 예측돼도 확신도가 임계값 미만이면 others로 강등(= 알림 안 함).
# deploy_config.py가 실환경 기준으로 정한 값이 있으면 그걸 쓴다.
DEPLOY_THR = os.path.join(config.MFCC_PATH, "thresholds_deploy.npy")
THRESHOLD = (np.load(DEPLOY_THR) if os.path.exists(DEPLOY_THR)
             else F.load_thresholds(config.MFCC_PATH, FEATURES))


# ======================
# 모델 로드
# ======================
# train.py가 앙상블 N개를 학습하고 배포도 그 평균을 쓴다.
# 여기서 단일 모델만 쓰면 눈으로 확인한 결과가 실제 동작과 달라진다.

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_models():
    paths = [os.path.join(MODEL_DIR, "best_model_%s_%d.pth" % (FEATURES, i))
             for i in range(10)]
    paths = [p for p in paths if os.path.exists(p)]

    if not paths:   # 앙상블 없이 단일 모델만 저장된 경우
        single = os.path.join(MODEL_DIR, "best_model_%s.pth" % FEATURES)
        if not os.path.exists(single):
            raise FileNotFoundError("모델이 없습니다. train.py를 먼저 실행하세요.")
        paths = [single]

    out = []
    for p in paths:
        m = (YamnetHead(num_classes=config.NUM_CLASSES) if FEATURES == "yamnet"
             else CNN(num_classes=config.NUM_CLASSES))
        m.load_state_dict(torch.load(p, map_location=device))
        m.to(device)
        m.eval()
        out.append(m)
    return out


models = load_models()
NORM_MEAN, NORM_STD = F.load_norm(config.MFCC_PATH, FEATURES)


def predict(path):
    """오디오 파일 → (최종 클래스, 원래 예측, 확신도, 강등 여부, 전체 확률)."""
    feat = F.yamnet_embed(path) if FEATURES == "yamnet" else F.extract(path)
    if feat is None:
        return None

    feat = F.apply_norm(feat, NORM_MEAN, NORM_STD)

    x = torch.tensor(feat, dtype=torch.float32).unsqueeze(0)   # 배치축
    if FEATURES != "yamnet":
        x = x.unsqueeze(1)                                     # CNN은 채널축도 필요
    x = x.to(device)

    with torch.no_grad():
        probs = np.mean([torch.softmax(m(x), dim=1)[0].cpu().numpy() for m in models],
                        axis=0)

    return F.decide(probs, THRESHOLD) + (probs,)


# ======================
# 홀드아웃에서 클래스별 균등 추출
# ======================

df = pd.read_csv(SAMPLES_CSV)
df["label"] = df["category"].apply(map_label)

# train.py가 저장한 홀드아웃 인덱스만 사용 (학습에 안 쓴 데이터)
test_idx = np.load(TEST_INDICES_PATH)
df = df[df["index"].isin(test_idx)]
print("모델 %d개 앙상블 | 홀드아웃 test 샘플 %d개 중에서 뽑는 중\n"
      % (len(models), len(df)))

parts = [
    g.sample(n=min(N_PER_CLASS, len(g)), random_state=SEED)
    for _, g in df.groupby("label")
]
samples = pd.concat(parts).sample(frac=1, random_state=SEED)


# ======================
# 예측
# ======================

correct = 0
per_class = {c: [0, 0] for c in range(config.NUM_CLASSES)}   # 라벨: [맞은 수, 전체 수]

print("=" * 78)

for _, row in samples.iterrows():

    result = predict(row["path"])
    if result is None:
        print("건너뜀 (너무 짧음):", row["path"])
        continue

    pred, raw_pred, conf, demoted, probs = result
    true_label = row["label"]

    is_correct = (pred == true_label)
    correct += is_correct
    per_class[true_label][0] += is_correct
    per_class[true_label][1] += 1

    print("파일:      %s  [%s]" % (os.path.basename(row["path"]), row["source"]))
    print("실제 라벨: %s" % F.CLASS_NAMES[true_label])
    print("예측 결과: %s  (%.4f)   %s"
          % (F.CLASS_NAMES[pred], conf, "O" if is_correct else "X"))

    if demoted:
        print("           ↳ 원래 예측 %s였지만 확신도 < %s → others로 강등 (알림 안 함)"
              % (F.CLASS_NAMES[raw_pred], THRESHOLD[raw_pred]))

    print("전체 확률:", "  ".join(
        "%s=%.3f" % (name, probs[i]) for i, name in enumerate(F.CLASS_NAMES)
    ))
    print("-" * 78)

total = sum(n for _, n in per_class.values())

print("클래스별 정확도")
for c in range(config.NUM_CLASSES):
    hit, n = per_class[c]
    print("  %-16s %d/%d  (%.2f%%)" % (F.CLASS_NAMES[c], hit, n, 100 * hit / n)
          if n else "  %-16s 샘플 없음" % F.CLASS_NAMES[c])

print("전체 정확도: %d/%d  (%.2f%%)" % (correct, total, 100 * correct / total))
print("적용 임계값: " + "  ".join(
    "%s=%.2f" % (F.CLASS_NAMES[c], THRESHOLD[c]) for c in F.MINORITY))
print("=" * 78)
