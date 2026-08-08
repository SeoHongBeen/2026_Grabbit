import torch
import torch.nn as nn
import torch.nn.functional as F


class CNN(nn.Module):
    def __init__(self, num_classes=5):
        super().__init__()

        self.conv1 = nn.Conv2d(1, 16, 3, padding=1)
        self.bn1   = nn.BatchNorm2d(16)
        self.conv2 = nn.Conv2d(16, 32, 3, padding=1)
        self.bn2   = nn.BatchNorm2d(32)
        self.conv3 = nn.Conv2d(32, 64, 3, padding=1)
        self.bn3   = nn.BatchNorm2d(64)

        self.pool = nn.MaxPool2d(2)

        # 거대한 flatten+fc1 대신 Global Average Pooling → 파라미터 급감(과적합 방지)
        self.gap = nn.AdaptiveAvgPool2d(1)
        self.dropout = nn.Dropout(0.3)
        self.fc = nn.Linear(64, num_classes)

    def forward(self, x):
        x = self.pool(F.relu(self.bn1(self.conv1(x))))
        x = self.pool(F.relu(self.bn2(self.conv2(x))))
        x = self.pool(F.relu(self.bn3(self.conv3(x))))

        x = self.gap(x)               # (B, 64, 1, 1)
        x = x.view(x.size(0), -1)     # (B, 64)

        x = self.dropout(x)
        x = self.fc(x)
        return x


class YamnetHead(nn.Module):
    """
    YAMNet 임베딩 (T, 1024) 위에 얹는 작은 분류기

    YAMNet 자체는 고정(사전학습 그대로)이고 이 머리만 학습

    프레임 집계는 평균과 최댓값을 이어붙인다:
      - 평균: 사이렌·불처럼 5초 내내 이어지는 소리에 유리
      - 최댓값: 유리 깨짐·노크처럼 1~2프레임에만 나타나는 소리에 유리
    한쪽만 쓰면 반대 성격의 소리를 놓침
    """

    def __init__(self, num_classes=5, in_dim=1024, hidden=256, dropout=0.3):
        super().__init__()

        self.norm = nn.BatchNorm1d(in_dim * 2)
        self.fc1 = nn.Linear(in_dim * 2, hidden)
        self.dropout = nn.Dropout(dropout)
        self.fc2 = nn.Linear(hidden, num_classes)

    def forward(self, x):
        # x: (B, T, 1024)
        mean = x.mean(dim=1)
        mx = x.max(dim=1).values
        x = torch.cat([mean, mx], dim=1)     # (B, 2048)

        x = self.norm(x)
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        return x
