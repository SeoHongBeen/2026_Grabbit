"""
출시용 임계값을 클래스별 '허용 오알림 빈도'로부터 결정

  glass_breaking  침입·사고. 드물게 일어나고 놓치면 위험      → 예산 중간
  siren           안전 정보. 도시에선 진짜 사이렌이 자주 울림  → 예산 작게
  door_wood_knock 편의 기능. 놓쳐도 손해가 작고 헛울리면 성가심 → 예산 작게
  doorbell        노크와 같은 용도 (차임·인터폰 부저)          → 예산 작게

측정은 eval_stream.py가 만든 스트림 확률 캐시를 사용
실환경 녹음(real)이 있으면 그걸 쓰고, 없으면 합성 스트림(synth)으로 넘어감
"""
import os
import sys

import numpy as np
import torch
from sklearn.metrics import recall_score

# core/ 의 공용 모듈(features, config, cnn, utils)을 찾기 위한 경로 설정
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "core"))

import config
import features as F
from cnn import YamnetHead
from eval_stream import to_events, load_models, COOLDOWN_SEC, FRAME_HOP
from utils import map_label

if sys.platform == "win32":
    os.system("chcp 65001 > nul")

sys.stdout.reconfigure(encoding="utf-8")

FEATURES = "yamnet"

# 클래스별 허용 오알림 (하루 기준).
# 실환경 녹음은 일상 그대로라 24시간 운용을 가정하고 하루 단위로 잡는다.
BUDGET_PER_DAY = {
    0: 1.0,   # glass_breaking  — 침입·사고. 드물어서 헛울림도 드물다
    1: 1.0,   # siren           — 진짜 사이렌이 자주 울리므로 헛울림을 아껴야 한다
    2: 1.0,   # door_wood_knock — 편의 기능. 헛울리면 문까지 갔다 오게 된다
    3: 1.0,   # doorbell        — 노크와 같은 용도. 헛울림 손해도 같은 수준
}

# RPi가 실제로 판정하는 간격(run_rpi.py 의 --hop). 스트림 캐시는 FRAME_HOP
# (0.48초) 간격이라 이 값에 맞게 솎아서 측정한다.
#
# 이걸 맞추지 않으면 도구와 배포가 다른 조건을 보게 된다. "연속 N회"는 결국
# "N × hop 초 동안 지속"이라, 같은 규칙이라도 hop 이 다르면 요구 지속시간과
# 알림 지연이 통째로 달라진다.
DEPLOY_HOP = 1.0

# 연속 조건: 소리가 얼마나 오래 지속되는지에 맞춘다.
# 유리·노크·초인종은 1~2윈도우에만 나타나므로 높이면 아예 안 울린다.
#
# 사이렌 4→2: DEPLOY_HOP 1초에서 4회는 4초를 요구해 알림이 그만큼 늦었다.
# 2회로 줄여도 임계값·recall·오알림이 그대로라(실환경 2시간 재측정) 공짜다.
# 유리·초인종은 1회로 줄이면 오알림 예산 때문에 임계값이 0.30 → 0.70/0.61 로
# 올라가고 recall 이 0.96 → 0.88 / 0.74 → 0.70 으로 떨어져서 2회를 유지한다.
CONSECUTIVE = {
    0: 2,     # glass_breaking  — 순간적
    1: 2,     # siren           — 계속 울리므로 더 요구할 이유가 없다
    2: 1,     # door_wood_knock — 순간적
    3: 2,     # doorbell        — 차임 1~2초. 노크와 같은 길이
    4: 1,     # others
}

# 실환경 녹음은 아침·밤 일상 그대로라 하루 종일 이 수준으로 본다.
# (합성 스트림을 쓸 때는 시끄러운 시간만 해당하므로 4 정도가 맞다)
HOURS_PER_DAY = 24


def pick_cache():
    """가장 신뢰할 수 있는 스트림 캐시를 고른다.

    실환경 녹음 > 합성 스트림. 합성은 후처리 튜닝용 대체물이고,
    출시 설정은 실환경에서 나온 수치로 정해야 한다.
    """
    for tag in ("real_gain", "real", "synth_gain", "synth"):
        p = os.path.join(config.MFCC_PATH, "stream_probs_%s_%s.npz" % (FEATURES, tag))
        if os.path.exists(p):
            return p, tag

    old = os.path.join(config.MFCC_PATH, "stream_probs_%s.npz" % FEATURES)
    return (old, "synth") if os.path.exists(old) else (None, None)


def main():
    cache, tag = pick_cache()
    if cache is None:
        print("스트림 캐시가 없습니다. 먼저 eval_stream.py 를 실행하세요.")
        return

    print("스트림: %s%s\n" % (tag, "  (실환경 녹음 기준)" if tag.startswith("real")
                              else "  (합성 — 실환경 녹음으로 다시 재는 것을 권장)"))

    z = np.load(cache)
    probs, dur_hr = z["probs"], float(z["dur_hr"])

    models = load_models()
    mean, std = F.load_norm(config.MFCC_PATH, FEATURES)

    # 클립 단위 recall 계산용 (홀드아웃)
    Xc = np.load(os.path.join(config.MFCC_PATH, "yamnet_frames.npy"))
    yc = np.array([map_label(v) for v in
                   np.load(os.path.join(config.MFCC_PATH, "labels.npy"))])
    idx = np.load(os.path.join(config.MFCC_PATH, "test_indices.npy"))
    xc = torch.tensor((Xc[idx] - mean) / std, dtype=torch.float32)
    with torch.no_grad():
        clip_prob = np.mean([torch.softmax(m(xc), dim=1).numpy() for m in models], axis=0)
    y_clip = yc[idx]

    rule = np.array([CONSECUTIVE[c] for c in range(config.NUM_CLASSES)])
    grid = np.round(np.arange(0.30, 0.999, 0.005), 3)

    # 캐시(FRAME_HOP 간격)를 배포 간격으로 솎는다. 시작 위상에 따라 결과가
    # 조금씩 달라지므로 모든 위상을 재고 가장 나쁜 쪽을 취한다
    stride = max(1, int(round(DEPLOY_HOP / FRAME_HOP)))
    hop = FRAME_HOP * stride
    print("배포 간격 %.2f초로 측정 (캐시 %.2f초 → %d칸씩 솎음)\n"
          % (hop, FRAME_HOP, stride))

    def n_events(t):
        return max(len(to_events(probs[off::stride], t, rule, COOLDOWN_SEC, hop=hop))
                   for off in range(stride))

    chosen = np.zeros(config.NUM_CLASSES)
    rows = []

    for c in F.MINORITY:
        budget_hr = BUDGET_PER_DAY[c] / HOURS_PER_DAY
        pick, n_ev = 0.999, 0

        for thr in grid:
            t = np.full(config.NUM_CLASSES, 1.1)   # 이 클래스만 켜고 측정
            t[c] = thr
            n = n_events(t)
            if n / dur_hr <= budget_hr:
                pick, n_ev = float(thr), n
                break

        chosen[c] = pick

        cp = clip_prob.argmax(1)
        cc = cp.copy()
        cc[np.isin(cp, F.MINORITY) & (clip_prob.max(1) < pick)] = F.OTHERS
        rec = recall_score(y_clip, cc, labels=[c], average="macro", zero_division=0)
        prec = (cc == c).sum()
        prec = ((cc == c) & (y_clip == c)).sum() / prec if prec else 0.0

        # 관측 횟수로부터 하루 오알림의 95% 상한 (Poisson).
        # 0회 관측이어도 "0회"가 아니라 "이 값보다 적다"까지만 말할 수 있다.
        upper = (n_ev + 1.96 * np.sqrt(n_ev) + 1.92) / dur_hr * HOURS_PER_DAY
        rows.append((F.CLASS_NAMES[c], BUDGET_PER_DAY[c], pick,
                     n_ev / dur_hr * HOURS_PER_DAY, upper, rec, prec))

    # 전체 적용 결과
    n_all = n_events(chosen)
    cp = clip_prob.argmax(1)
    cc = cp.copy()
    thr_of = np.array([chosen[p] if p in F.MINORITY else 0.0 for p in cp])
    cc[np.isin(cp, F.MINORITY) & (clip_prob.max(1) < thr_of)] = F.OTHERS
    rec_all = recall_score(y_clip, cc, labels=F.MINORITY, average="macro", zero_division=0)
    per_hour = n_all / dur_hr

    print("=" * 78)
    print(" 출시 설정 (클래스별 오알림 예산 기준)")
    print("=" * 78)
    print(" %-16s %8s %8s %9s %11s %8s %9s" %
          ("클래스", "예산/일", "임계값", "실측/일", "95%상한/일", "recall", "precision"))
    for name, bud, thr, rate, upper, rec, prec in rows:
        print(" %-16s %8.1f %8.3f %9.1f %11.1f %8.3f %9.3f"
              % (name, bud, thr, rate, upper, rec, prec))

    print("\n 연속 조건: " + ", ".join(
        "%s %d회 (%.2f초)" % (F.CLASS_NAMES[c], CONSECUTIVE[c], CONSECUTIVE[c] * hop)
        for c in F.MINORITY))
    print(" 쿨다운: %.0f초 / 판정 간격: %.2f초" % (COOLDOWN_SEC, hop))

    print("\n" + "-" * 78)
    print(" 종합")
    print("-" * 78)
    print(" 소리 macro recall      %.3f" % rec_all)
    print(" 오알림 (하루 환산)     %.1f회   (관측 %d회 / %.1f시간)"
          % (per_hour * HOURS_PER_DAY, n_all, dur_hr))

    # 측정 한계를 명시한다. 짧은 녹음으로 낮은 빈도를 확인했다고 말할 수 없다.
    floor = 3.0 / dur_hr * HOURS_PER_DAY
    print("\n [측정 한계] 녹음이 %.1f시간뿐이라, 0회를 관측해도 통계적으로는" % dur_hr)
    print("             '하루 %.0f회 미만'까지만 보장됩니다 (Poisson 95%%)." % floor)
    print("             하루 1~2회를 검증하려면 약 %.0f시간 연속 녹음이 필요합니다."
          % (3.0 / (2.0 / HOURS_PER_DAY)))

    out = os.path.join(config.MFCC_PATH, "thresholds_deploy.npy")
    np.save(out, chosen)
    np.save(os.path.join(config.MFCC_PATH, "consecutive_deploy.npy"), rule)
    print("\n 저장: %s" % out)
    print("       %s" % os.path.join(config.MFCC_PATH, "consecutive_deploy.npy"))


if __name__ == "__main__":
    main()
