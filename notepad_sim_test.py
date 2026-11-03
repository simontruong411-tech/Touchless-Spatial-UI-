"""
notepad_sim_test.py
--------------------
Test GIẢ LẬP (không cần webcam, không cần ESP32) cho chức năng KY TEN (notepad.py)
và việc đổi nút KHAN CAP -> KY TEN trong main_spatial_ui_demo.py.

Gồm 2 phần:
  A. Test riêng lớp Notepad và PalmHoldClear (không cần cửa sổ).
  B. Test cả vòng lặp main(): thay camera, bộ theo dõi tay, nhận diện cử chỉ, Snap, iot
     và cv2.imshow bằng bản giả có kịch bản; chạy main() thật rồi kiểm tra file PNG và
     nhật ký sinh ra.

CHẠY:  python notepad_sim_test.py
Kết quả mô phỏng KHÔNG phải số đo thật; nó chỉ chứng minh luồng logic chạy đúng.
Chưa kiểm được: webcam thật, nhận diện Pinch/Open palm thật, độ mượt khi vẽ ở ~14 FPS.
"""

import glob
import os
import shutil
import sys
import tempfile
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

passed, failed = 0, 0


def check(name, condition, extra=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [OK]   {name}")
    else:
        failed += 1
        print(f"  [LOI]  {name} {extra}")


# ----------------------------------------------------------------------------
# A. LỚP Notepad và PalmHoldClear
# ----------------------------------------------------------------------------
def test_classes():
    print("A. Notepad / PalmHoldClear")
    from notepad import Notepad, PalmHoldClear, COLOR_CANVAS_BG

    tmp = tempfile.mkdtemp()
    pad = Notepad(640, 480, save_dir=os.path.join(tmp, "d"))
    bg = np.array(COLOR_CANVAS_BG, dtype=np.uint8)

    check("tờ giấy trống: save() trả None và không tạo file", pad.save() is None
          and not os.path.exists(os.path.join(tmp, "d")))

    pad.start_stroke((100, 100))
    for i in range(1, 30):
        pad.draw_to((100 + i * 5, 100 + i * 2))
    pad.end_stroke()
    check("vẽ một nét làm canvas thay đổi", (pad.canvas != bg).any())

    path = pad.save()
    check("save() tạo file PNG", path is not None and os.path.isfile(path))
    saved = cv2.imread(path)
    check("PNG lưu có kích thước 640x480", saved is not None and saved.shape[:2] == (480, 640))
    # PNG phải sạch: không có chữ SAVE/BACK/con trỏ. Điểm trên nút SAVE (20..130, 20..64) phải là nền.
    check("PNG không dính nút/toolbar", (saved[20:64, 20:240] == bg).all())

    path2 = pad.save()
    check("hai lần lưu liên tiếp không đè nhau", path2 != path and os.path.isfile(path2))

    pad.start_stroke((300, 300))
    pad.end_stroke()
    check("chạm nhanh (chụm rồi thả) vẫn để lại dấu chấm", (pad.canvas[298:303, 298:303] != bg).any())

    pad.clear()
    check("clear() trả về nền trơn", (pad.canvas == bg).all())
    check("sau clear(), save() lại trả None", pad.save() is None)

    check("hover SAVE", pad.get_hover_button((50, 40)) == "SAVE")
    check("hover BACK", pad.get_hover_button((20 + 110 + 12 + 10, 40)) == "BACK")
    check("không hover chỗ khác", pad.get_hover_button((400, 400)) is None
          and pad.get_hover_button(None) is None)

    # draw() không được sửa canvas gốc
    before = pad.canvas.copy()
    frame = pad.draw(cursor_pos=(200, 200), is_pinching_now=True, clear_progress=0.5)
    check("draw() trả frame 480x640x3 và không sửa canvas gốc",
          frame.shape == (480, 640, 3) and (pad.canvas == before).all())

    # PalmHoldClear với đồng hồ giả
    hold = PalmHoldClear(hold_seconds=0.8)
    fired, prog = hold.update(True, now=10.0)
    check("mới xòe: chưa xóa, tiến độ 0", (fired, prog) == (False, 0.0))
    fired, prog = hold.update(True, now=10.4)
    check("giữ 0,4 s: tiến độ 0,5, chưa xóa", (not fired) and abs(prog - 0.5) < 1e-6)
    fired, prog = hold.update(True, now=10.85)
    check("giữ 0,85 s: xóa đúng 1 lần", fired and prog == 1.0)
    fired, prog = hold.update(True, now=11.5)
    check("vẫn giữ tiếp: KHÔNG xóa lần nữa", (not fired) and prog == 1.0)
    hold.update(False, now=12.0)
    hold.update(True, now=12.1)
    fired, _ = hold.update(True, now=13.0)
    check("thả ra rồi giữ lại: xóa được lần mới", fired)
    hold.update(True, now=20.0)
    fired, _ = hold.update(False, now=20.5)
    hold.update(True, now=20.6)
    fired, _ = hold.update(True, now=21.0)
    check("xòe thoáng qua (< 0,8 s) rồi thả: KHÔNG xóa", not fired)

    shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------
# B. CẢ VÒNG LẶP main()
# ----------------------------------------------------------------------------
def make_hand(label, xy, gesture, pinch):
    """Tay giả: chỉ mang những trường mà main_spatial_ui_demo.py đọc."""
    px = [(int(xy[0]), int(xy[1]))] * 21
    return {"type": label, "pixels": px, "world_landmarks": [(0.0, 0.0, 0.0)] * 21,
            "_gesture": gesture, "_pinch": pinch}


def build_script(menu_rect_ky_ten, menu_rect_goi_y_ta, save_rect, back_rect):
    """Trả về list các frame: mỗi frame là dict(right=(x,y,pinch)|None,
    left=gesture|None, snap=bool, key=int|None)."""
    def center(r):
        return (r[0] + r[2] // 2, r[1] + r[3] // 2)

    S = []

    def add(n, **kw):
        for _ in range(n):
            S.append(dict(right=None, left=None, snap=False, key=None, **kw)
                     if False else {**dict(right=None, left=None, snap=False, key=None), **kw})

    add(6)                                                   # camera, chưa có tay
    add(1, left="Open palm", snap=True)                      # Snap -> mở menu
    add(6, right=(*center(menu_rect_goi_y_ta), False))       # rê vào GOI Y TA
    add(2, right=(*center(menu_rect_goi_y_ta), True))        # bấm GOI Y TA (còn hoạt động)
    add(6, right=(*center(menu_rect_ky_ten), False))        # rê sang KY TEN
    add(3, right=(*center(menu_rect_ky_ten), True))         # bấm KY TEN -> NOTEPAD
    add(6, right=(300, 300, False))                          # vào notepad, tay ở giữa
    add(2, right=(300, 300, True))                           # hạ bút
    for i in range(1, 25):                                   # vẽ nét chéo
        add(1, right=(300 + i * 8, 300 + i * 3, True))
    add(4, right=(500, 380, False))                          # nhấc bút
    add(4, right=(*center(save_rect), False))                # rê lên SAVE
    add(3, right=(*center(save_rect), True))                 # bấm SAVE (lần 1: có nét)
    add(4, right=(300, 300, False))
    add(40, left="Open palm")                                # giữ Open palm ~1,2 s -> xóa
    add(4)                                                   # thả tay trái
    add(4, right=(*center(save_rect), False))
    add(3, right=(*center(save_rect), True))                 # bấm SAVE (lần 2: đã xóa -> trống)
    add(4, right=(*center(back_rect), False))
    add(3, right=(*center(back_rect), True))                 # BACK -> menu
    add(3)
    add(1, left="Open palm", snap=True)                      # Snap -> đóng menu
    add(3)
    add(1, key=ord('q'))                                     # thoát
    return S


def test_main_loop():
    print("B. Vòng lặp main() với camera/tay giả")
    import iot as iot_module
    from spatial_ui import SpatialMenu

    tmp = tempfile.mkdtemp()
    old_cwd = os.getcwd()
    os.chdir(tmp)                       # logs/, drawings/ ghi vào thư mục tạm
    try:
        import main_spatial_ui_demo as m

        buttons = m.MENU_BUTTONS
        check("menu có KY TEN và không còn KHAN CAP",
              "KY TEN" in buttons and "KHAN CAP" not in buttons and len(buttons) == 6)

        menu = SpatialMenu(buttons=buttons, frame_width=640, frame_height=480)
        rects = {b["label"]: b["rect"] for b in menu._buttons}
        from notepad import Notepad
        npad = Notepad(640, 480)
        script = build_script(rects["KY TEN"], rects["GOI Y TA"],
                              npad.buttons["SAVE"], npad.buttons["BACK"])

        # --- bản giả ---
        state = {"i": 0, "frames": 0, "iot_calls": []}

        class FakeCap:
            def read(self):
                return True, np.zeros((480, 640, 3), dtype=np.uint8)

            def release(self):
                pass

        class FakeTracker:
            def __init__(self, *a, **k):
                pass

            def process(self, frame):
                step = script[min(state["i"], len(script) - 1)]
                hands = []
                if step["right"] is not None:
                    x, y, pinch = step["right"]
                    hands.append(make_hand("Right", (x, y), "Pinch" if pinch else "Point", pinch))
                if step["left"] is not None:
                    hands.append(make_hand("Left", (100, 100), step["left"], False))
                return hands

            def close(self):
                pass

        class FakeSnap:
            def update(self, hand):
                step = script[min(state["i"], len(script) - 1)]
                return bool(step["snap"])

            def reset(self):
                pass

        class FakeSwipe:
            def update(self, *a, **k):
                return None

        def fake_waitkey(_ms):
            step = script[min(state["i"], len(script) - 1)]
            state["i"] += 1
            time.sleep(0.03)            # ~33 FPS giả để PalmHoldClear (đồng hồ thật) chạy được
            return step["key"] if step["key"] is not None else 255

        m.HandTracker = FakeTracker
        m.SnapDetector = FakeSnap
        m.SwipeDetector = FakeSwipe
        m.open_camera = lambda *a, **k: (FakeCap(), np.zeros((480, 640, 3), dtype=np.uint8), 0)
        m.detect_gesture = lambda hand: hand["_gesture"]
        m.is_pinching = lambda hand, was: hand["_pinch"]
        m.smoothed_copy = lambda hand, smoother: hand
        m.select_primary_hand = lambda hands, label: next((h for h in hands if h["type"] == label), None)
        m.iot.buzz_call_nurse = lambda: state["iot_calls"].append("nurse") or True
        m.iot.buzz_emergency = lambda: state["iot_calls"].append("EMERGENCY") or True
        shown = []
        cv2.imshow = lambda title, img: shown.append(img.copy())
        cv2.waitKey = fake_waitkey
        cv2.destroyAllWindows = lambda: None

        m.main()

        # --- kiểm tra kết quả ---
        pngs = sorted(glob.glob(os.path.join(tmp, "drawings", "*.png")))
        check("đúng 1 file PNG được lưu (lần SAVE thứ 2 trống nên không tạo file)", len(pngs) == 1,
              f"(thấy {len(pngs)})")
        if pngs:
            img = cv2.imread(pngs[0])
            from notepad import COLOR_CANVAS_BG
            ink = int((img != np.array(COLOR_CANVAS_BG, dtype=np.uint8)).any(axis=2).sum())
            check("PNG đã lưu có nét vẽ (lưu TRƯỚC khi xóa)", ink > 200, f"(pixel có mực: {ink})")
            # Lúc bấm nút KY TEN ở menu, kịch bản giữ Pinch thêm 2 frame ở vị trí nút menu:
            # chỗ đó KHÔNG được có mực (Pinch mang theo phải bị bỏ qua).
            gx, gy, gw, gh = rects["KY TEN"]
            region = img[gy:gy + gh, gx:gx + gw]
            stray = int((region != np.array(COLOR_CANVAS_BG, dtype=np.uint8)).any(axis=2).sum())
            check("không có vệt mực ở chỗ nút menu (Pinch mang theo bị bỏ qua)", stray == 0,
                  f"(pixel mực: {stray})")

        logs = sorted(glob.glob(os.path.join(tmp, "logs", "session_*.csv")))
        check("có file nhật ký", len(logs) == 1)
        text = open(logs[0], encoding="utf-8").read()
        for ev in ("OPEN_KY_TEN", "NOTE_SAVE", "NOTE_CLEAR", "BACK_TO_MENU_MAIN", "GOI_Y_TA"):
            check(f"nhật ký có sự kiện {ev}", ev in text)
        check("nhật ký có NOTE_SAVE;trong (lần lưu thứ 2 khi bảng trống)", "trong" in text)
        check("nhật ký KHÔNG có KHAN_CAP", "KHAN_CAP" not in text)
        from measurement_logger import verify_log
        ok, bad, n = verify_log(logs[0])
        check("chuỗi băm nhật ký còn toàn vẹn", ok, f"(dòng lỗi {bad})")
        check("GOI Y TA vẫn gọi iot, còi khẩn cấp KHÔNG bị gọi",
              state["iot_calls"].count("nurse") == 1 and "EMERGENCY" not in state["iot_calls"],
              f"(gọi: {state['iot_calls']})")
        check("đã vẽ nhiều frame hiển thị", len(shown) > 100)
        # Có frame hiển thị màn notepad (nền charcoal) và có frame có thanh tiến trình xóa
        notepad_frames = [f for f in shown if tuple(f[300, 600]) == (35, 34, 32) and tuple(f[5, 5]) == (35, 34, 32)]
        check("có frame hiển thị màn Ky ten", len(notepad_frames) > 20)
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_classes()
    test_main_loop()
    print(f"\nTONG KET: {passed} dat, {failed} loi")
    sys.exit(1 if failed else 0)
