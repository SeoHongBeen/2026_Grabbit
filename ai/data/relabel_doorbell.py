"""
FSD50K에서 초인종(doorbell) 클립을 받아와 manifest.csv에 반영

FSD50K의 정식 Doorbell 라벨을 사용, dev와 eval 양쪽 모두 사용
(dev 107 + eval 37 = 144개, 업로더 83명)

지하철 차임은 제외(7개 제외됨)

이 스크립트를 다시 돌린 뒤에는
build_dataset.py → build_embeddings.py → train.py
순서로 다시 실행
"""
import csv
import io
import os
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

# core/ 의 공용 모듈(config)을 찾기 위한 경로 설정
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "core"))

import config

sys.stdout.reconfigure(encoding="utf-8")

ROOT = config.DATASET_PATH
DEST = os.path.join(ROOT, "FSD50K")
AUDIO_DIR = os.path.join(DEST, "audio")
MANIFEST = os.path.join(DEST, "manifest.csv")
GT_ZIP = os.path.join(DEST, "ground_truth.zip")

GT_URL = "https://zenodo.org/records/4060432/files/FSD50K.ground_truth.zip?download=1"
HF = "https://huggingface.co/datasets/Fhrozen/FSD50k/resolve/main/clips"

TARGET = "Doorbell"
NEW_CLASS = "doorbell"

# 집에서 날 소리가 아닌 초인종류 (지하철 출입문 차임)
EXCLUDE = {"Rail_transport", "Subway_and_metro_and_underground"}


def ground_truth():
    """dev/eval 라벨 표. 없으면 받아온다."""
    if not os.path.exists(GT_ZIP):
        print("ground_truth.zip 다운로드 중...")
        urllib.request.urlretrieve(GT_URL, GT_ZIP)

    with zipfile.ZipFile(GT_ZIP) as z:
        out = {}
        for split in ("dev", "eval"):
            name = next(n for n in z.namelist() if n.endswith("%s.csv" % split))
            out[split] = list(csv.DictReader(
                io.StringIO(z.read(name).decode("utf-8"))))
    return out


def main():
    gt = ground_truth()

    wanted, skipped = {}, 0
    for split, rows in gt.items():
        for r in rows:
            labels = set(r["labels"].split(","))
            if TARGET not in labels:
                continue
            if labels & EXCLUDE:
                skipped += 1
                continue
            wanted[r["fname"]] = split

    print("%s: %d개 (지하철 차임 %d개 제외 → %d개 사용)"
          % (TARGET, len(wanted) + skipped, skipped, len(wanted)))

    # 없는 것만 받아온다
    os.makedirs(AUDIO_DIR, exist_ok=True)
    todo = [(f, s) for f, s in wanted.items()
            if not os.path.exists(os.path.join(AUDIO_DIR, "%s.wav" % f))]

    if todo:
        print("다운로드 %d개..." % len(todo))
        done = {"n": 0, "fail": 0}
        t0 = time.time()

        def get(item):
            fname, split = item
            url = "%s/%s/%s.wav" % (HF, split, fname)
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(url, timeout=90) as r:
                        blob = r.read()
                    with open(os.path.join(AUDIO_DIR, "%s.wav" % fname), "wb") as fp:
                        fp.write(blob)
                    done["n"] += 1
                    return
                except Exception:
                    if attempt == 2:
                        done["fail"] += 1
                    else:
                        time.sleep(2)

        with ThreadPoolExecutor(16) as ex:
            list(ex.map(get, todo))
        print("  %d개 완료 / %d개 실패 / %.0f초" % (done["n"], done["fail"], time.time() - t0))
    else:
        print("이미 모두 받아져 있음")

    # manifest 갱신
    with open(MANIFEST, encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))

    # 제외 대상이 이미 doorbell로 들어가 있으면 빼낸다
    before = len(rows)
    rows = [r for r in rows
            if not (r["category"] == NEW_CLASS
                    and r["filename"].replace(".wav", "") not in wanted)]
    removed = before - len(rows)

    have = {r["filename"] for r in rows}
    added = 0
    for fname in sorted(wanted):
        name = "%s.wav" % fname
        if name not in have and os.path.exists(os.path.join(AUDIO_DIR, name)):
            rows.append({"filename": name, "category": NEW_CLASS})
            added += 1

    with open(MANIFEST, "w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=["filename", "category"])
        w.writeheader()
        w.writerows(rows)

    import collections
    print("\nmanifest: %d개 추가, %d개 제거" % (added, removed))
    print("  구성:", dict(collections.Counter(r["category"] for r in rows)))
    print("\n다음: build_dataset.py → build_embeddings.py → train.py")


if __name__ == "__main__":
    main()
