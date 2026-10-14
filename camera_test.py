"""
camera_test.py
--------------------
Công cụ DÒ CAMERA: thử lần lượt MỌI camera (số 0 đến 4) với MỌI cách mở
(DirectShow, DirectShow+MJPG, MSMF, mặc định), chụp mỗi cách 1 tấm hình, rồi xếp
tất cả vào 1 TẤM ẢNH DUY NHẤT để bạn nhìn bằng mắt xem cách nào cho hình ĐẸP.

CÁCH DÙNG (trong PyCharm: chuột phải file này > Run 'camera_test'):
    1. ĐÓNG hết app đang dùng camera (Zoom, Teams, Camera, trình duyệt...).
    2. Chạy file. Mất khoảng 30-90 giây (mỗi lần thử có thể chờ vài giây). Khung Run
       sẽ in tiến độ.
    3. Xong sẽ hiện 1 cửa sổ "Camera test" + lưu file camera_test_result.png cạnh
       file này. Nhìn xem ô nào là hình THẬT của bạn/căn phòng (không sọc, không đen).
    4. Đọc nhãn của ô đó, ví dụ "cam 1 | DirectShow". Mở main_spatial_ui_demo.py, sửa
       CAMERA_INDEX = 1 (số camera). Nếu nhãn ghi cách mở khác DirectShow+MJPG, nhắn
       lại cho mình nhãn đó để mình đặt đúng cách mở mặc định.
    5. Bấm phím bất kỳ trong cửa sổ để đóng.

Có thể gửi file camera_test_result.png cho mình để mình xem giúp.
Nhãn chữ KHÔNG DẤU vì OpenCV không vẽ được dấu tiếng Việt.
"""

import time

import cv2
import numpy as np

MAX_INDEX = 5            # thử camera số 0..4
TILE_W, TILE_H = 320, 240
COLUMNS = 4

WAYS = [
    ("DirectShow+MJPG", cv2.CAP_DSHOW, True),
    ("DirectShow", cv2.CAP_DSHOW, False),
    ("MSMF", cv2.CAP_MSMF, False),
    ("mac dinh", None, False),
]


def grab(index, backend, use_mjpg):
    """Thử mở 1 cách. Trả về (frame hoặc None, ghi chú ngắn)."""
    cap = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
    try:
        if not cap.isOpened():
            return None, "khong mo duoc"
        if use_mjpg:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        good, last = 0, None
        for _ in range(40):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                good += 1
                last = frame
                if good >= 10:          # bỏ vài frame đầu cho camera ổn định
                    break
            else:
                time.sleep(0.05)
        if last is None:
            return None, "mo duoc nhung khong doc duoc hinh"
        return last, f"{last.shape[1]}x{last.shape[0]}"
    finally:
        cap.release()


def make_tile(frame, label, note):
    tile = np.full((TILE_H, TILE_W, 3), (40, 40, 44), dtype=np.uint8)
    if frame is not None:
        tile[:] = cv2.resize(frame, (TILE_W, TILE_H))
    else:
        cv2.putText(tile, note, (10, TILE_H // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (140, 140, 150), 1, cv2.LINE_AA)
    cv2.rectangle(tile, (0, 0), (TILE_W, 22), (20, 20, 22), -1)
    cv2.putText(tile, label, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (55, 150, 210), 1, cv2.LINE_AA)
    cv2.rectangle(tile, (0, 0), (TILE_W - 1, TILE_H - 1), (75, 75, 80), 1)
    return tile


def main():
    tiles = []
    print("Dang do camera... (mat khoang 30-90 giay, vui long cho)")
    for index in range(MAX_INDEX):
        for name, backend, mjpg in WAYS:
            label = f"cam {index} | {name}"
            print(f"  thu {label} ...", end=" ", flush=True)
            try:
                frame, note = grab(index, backend, mjpg)
            except Exception as e:           # một số driver ném lỗi lạ
                frame, note = None, f"loi: {type(e).__name__}"
            print(note)
            tiles.append(make_tile(frame, label, note))

    rows = []
    for i in range(0, len(tiles), COLUMNS):
        row = tiles[i:i + COLUMNS]
        while len(row) < COLUMNS:
            row.append(np.full((TILE_H, TILE_W, 3), (20, 20, 22), dtype=np.uint8))
        rows.append(np.hstack(row))
    sheet = np.vstack(rows)

    cv2.imwrite("camera_test_result.png", sheet)
    print("Da luu: camera_test_result.png (cung thu muc voi file nay)")
    print("Nhin o nao co hinh THAT, khong song/den -> do la cach mo dung.")
    print("Bam phim bat ky trong cua so anh de dong.")
    cv2.imshow("Camera test - bam phim bat ky de dong", sheet)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
