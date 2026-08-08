"""
ESC-50 + FSD50K + UrbanSound8K를 하나로 합쳐 MFCC 특징 제조

세 데이터셋의 클립 길이가 제각각이라 5초로 통일함:
  - 1초 미만        → 버림 (대부분이 0 패딩이라 학습에 방해)
  - 1초 이상 5초 이하 → 뒤를 0으로 패딩 (ESC-50 처리와 동일)
  - 5초 초과        → RMS 에너지가 가장 높은 5초 구간 선택
    (앞 5초를 그냥 자르면 도입부 정적만 담길 수 있음)

클립 하나당 샘플 하나만: 성능이 부풀려짐 방지

같은 이유로 '그룹 키'도 같이 저장:
  - ESC-50       : src_file (원본 녹음)
  - FSD50K       : uploader (업로더. 같은 방·마이크로 녹음한 묶음)
  - UrbanSound8K : fsID (slice_file_name 앞부분 = Freesound 원본 ID)
"""
import csv
import json
import os
import random
import sys

import numpy as np
from tqdm import tqdm

# core/ 의 공용 모듈(features, config, cnn, utils)을 찾기 위한 경로 설정
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "core"))

import config
import features as F
from features import CLASS_NAMES

sys.stdout.reconfigure(encoding="utf-8")

ROOT = config.DATASET_PATH
OUT = os.path.join(ROOT, "mfcc")

# UrbanSound8K 원본 녹음당 최대 클립 수.
# 사이렌은 원본이 74개뿐인데 상한 8이면 539개가 되어 소리 클래스 중 가장 많아졌고,
# 다양성 대비 수가 과해 그 74개 녹음에 치우칠 위험이 있어 4로 낮춤.
US8K_PER_GROUP = 4

# others를 출처당 최대 몇 개까지 쓸지.
# 한 데이터셋이 others를 지배하면 모델이 '그 데이터셋의 녹음 특성 = others'로
# 배워버려서, 다른 환경(실제 RPi 마이크)에서 오탐이 늘어난다.
OTHERS_PER_SOURCE = 1800

# ESC-50 category → 우리 클래스 (나머지는 others)
# 초인종은 ESC-50에 없다 (church_bells는 교회 종이라 다른 소리).
# FSD50K의 Doorbell 라벨에서만 온다.
#
# crackling_fire는 클래스에서 제외했다 (아래 DROP_CATEGORIES 참고).
ESC50_MAP = {
    "glass_breaking": "glass_breaking",
    "siren": "siren",
    "door_wood_knock": "door_wood_knock",
}

# 제외된 클래스의 클립은 others로 넣지 않고 아예 버린다.
# 화재 소리는 '알림 대상이 아닌 소리'가 아니라 '지금은 다루지 않는 소리'라,
# others로 학습시키면 나중에 다시 넣을 때 방해가 된다.
DROP_CATEGORIES = {"crackling_fire"}


def collect_esc50():
    """(경로, 클래스, 출처, 그룹) 목록."""
    meta = os.path.join(ROOT, "ESC-50/meta/esc50.csv")
    audio = os.path.join(ROOT, "ESC-50/audio")
    items = []
    with open(meta, encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            cls = ESC50_MAP.get(r["category"], "others")
            group = "esc50:%s" % r["src_file"]
            items.append((os.path.join(audio, r["filename"]), cls, "ESC-50", group))
    return items


def collect_fsd50k():
    base = os.path.join(ROOT, "FSD50K")
    meta = os.path.join(base, "manifest.csv")
    audio = os.path.join(base, "audio")
    if not os.path.exists(meta):
        print("[건너뜀] FSD50K: manifest.csv 없음")
        return []

    info_path = os.path.join(base, "clips_info.json")
    info = {}
    if os.path.exists(info_path):
        with open(info_path, encoding="utf-8") as fp:
            info = json.load(fp)
    else:
        print("[경고] FSD50K clips_info.json 없음 → 업로더 그룹화 불가")

    items = []
    with open(meta, encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            path = os.path.join(audio, r["filename"])
            if not os.path.exists(path):
                continue
            fid = r["filename"].replace(".wav", "")
            uploader = info.get(fid, {}).get("uploader")
            # 업로더를 모르면 자기 자신만의 그룹 (섞이지 않게 보수적으로)
            group = "fsd:%s" % uploader if uploader else "fsd_clip:%s" % fid
            items.append((path, r["category"], "FSD50K", group))
    return items


def collect_us8k():
    """UrbanSound8K는 연속 녹음 하나를 4초씩 잘라낸 것이라 원본당 클립이 최대 100개다.

    그대로 넣으면 모델이 같은 녹음을 수십 번 보게 돼 그 녹음에 과적합되고,
    사이렌 한 클래스가 데이터를 지배한다. 원본당 US8K_PER_GROUP개까지만 쓴다
    (원본 자체는 하나도 버리지 않음 → 다양성은 유지, 중복만 제거).
    """
    base = os.path.join(ROOT, "UrbanSound8K")
    meta = os.path.join(base, "manifest.csv")
    audio = os.path.join(base, "audio")
    if not os.path.exists(meta):
        print("[건너뜀] UrbanSound8K: manifest.csv 없음")
        return []

    by_group = {}
    with open(meta, encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            path = os.path.join(audio, r["filename"])
            if not os.path.exists(path):
                continue
            # slice_file_name 형식: fsID-classID-occurrenceID-sliceID.wav
            fs_id = r["filename"].split("-")[0]
            by_group.setdefault(fs_id, []).append((path, r["category"]))

    rng = random.Random(42)
    items, dropped = [], 0
    for fs_id, rows in sorted(by_group.items()):
        rng.shuffle(rows)
        dropped += max(0, len(rows) - US8K_PER_GROUP)
        for path, cls in rows[:US8K_PER_GROUP]:
            items.append((path, cls, "UrbanSound8K", "us8k:%s" % fs_id))

    print("UrbanSound8K: 원본 %d개에서 %d개 사용 (원본당 최대 %d개, 중복 %d개 제외)"
          % (len(by_group), len(items), US8K_PER_GROUP, dropped))
    return items


def main():
    os.makedirs(OUT, exist_ok=True)

    items = collect_esc50() + collect_fsd50k() + collect_us8k()

    n_before = len(items)
    items = [it for it in items if it[1] not in DROP_CATEGORIES]
    if len(items) < n_before:
        print("제외한 클래스(%s): %d개" % (", ".join(sorted(DROP_CATEGORIES)),
                                           n_before - len(items)))

    # others를 출처당 상한까지만 사용 (소리 클래스는 그대로 — 원래 부족하므로)
    rng = random.Random(1234)
    kept, by_src = [], {}
    for it in items:
        path, cls, src, grp = it
        if cls != "others":
            kept.append(it)
        else:
            by_src.setdefault(src, []).append(it)

    print("others 출처별 조정 (상한 %d)" % OTHERS_PER_SOURCE)
    for src in sorted(by_src):
        pool = by_src[src]
        rng.shuffle(pool)
        print("  %-14s %5d개 → %5d개" % (src, len(pool), min(len(pool), OTHERS_PER_SOURCE)))
        kept.extend(pool[:OTHERS_PER_SOURCE])

    items = kept
    print("후보 클립 %d개" % len(items))

    features, labels, sources, groups, paths = [], [], [], [], []
    skipped_short, failed = 0, 0

    for path, cls, src, grp in tqdm(items):
        try:
            y = F.load_5sec(path)
        except Exception:
            failed += 1
            continue

        if y is None:
            skipped_short += 1
            continue

        mfcc = F.to_mfcc(y)

        features.append(mfcc)
        labels.append(cls)
        sources.append(src)
        groups.append(grp)
        paths.append(path)

    X = np.array(features, dtype=np.float32)
    y = np.array(labels)
    s = np.array(sources)
    g = np.array(groups)

    np.save(os.path.join(OUT, "mfcc_features.npy"), X)
    np.save(os.path.join(OUT, "labels.npy"), y)
    np.save(os.path.join(OUT, "sources.npy"), s)
    np.save(os.path.join(OUT, "groups.npy"), g)

    # 샘플 번호 ↔ 원본 파일 대응표.
    # 이게 없으면 test.py가 "몇 번 샘플이 어느 파일인지"를 추측해야 하고,
    # 데이터셋이 늘어나는 순간 어긋난다 (실제로 esc50.csv 기준으로 추측하다 깨졌음).
    manifest = os.path.join(OUT, "samples.csv")
    with open(manifest, "w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(["index", "path", "category", "source", "group"])
        for i, (p, c, sc, gr) in enumerate(zip(paths, labels, sources, groups)):
            w.writerow([i, p, c, sc, gr])
    print("샘플 대응표 저장:", manifest)

    print("\n저장 완료:", X.shape)
    print("1초 미만이라 제외: %d개 | 읽기 실패: %d개" % (skipped_short, failed))

    print("\n클래스 × 출처 분포")
    print("%-16s %8s %8s %13s %8s %8s" % ("클래스", "ESC-50", "FSD50K", "UrbanSound8K", "합계", "그룹수"))
    for c in CLASS_NAMES:
        row = [int(((y == c) & (s == src)).sum()) for src in ("ESC-50", "FSD50K", "UrbanSound8K")]
        n_grp = len(set(g[y == c]))
        print("%-16s %8d %8d %13d %8d %8d" % (c, row[0], row[1], row[2], sum(row), n_grp))
    print("\n전체 그룹 수: %d (이 단위로 train/test를 나눔)" % len(set(g)))


if __name__ == "__main__":
    main()
