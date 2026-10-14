"""
iot.py
--------------------
Cầu nối giữa Gesture Engine (Python) và ESP32 thật, gửi lệnh bật/tắt
đèn LED 3.3V (nối trực tiếp vào GPIO của ESP32, không qua relay) bằng
HTTP GET request qua Wi-Fi.

CÁCH DÙNG:
    from iot import turn_light_on, turn_light_off

    turn_light_on()   # gửi lệnh bật đèn LED
    turn_light_off()  # gửi lệnh tắt đèn LED

TRƯỚC KHI DÙNG:
    1. Đảm bảo ESP32 đã lên Wi-Fi và bạn đã lấy được IP từ Serial Monitor
       (ví dụ: 192.168.1.18).
    2. Sửa lại ESP32_IP bên dưới cho khớp đúng IP đó.
    3. Máy tính chạy Python và ESP32 phải cùng chung 1 mạng Wi-Fi.
    4. Cài thư viện requests nếu chưa có:  pip install requests

LƯU Ý: IP có thể đổi mỗi lần ESP32 khởi động lại (do router cấp DHCP động).
Nếu sau này lệnh không gửi được nữa, mở lại Serial Monitor xem IP mới rồi
cập nhật lại ESP32_IP bên dưới.
"""

import requests

# ==== SỬA IP NÀY CHO KHỚP VỚI IP HIỆN TẠI CỦA ESP32 ====
ESP32_IP = "192.168.1.20"

# Thời gian chờ tối đa (giây) trước khi coi là gửi lệnh thất bại — để
# tránh trường hợp ESP32 mất kết nối làm Python bị treo chờ vô thời hạn.
REQUEST_TIMEOUT = 2.0


def _send_command(path):
    """
    Gửi 1 HTTP GET request tới ESP32 theo đường dẫn (path) cho trước.
    Trả về True nếu gửi thành công (ESP32 phản hồi status 200),
    False nếu có lỗi (ESP32 tắt, sai IP, mất Wi-Fi, timeout, ...).

    Không để lỗi mạng làm crash toàn bộ chương trình Gesture Engine —
    chỉ in cảnh báo ra console rồi trả về False, để phần còn lại của
    ứng dụng (Spatial UI, Notepad, Speak Board) vẫn chạy bình thường
    dù ESP32 có đang offline.
    """
    url = f"http://{ESP32_IP}{path}"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            print(f"[iot.py] OK -> {url} : {response.text}")
            return True
        else:
            print(f"[iot.py] ESP32 tra ve loi status {response.status_code} -> {url}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"[iot.py] KHONG gui duoc lenh toi ESP32 ({url}). Loi: {e}")
        return False


def turn_light_on():
    return _send_command("/light/on")


def turn_light_off():
    return _send_command("/light/off")


# -- Buzzer + OLED (esp32code.ino ban co OLED/buzzer) --
def buzz_emergency():
    """Coi bao KHAN CAP: bip nhanh lien tuc ~3 giay."""
    return _send_command("/buzzer/emergency")


def buzz_call_nurse():
    """Coi GOI Y TA: 2 tieng bip cham (khac am thanh khan cap)."""
    return _send_command("/buzzer/nurse")


def buzz_off():
    return _send_command("/buzzer/off")


def oled_show(line1="", line2=""):
    """Hien 2 dong chu (toi da 10 ky tu/dong, KHONG dau) tren OLED trong 4 giay."""
    from urllib.parse import quote
    return _send_command(f"/oled?l1={quote(line1[:10])}&l2={quote(line2[:10])}")


# -- Test nhanh khi chạy trực tiếp file này (python iot.py) --
if __name__ == "__main__":
    import time

    print(f"Dang test ket noi toi ESP32 tai {ESP32_IP} ...")
    print("Bat den...")
    turn_light_on()
    time.sleep(2)
    print("Tat den...")
    turn_light_off()
    print("Test buzzer GOI Y TA..."); buzz_call_nurse(); time.sleep(3)
    print("Test buzzer KHAN CAP..."); buzz_emergency(); time.sleep(4)
    oled_show("XIN CHAO", "OLED OK"); time.sleep(5)
    print("Test xong. Kiem tra lai console phia tren xem co dong loi nao khong.")
