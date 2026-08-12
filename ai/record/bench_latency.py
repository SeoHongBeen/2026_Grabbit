"""
!/usr/bin/env python3
RPi에서 실제 추론 속도를 잼

목표는 소리 발생 → 알림까지 1.5초

전체 지연은 이렇게 쪼개진다:
    녹음 버퍼 대기 + 리샘플링 + YAMNet + 분류기
이 스크립트는 뒤 세 개(= 오디오가 준비된 뒤의 계산 시간)를 잼
녹음 버퍼 대기는 윈도우 간격(hop)에 해당하며 설계로 정해지는 값

필요한 것:
    pip install tflite-runtime numpy soundfile
    (또는 tensorflow가 이미 있으면 그것도 됨)
    yamnet.tflite  — 같은 폴더에 두거나 --model 로 경로 지정
"""
import argparse
import os
import sys
import time

import numpy as np

SR = 16000
CLIP_SEC = 5


def load_interpreter(path):
    Interpreter = None

    # RPi에는 tflite-runtime만 깔면 되고(가벼움), PC에는 보통 tensorflow가 있다.
    # 버전마다 위치가 달라서 순서대로 시도한다.
    try:
        from tflite_runtime.interpreter import Interpreter
    except ImportError:
        pass

    if Interpreter is None:
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            pass

    if Interpreter is None:
        try:
            import tensorflow as tf
            Interpreter = tf.lite.Interpreter
        except ImportError:
            pass

    if Interpreter is None:
        print("tflite-runtime 또는 tensorflow가 필요합니다:")
        print("  pip install tflite-runtime")
        sys.exit(1)

    if not os.path.exists(path):
        print("모델 파일이 없습니다: %s" % path)
        print("\n내려받기 (임베딩 출력이 있는 버전이어야 함):")
        print("  curl -L -o yam.tar.gz \\")
        print("    'https://www.kaggle.com/api/v1/models/google/yamnet/tfLite/tflite/1/download'")
        print("  tar xzf yam.tar.gz && mv 1.tflite yamnet.tflite")
        print("\n주의: MediaPipe판 yamnet.tflite는 클래스 점수(521)만 뱉고")
        print("      1024차원 임베딩이 없어서 이 프로젝트에서는 쓸 수 없습니다.")
        sys.exit(1)

    it = Interpreter(model_path=path)
    it.allocate_tensors()
    return it


def bench(interpreter, n=30):
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()

    # 입력 길이가 고정이 아니면 5초로 맞춘다
    want = SR * CLIP_SEC
    shape = list(inp["shape"])
    if shape[-1] != want:
        try:
            interpreter.resize_tensor_input(inp["index"], [want])
            interpreter.allocate_tensors()
            inp = interpreter.get_input_details()[0]
        except Exception:
            want = int(shape[-1])
            print("입력 길이를 %d 샘플(%.2f초)로 고정합니다." % (want, want / SR))

    rng = np.random.default_rng(0)
    wave = rng.normal(0, 0.05, want).astype(np.float32)

    # 예열 — 첫 호출은 초기화 때문에 유난히 느리다
    for _ in range(3):
        interpreter.set_tensor(inp["index"], wave)
        interpreter.invoke()

    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        interpreter.set_tensor(inp["index"], wave)
        interpreter.invoke()
        for o in out:
            interpreter.get_tensor(o["index"])
        times.append((time.perf_counter() - t0) * 1000)

    return np.array(times), [tuple(o["shape"]) for o in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.join(os.path.dirname(__file__), "yamnet.tflite"))
    ap.add_argument("-n", type=int, default=30)
    args = ap.parse_args()

    print("=" * 62)
    print(" RPi 추론 속도 측정")
    print("=" * 62)

    try:
        import platform
        print(" 기기 : %s" % platform.machine())
        with open("/proc/cpuinfo") as fp:
            for line in fp:
                if "Model" in line:
                    print(" CPU  : %s" % line.split(":", 1)[1].strip())
                    break
    except Exception:
        pass

    it = load_interpreter(args.model)
    times, shapes = bench(it, args.n)

    print(" 출력 : %s" % shapes)
    if not any(len(s) == 2 and s[1] == 1024 for s in shapes):
        print("\n [경고] 1024차원 임베딩 출력이 없습니다.")
        print("        이 모델로는 우리 분류기를 못 씁니다 — 위 안내대로 다시 받으세요.")
    print()
    print(" 5초 오디오 1회 처리 (%d회 반복)" % args.n)
    print("   평균   %6.1f ms" % times.mean())
    print("   중앙   %6.1f ms" % np.median(times))
    print("   최소   %6.1f ms" % times.min())
    print("   최대   %6.1f ms" % times.max())
    print()

    p95 = np.percentile(times, 95)
    print(" 상위 5%% 느린 경우 %.1f ms" % p95)
    print()
    print("=" * 62)
    print(" 판정 (목표 1500 ms)")
    print("=" * 62)

    # 분류기 머리는 53만 파라미터라 YAMNet에 비하면 무시할 수준이지만
    # 여유를 두고 20% 더 잡는다
    est = p95 * 1.2
    print(" YAMNet + 분류기 예상 %.0f ms" % est)

    if est < 300:
        print(" → 여유 충분. 윈도우 간격을 0.5초까지 좁혀도 실시간 처리 가능")
    elif est < 1000:
        print(" → 목표 안에 들어옴. 윈도우 간격은 1초 이상 권장")
    else:
        print(" → 빠듯함. 윈도우 간격을 늘리거나 양자화(int8) 모델 검토 필요")

    print()
    print(" 참고: 실제 체감 지연 = 윈도우 간격 + 위 처리 시간")
    print("       예) 간격 1초 + 처리 %.0f ms = 약 %.1f초" % (est, 1 + est / 1000))


if __name__ == "__main__":
    main()
