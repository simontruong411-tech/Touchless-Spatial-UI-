"""
main_spatial_ui_demo.py  (bản RÚT GỌN)
--------------------
Spatial UI cho bác sĩ trong PHÒNG MỔ: điều khiển ảnh chẩn đoán, xương 3D, quy trình
ca mổ (theo Bảng kiểm WHO), đèn và gọi hỗ trợ bằng cử chỉ tay, KHÔNG chạm gì.
Đây là MÔ PHỎNG NGHIÊN CỨU, không phải thiết bị lâm sàng.

HAI TAY
  Tay PHẢI = con trỏ:  Point (ngón trỏ) = di chuyển;  Pinch (chụm) = bấm / kéo.
  Tay TRÁI:
    Snap       = ở camera: mở/đóng menu; ở màn Ảnh/Xương/Quy trình: thoát về camera.
    Fist       = đóng menu ngay ("phanh an toàn").
    Open palm  = đổi nghĩa của Pinch+kéo: Ảnh -> chỉnh sáng/tương phản
                 (ngang = tương phản, dọc = độ sáng); Xương -> cắt lớp (kéo dọc).
                 Vẫy tay trái đang xòe (lúc tay phải không Pinch) ở màn Ảnh =
                 lật ảnh (vẫy trái = SAU, vẫy phải = TRƯỚC).
  Hai tay xa/gần nhau = ZOOM (không tính khi đang chỉnh sáng/cắt lớp).

MÀN HÌNH (biến `mode`): IDLE (camera) / MENU_MAIN / IMAGE_VIEWER / MODEL_VIEWER /
  WORKFLOW. Menu một tầng: QUY TRINH, ANH, XUONG 3D, DEN, GOI Y TA, KHAN CAP.

AN TOÀN: Pinch+kéo tính theo quãng di chuyển và chỉ chạy khi đang Pinch (thả Pinch =
  "nhả côn"); nhiều tay cùng nhãn -> chọn tay lớn nhất; quy trình ca mổ không cho
  sang giai đoạn sau nếu còn mục chưa tick. (Đã gỡ vùng vô trùng và khóa xòe 2 tay
  theo yêu cầu -> phải đo "kích hoạt nhầm" để biện luận trong báo cáo.)

LÀM MƯỢT: world_landmarks của mỗi tay được làm mượt TRƯỚC khi nhận diện Point/
  Pinch/Fist/Open palm; SnapDetector luôn nhận dữ liệu GỐC (Snap rất nhanh, làm
  mượt sẽ mất tín hiệu). Pinch có hysteresis; mất dấu tay phải <= 5 frame thì giữ
  nguyên cursor và trạng thái pinch.

ẢNH & XƯƠNG: đặt ảnh vào "medical_images/", file .obj vào "medical_models/" TRƯỚC ca
  mổ bằng upload_tool.py (dùng chuột, cố ý không touchless). Xương mặc định là mô
  hình minh họa, không dùng chẩn đoán.

IOT: bấm DEN / GOI Y TA / KHAN CAP gửi HTTP tới ESP32 (iot.py, sửa ESP32_IP trước).
  Lệnh gọi đồng bộ, timeout 2 giây: nếu ESP32 mất mạng, vòng lặp có thể khựng tối đa
  2 giây mỗi lần bấm (nếu giật thì chuyển sang thread riêng).

ĐO LƯỜNG: mọi sự kiện ghi vào logs/session_*.csv (chuỗi băm SHA-256 chống sửa) +
  file _meta.json tóm tắt. Điền PARTICIPANT_ID / SCENARIO / CONDITIONS bên dưới
  (mã ẩn danh, KHÔNG thông tin bệnh nhân).
  PHÍM NGƯỜI QUAN SÁT: f = kích hoạt nhầm, x = bỏ sót cử chỉ, t = bắt đầu nhiệm vụ,
  y = nhiệm vụ xong, n = nhiệm vụ thất bại, q = thoát.
  PHÍM CAMERA: c = đổi sang cách mở camera khác (khi hình sọc/nhiễu/đen).
"""

import atexit
import cv2
import time

from hand_utils import (
    HandTracker, detect_gesture, is_pinching,
    GestureStabilizer, CursorSmoother, LandmarkSmoother,
    SwipeDetector, select_primary_hand,
)
from snap_detector import SnapDetector
from spatial_ui import SpatialMenu
from image_viewer import ImageViewer
from model_viewer import Model3DViewer
from or_workflow import WorkflowScreen
from measurement_logger import MeasurementLogger
import iot
from iot import turn_light_on, turn_light_off

# ---------------------------- CẤU HÌNH ----------------------------
INDEX_TIP = 8                          # landmark đầu ngón trỏ
LANDMARK_DOT_COLOR = (140, 140, 145)
LANDMARK_DOT_RADIUS = 2
COLOR_ACCENT = (55, 150, 210)          # BGR, cùng tông với spatial_ui.py

# Mất dấu tay phải tối đa ngần này frame vẫn coi là "tạm thời" (~150 ms ở 30 FPS).
MAX_MISSING_RIGHT_FRAMES = 5

ZOOM_SENSITIVITY = 0.01                # pixel khoảng cách 2 tay -> mức zoom
BRIGHTNESS_SENSITIVITY = 0.5           # kéo dọc -> độ sáng
CONTRAST_SENSITIVITY = 0.01            # kéo ngang -> tương phản

# Số thứ tự camera (0 = mặc định). Có webcam ngoài / app điện thoại thì thử 1 hoặc 2.
CAMERA_INDEX = 0

# Thông tin phiên thực nghiệm (ghi vào log, xem measurement_logger.py)
PARTICIPANT_ID = "P01"
SCENARIO = "mo_phong_ca_mo"
CONDITIONS = {"anh_sang": "", "khoang_cach_cm": "", "gang_tay": ""}

MENU_BUTTONS = ["QUY TRINH", "ANH", "XUONG 3D", "DEN", "GOI Y TA", "KHAN CAP"]
MENU_MODES = ("MENU_MAIN",)
FULLSCREEN_MODES = ("IMAGE_VIEWER", "MODEL_VIEWER", "WORKFLOW")   # màn thay cho camera

# Phím cho NGƯỜI QUAN SÁT: ghi điều phần mềm không tự biết
OBSERVER_KEYS = {
    ord('f'): ("FALSE_TRIGGER", "event"),
    ord('x'): ("MISSED_GESTURE", "event"),
    ord('t'): ("TASK_START", "task_start"),
    ord('y'): ("TASK_OK", "task_ok"),
    ord('n'): ("TASK_FAIL", "task_fail"),
}


# ---------------------------- HÀM PHỤ ----------------------------
def timed_call(fn):
    """Gọi 1 hàm IoT, đo độ trễ. Trả về (thành_công, độ_trễ_ms)."""
    t0 = time.perf_counter()
    ok = bool(fn())
    return ok, (time.perf_counter() - t0) * 1000.0


def log_iot(logger, mode, event, result):
    ok, ms = result
    logger.log_event(mode, event, detail="iot_ok" if ok else "iot_FAIL", latency_ms=ms)


def trigger_emergency_alert():
    """KHAN CAP: buzzer bíp nhanh + OLED "KHAN CAP!"."""
    print("[KHAN CAP] Bao dong! Buzzer + OLED...")
    return timed_call(iot.buzz_emergency)


def trigger_call_nurse_alert():
    """GOI Y TA: buzzer 2 tiếng chậm (khác âm khẩn cấp để phân biệt 2 mức)."""
    print("[GOI Y TA] Dang goi y ta ho tro! Buzzer + OLED...")
    return timed_call(iot.buzz_call_nurse)


def camera_options(preferred_index=CAMERA_INDEX):
    """Danh sách "cách mở camera" theo thứ tự ưu tiên:
    (số camera, tên cách mở, backend OpenCV, có ép MJPG không)."""
    indexes = [preferred_index] + [i for i in range(3) if i != preferred_index]
    ways = [("DirectShow+MJPG", cv2.CAP_DSHOW, True),
            ("DirectShow", cv2.CAP_DSHOW, False),
            ("MSMF", cv2.CAP_MSMF, False),
            ("mac dinh", None, False)]
    return [(i, name, be, mjpg) for i in indexes for (name, be, mjpg) in ways]


def open_camera(start=0, preferred_index=CAMERA_INDEX):
    """Mở webcam "chịu khó": thử lần lượt các cách trong camera_options() từ vị trí
    `start`, đọc tới khi có hình thật. Trả về (cap, frame, vị_trí_cách) hoặc
    (None, None, None). Phím 'c' gọi lại với start = vị trí kế tiếp.
    Vì sao cần: trên Windows camera có thể bị app khác chiếm, cần vài giây khởi động
    (frame đầu đen/nhiễu) hoặc trả định dạng làm hình sọc -> ép MJPG 640x480 và bỏ
    vài frame đầu thường khắc phục."""
    options = camera_options(preferred_index)
    for step in range(len(options)):
        k = (start + step) % len(options)
        index, name, backend, use_mjpg = options[k]
        cap = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            continue
        if use_mjpg:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        good, last = 0, None
        for _ in range(60):                       # ~3 giây chờ camera khởi động
            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                good += 1
                last = frame
                if good >= 8:                     # bỏ 7 frame đầu cho camera ổn định sáng
                    print(f"[camera] Dang dung: camera so {index}, cach mo {name}.  (hinh loi/song? bam phim 'c' de doi cach)")
                    return cap, last, k
            else:
                time.sleep(0.05)
        cap.release()
    return None, None, None


def draw_case_pill(display, text):
    """Thanh nhỏ góc dưới phải: giai đoạn ca + đồng hồ, thấy ở mọi màn hình."""
    if not text:
        return
    h, w = display.shape[:2]
    ts = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
    x1, y1 = w - 8, h - 8 - 24
    x0 = x1 - ts[0] - 16
    cv2.rectangle(display, (x0, y1), (x1, y1 + 22), (20, 20, 22), -1)
    cv2.rectangle(display, (x0, y1), (x1, y1 + 22), COLOR_ACCENT, 1)
    cv2.putText(display, text, (x0 + 8, y1 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_ACCENT, 1, cv2.LINE_AA)


def smoothed_copy(hand, landmark_smoother):
    """Bản sao của hand với world_landmarks đã làm mượt (chỉ để nhận diện Pinch/
    Point/Fist/Open palm; SnapDetector vẫn nhận `hand` gốc)."""
    out = dict(hand)
    out["world_landmarks"] = landmark_smoother.update(hand["world_landmarks"])
    return out


def image_detail(viewer):
    return f"anh={viewer.index + 1}/{len(viewer.image_paths)}"


def update_two_hand_zoom(viewer, allowed, left_hand, right_hand, last_distance):
    """Zoom theo khoảng cách đầu ngón trỏ 2 tay (xa ra = to, gần lại = nhỏ).
    Trả về khoảng cách mới để lưu cho frame sau; None nếu không đủ điều kiện (đặt về
    None để lần zoom sau không bị "nhảy" tính từ khoảng cách cũ)."""
    if not (allowed and left_hand is not None and right_hand is not None):
        return None
    lx, ly = left_hand["pixels"][INDEX_TIP]
    rx, ry = right_hand["pixels"][INDEX_TIP]
    current = ((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5
    if last_distance is not None:
        viewer.set_zoom(viewer.zoom + (current - last_distance) * ZOOM_SENSITIVITY)
    return current


# ---------------------------- CHƯƠNG TRÌNH CHÍNH ----------------------------
def main():
    tracker = HandTracker(model_path="hand_landmarker.task")
    snap_detector = SnapDetector()

    # Mỗi tay một bộ lọc riêng vì hai tay làm hai việc khác nhau.
    right_stabilizer = GestureStabilizer(history_size=6, min_agreement=4)
    left_stabilizer = GestureStabilizer(history_size=6, min_agreement=4)
    cursor_smoother = CursorSmoother(smoothing_factor=0.4)
    left_landmark_smoother = LandmarkSmoother(smoothing_factor=0.5)
    right_landmark_smoother = LandmarkSmoother(smoothing_factor=0.5)
    swipe_detector = SwipeDetector()

    # Menu/viewer cần kích thước khung hình -> open_camera đã đọc sẵn frame đầu.
    cap, first_frame, camera_option = open_camera()
    if cap is None:
        print("Khong mo/doc duoc camera sau khi thu nhieu cach. Hay kiem tra:")
        print("  1) Dong cac app dang dung camera (Zoom, Teams, Camera, trinh duyet, Discord...).")
        print("  2) Windows: Settings > Privacy & security > Camera > bat 'Let desktop apps access your camera'.")
        print("  3) Neu co nhieu camera, doi CAMERA_INDEX o dau file (thu 1 hoac 2).")
        print("  4) Rut ra cam lai webcam roi chay lai.")
        tracker.close()
        return
    frame_height, frame_width = first_frame.shape[:2]

    main_menu = SpatialMenu(buttons=MENU_BUTTONS, frame_width=frame_width, frame_height=frame_height)
    image_viewer = ImageViewer(frame_width=frame_width, frame_height=frame_height)
    model_viewer = Model3DViewer(frame_width=frame_width, frame_height=frame_height)
    if not image_viewer.has_images():
        print("[image_viewer] CANH BAO: khong tim thay anh nao trong thu muc 'medical_images/'.")
        print("[image_viewer] Hay tao thu muc nay (cung cap voi main_spatial_ui_demo.py) va dat vao vai file .jpg/.png de test.")

    logger = MeasurementLogger(participant_id=PARTICIPANT_ID, scenario=SCENARIO, conditions=CONDITIONS)
    atexit.register(logger.close)   # lỗi/đóng đột ngột vẫn đóng log + ghi tóm tắt
    workflow = WorkflowScreen(frame_width=frame_width, frame_height=frame_height, logger=logger)

    mode = "IDLE"            # IDLE | MENU_MAIN | IMAGE_VIEWER | MODEL_VIEWER | WORKFLOW
    light_on = False         # đồng bộ với ESP32 qua iot.py
    was_pinching = False     # pinch của frame trước (cạnh lên + hysteresis)
    last_pan_cursor = None   # cursor frame trước khi đang Pinch kéo (None = chưa kéo)
    last_two_hand_distance = None
    last_cursor_pos = None   # để "đóng băng" khi mất dấu tay phải ngắn
    missing_right_frames = 0

    def go_menu():
        """Về MENU_MAIN (nút BACK)."""
        nonlocal mode
        mode = "MENU_MAIN"
        main_menu.open()
        logger.log_event(mode, "BACK_TO_MENU_MAIN")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame.shape[1] != frame_width or frame.shape[0] != frame_height:
            # Đổi cách mở camera có thể đổi độ phân giải -> co lại cho khớp.
            frame = cv2.resize(frame, (frame_width, frame_height))
        frame = cv2.flip(frame, 1)  # lật gương cho dễ điều khiển

        hands = tracker.process(frame)
        right_hand = select_primary_hand(hands, "Right")   # tay cursor
        left_hand = select_primary_hand(hands, "Left")     # tay điều khiển

        if mode not in FULLSCREEN_MODES:
            for hand in hands:
                for (x, y) in hand["pixels"]:
                    cv2.circle(frame, (x, y), LANDMARK_DOT_RADIUS, LANDMARK_DOT_COLOR, -1, cv2.LINE_AA)

        # ---------- TAY TRÁI ----------
        left_status_text = "Left: (khong thay tay)"
        left_gesture = None      # gán lại mỗi frame, tránh nhớ nhầm giá trị cũ
        if left_hand is not None:
            left_gesture = left_stabilizer.update(
                detect_gesture(smoothed_copy(left_hand, left_landmark_smoother)))
            left_status_text = f"Left: {left_gesture or '...'}"

            snapped = snap_detector.update(left_hand)      # Snap dùng dữ liệu GỐC
            if snapped and mode in FULLSCREEN_MODES:
                was_in_mode = mode
                mode = "IDLE"
                left_status_text += f"  -> SNAP! thoat {was_in_mode}"
                logger.log_event(was_in_mode, f"SNAP_EXIT_{was_in_mode}")
            elif snapped:
                # Ở camera: Snap toggle menu (IDLE -> mở, đang ở menu -> đóng)
                if mode == "IDLE":
                    mode = "MENU_MAIN"
                    main_menu.open()
                    logger.log_event(mode, "SNAP_OPEN_MENU")
                else:
                    mode = "IDLE"
                    main_menu.close()
                    logger.log_event(mode, "SNAP_CLOSE_MENU")
                left_status_text += "  -> SNAP! toggle menu"

            if mode not in FULLSCREEN_MODES and left_gesture == "Fist" and mode in MENU_MODES:
                mode = "IDLE"
                main_menu.close()
                logger.log_event(mode, "FIST_CLOSE_MENU")
        else:
            snap_detector.reset()
            left_landmark_smoother.reset()

        # ---------- TAY PHẢI: cursor_pos + is_pinching_now ----------
        cursor_pos = None
        is_pinching_now = False
        right_status_text = "Right: (khong thay tay)"

        if right_hand is not None:
            missing_right_frames = 0
            right_smoothed = smoothed_copy(right_hand, right_landmark_smoother)
            right_gesture = right_stabilizer.update(detect_gesture(right_smoothed))
            right_status_text = f"Right: {right_gesture or '...'}"

            # Luôn cập nhật CursorSmoother cho liên tục, nhưng ở MENU/WORKFLOW (bấm nút
            # rời rạc) dùng vị trí ngón tay THẬT để phản hồi tức thì; nếu dùng cursor đã
            # làm mượt thì lúc vừa tới nút cursor còn "đuổi theo" nên có thể trượt click.
            raw_x, raw_y = right_hand["pixels"][INDEX_TIP]
            smoothed_x, smoothed_y = cursor_smoother.update(raw_x, raw_y)
            if mode in MENU_MODES or mode == "WORKFLOW":
                cursor_pos = (int(raw_x), int(raw_y))
            else:
                cursor_pos = (int(smoothed_x), int(smoothed_y))
            last_cursor_pos = cursor_pos
            is_pinching_now = is_pinching(right_smoothed, was_pinching)
        else:
            missing_right_frames += 1
            if missing_right_frames <= MAX_MISSING_RIGHT_FRAMES and last_cursor_pos is not None:
                # Mất dấu tạm thời -> giữ cursor và pinch cũ, không ngắt thao tác kéo.
                cursor_pos = last_cursor_pos
                is_pinching_now = was_pinching
                right_status_text = "Right: (mat dau tam thoi, giu nguyen)"
            else:
                cursor_smoother.reset()
                right_landmark_smoother.reset()
                last_cursor_pos = None
                last_pan_cursor = None
                last_two_hand_distance = None
                was_pinching = False

        # ---------- VẪY TAY TRÁI ở màn ẢNH: trái = SAU, phải = TRƯỚC ----------
        swipe_dir = None
        if (mode == "IMAGE_VIEWER" and left_hand is not None
                and left_gesture == "Open palm" and not is_pinching_now):
            swipe_dir = swipe_detector.update(left_hand)
        else:
            swipe_detector.update(None)
        if swipe_dir == "left":
            image_viewer.next_image()
            logger.log_event(mode, "IMG_NEXT_SWIPE", detail=image_detail(image_viewer))
            right_status_text += "  -> VAY TRAI: SAU"
        elif swipe_dir == "right":
            image_viewer.prev_image()
            logger.log_event(mode, "IMG_PREV_SWIPE", detail=image_detail(image_viewer))
            right_status_text += "  -> VAY PHAI: TRUOC"

        # ---------- CLICK / THAO TÁC theo từng màn hình ----------
        is_clicking = is_pinching_now
        just_pinched = is_pinching_now and not was_pinching     # chỉ bấm ở cạnh lên

        if cursor_pos is not None:
            if mode == "MENU_MAIN":
                hovered = main_menu.get_hover(cursor_pos)
                if just_pinched and hovered is not None:
                    right_status_text += f"  -> CLICK: {hovered}"
                    if hovered == "QUY TRINH":
                        mode = "WORKFLOW"
                        main_menu.close()
                        print("[CLICK] Mo Quy trinh ca mo")
                        logger.log_event(mode, "OPEN_QUY_TRINH")
                    elif hovered == "ANH":
                        mode = "IMAGE_VIEWER"
                        main_menu.close()
                        print("[CLICK] Mo Anh chan doan")
                        logger.log_event(mode, "OPEN_ANH")
                    elif hovered == "XUONG 3D":
                        mode = "MODEL_VIEWER"
                        main_menu.close()
                        last_pan_cursor = None
                        last_two_hand_distance = None
                        print("[CLICK] Mo Xuong 3D")
                        logger.log_event(mode, "OPEN_XUONG_3D")
                    elif hovered == "DEN":
                        light_on = not light_on
                        result = timed_call(turn_light_on if light_on else turn_light_off)
                        if not result[0]:
                            light_on = not light_on   # ESP32 không phản hồi -> giữ trạng thái cũ
                        state = "ON" if light_on else "OFF"
                        print(f"[CLICK] DEN (phong mo) -> {state}")
                        right_status_text += f" {state}"
                        log_iot(logger, mode, f"DEN_{state}", result)
                    elif hovered == "GOI Y TA":
                        log_iot(logger, mode, "GOI_Y_TA", trigger_call_nurse_alert())
                    elif hovered == "KHAN CAP":
                        log_iot(logger, mode, "KHAN_CAP", trigger_emergency_alert())

            elif mode == "IMAGE_VIEWER":
                hovered = image_viewer.get_hover_button(cursor_pos)
                # Tay trái xòe + Pinch kéo (không hover nút) = chỉnh sáng/tương phản.
                # Dùng chung điều kiện này để chặn zoom: kéo làm 2 tay đổi khoảng cách
                # và không được hiểu nhầm là ý định zoom.
                is_adjusting_tone = (is_pinching_now and hovered is None
                                     and left_hand is not None and left_gesture == "Open palm")

                if just_pinched and hovered is not None:
                    right_status_text += f"  -> CLICK: {hovered}"
                    if hovered == "TRUOC":
                        image_viewer.prev_image()
                        print("[CLICK] Anh TRUOC")
                        logger.log_event(mode, "IMG_PREV", detail=image_detail(image_viewer))
                    elif hovered == "SAU":
                        image_viewer.next_image()
                        print("[CLICK] Anh SAU")
                        logger.log_event(mode, "IMG_NEXT", detail=image_detail(image_viewer))
                    elif hovered == "RESET":
                        image_viewer.reset_view()
                        print("[CLICK] Reset zoom/pan/sang/tuong phan")
                        logger.log_event(mode, "IMG_RESET")
                    elif hovered == "BACK":
                        go_menu()
                elif is_pinching_now and hovered is None:
                    if last_pan_cursor is not None:
                        dx = cursor_pos[0] - last_pan_cursor[0]
                        dy = cursor_pos[1] - last_pan_cursor[1]
                        if is_adjusting_tone:
                            image_viewer.adjust_contrast(dx * CONTRAST_SENSITIVITY)
                            image_viewer.adjust_brightness(dy * BRIGHTNESS_SENSITIVITY)
                        else:
                            image_viewer.pan(dx, dy)
                    last_pan_cursor = cursor_pos
                else:
                    last_pan_cursor = None      # thả Pinch -> lần kéo sau không bị "nhảy"

                last_two_hand_distance = update_two_hand_zoom(
                    image_viewer, not is_adjusting_tone, left_hand, right_hand, last_two_hand_distance)

            elif mode == "WORKFLOW":
                hovered = workflow.get_hover(cursor_pos)
                if just_pinched and hovered is not None:
                    if workflow.click(hovered) == "BACK":
                        go_menu()
                        right_status_text += "  -> CLICK: BACK"

            elif mode == "MODEL_VIEWER":
                hovered = model_viewer.get_hover_button(cursor_pos)
                # Tay trái xòe + Pinch kéo = CẮT LỚP thay vì xoay.
                is_adjusting_clip = (is_pinching_now and hovered is None
                                     and left_hand is not None and left_gesture == "Open palm")

                if just_pinched and hovered is not None:
                    right_status_text += f"  -> CLICK: {hovered}"
                    if hovered == "LOP":
                        model_viewer.cycle_layer()
                        logger.log_event(mode, "MODEL_LAYER")
                    elif hovered == "GOC":
                        model_viewer.cycle_view()
                        logger.log_event(mode, "MODEL_VIEW")
                    elif hovered == "RESET":
                        model_viewer.reset_view()
                        logger.log_event(mode, "MODEL_RESET")
                    elif hovered == "BACK":
                        go_menu()
                elif is_pinching_now and hovered is None:
                    if last_pan_cursor is not None:
                        dx = cursor_pos[0] - last_pan_cursor[0]
                        dy = cursor_pos[1] - last_pan_cursor[1]
                        if is_adjusting_clip:
                            model_viewer.adjust_clip(dy)
                        else:
                            model_viewer.rotate(dx, dy)
                    last_pan_cursor = cursor_pos
                else:
                    last_pan_cursor = None

                # Zoom CHỈ khi không Pinch (đang Pinch xoay thì khoảng cách 2 tay đổi
                # theo, không được hiểu nhầm là zoom).
                last_two_hand_distance = update_two_hand_zoom(
                    model_viewer, not is_adjusting_clip and not is_pinching_now,
                    left_hand, right_hand, last_two_hand_distance)

        was_pinching = is_pinching_now

        # ---------- HIỂN THỊ ----------
        if mode == "IMAGE_VIEWER":
            display = image_viewer.draw(cursor_pos=cursor_pos, is_pinching_now=is_clicking)
        elif mode == "MODEL_VIEWER":
            display = model_viewer.draw(cursor_pos=cursor_pos, is_pinching_now=is_clicking)
        elif mode == "WORKFLOW":
            display = workflow.draw(cursor_pos=cursor_pos, is_pinching_now=is_clicking)
        else:
            if mode == "MENU_MAIN":
                main_menu.draw(frame, cursor_pos=cursor_pos, is_clicking=is_clicking)
            elif cursor_pos is not None:
                cv2.circle(frame, cursor_pos, 6, (225, 225, 225), 1, cv2.LINE_AA)
            display = frame
            cv2.putText(display, left_status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (225, 225, 225), 2)
            cv2.putText(display, right_status_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (225, 225, 225), 2)
            cv2.putText(display, f"Mode: {mode}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_ACCENT, 2)

        draw_case_pill(display, workflow.status_text() if workflow.case_start is not None else "")

        cv2.imshow("Spatial UI Demo", display)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('c'):
            # Đổi sang CÁCH MỞ CAMERA kế tiếp (khi hình sọc/nhiễu/đen)
            new_cap, _, new_option = open_camera(start=camera_option + 1)
            if new_cap is not None:
                cap.release()
                cap, camera_option = new_cap, new_option
        elif key in OBSERVER_KEYS:
            # Phím người quan sát -> tính tỉ lệ kích hoạt nhầm / bỏ sót / thời gian nhiệm vụ
            name, action = OBSERVER_KEYS[key]
            if action == "event":
                logger.log_event(mode, name)
            elif action == "task_start":
                logger.start_task()
            elif action == "task_ok":
                logger.end_task(success=True)
            elif action == "task_fail":
                logger.end_task(success=False)
            print(f"[QUAN SAT] {name}")

    cap.release()
    cv2.destroyAllWindows()
    tracker.close()
    logger.close()


if __name__ == "__main__":
    # Nếu lỗi giữa chừng: in dòng lỗi cuối thật rõ ở cuối khung Run và lưu toàn bộ vào
    # crash_report.txt để gửi người hỗ trợ chỉ cần đính kèm 1 file.
    try:
        main()
    except Exception:
        import sys
        import traceback
        report = traceback.format_exc()
        with open("crash_report.txt", "w", encoding="utf-8") as f:
            f.write(report)
        cv2.destroyAllWindows()
        print("=" * 60)
        print("CHUONG TRINH BI LOI. Noi dung day du da luu o file: crash_report.txt")
        print("DONG LOI CUOI CUNG:")
        print("   " + report.strip().splitlines()[-1])
        print("=" * 60)
        sys.exit(1)
