# Touchless Spatial Interface in STERILE ROOM

Mo phong nghien cuu: bac si trong phong mo dieu khien anh chan doan, xuong 3D,
quy trinh ca mo (Bang kiem WHO), den va goi ho tro bang cu chi tay truoc webcam.
Python + MediaPipe + OpenCV, gui lenh qua Wi-Fi toi ESP32 (LED, buzzer, OLED).
**Day khong phai thiet bi lam sang.**

## Cai dat (Windows 11)
1. Cai Python 3.11 hoac 3.12 (tick "Add python.exe to PATH"). Cai Git.
2. Mo PowerShell trong thu muc nay:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Dam bao co du cac file: `snap_detector.py`, `spatial_ui.py`, `hand_landmarker.task`.
4. Sua `ESP32_IP` trong `iot.py` (xem IP trong Serial Monitor cua Arduino IDE).
5. Chay: `python main_spatial_ui_demo.py` (bam `q` de thoat, `c` de doi cach mo camera).
   Hinh camera loi: chay `python camera_test.py` de do camera.

## Phim nguoi quan sat
f = kich hoat nham, x = bo sot cu chi, t/y/n = bat dau/xong/that bai nhiem vu, q = thoat.

## ESP32
Nap `esp32code.ino` (sua WIFI_SSID, WIFI_PASSWORD, BUZZER_PASSIVE). Khong commit mat khau Wi-Fi that.

## Du lieu
Nhat ky do dac nam trong `logs/` (CSV co chuoi bam SHA-256). Ma nguoi thu an danh (P01...), khong luu thong tin benh nhan.
Danh muc kiem WHO la ban rut gon, can bac si/dieu duong ra soat.
