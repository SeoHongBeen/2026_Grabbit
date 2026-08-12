CLASS_MAP  = {
    "glass_breaking":   0,  # 유리 깨짐
    "siren":            1,  # 사이렌
    "door_wood_knock":  2,  # 노크 소리
    "doorbell":         3,  # 초인종 (차임·인터폰 부저)
}


def map_label(category):
    return CLASS_MAP.get(category, 4)  # 나머지는 others
