import subprocess
import time
import re
from datetime import datetime

SCHOOL_WIFI_LIST = [
    "SUNGSHIN"
]

OUTPUT_FILE = "/tmp/indoor_status.txt"
INTERFACE = "wlan0"


def scan_wifi():
    try:
        result = subprocess.check_output(
            ["sudo", "iwlist", INTERFACE, "scan"],
            text=True,
            stderr=subprocess.DEVNULL
        )
        ssids = re.findall(r'ESSID:"(.*?)"', result)
        return ssids
    except Exception as e:
        print("Wi-Fi 스캔 오류:", e)
        return []


def is_indoor(ssids):
    for wifi in SCHOOL_WIFI_LIST:
        if wifi in ssids:
            return True
    return False


def write_status(indoor):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "INDOOR" if indoor else "OUTDOOR"

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"time={now}\n")
        f.write(f"status={status}\n")


def main():
    print("[실내/실외 판단 시작] 종료: Ctrl+C")
    while True:
        ssids = scan_wifi()
        indoor = is_indoor(ssids)

        write_status(indoor)

        print("현재 상태:", "실내" if indoor else "실외", f"(감지된 SSID 수: {len(ssids)})")

        time.sleep(5)


if __name__ == "__main__":
    main()
