from django.db import models


class AlertLog(models.Model):
    """RPi → 폰으로 전달된 소리 알림 1건의 로그"""

    sound_class = models.CharField(max_length=50)   # 예: siren, glass_breaking
    direction = models.IntegerField()               # 0~359 (도)
    danger = models.IntegerField()                  # 위험도
    timestamp = models.BigIntegerField()            # 폰이 받은 시각 (epoch millis)
    received_at = models.DateTimeField(auto_now_add=True)  # 서버가 받은 시각

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.sound_class} ({self.direction}°, danger={self.danger})"
