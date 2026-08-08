"""
Grabbit 소리 분류 — RPi 추론 (PyTorch 불필요)

필요한 것: numpy, tflite-runtime  (오디오 입력은 arecord 사용)
"""
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_NPZ = os.path.join(HERE, "grabbit_model.npz")
YAMNET_TFLITE = os.path.join(HERE, "yamnet.tflite")


def _interpreter(path):
    """tflite-runtime(가벼움) → ai_edge_litert → tensorflow 순으로 시도."""
    for mod, attr in (("tflite_runtime.interpreter", "Interpreter"),
                      ("ai_edge_litert.interpreter", "Interpreter"),
                      ("tensorflow", "lite")):
        try:
            m = __import__(mod, fromlist=[attr])
            cls = getattr(m, attr)
            if mod == "tensorflow":
                cls = cls.Interpreter
            return cls(model_path=path)
        except ImportError:
            continue

    raise ImportError("tflite-runtime 또는 tensorflow 가 필요합니다:\n"
                      "  pip install tflite-runtime")


class Detector:
    """5초 오디오 → 클래스 확률 → 알림 판정."""

    def __init__(self, model_npz=MODEL_NPZ, yamnet=YAMNET_TFLITE):
        if not os.path.exists(model_npz):
            raise FileNotFoundError(
                "%s 가 없습니다. PC에서 export/export_model.py 를 실행해 만드세요." % model_npz)
        if not os.path.exists(yamnet):
            raise FileNotFoundError(
                "%s 가 없습니다. README의 내려받기 안내를 보세요." % yamnet)

        z = np.load(model_npz, allow_pickle=True)
        self.z = z

        self.class_names = [str(s) for s in z["class_names"]]
        self.minority = set(int(v) for v in z["minority"])
        self.others = int(z["others"])
        self.thresholds = z["thresholds"]
        self.consecutive = z["consecutive"].astype(int)

        self.sr = int(z["sr"])
        self.clip_len = int(z["sr"]) * int(z["clip_sec"])
        self.gain_normalize = bool(z["gain_normalize"])
        self.target_rms = float(z["target_rms"])
        self.max_gain = float(z["max_gain"])

        self.emb_mean = z["emb_mean"]
        self.emb_std = z["emb_std"]
        self.n_models = int(z["n_models"])
        self.bn_eps = float(z["bn_eps"])

        # YAMNet 준비 — 입력 길이를 5초로 고정
        self.itp = _interpreter(yamnet)
        inp = self.itp.get_input_details()[0]
        self.itp.resize_tensor_input(inp["index"], [self.clip_len])
        self.itp.allocate_tensors()
        self.in_idx = self.itp.get_input_details()[0]["index"]

        # 1024차원 임베딩을 내놓는 출력을 찾는다
        self.emb_idx = None
        for d in self.itp.get_output_details():
            if len(d["shape"]) == 2 and d["shape"][-1] == 1024:
                self.emb_idx = d["index"]
        if self.emb_idx is None:
            raise RuntimeError(
                "이 yamnet.tflite 에는 1024차원 임베딩 출력이 없습니다.\n"
                "MediaPipe판(4MB)은 클래스 점수만 뱉으므로 쓸 수 없습니다. "
                "README의 안내대로 다시 받으세요.")

        # 알림 판정 상태
        self._run_cls, self._run_len = -1, 0
        self._last_alert = {}

    # ------------------------------------------------------------------
    # 전처리
    # ------------------------------------------------------------------

    def prepare(self, wave):
        """1차원 파형 → 5초 float32. 학습 때와 같은 규칙."""
        y = np.asarray(wave, dtype=np.float32)

        if y.ndim > 1:                       # 마이크 어레이 → 모노
            y = y.mean(axis=1)

        if len(y) < self.clip_len:
            y = np.pad(y, (0, self.clip_len - len(y)))
        elif len(y) > self.clip_len:
            y = y[-self.clip_len:]           # 가장 최근 5초

        if self.gain_normalize:
            rms = float(np.sqrt(np.mean(y ** 2)))
            if rms > 1e-8:
                gain = min(self.target_rms / rms, self.max_gain)
                y = np.clip(y * gain, -1.0, 1.0)

        return y.astype(np.float32)

    # ------------------------------------------------------------------
    # 추론
    # ------------------------------------------------------------------

    def embed(self, wave5):
        self.itp.set_tensor(self.in_idx, wave5)
        self.itp.invoke()
        return self.itp.get_tensor(self.emb_idx)      # (10, 1024)

    def classify(self, emb):
        """임베딩 (T,1024) → 클래스 확률. 앙상블 평균."""
        x = (emb - self.emb_mean) / self.emb_std

        # YamnetHead와 동일: 프레임 평균과 최댓값을 이어붙임
        feat = np.concatenate([x.mean(axis=0), x.max(axis=0)])

        probs = np.zeros(len(self.class_names), dtype=np.float64)
        for i in range(self.n_models):
            h = feat

            # BatchNorm1d (추론 모드)
            h = (h - self.z["m%d_bn_mean" % i]) / np.sqrt(
                self.z["m%d_bn_var" % i] + self.bn_eps)
            h = h * self.z["m%d_bn_w" % i] + self.z["m%d_bn_b" % i]

            h = self.z["m%d_fc1_w" % i] @ h + self.z["m%d_fc1_b" % i]
            h = np.maximum(h, 0.0)                    # ReLU (Dropout은 추론 시 없음)
            h = self.z["m%d_fc2_w" % i] @ h + self.z["m%d_fc2_b" % i]

            e = np.exp(h - h.max())
            probs += e / e.sum()

        return probs / self.n_models

    def predict(self, wave):
        """파형 → (클래스, 확신도, 전체확률)."""
        probs = self.classify(self.embed(self.prepare(wave)))
        c = int(np.argmax(probs))
        return c, float(probs[c]), probs

    # ------------------------------------------------------------------
    # 알림 판정 (연속 조건 + 쿨다운)
    # ------------------------------------------------------------------

    def should_alert(self, cls, conf, now, cooldown=30.0):
        """
        이번 판정으로 알림을 울릴지. 상태를 내부에 누적

        연속 조건: 같은 클래스가 consecutive[c]번 연속 나와야 울림
          사이렌처럼 오래 지속되는 소리는 높여도 놓치지 않지만,
          유리·노크·초인종은 1~2회만 나타나므로 높이면 아예 안 울림
        쿨다운: 한 번 울리면 그 시간 동안 같은 클래스는 다시 안 울림
          사이렌이 30초 울려도 사용자에겐 알림 1번이어야 함
        """
        fired = cls in self.minority and conf >= float(self.thresholds[cls])
        c = cls if fired else self.others

        if c == self._run_cls:
            self._run_len += 1
        else:
            self._run_cls, self._run_len = c, 1

        if c == self.others or self._run_len < self.consecutive[c]:
            return False

        if now - self._last_alert.get(c, -1e9) < cooldown:
            return False

        self._last_alert[c] = now
        return True

    def name(self, cls):
        return self.class_names[cls]
