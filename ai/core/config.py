import os

# core/ 의 부모 = ai/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATASET_PATH = os.path.join(ROOT, "dataset")
MFCC_PATH = os.path.join(DATASET_PATH, "mfcc")       # 특징·라벨·그룹·임계값 저장소
MODEL_PATH = os.path.join(ROOT, "model")             # 학습된 가중치
REALWORLD_PATH = os.path.join(DATASET_PATH, "realworld")

# 소리 4개(glass_breaking, siren, door_wood_knock, doorbell) + others
# features.CLASS_NAMES 와 반드시 같아야 함
NUM_CLASSES = 5
BATCH_SIZE = 32

LR = 1e-3
EPOCHS = 20
