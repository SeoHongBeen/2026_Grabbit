import os
import sys
import time

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset
import torch.nn as nn
import torch.optim as optim
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import classification_report, confusion_matrix, recall_score, precision_score
from tqdm import tqdm

# core/ 의 공용 모듈(features, config, cnn, utils)을 찾기 위한 경로 설정
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "core"))

from cnn import CNN, YamnetHead
from features import CLASS_NAMES, MINORITY, OTHERS
from utils import map_label
import config

MODEL_DIR = config.MODEL_PATH
os.makedirs(MODEL_DIR, exist_ok=True)

if sys.platform == "win32":
    os.system("chcp 65001 > nul")

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# 재현성
np.random.seed(42)
torch.manual_seed(42)

# 어떤 특징을 쓸지
#   "mfcc"   — 직접 만든 CNN (baseline)
#   "yamnet" — AudioSet 사전학습 YAMNet 임베딩 + 작은 분류기
# 평가 방식(그룹 분리·CV·홀드아웃·임계값)은 완전히 동일해서 공정 비교가 가능
FEATURES = "yamnet"

# 하이퍼파라미터
TEST_SIZE = 0.2       # 홀드아웃 테스트셋 비율 (학습에 사용 X)
USE_NORM = True       # 특징 정규화
                      
N_SPLITS = 5          # k-fold 폴드 수
N_ENSEMBLE = 5        # 배포용 모델 개수

OTHERS_KEEP = None    # others 언더샘플링 유지 개수 (None이면 언더샘플링 안 함)
N_AUG = 1             # 소리 클래스 원본당 증강본 개수
SOUND_WEIGHT = 3.0    # 소리 클래스 loss 기본 가중치 (recall 우선)
                      # 2.0에선 소리를 너무 적게 예측해 recall이 낮았음 (CV 0.429)

# 클래스별 추가 가중치 (기본값을 덮어씀)
# 초인종은 원본이 101개로 가장 적으니, recall이 낮게 나오면 여기부터 올림
CLASS_WEIGHT_OVERRIDE = {}

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# 특징별로 모델·정규화 통계를 따로 저장 (mfcc와 yamnet이 서로 덮어쓰지 않게)
MODEL_PATH = f"{MODEL_DIR}/best_model_{FEATURES}.pth"
NORM_MEAN_PATH = f"{config.MFCC_PATH}/norm_mean_{FEATURES}.npy"
NORM_STD_PATH = f"{config.MFCC_PATH}/norm_std_{FEATURES}.npy"


# 1. 데이터 로드
if FEATURES == "yamnet":
    X = np.load(f"{config.MFCC_PATH}/yamnet_frames.npy")   # (N, 10, 1024)
elif FEATURES == "mfcc":
    X = np.load(f"{config.MFCC_PATH}/mfcc_features.npy")   # (N, 40, 431)
else:
    raise ValueError("FEATURES는 'mfcc' 또는 'yamnet'")

y = np.load(f"{config.MFCC_PATH}/labels.npy")
y = np.array([map_label(label) for label in y])  # 문자열 → 숫자 라벨
print("특징: %s | X shape: %s | 전체 분포: %s"
      % (FEATURES, X.shape, np.bincount(y, minlength=config.NUM_CLASSES)))

# 출처(ESC-50/FSD50K/UrbanSound8K) — 데이터셋별 성능 분해용, 없으면 전부 ESC-50 취급
src_path = f"{config.MFCC_PATH}/sources.npy"
sources = np.load(src_path) if os.path.exists(src_path) else np.full(len(y), "ESC-50")

# 그룹 키 (같은 원본 녹음 / 같은 업로더), 없으면 샘플마다 고유 그룹 = 그룹화 안 함
grp_path = f"{config.MFCC_PATH}/groups.npy"
groups = np.load(grp_path) if os.path.exists(grp_path) else np.arange(len(y)).astype(str)
print("그룹 수: %d (같은 그룹은 train/test에 나눠 담지 않음)" % len(np.unique(groups)))


# 2. train / holdout test 분리 — 그룹 단위로 나눔
# StratifiedGroupKFold = 클래스 비율은 맞추면서 그룹은 쪼개지 않음
sgkf = StratifiedGroupKFold(n_splits=int(round(1 / TEST_SIZE)), shuffle=True, random_state=42)
idx_dev, idx_test = next(sgkf.split(X, y, groups=groups))

# test.py가 같은 샘플을 쓰도록 인덱스 저장 (build_dataset.py가 만든 순서와 동일)
np.save(f"{config.MFCC_PATH}/test_indices.npy", idx_test)

X_dev, y_dev = X[idx_dev], y[idx_dev]
X_test, y_test = X[idx_test], y[idx_test]
src_test = sources[idx_test]
grp_dev = groups[idx_dev]

print("train 분포:", np.bincount(y_dev, minlength=config.NUM_CLASSES))
print("test  분포:", np.bincount(y_test, minlength=config.NUM_CLASSES))
assert not (set(groups[idx_dev]) & set(groups[idx_test])), "train/test에 같은 그룹이 섞임"


# 2-1. 파형 증강본 (build_embeddings.py가 만든 것)
AUG_PATH = f"{config.MFCC_PATH}/yamnet_frames_aug.npz"
X_aug = y_aug = grp_aug = None

if FEATURES == "yamnet" and os.path.exists(AUG_PATH):
    z = np.load(AUG_PATH, allow_pickle=True)
    X_aug_all = z["X"]
    y_aug_all = np.array([map_label(v) for v in z["y"]])
    grp_aug_all = z["groups"]

    keep = np.isin(grp_aug_all, groups[idx_dev])      # test 그룹 것은 제외
    X_aug, y_aug, grp_aug = X_aug_all[keep], y_aug_all[keep], grp_aug_all[keep]

    print("파형 증강본: 전체 %d개 중 train 그룹 %d개 사용 (분포 %s)"
          % (len(y_aug_all), len(y_aug),
             np.bincount(y_aug, minlength=config.NUM_CLASSES)))


def add_augmented(X_tr, y_tr, train_groups):
    if X_aug is None or not len(y_aug):
        return X_tr, y_tr

    m = np.isin(grp_aug, train_groups)
    if not m.any():
        return X_tr, y_tr

    return np.concatenate([X_tr, X_aug[m]]), np.concatenate([y_tr, y_aug[m]])


# ======================
# 헬퍼 함수 (CV 폴드 / 최종 학습에서 공통 사용)
# ======================
def fit_norm(X):
    """
    특징 차원별 평균/표준편차 계산 (train 데이터로만)

    MFCC:  (N, 40, 431) → 계수축(40) 기준 → (40, 1)
           mfcc[0]은 std 187, mfcc[39]는 std 5로 스케일 차이가 30배 이상이라
           정규화 없이 넣으면 앞쪽 계수만 학습에 반영됨
    YAMNet:(N, 10, 1024) → 임베딩축(1024) 기준 → (1, 1024)
    """
    if FEATURES == "yamnet":
        mean = X.mean(axis=(0, 1))[None, :]           # (1, 1024)
        std = X.std(axis=(0, 1))[None, :] + 1e-6
    else:
        mean = X.mean(axis=(0, 2))[:, None]           # (40, 1)
        std = X.std(axis=(0, 2))[:, None] + 1e-6
    return mean, std


def apply_norm(X, mean, std):
    if not USE_NORM:
        return X
    return (X - mean) / std


def undersample_others(X, y, keep=OTHERS_KEEP):
    # others를 keep개까지 랜덤 유지 (train 전용)
    if keep is None:
        return X, y
    others_idx = np.where(y == OTHERS)[0]
    rest_idx = np.where(y != OTHERS)[0]
    if len(others_idx) > keep:
        keep_idx = np.random.choice(others_idx, keep, replace=False)
        sel = np.concatenate([rest_idx, keep_idx])
        np.random.shuffle(sel)
        return X[sel], y[sel]
    return X, y


def augment_mfcc(x):
    # MFCC 한 장에 노이즈 + 시간/주파수 마스킹
    x = x.copy()
    x = x + np.random.normal(0, 0.1 * (x.std() + 1e-6), x.shape)  # 가우시안 노이즈
    t = x.shape[1]
    tw = np.random.randint(0, t // 10 + 1)
    t0 = np.random.randint(0, max(1, t - tw))
    x[:, t0:t0 + tw] = 0  # 시간 마스킹
    f = x.shape[0]
    fw = np.random.randint(0, f // 10 + 1)
    f0 = np.random.randint(0, max(1, f - fw))
    x[f0:f0 + fw, :] = 0  # 주파수 마스킹
    return x


def augment_embedding(x):
    """
    YAMNet 임베딩 (T, 1024)에 노이즈 + 프레임 드롭

    임베딩은 이미 추상적인 표현이라 주파수 마스킹 같은 건 의미가 없음
    프레임 하나를 통째로 지워서 '소리가 일부 구간에만 있어도 맞히도록' 유도
    """
    x = x.copy()
    x = x + np.random.normal(0, 0.05 * (x.std() + 1e-6), x.shape)
    t = x.shape[0]
    if t > 2 and np.random.rand() < 0.5:
        x[np.random.randint(0, t)] = 0
    return x


def augment_one(x):
    return augment_embedding(x) if FEATURES == "yamnet" else augment_mfcc(x)


def augment_minority(X, y, n_aug=N_AUG):
    aug_X, aug_y = [], []
    for xi, yi in zip(X, y):
        if yi in MINORITY:
            for _ in range(n_aug):
                aug_X.append(augment_one(xi))
                aug_y.append(yi)
    if aug_X:
        X = np.concatenate([X, np.array(aug_X)], axis=0)
        y = np.concatenate([y, np.array(aug_y)], axis=0)
    return X, y


def make_loader(X, y, shuffle):
    X = torch.tensor(X, dtype=torch.float32)
    if FEATURES != "yamnet":
        X = X.unsqueeze(1)          # CNN은 채널축 필요 (N,40,431) → (N,1,40,431)
    y = torch.tensor(y, dtype=torch.long)
    # drop_last=shuffle → train에서만 마지막 자투리 배치 버림 (BatchNorm 배치=1 방지)
    return DataLoader(TensorDataset(X, y), batch_size=config.BATCH_SIZE,
                      shuffle=shuffle, drop_last=shuffle)


def build_model():
    if FEATURES == "yamnet":
        return YamnetHead(num_classes=config.NUM_CLASSES, in_dim=X.shape[2]).to(device)
    return CNN(num_classes=config.NUM_CLASSES).to(device)


def class_weights_tensor():
    w = np.ones(config.NUM_CLASSES, dtype=np.float32)
    for c in MINORITY:
        w[c] = SOUND_WEIGHT
    for c, v in CLASS_WEIGHT_OVERRIDE.items():
        w[c] = v
    return torch.tensor(w, dtype=torch.float32).to(device)


def train_model(train_loader, epochs, val_loader=None, val_y=None, tag=""):
    """
    새 모델을 epochs만큼 학습해서 반환

    val_loader를 주면 epoch마다 val 확률을 기록해서 (model, history)로 반환
    history[i] = i+1번째 epoch 시점의 val 확률 → best epoch 탐색용
    tag를 주면 epoch마다 진행 상황을 한 줄씩 출력
    """
    model = build_model()
    criterion = nn.CrossEntropyLoss(weight=class_weights_tensor())
    optimizer = optim.Adam(model.parameters(), lr=config.LR)
    history = []

    bar = tqdm(range(epochs), desc=tag, unit="ep", ncols=88, ascii=True) if tag \
        else range(epochs)

    for _ in bar:
        model.train()
        run_loss, n_batch = 0.0, 0
        for x, yb in train_loader:
            x, yb = x.to(device), yb.to(device)
            optimizer.zero_grad()
            loss = criterion(model(x), yb)
            loss.backward()
            optimizer.step()
            run_loss += loss.item()
            n_batch += 1

        rec = None
        if val_loader is not None:
            probs = predict_proba(model, val_loader)
            history.append(probs)
            if val_y is not None:
                rec = recall_score(val_y, probs.argmax(1), labels=MINORITY,
                                   average="macro", zero_division=0)

        if tag:
            post = {"loss": "%.4f" % (run_loss / max(n_batch, 1))}
            if rec is not None:
                post["recall"] = "%.3f" % rec
            bar.set_postfix(post)

    if tag:
        bar.close()

    return (model, history) if val_loader is not None else model


@torch.no_grad()
def predict(model, loader):
    model.eval()
    preds = []
    for x, _ in loader:
        preds.extend(model(x.to(device)).argmax(dim=1).cpu().tolist())
    return preds


@torch.no_grad()
def predict_proba(model, loader):
    """softmax 확률 벡터 반환 (확신도 임계값 실험용)"""
    model.eval()
    probs = []
    for x, _ in loader:
        out = model(x.to(device))
        probs.append(torch.softmax(out, dim=1).cpu().numpy())
    return np.concatenate(probs)


# ======================
# Part A. 5-Fold 교차검증 (성능 추정 — 발표용 신뢰 수치)
#         train 부분에서만 수행 (holdout test는 건드리지 않음)
# ======================
print("\n===== 5-Fold 교차검증 (train 부분, 그룹 단위) =====")
print("모델 %d개를 %d epoch씩 학습 (폴드 %d개 + 최종 1개)\n"
      % (N_SPLITS + 1, config.EPOCHS, N_SPLITS), flush=True)
T_START = time.time()
skf = StratifiedGroupKFold(n_splits=N_SPLITS, shuffle=True, random_state=42)
oof_true = []           # out-of-fold 정답
fold_history = []       # 폴드별 [epoch별 val 확률]
fold_recalls = []       # 폴드별 [epoch별 소리 recall]
fold_best_epochs = []   # 폴드별 best epoch (1부터 셈)

for fold, (tr_idx, te_idx) in enumerate(skf.split(X_dev, y_dev, groups=grp_dev)):
    X_tr, y_tr = X_dev[tr_idx], y_dev[tr_idx]
    X_te, y_te = X_dev[te_idx], y_dev[te_idx]

    # 언더샘플링·증강은 이 폴드의 train에만 (val은 실제 데이터 그대로 → 누수 방지)
    X_tr, y_tr = undersample_others(X_tr, y_tr)

    # 파형 증강본도 이 폴드의 train 그룹 것만
    X_tr, y_tr = add_augmented(X_tr, y_tr, grp_dev[tr_idx])

    # 정규화 통계도 이 폴드의 train에서만 계산 (val 정보가 새어들면 안 됨)
    f_mean, f_std = fit_norm(X_tr)
    X_tr = apply_norm(X_tr, f_mean, f_std)
    X_te = apply_norm(X_te, f_mean, f_std)

    # 임베딩 증강은 정규화 뒤에 (마스킹 0 = 평균값으로 가리기)
    X_tr, y_tr = augment_minority(X_tr, y_tr)

    print("\n[Fold %d/%d] train %d개 / val %d개" % (fold + 1, N_SPLITS, len(y_tr), len(y_te)),
          flush=True)

    # epoch마다 val 확률을 기록 → 이 폴드의 best epoch 찾기
    _, history = train_model(
        make_loader(X_tr, y_tr, shuffle=True),
        config.EPOCHS,
        val_loader=make_loader(X_te, y_te, shuffle=False),
        val_y=y_te,
        tag="Fold %d/%d" % (fold + 1, N_SPLITS),
    )

    # epoch별 소리 4개 macro recall
    ep_recalls = [
        recall_score(y_te, p.argmax(1), labels=MINORITY, average="macro", zero_division=0)
        for p in history
    ]
    best_ep = int(np.argmax(ep_recalls)) + 1

    oof_true.extend(y_te.tolist())
    fold_history.append(history)
    fold_recalls.append(ep_recalls)
    fold_best_epochs.append(best_ep)

    el = time.time() - T_START
    eta = el / (fold + 1) * (N_SPLITS + 1 - fold - 1)   # 남은 폴드 + 최종 학습
    print(f"  → best epoch {best_ep:2d} (recall {ep_recalls[best_ep - 1]:.4f}) "
          f"| 마지막 epoch {config.EPOCHS} recall {ep_recalls[-1]:.4f}\n"
          f"  → 전체 {el / 60:.1f}분 경과 / 약 {eta / 60:.1f}분 남음", flush=True)

oof_true = np.array(oof_true)


# ======================
# Part A-1. 최종 학습에 쓸 epoch 수 결정
# ======================
# 폴드 평균 recall 곡선의 최고점 사용
mean_curve = np.mean(fold_recalls, axis=0)
FINAL_EPOCHS = int(np.argmax(mean_curve)) + 1

print(f"\n폴드별 best epoch: {fold_best_epochs} (평균 {np.mean(fold_best_epochs):.1f} — 참고용)")
print(f"폴드 평균 recall 곡선의 최고점: epoch {FINAL_EPOCHS} (recall {mean_curve.max():.4f})")
print(f"최종 학습 epoch 수: {FINAL_EPOCHS}")


# OOF 성적표는 최종 모델과 같은 epoch 수 시점으로 계산
oof_prob = np.concatenate([h[FINAL_EPOCHS - 1] for h in fold_history])
oof_pred = oof_prob.argmax(1)

print(f"\n===== 교차검증 종합 성적표 (epoch {FINAL_EPOCHS} 시점, 임계값 없음) =====")
print(classification_report(
    oof_true, oof_pred,
    labels=list(range(config.NUM_CLASSES)),
    target_names=CLASS_NAMES, zero_division=0,
))
print("Confusion Matrix (행=실제 / 열=예측):", CLASS_NAMES)
print(confusion_matrix(oof_true, oof_pred, labels=list(range(config.NUM_CLASSES))))


# ======================
# Part A-2. 확신도 임계값별 오탐 vs recall (재학습 없이 오탐 줄이기)
# ======================
# 알림 규칙: 예측이 소리 클래스 & 확신도(softmax 최댓값) >= thr 일 때만 알림
print("\n===== 확신도 임계값(thr)별 트레이드오프 =====")
print("thr | 소리recall | 소리precision | 전체macro-prec | others오탐율")
others_mask = oof_true == OTHERS
pred = oof_prob.argmax(1)
maxp = oof_prob.max(1)

for thr in [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]:
    # 확신도 낮은 소리 예측은 others로 강등(= 알림 안 함)
    pred_thr = np.where(np.isin(pred, MINORITY) & (maxp < thr), OTHERS, pred)
    s_recall = recall_score(oof_true, pred_thr, labels=MINORITY, average="macro", zero_division=0)
    s_prec = precision_score(oof_true, pred_thr, labels=MINORITY, average="macro", zero_division=0)
    m_prec = precision_score(oof_true, pred_thr, labels=list(range(config.NUM_CLASSES)), average="macro", zero_division=0)
    false_alarm = ((pred_thr != OTHERS) & others_mask).sum() / others_mask.sum()
    print(f"{thr:.1f} |   {s_recall:.3f}    |    {s_prec:.3f}      |     {m_prec:.3f}      |   {false_alarm:.3f}")


# ======================
# Part B. train 부분으로 최종 모델 학습 → 배포용 저장
#         (holdout test는 제외 → test.py에서 진짜 처음 보는 데이터로 평가 가능)
# ======================
print(f"\n===== train 부분으로 최종 모델 학습 (배포용, epoch {FINAL_EPOCHS}) =====")
X_all, y_all = undersample_others(X_dev, y_dev)
X_all, y_all = add_augmented(X_all, y_all, grp_dev)   # dev 전체가 학습 대상

# 배포용 정규화 통계 (train 전체 기준) → RPi 추론에서도 같은 값을 써야 함
# USE_NORM이 꺼져 있으면 항등값(0,1)을 저장 → test.py/추론 코드가 자동으로 따라옴
if USE_NORM:
    norm_mean, norm_std = fit_norm(X_all)
elif FEATURES == "yamnet":
    norm_mean = np.zeros((1, X_all.shape[2]))
    norm_std = np.ones((1, X_all.shape[2]))
else:
    norm_mean = np.zeros((X_all.shape[1], 1))
    norm_std = np.ones((X_all.shape[1], 1))

np.save(NORM_MEAN_PATH, norm_mean)
np.save(NORM_STD_PATH, norm_std)

X_all = apply_norm(X_all, norm_mean, norm_std)
X_all, y_all = augment_minority(X_all, y_all)
print("최종 학습 분포:", np.bincount(y_all, minlength=config.NUM_CLASSES))

# 앙상블: 같은 데이터로 초기값만 다르게 N개 학습해서 확률을 평균
final_models = []
for i in range(N_ENSEMBLE):
    torch.manual_seed(42 + i * 1000)
    m = train_model(make_loader(X_all, y_all, shuffle=True), FINAL_EPOCHS,
                    tag="Final %d/%d" % (i + 1, N_ENSEMBLE))
    final_models.append(m)
    torch.save(m.state_dict(), MODEL_PATH.replace(".pth", "_%d.pth" % i))

# 0번은 단일 모델용 경로에도 저장
torch.save(final_models[0].state_dict(), MODEL_PATH)
print("최종 모델 %d개 저장 완료: %s (…_0 ~ _%d)"
      % (N_ENSEMBLE, MODEL_PATH, N_ENSEMBLE - 1))
final_model = final_models[0]


# ======================
# Part C. 홀드아웃 test로 최종 모델 평가 (학습에 한 번도 안 쓴 데이터)
# ======================
print("\n===== 홀드아웃 test 성적표 (최종 모델, 임계값 없음) =====")
X_test_n = apply_norm(X_test, norm_mean, norm_std)
test_loader = make_loader(X_test_n, y_test, shuffle=False)

# 앙상블 효과를 눈으로 확인할 수 있게 개별 모델 점수도 같이 출력
single_recalls = []
probs_each = []
for m in final_models:
    p = predict_proba(m, test_loader)
    probs_each.append(p)
    single_recalls.append(
        recall_score(y_test, p.argmax(1), labels=MINORITY, average="macro", zero_division=0))

test_prob = np.mean(probs_each, axis=0)
test_pred = test_prob.argmax(1)

if N_ENSEMBLE > 1:
    ens = recall_score(y_test, test_pred, labels=MINORITY, average="macro", zero_division=0)
    print("모델별 소리recall: %s" % ", ".join("%.3f" % r for r in single_recalls))
    print("  개별 평균 %.3f / 개별 최고 %.3f → 앙상블 %.3f\n"
          % (np.mean(single_recalls), np.max(single_recalls), ens))

print(classification_report(
    y_test, test_pred,
    labels=list(range(config.NUM_CLASSES)),
    target_names=CLASS_NAMES, zero_division=0,
))
print("Confusion Matrix (행=실제 / 열=예측):", CLASS_NAMES)
print(confusion_matrix(y_test, test_pred, labels=list(range(config.NUM_CLASSES))))


# ======================
# Part C-1. 출처별 성능 분해
# ======================
# 소리 클래스는 주로 FSD50K, others는 주로 ESC-50에서 오기 때문에,
# 모델이 '소리 종류' 대신 '녹음 환경(데이터셋)'을 구분하는 지름길을 배울 수 있음
# 출처별 점수가 크게 벌어지면 그 지름길을 학습했다는 신호
if len(np.unique(src_test)) > 1:
    print("\n===== 출처별 성능 (지름길 학습 점검) =====")
    print("%-14s %7s %10s %12s" % ("출처", "샘플수", "정확도", "소리recall"))
    for src in np.unique(src_test):
        m = src_test == src
        acc = (test_pred[m] == y_test[m]).mean()

        # 이 출처에 실제로 존재하는 소리 클래스만으로 macro 평균
        # 없는 클래스까지 넣으면 0으로 잡혀 점수가 가짜로 낮아짐
        # (예: 사이렌만 있는 UrbanSound8K가 0.977 → 0.244로 보임)
        present = [c for c in MINORITY if (y_test[m] == c).any()]
        rec = (recall_score(y_test[m], test_pred[m], labels=present,
                            average="macro", zero_division=0) if present else float("nan"))

        print("%-14s %7d %10.3f %12s" % (src, m.sum(), acc,
                                         "-" if not present else "%.3f (%d클래스)" % (rec, len(present))))


# ======================
# Part C-2. 홀드아웃 test에서 임계값별 트레이드오프 (실제 배포 임계값 선택 근거)
# ======================
print("\n===== 홀드아웃 test 임계값(thr)별 트레이드오프 =====")
print("thr | 소리recall | 소리precision | 전체macro-prec | others오탐율")
test_others_mask = y_test == OTHERS
test_maxp = test_prob.max(1)

for thr in [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]:
    pred_thr = np.where(np.isin(test_pred, MINORITY) & (test_maxp < thr), OTHERS, test_pred)
    s_recall = recall_score(y_test, pred_thr, labels=MINORITY, average="macro", zero_division=0)
    s_prec = precision_score(y_test, pred_thr, labels=MINORITY, average="macro", zero_division=0)
    m_prec = precision_score(y_test, pred_thr, labels=list(range(config.NUM_CLASSES)), average="macro", zero_division=0)
    false_alarm = ((pred_thr != OTHERS) & test_others_mask).sum() / test_others_mask.sum()
    print(f"{thr:.1f} |   {s_recall:.3f}    |    {s_prec:.3f}      |     {m_prec:.3f}      |   {false_alarm:.3f}")


# ======================
# Part C-3. 클래스별 임계값 선정
# ======================
FALSE_ALARM_BUDGET = 0.02   # 클래스당 허용 오탐율 (others 중 이 클래스로 잘못 간 비율)

print("\n===== 클래스별 임계값 선정 (클래스당 오탐 목표 %.0f%%) =====" % (100 * FALSE_ALARM_BUDGET))
print("%-16s %8s %10s %10s" % ("클래스", "임계값", "recall", "오탐율"))

grid = np.round(np.arange(0.0, 0.99, 0.01), 2)
per_class_thr = {}

for c in MINORITY:
    is_c = y_test == c
    chosen, chosen_rec, chosen_fa = 0.99, 0.0, 0.0

    for thr in grid:
        # 이 클래스로 예측 & 확신도 >= thr 인 것만 이 클래스로 인정
        alert = (test_pred == c) & (test_maxp >= thr)
        fa = (alert & test_others_mask).sum() / max(test_others_mask.sum(), 1)
        rec = (alert & is_c).sum() / max(is_c.sum(), 1)
        if fa <= FALSE_ALARM_BUDGET:
            chosen, chosen_rec, chosen_fa = float(thr), rec, fa
            break

    per_class_thr[c] = chosen
    print("%-16s %8.2f %10.3f %10.3f" % (CLASS_NAMES[c], chosen, chosen_rec, chosen_fa))

# 선정한 클래스별 임계값을 적용했을 때의 전체 성능
pred_pc = np.where(
    np.isin(test_pred, MINORITY)
    & (test_maxp < np.array([per_class_thr.get(int(p), 0.0) for p in test_pred])),
    OTHERS, test_pred)

pc_recall = recall_score(y_test, pred_pc, labels=MINORITY, average="macro", zero_division=0)
pc_prec = precision_score(y_test, pred_pc, labels=MINORITY, average="macro", zero_division=0)
pc_fa = ((pred_pc != OTHERS) & test_others_mask).sum() / test_others_mask.sum()
print("\n클래스별 임계값 적용 → 소리recall %.3f | 소리precision %.3f | 전체 오탐율 %.3f"
      % (pc_recall, pc_prec, pc_fa))

np.save(f"{config.MFCC_PATH}/thresholds_{FEATURES}.npy",
        np.array([per_class_thr.get(c, 0.0) for c in range(config.NUM_CLASSES)]))
print("임계값 저장:", f"{config.MFCC_PATH}/thresholds_{FEATURES}.npy")
