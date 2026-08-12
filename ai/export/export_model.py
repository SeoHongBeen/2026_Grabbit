"""
학습 결과를 RPi 배포용 파일 하나로 내보냄

RPi에는 tflite-runtime + numpy만 있으면 됨

내보내는 것 (grabbit_model.npz 하나):
  - 앙상블 모델 N개의 가중치
  - 임베딩 정규화 통계 (train 데이터 기준)
  - 클래스별 임계값 / 연속 조건
  - 클래스 이름, 오디오 규격

전처리 상수(샘플레이트·길이·음량 정규화)도 같이 포함
"""
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import config
import features as F
from cnn import YamnetHead

sys.stdout.reconfigure(encoding="utf-8")

FEATURES = "yamnet"
MODEL_DIR = config.MODEL_PATH
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grabbit_model.npz")


def collect_models():
    paths = []
    for i in range(10):
        p = os.path.join(MODEL_DIR, "best_model_%s_%d.pth" % (FEATURES, i))
        if os.path.exists(p):
            paths.append(p)

    if not paths:
        p = os.path.join(MODEL_DIR, "best_model_%s.pth" % FEATURES)
        if os.path.exists(p):
            paths.append(p)

    if not paths:
        sys.exit("모델 파일이 없습니다. train.py를 먼저 실행하세요.")

    return paths


def main():
    paths = collect_models()
    print("모델 %d개" % len(paths))

    out = {}
    for i, p in enumerate(paths):
        m = YamnetHead(num_classes=config.NUM_CLASSES)
        m.load_state_dict(torch.load(p, map_location="cpu"))
        m.eval()

        sd = m.state_dict()
        # BatchNorm1d는 추론 시 (x - running_mean) / sqrt(running_var + eps) * weight + bias
        out["m%d_bn_mean" % i] = sd["norm.running_mean"].numpy()
        out["m%d_bn_var" % i] = sd["norm.running_var"].numpy()
        out["m%d_bn_w" % i] = sd["norm.weight"].numpy()
        out["m%d_bn_b" % i] = sd["norm.bias"].numpy()
        out["m%d_fc1_w" % i] = sd["fc1.weight"].numpy()
        out["m%d_fc1_b" % i] = sd["fc1.bias"].numpy()
        out["m%d_fc2_w" % i] = sd["fc2.weight"].numpy()
        out["m%d_fc2_b" % i] = sd["fc2.bias"].numpy()
        print("  %s" % os.path.basename(p))

    out["n_models"] = np.array(len(paths))
    out["bn_eps"] = np.array(1e-5)   # nn.BatchNorm1d 기본값

    # 임베딩 정규화 (train.py가 저장한 것)
    mean, std = F.load_norm(config.MFCC_PATH, FEATURES)
    out["emb_mean"] = mean.astype(np.float32)
    out["emb_std"] = std.astype(np.float32)

    # 클래스별 임계값 / 연속 조건 (deploy_config.py가 실환경 기준으로 정한 것)
    thr_path = os.path.join(config.MFCC_PATH, "thresholds_deploy.npy")
    con_path = os.path.join(config.MFCC_PATH, "consecutive_deploy.npy")

    if os.path.exists(thr_path):
        out["thresholds"] = np.load(thr_path)
        print("임계값: deploy (실환경 기준)")
    else:
        out["thresholds"] = F.load_thresholds(config.MFCC_PATH, FEATURES)
        print("[주의] thresholds_deploy.npy 가 없어 클립 기준 임계값을 씁니다")
        print("       deploy_config.py 를 먼저 실행하는 것을 권장합니다")

    if os.path.exists(con_path):
        out["consecutive"] = np.load(con_path)
    else:
        out["consecutive"] = np.ones(config.NUM_CLASSES, dtype=int)
        print("[주의] consecutive_deploy.npy 가 없어 연속 조건 없이 내보냅니다")

    # 클래스 정의
    out["class_names"] = np.array(F.CLASS_NAMES)
    out["minority"] = np.array(F.MINORITY)
    out["others"] = np.array(F.OTHERS)

    # 전처리 규격 — 학습과 반드시 같아야 하므로 함께 내보낸다
    out["sr"] = np.array(F.YAMNET_SR)
    out["clip_sec"] = np.array(F.CLIP_SEC)
    out["gain_normalize"] = np.array(F.GAIN_NORMALIZE)
    out["target_rms"] = np.array(F.TARGET_RMS)
    out["max_gain"] = np.array(F.MAX_GAIN)

    np.savez(OUT, **out)
    size = os.path.getsize(OUT) / 1e6

    print("\n저장: %s (%.1f MB)" % (OUT, size))
    print("\n클래스별 설정")
    print("  %-18s %10s %8s" % ("클래스", "임계값", "연속"))
    for c in F.MINORITY:
        print("  %-18s %10.3f %8d"
              % (F.CLASS_NAMES[c], out["thresholds"][c], out["consecutive"][c]))

    print("\n전처리: %dHz / %d초 / 음량정규화 %s (목표 RMS %.3f, 상한 %.0f배)"
          % (F.YAMNET_SR, F.CLIP_SEC, "켬" if F.GAIN_NORMALIZE else "끔",
             F.TARGET_RMS, F.MAX_GAIN))


if __name__ == "__main__":
    main()
