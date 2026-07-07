import os

os.environ["NUMBA_CACHE_DISABLE"] = "1"
os.environ["LIBROSA_CACHE_DIR"] = ""

import librosa
import numpy as np
import pandas as pd
from tqdm import tqdm
import matplotlib.pyplot as plt
import seaborn as sns
import soundfile as sf

meta_path = r"C:\hj\Grabbit\2026_Grabbit\ai\dataset\ESC-50\meta\esc50.csv"
audio_dir = r"C:\hj\Grabbit\2026_Grabbit\ai\dataset\ESC-50\audio"

df = pd.read_csv(meta_path)
print(df.head())


# Extract MFCC features from audio files
def extract_mfcc(file_path, n_mfcc=40):
    y, sr = sf.read(file_path)

    if y.ndim > 1:
        y = np.mean(y, axis=1)

    mfcc = librosa.feature.mfcc(
        y=y,
        sr=sr,
        n_mfcc=n_mfcc
    )

    return mfcc

    # 평균값으로 고정 길이 feature 만들기
    mfcc_mean = np.mean(mfcc, axis=1)

    return mfcc_mean

# Extract MFCC features and labels for all audio files
features = []
labels = []

for idx, row in tqdm(df.iterrows(), total=len(df)):
    file_path = os.path.join(audio_dir, row["filename"])
    
    if idx == 0:
        print(file_path)
        print(os.path.exists(file_path))
        
    mfcc = extract_mfcc(file_path)
    
    features.append(mfcc)
    labels.append(row["category"])
    

# Save features and labels as numpy arrays
X = np.array(features)
y = np.array(labels)

np.save("mfcc_features.npy", X)     # 실행 위치에 저장됨, 이후 ai/features로 옮김
np.save("labels.npy", y)

print("저장 완료", X.shape)

# Check the distribution of labels
label_counts = pd.Series(y).value_counts().sort_index()
print(label_counts)

# Plot the distribution of labels
plt.figure(figsize=(12, 6))
sns.barplot(x=label_counts.index, y=label_counts.values)

plt.xticks(rotation=90)
plt.title("ESC-50 Class Distribution")
plt.xlabel("Class")
plt.ylabel("Count")

plt.tight_layout()
plt.show()