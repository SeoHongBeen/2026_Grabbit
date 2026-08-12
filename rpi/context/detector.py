from gps import get_gps
from wifi import get_wifi_count


def detect_mode():

    gps = get_gps()
    wifi = get_wifi_count()

    accuracy = gps["accuracy"]

    if accuracy <= 20:
        return "OUTDOOR"

    elif accuracy >= 50 and wifi >= 5:
        return "INDOOR"

    else:
        return "UNKNOWN"


if __name__ == "__main__":
    print("Mode :", detect_mode())
