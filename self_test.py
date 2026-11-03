"""
self_test.py
--------------------
CHẾ ĐỘ TỰ KIỂM TRA (self-test) — phần mềm TỰ RA ĐỀ, TỰ CHẤM, TỰ ĐO, để nhóm có số
liệu định lượng mà không cần nhiều người thử và không cần người quan sát ghi tay.

VÌ SAO CẦN FILE NÀY:
  Ban giám khảo yêu cầu số liệu về: độ chính xác từng cử chỉ, bỏ sót, kích hoạt nhầm,
  độ trễ (trung bình và P95), tốc độ khung hình, ảnh hưởng của ánh sáng/khoảng cách/
  găng tay/người đi ngang, và hiệu quả của cơ chế chống kích hoạt nhầm. Chương trình
  chính (main_spatial_ui_demo.py) không biết người dùng ĐỊNH làm cử chỉ gì, nên không
  tự chấm đúng/sai được. Ở đây phần mềm RA ĐỀ trước ("hãy chụm tay"), nên nó biết đáp
  án đúng và tự chấm.

QUY TRÌNH 1 PHIÊN (khoảng 7-8 phút):
  1. Màn giới thiệu: đọc hướng dẫn, bấm SPACE để bắt đầu.
  2. PHẦN A — CÁC LƯỢT THỬ CỬ CHỈ: mỗi cử chỉ REPS_PER_GESTURE lần, xáo trộn thứ tự
     ngẫu nhiên (để người thử không đoán trước được, tránh "học thuộc"). Mỗi lượt:
       CHUẨN BỊ (READY_TIME_S giây, hiện tên cử chỉ) -> LÀM NGAY! (tối đa
       TRIAL_TIMEOUT_S giây) -> hiện ĐÚNG / BỎ SÓT.
  3. PHẦN B — NGHỈ TỰ NHIÊN (REST_PHASE_S giây): người thử cử động tay tự nhiên (nói
     chuyện, chỉ trỏ, gãi đầu...) nhưng KHÔNG cố ra lệnh. Mọi "lệnh" phần mềm nhận được
     lúc này đều là KÍCH HOẠT NHẦM. Phần mềm đếm song song 3 mức:
        Mức 1 - KHÔNG chống nhầm : nhận diện thô từng khung hình, không làm mượt, không
                                   hysteresis, không yêu cầu xòe tay khi vẩy.
        Mức 2 - CÓ chống nhầm    : đúng như chương trình chính (làm mượt, bỏ phiếu đa số,
                                   hysteresis 2 ngưỡng, chỉ bấm ở cạnh lên, thời gian nghỉ).
        Mức 3 - CÓ thêm ngữ cảnh : ở màn camera chỉ búng tay mới có tác dụng (mở menu);
                                   chụm/nắm/vẩy khi menu đóng không gây ra lệnh nào.
     -> Đây chính là THÍ NGHIỆM ĐỐI CHỨNG "có/không có cơ chế chống nhầm" mà giám khảo
        gợi ý, đo trên CÙNG một đoạn dữ liệu nên so sánh công bằng.
  4. PHẦN C — THỬ IoT (nếu IOT_TRIALS > 0): tự gửi lệnh bật/tắt đèn tới ESP32, đo độ
     trễ và tỉ lệ thành công.
  5. Màn tổng kết: hiện kết quả chính; bấm SPACE hoặc q để thoát.

PHÍM TRONG LÚC CHẠY:
  SPACE = bắt đầu / tiếp tục     p = tạm dừng / chạy tiếp
  z     = HỦY lượt vừa rồi (người thử làm sai đề, vd làm nhầm tay) -> lượt đó không tính
          và được xếp lại vào cuối để đủ số lượt
  q     = thoát (dữ liệu đã đo vẫn được lưu)

CÁC FILE TẠO RA (thư mục logs/):
  selftest_<giờ>.csv           : 1 dòng = 1 lượt thử / 1 kết quả nghỉ / 1 lệnh IoT,
                                 có mã băm SHA-256 nối chuỗi như measurement_logger.py
  selftest_<giờ>_summary.json  : tóm tắt: độ chính xác từng cử chỉ (kèm khoảng tin cậy
                                 95%), ma trận nhầm lẫn, độ trễ, kích hoạt nhầm/phút 3
                                 mức, hiệu năng (FPS...), điều kiện thử, các ngưỡng đang dùng
  Kiểm tra file không bị sửa:  python self_test.py --verify logs/selftest_xxx.csv
  Gộp nhiều phiên (nhiều điều kiện) thành 1 bảng Excel: python selftest_report.py

ĐỊNH NGHĨA CÁC SỐ ĐO (để ghi đúng vào báo cáo):
  - Độ chính xác (tỉ lệ nhận đúng) = số lượt ĐÚNG / số lượt hợp lệ (không tính lượt hủy).
  - Bỏ sót = lượt hết giờ mà không nhận ra cử chỉ được yêu cầu.
  - Thời gian phản hồi (response_s) = từ lúc hiện "LAM NGAY!" tới lúc phần mềm nhận ra.
    GỒM CẢ thời gian người thử phản xạ + làm động tác, nên dùng để so sánh độ dễ làm
    giữa các cử chỉ / điều kiện, KHÔNG phải độ trễ của máy.
  - Độ trễ hệ thống (system_latency_ms) = từ đầu khung hình ĐẦU TIÊN mà tư thế tay đã
    xuất hiện (bộ nhận diện thô thấy) tới lúc phần mềm chính thức "chốt" lệnh. Gồm thời
    gian xử lý + thời gian chờ bỏ phiếu đa số. KHÔNG gồm độ trễ bên trong webcam (không
    đo được bằng phần mềm) — cần ghi rõ hạn chế này trong báo cáo.
  - Lệnh khác trong lượt (other_commands) = số lệnh KHÔNG được yêu cầu mà phần mềm phát
    ra trong lúc người thử đang làm cử chỉ khác (kích hoạt nhầm trong lúc thao tác).
  - Tỉ lệ khung hình thấy tay (hand_visible_pct) = % khung hình trong lượt mà MediaPipe
    tìm thấy bàn tay cần dùng -> cho thấy ảnh hưởng của găng tay, ánh sáng, khoảng cách.

GHI CHÚ TRUNG THỰC: người thử là chính tác giả (biết rõ hệ thống) nên kết quả thường
TỐT HƠN người dùng mới. Đây là "kiểm thử kỹ thuật", chưa phải nghiên cứu người dùng.
Chữ trên màn hình KHÔNG DẤU vì OpenCV không vẽ được dấu tiếng Việt.
"""

import csv
import json
import math
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime

import cv2

from hand_utils import (
    HandTracker, detect_gesture, is_pinching, pinch_ratio,
    GestureStabilizer, LandmarkSmoother, select_primary_hand,
    PINCH_RATIO_THRESHOLD,
)
from snap_detector import SnapDetector
import swipe
from swipe import SwipeDetector, SwipeTrace
from measurement_logger import _row_hash
from perf_monitor import PerfMonitor, describe

# ============================ CẤU HÌNH (sửa trước mỗi phiên) ============================
# Mã ẩn danh người thử (P01, P02...). KHÔNG ghi tên thật.
PARTICIPANT_ID = "P01"

# Điều kiện của PHIÊN NÀY — mỗi phiên chỉ nên đổi 1 yếu tố so với phiên chuẩn, để biết
# yếu tố nào ảnh hưởng. Ghi đúng sự thật, vì selftest_report.py dựa vào đây để gộp bảng.
CONDITIONS = {
    "anh_sang": "sang",          # sang / toi / den_chieu_thang
    "khoang_cach_cm": "80",      # 50 / 80 / 120 (đo bằng thước từ camera tới bàn tay)
    "gang_tay": "khong",         # khong / co (ghi màu găng vào CONDITION_NOTE)
    "nguoi_di_ngang": "khong",   # khong / co (nhờ 1 bạn đi qua lại phía sau)
}
CONDITION_NOTE = ""              # ghi chú thêm, vd "gang nitrile xanh", "den ban 60W"

# Số lượt cho MỖI cử chỉ. 10 lượt x 7 cử chỉ = 70 lượt ~ 4-5 phút. Muốn chắc chắn
# hơn thì tăng lên 20 (khoảng tin cậy hẹp lại), nhưng phiên sẽ dài gấp đôi.
REPS_PER_GESTURE = 10

# Danh sách cử chỉ được thử (bỏ bớt nếu muốn phiên ngắn hơn).
# Đã BỎ "FIST" khỏi danh sách thử theo quyết định của nhóm (muốn thử lại thì thêm
# "FIST" vào danh sách này; phần chấm Fist vẫn giữ nguyên trong code).
GESTURES_TO_TEST = ["POINT", "PINCH", "SNAP", "OPEN_PALM",
                    "SWIPE_LEFT", "SWIPE_RIGHT", "ZOOM"]

READY_TIME_S = 1.5        # thời gian hiện "CHUAN BI" trước mỗi lượt
TRIAL_TIMEOUT_S = 4.0     # quá thời gian này mà chưa nhận ra = BỎ SÓT
RESULT_SHOW_S = 0.8       # thời gian hiện kết quả ĐÚNG/BỎ SÓT
REST_PHASE_S = 60         # thời lượng phần NGHỈ TỰ NHIÊN (đo kích hoạt nhầm)
ZOOM_RATIO = 1.4          # 2 tay phải ra xa thêm >= 40% so với lúc bắt đầu lượt

# Thử IoT: số lệnh gửi tới ESP32 (0 = bỏ qua, ví dụ khi không mang mạch theo).
IOT_TRIALS = 0

# Mỗi lượt vẩy được ghi thêm số đo chẩn đoán (SwipeTrace, trong swipe.py) vào cột detail.

CAMERA_INDEX = 0
RANDOM_SEED = None        # None = tự lấy theo giờ (được ghi lại trong file tóm tắt)

# Thông số bộ lọc — PHẢI giống main_spatial_ui_demo.py để kết quả đại diện cho phần mềm thật.
STABILIZER_HISTORY, STABILIZER_AGREEMENT = 6, 4
LANDMARK_SMOOTHING = 0.5
MAX_MISSING_RIGHT_FRAMES = 5
INDEX_TIP = 8

# Tên hiển thị (không dấu) và tay dùng cho từng cử chỉ.
GESTURE_INFO = {
    "POINT":       ("TAY PHAI: CHI NGON TRO (Point)", "Right"),
    "PINCH":       ("TAY PHAI: CHUM NGON CAI + NGON TRO (Pinch)", "Right"),
    "SNAP":        ("TAY TRAI: BUNG TAY (Snap)", "Left"),
    "FIST":        ("TAY TRAI: NAM TAY (Fist)", "Left"),
    "OPEN_PALM":   ("TAY TRAI: XOE TAY (Open palm)", "Left"),
    "SWIPE_LEFT":  ("TAY TRAI DANG XOE: VAY SANG TRAI", "Left"),
    "SWIPE_RIGHT": ("TAY TRAI DANG XOE: VAY SANG PHAI", "Left"),
    "ZOOM":        ("HAI TAY: DUA RA XA NHAU (Zoom)", "Both"),
}
# Cử chỉ dạng "tư thế giữ yên": phải THẢ ra rồi làm lại nếu lúc bắt đầu lượt tay đã ở
# sẵn tư thế đó (nếu không, lượt sẽ "đúng" ngay lập tức mà người thử chưa làm gì).
STATE_GESTURES = {"POINT": "Point", "FIST": "Fist", "OPEN_PALM": "Open palm"}

COLUMNS = ["timestamp_real", "seconds_since_start", "section", "item", "result",
           "detected", "response_s", "system_latency_ms", "hand_visible_pct",
           "other_commands", "detail", "row_hash"]

COLOR_ACCENT = (55, 150, 210)
COLOR_OK = (120, 190, 90)
COLOR_BAD = (70, 80, 230)
COLOR_TEXT = (235, 235, 235)


# ============================ HÀM PHỤ ============================
def wilson_interval(successes, n, z=1.96):
    """Khoảng tin cậy 95% của một tỉ lệ (phương pháp Wilson — dùng tốt cả khi số lượt
    ít, ví dụ 10 lượt). Ý nghĩa: nếu lặp lại thí nghiệm nhiều lần, tỉ lệ thật nằm trong
    khoảng này với độ tin cậy 95%. Số lượt càng nhiều, khoảng càng hẹp."""
    if n == 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def smoothed_copy(hand, landmark_smoother):
    """Giống hàm cùng tên trong main_spatial_ui_demo.py."""
    out = dict(hand)
    out["world_landmarks"] = landmark_smoother.update(hand["world_landmarks"])
    return out


def index_tip_distance(left_hand, right_hand):
    lx, ly = left_hand["pixels"][INDEX_TIP]
    rx, ry = right_hand["pixels"][INDEX_TIP]
    return ((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5


class ChainCsv:
    """Ghi CSV có mã băm nối chuỗi (cùng cách với measurement_logger.py): sửa/xóa/chèn
    1 dòng bất kỳ sẽ bị phát hiện bằng verify_csv()."""

    def __init__(self, path):
        self.path = path
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(COLUMNS)
        self._prev = "GENESIS"
        self._t0 = time.perf_counter()

    def write(self, section, item, result="", detected="", response_s="", system_latency_ms="",
              hand_visible_pct="", other_commands="", detail=""):
        fields = [datetime.now().astimezone().isoformat(timespec="milliseconds"),
                  f"{time.perf_counter() - self._t0:.3f}", section, item, result, detected,
                  response_s, system_latency_ms, hand_visible_pct, other_commands, detail]
        h = _row_hash(self._prev, fields)
        self._prev = h
        self._writer.writerow(fields + [h])
        self._file.flush()          # ghi ngay xuống đĩa, tắt đột ngột cũng không mất

    @property
    def final_hash(self):
        return self._prev

    def close(self):
        self._file.close()


def verify_csv(path):
    """Tính lại chuỗi băm. Trả về (ok, dòng_lỗi_đầu_tiên_hoặc_None, số_dòng_hợp_lệ)."""
    prev, n = "GENESIS", 0
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        if next(reader, None) != COLUMNS:
            return False, 1, 0
        for i, row in enumerate(reader, start=2):
            if len(row) != len(COLUMNS) or _row_hash(prev, row[:-1]) != row[-1]:
                return False, i, n
            prev = row[-1]
            n += 1
    return True, None, n


def draw_banner(frame, lines, color=COLOR_ACCENT, progress=None):
    """Vẽ khung chữ phía trên khung hình. lines = [(chữ, cỡ), ...]."""
    h, w = frame.shape[:2]
    height = 22 + sum(int(34 * s) for _, s in lines)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, height), (20, 20, 22), -1)
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
    y = 10
    for text, scale in lines:
        y += int(34 * scale)
        cv2.putText(frame, text, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75 * scale, color, 2, cv2.LINE_AA)
    if progress is not None:   # thanh thời gian còn lại của lượt
        cv2.rectangle(frame, (0, height - 6), (int(w * max(0.0, min(1.0, progress))), height), color, -1)


def make_swipe_detector():
    return SwipeDetector()


def swipe_settings():
    """Các hằng số SWIPE_* của swipe.py đang dùng (ghi vào _summary.json để biết phiên
    đo dùng ngưỡng nào)."""
    return {k: v for k, v in vars(swipe).items() if k.startswith("SWIPE_")}


def diag_text(d):
    """Biến dict last_diag của SwipeDetector thành chuỗi 'v2_khoa=giatri;...' (bỏ các trường rỗng)."""
    keep = ("reason", "dist_hs", "speed_hs", "peak_hs", "ratio", "duration", "windup_hs", "dir", "open_dropped")
    return ";".join(f"v2_{k}={d[k]}" for k in keep if k in d)


# ============================ BỘ NHẬN DIỆN (giống chương trình chính) ============================
class Pipeline:
    """Chạy CÙNG LÚC 2 bộ nhận diện trên mỗi khung hình:
       - "protected": y hệt chương trình chính (có mọi cơ chế chống nhầm),
       - "raw": nhận diện thô, không chống nhầm (chỉ để làm đối chứng ở phần NGHỈ).
    Kết quả của khung hình hiện tại nằm trong các thuộc tính sau mỗi lần update()."""

    def __init__(self):
        self.left_stab = GestureStabilizer(STABILIZER_HISTORY, STABILIZER_AGREEMENT)
        self.right_stab = GestureStabilizer(STABILIZER_HISTORY, STABILIZER_AGREEMENT)
        self.left_lm = LandmarkSmoother(LANDMARK_SMOOTHING)
        self.right_lm = LandmarkSmoother(LANDMARK_SMOOTHING)
        self.snap = SnapDetector()
        # có điều kiện: chỉ khi tay trái đang xòe (SwipeDetector chịu được nhãn rớt ngắn, xem swipe.py)
        self.swipe = make_swipe_detector()
        self.swipe_raw = make_swipe_detector()   # đối chứng: vẩy lúc nào cũng tính
        self.was_pinching = False
        self.missing_right = 0
        self.raw_was_pinch = False
        self.prev_left_g = None
        self.prev_raw_left_g = None
        self.reset_frame()

    def reset_frame(self):
        self.left_hand = self.right_hand = None
        self.left_g = self.right_g = None
        self.raw_left_g = self.raw_right_g = None
        self.snapped = False
        self.click = False
        self.pinch_now = False
        self.raw_pinch = False
        self.raw_click = False
        self.swipe_dir = None
        self.raw_swipe_dir = None
        self.fist_edge = False
        self.raw_fist_edge = False

    def update(self, hands):
        self.reset_frame()
        right = select_primary_hand(hands, "Right")
        left = select_primary_hand(hands, "Left")
        self.left_hand, self.right_hand = left, right

        # ---- tay trái ----
        if left is not None:
            self.left_g = self.left_stab.update(detect_gesture(smoothed_copy(left, self.left_lm)))
            self.snapped = self.snap.update(left)            # Snap dùng dữ liệu GỐC
            self.raw_left_g = detect_gesture(left)
        else:
            self.snap.reset()
            self.left_lm.reset()

        # ---- tay phải ----
        if right is not None:
            self.missing_right = 0
            right_s = smoothed_copy(right, self.right_lm)
            self.right_g = self.right_stab.update(detect_gesture(right_s))
            self.pinch_now = is_pinching(right_s, self.was_pinching)
            self.raw_right_g = detect_gesture(right)
            self.raw_pinch = pinch_ratio(right) < PINCH_RATIO_THRESHOLD
        else:
            self.missing_right += 1
            if self.missing_right <= MAX_MISSING_RIGHT_FRAMES:
                self.pinch_now = self.was_pinching           # giữ trạng thái khi mất dấu ngắn
            else:
                self.right_lm.reset()
                self.pinch_now = False

        self.click = self.pinch_now and not self.was_pinching
        self.was_pinching = self.pinch_now
        self.raw_click = self.raw_pinch and not self.raw_was_pinch
        self.raw_was_pinch = self.raw_pinch

        # ---- vẩy tay trái ----
        swipe_ready = left is not None and not self.pinch_now
        # y hệt main_spatial_ui_demo.py: luôn đưa tay vào, báo thêm "đang xòe hay không"
        self.swipe_dir = self.swipe.update(left if swipe_ready else None,
                                           palm_open=(self.left_g == "Open palm"))
        self.raw_swipe_dir = self.swipe_raw.update(left, palm_open=True) if left is not None \
            else self.swipe_raw.update(None)

        # ---- nắm tay: tính "cạnh lên" (lúc vừa chuyển sang Fist) ----
        self.fist_edge = self.left_g == "Fist" and self.prev_left_g != "Fist"
        self.raw_fist_edge = self.raw_left_g == "Fist" and self.prev_raw_left_g != "Fist"
        self.prev_left_g = self.left_g
        self.prev_raw_left_g = self.raw_left_g

    def commands(self):
        """Các LỆNH rời rạc phần mềm thật sẽ phát ra ở khung hình này (có chống nhầm)."""
        out = []
        if self.snapped:
            out.append("SNAP")
        if self.click:
            out.append("CLICK")
        if self.fist_edge:
            out.append("FIST")
        if self.swipe_dir in ("left", "right"):
            out.append("SWIPE_" + self.swipe_dir.upper())
        return out


# ============================ PHIÊN TỰ KIỂM TRA ============================
class SelfTestSession:
    def __init__(self, log_dir="logs", seed=None):
        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base = os.path.join(log_dir, f"selftest_{stamp}")
        self.csv = ChainCsv(self.base + ".csv")
        self.seed = seed if seed is not None else int(time.time())
        rng = random.Random(self.seed)
        self.queue = [g for g in GESTURES_TO_TEST for _ in range(REPS_PER_GESTURE)]
        rng.shuffle(self.queue)
        self.total_planned = len(self.queue)
        self.trials = []                 # kết quả từng lượt (dict)
        self.rest = None                 # kết quả phần nghỉ
        self.iot = None
        self.started_real = datetime.now().astimezone()
        self.csv.write("SESSION", "START", detail=(
            f"participant={PARTICIPANT_ID};seed={self.seed};"
            + ";".join(f"{k}={v}" for k, v in CONDITIONS.items())
            + (f";note={CONDITION_NOTE}" if CONDITION_NOTE else "")))

        # trạng thái máy
        self.phase = "INTRO"             # INTRO, READY, GO, RESULT, REST_INTRO, REST, DONE
        self.phase_t0 = time.perf_counter()
        self.paused = False
        self.current = None              # lượt đang chạy (dict)
        self.last_result = None          # để hiện ĐÚNG/BỎ SÓT và hủy bằng phím z

    # ---------- chuyển pha ----------
    def _set_phase(self, phase):
        self.phase = phase
        self.phase_t0 = time.perf_counter()

    def _elapsed(self):
        return time.perf_counter() - self.phase_t0

    # ---------- bắt đầu / kết thúc một lượt ----------
    def _start_trial(self, pipe):
        target = self.queue.pop(0)
        self.current = {
            "target": target, "hand": GESTURE_INFO[target][1],
            "no": len(self.trials) + 1,
            "t_go": None, "raw_first_t": None, "armed": True,
            "zoom_base": None, "frames": 0, "visible_frames": 0,
            "seen": Counter(), "other_commands": 0, "zoom_max_ratio": 0.0,
            "trace": SwipeTrace() if target in ("SWIPE_LEFT", "SWIPE_RIGHT") else None,
            "swipe_diag": "",
        }
        self._set_phase("READY")

    def _go(self, pipe):
        c = self.current
        c["t_go"] = time.perf_counter()
        if c["target"] in STATE_GESTURES:
            gesture_now = pipe.left_g if c["hand"] == "Left" else pipe.right_g
            # tay đang ở sẵn tư thế đích -> phải thả ra rồi làm lại mới tính
            c["armed"] = gesture_now != STATE_GESTURES[c["target"]]
        self._set_phase("GO")

    def _finish_trial(self, ok, detected, t_decision=None):
        c = self.current
        response_s = round(t_decision - c["t_go"], 3) if ok else ""
        latency_ms = ""
        if ok and c["raw_first_t"] is not None:
            latency_ms = round((t_decision - c["raw_first_t"]) * 1000.0, 1)
        visible = round(100.0 * c["visible_frames"] / c["frames"], 1) if c["frames"] else 0.0
        rec = {"no": c["no"], "target": c["target"], "result": "OK" if ok else "MISS",
               "detected": detected, "response_s": response_s, "system_latency_ms": latency_ms,
               "hand_visible_pct": visible, "other_commands": c["other_commands"], "void": False}
        self.trials.append(rec)
        detail = f"trial={c['no']}" + (f";zoom_max_ratio={c['zoom_max_ratio']:.2f}" if c["target"] == "ZOOM" else "")
        if c["trace"] is not None:
            detail += ";" + c["trace"].summary()
            if c["swipe_diag"]:
                detail += ";" + c["swipe_diag"]
        self.csv.write("TRIAL", c["target"], rec["result"], detected, response_s, latency_ms,
                       visible, c["other_commands"], detail=detail)
        self.last_result = rec
        self.current = None
        self._set_phase("RESULT")

    def toggle_pause(self):
        """Phím p. Tạm dừng giữa một lượt thì lượt đó được làm lại từ đầu (không tính
        là bỏ sót). Không cho tạm dừng trong phần NGHỈ (sẽ làm sai số lần nhầm/phút)."""
        if self.phase == "REST":
            print("[self_test] Khong tam dung trong phan nghi.")
            return
        if not self.paused:
            self.paused = True
            if self.phase in ("READY", "GO") and self.current is not None:
                self.queue.insert(0, self.current["target"])
                self.current = None
                self._set_phase("RESUME")
        else:
            self.paused = False
            if self.phase == "RESUME":
                self._start_trial(None)

    def void_last(self):
        """Phím z: hủy lượt vừa xong (người thử làm sai đề) và xếp lại cử chỉ đó vào cuối."""
        if self.last_result is None or self.last_result["void"]:
            return
        self.last_result["void"] = True
        self.queue.append(self.last_result["target"])
        self.csv.write("TRIAL", self.last_result["target"], "VOID",
                       detail=f"huy_luot={self.last_result['no']}")
        print(f"[self_test] Da huy luot {self.last_result['no']} ({self.last_result['target']}), xep lai vao cuoi.")

    # ---------- chấm một khung hình trong lượt ----------
    def _evaluate_frame(self, pipe, frame_start, t_now):
        """Kiểm tra khung hình hiện tại đã đạt đề chưa. Trả về (đạt?, nhãn_nhận_được)."""
        c = self.current
        target = c["target"]
        hand_needed = c["hand"]
        visible = ((hand_needed == "Right" and pipe.right_hand is not None)
                   or (hand_needed == "Left" and pipe.left_hand is not None)
                   or (hand_needed == "Both" and pipe.left_hand is not None and pipe.right_hand is not None))
        c["frames"] += 1
        c["visible_frames"] += int(visible)

        # Ghi lại những gì phần mềm "thấy" để dựng ma trận nhầm lẫn khi bỏ sót
        g = pipe.right_g if hand_needed == "Right" else pipe.left_g
        if g:
            c["seen"][g] += 1
        cmds = pipe.commands()

        raw_hit = False
        hit = False
        if target in STATE_GESTURES:
            want = STATE_GESTURES[target]
            raw_g = pipe.raw_right_g if hand_needed == "Right" else pipe.raw_left_g
            if not c["armed"]:
                if g != want:
                    c["armed"] = True          # đã thả tư thế cũ -> bắt đầu tính
            else:
                raw_hit = raw_g == want
                hit = g == want
        elif target == "PINCH":
            raw_hit = pipe.raw_pinch
            hit = pipe.click
        elif target == "SNAP":
            raw_hit = hit = pipe.snapped
        elif target in ("SWIPE_LEFT", "SWIPE_RIGHT"):
            want = "left" if target == "SWIPE_LEFT" else "right"
            raw_hit = pipe.raw_swipe_dir == want
            hit = pipe.swipe_dir == want
        elif target == "ZOOM":
            if pipe.left_hand is not None and pipe.right_hand is not None:
                d = index_tip_distance(pipe.left_hand, pipe.right_hand)
                if c["zoom_base"] is None:
                    c["zoom_base"] = max(d, 1.0)
                ratio = d / c["zoom_base"]
                c["zoom_max_ratio"] = max(c["zoom_max_ratio"], ratio)
                raw_hit = hit = ratio >= ZOOM_RATIO

        # Ghi chẩn đoán lượt vẩy: vị trí tay + nhãn Open palm mỗi khung, cùng lý do bộ nhận diện từ chối
        if c["trace"] is not None:
            c["trace"].add(pipe.left_hand, palm_open=(pipe.left_g == "Open palm"), now=frame_start)
            if not c.get("diag_reset"):
                pipe.swipe.reset_best()      # bắt đầu lượt: quên chẩn đoán của lượt trước
                c["diag_reset"] = True
            # best_diag = khung có quãng dài nhất của lượt (đúng lúc cú vẩy), KHÔNG phải khung cuối
            c["swipe_diag"] = diag_text(pipe.swipe.best_diag)

        # Mốc bắt đầu tính độ trễ = khung ĐẦU TIÊN của chuỗi khung liên tiếp mà bộ nhận
        # diện thô đã thấy tư thế. Chuỗi bị ngắt (tay đổi tư thế) thì tính lại từ đầu, để
        # không tính oan thời gian người thử làm dở rồi làm lại.
        if raw_hit:
            if c["raw_first_t"] is None:
                c["raw_first_t"] = frame_start
        elif not hit and (target in STATE_GESTURES or target == "PINCH"):
            c["raw_first_t"] = None
        # Cử chỉ dạng "sự kiện" (búng, vẩy, zoom) được chốt ngay trong khung phát hiện ->
        # độ trễ hệ thống = thời gian xử lý của chính khung đó.
        if hit and c["raw_first_t"] is None:
            c["raw_first_t"] = frame_start

        # Lệnh KHÁC đề phát ra trong lượt = kích hoạt nhầm trong lúc thao tác
        expected = {"PINCH": "CLICK", "SNAP": "SNAP", "FIST": "FIST",
                    "SWIPE_LEFT": "SWIPE_LEFT", "SWIPE_RIGHT": "SWIPE_RIGHT"}.get(target)
        c["other_commands"] += sum(1 for cmd in cmds if cmd != expected)
        return hit, cmds

    def _miss_label(self, cmds_seen):
        """Khi bỏ sót: phần mềm đã nhận thành gì? (để dựng ma trận nhầm lẫn)."""
        c = self.current
        if c["target"] == "ZOOM":
            return "ZOOM_CHUA_DU" if c["zoom_base"] else "KHONG_THAY_2_TAY"   # tỉ lệ đạt được ghi ở cột detail
        if cmds_seen:
            return cmds_seen.most_common(1)[0][0]
        if c["seen"]:
            return c["seen"].most_common(1)[0][0]
        return "KHONG_THAY_TAY" if c["visible_frames"] == 0 else "NONE"

    # ---------- phần NGHỈ: đếm kích hoạt nhầm 3 mức ----------
    def _start_rest(self):
        self.rest_counts = {"raw": Counter(), "protected": Counter(), "context": Counter()}
        self.rest_frames = 0
        self.rest_visible = 0
        self._set_phase("REST")

    def _rest_frame(self, pipe):
        self.rest_frames += 1
        self.rest_visible += int(pipe.left_hand is not None or pipe.right_hand is not None)
        raw, prot, ctx = self.rest_counts["raw"], self.rest_counts["protected"], self.rest_counts["context"]
        # Mức 1: thô
        if pipe.raw_click:
            raw["CLICK"] += 1
        if pipe.raw_fist_edge:
            raw["FIST"] += 1
        if pipe.raw_swipe_dir in ("left", "right"):
            raw["SWIPE"] += 1
        if pipe.snapped:
            raw["SNAP"] += 1          # búng tay chỉ có 1 thuật toán, tính như nhau ở mọi mức
        # Mức 2: có chống nhầm (như chương trình chính)
        for cmd in pipe.commands():
            prot["SWIPE" if cmd.startswith("SWIPE") else cmd] += 1
        # Mức 3: thêm ngữ cảnh — ở màn camera (menu đóng) chỉ SNAP mới gây ra lệnh
        if pipe.snapped:
            ctx["SNAP"] += 1

    def _finish_rest(self):
        minutes = max(self._elapsed() / 60.0, 1e-9)
        result = {"duration_s": round(self._elapsed(), 1),
                  "hand_visible_pct": round(100.0 * self.rest_visible / max(self.rest_frames, 1), 1)}
        for level in ("raw", "protected", "context"):
            counts = self.rest_counts[level]
            total = sum(counts.values())
            result[level] = {"total": total, "per_min": round(total / minutes, 2), "by_command": dict(counts)}
            self.csv.write("REST", level, detected=json.dumps(dict(counts)),
                           other_commands=total, detail=f"per_min={total / minutes:.2f};duration_s={self._elapsed():.1f}")
        self.rest = result

    # ---------- phần IoT ----------
    def run_iot(self):
        if IOT_TRIALS <= 0:
            return
        import iot
        latencies, ok_count = [], 0
        for i in range(IOT_TRIALS):
            fn = iot.turn_light_on if i % 2 == 0 else iot.turn_light_off
            t0 = time.perf_counter()
            ok = bool(fn())
            ms = (time.perf_counter() - t0) * 1000.0
            ok_count += int(ok)
            if ok:
                latencies.append(ms)
            self.csv.write("IOT", fn.__name__, "OK" if ok else "FAIL", system_latency_ms=round(ms, 1))
            time.sleep(0.3)
        lo, hi = wilson_interval(ok_count, IOT_TRIALS)
        self.iot = {"n": IOT_TRIALS, "success": ok_count, "success_rate": round(ok_count / IOT_TRIALS, 3),
                    "success_rate_ci95": [lo, hi], "latency_ms_ok": describe(latencies)}

    # ---------- tổng kết ----------
    def summary(self, perf):
        valid = [t for t in self.trials if not t["void"]]
        per_gesture = {}
        confusion = {}
        for g in GESTURES_TO_TEST:
            rows = [t for t in valid if t["target"] == g]
            ok = [t for t in rows if t["result"] == "OK"]
            lo, hi = wilson_interval(len(ok), len(rows))
            per_gesture[g] = {
                "n": len(rows), "ok": len(ok), "miss": len(rows) - len(ok),
                "accuracy": round(len(ok) / len(rows), 3) if rows else None,
                "accuracy_ci95": [lo, hi],
                "response_s": describe([t["response_s"] for t in ok], 3),
                "system_latency_ms": describe([t["system_latency_ms"] for t in ok if t["system_latency_ms"] != ""]),
                "hand_visible_pct_mean": round(sum(t["hand_visible_pct"] for t in rows) / len(rows), 1) if rows else None,
                "other_commands": sum(t["other_commands"] for t in rows),
            }
            confusion[g] = dict(Counter(t["detected"] for t in rows))
        total_ok = sum(1 for t in valid if t["result"] == "OK")
        lo, hi = wilson_interval(total_ok, len(valid))
        all_lat = [t["system_latency_ms"] for t in valid if t["result"] == "OK" and t["system_latency_ms"] != ""]
        return {
            "participant_id": PARTICIPANT_ID,
            "conditions": CONDITIONS,
            "condition_note": CONDITION_NOTE,
            "started_at": self.started_real.isoformat(timespec="seconds"),
            "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "random_seed": self.seed,
            "settings": {
                "reps_per_gesture": REPS_PER_GESTURE, "trial_timeout_s": TRIAL_TIMEOUT_S,
                "ready_time_s": READY_TIME_S, "rest_phase_s": REST_PHASE_S, "zoom_ratio": ZOOM_RATIO,
                "pinch_ratio_threshold": PINCH_RATIO_THRESHOLD,
                "pinch_exit_ratio": PINCH_RATIO_THRESHOLD + 0.15,
                "stabilizer": f"{STABILIZER_AGREEMENT}/{STABILIZER_HISTORY} khung",
                "snap": {k: getattr(SnapDetector(), k) for k in
                         ("cock_dist", "release_dist", "max_release_time", "cooldown_sec")},
                "swipe": swipe_settings(),
            },
            "trials_valid": len(valid),
            "trials_void": len(self.trials) - len(valid),
            "overall_accuracy": round(total_ok / len(valid), 3) if valid else None,
            "overall_accuracy_ci95": [lo, hi],
            "system_latency_ms_all": describe(all_lat),
            "per_gesture": per_gesture,
            "confusion": confusion,
            "other_commands_during_trials": sum(t["other_commands"] for t in valid),
            "rest_false_triggers": self.rest,
            "iot": self.iot,
            "performance": perf.summary(),
            "csv_file": os.path.basename(self.csv.path),
            "note": ("Nguoi thu la tac gia (kiem thu ky thuat). Do tre he thong khong gom do tre ben "
                     "trong webcam. Khong chua thong tin ca nhan."),
        }


# ============================ VÒNG LẶP CHÍNH ============================
def open_camera(index=CAMERA_INDEX):
    """Mở webcam đơn giản (nếu lỗi hình, dùng main_spatial_ui_demo.py để tìm cách mở
    phù hợp, rồi sửa CAMERA_INDEX ở đây cho giống)."""
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    if sys.platform.startswith("win"):
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return cap


def run(tracker=None, cap=None, log_dir="logs"):
    tracker = tracker or HandTracker(model_path="hand_landmarker.task")
    cap = cap or open_camera()
    pipe = Pipeline()
    perf = PerfMonitor()
    session = SelfTestSession(log_dir=log_dir, seed=RANDOM_SEED)
    print(f"[self_test] Ghi ket qua vao: {session.csv.path}")
    quit_early = False

    while True:
        ok, frame = cap.read()
        if not ok:
            print("[self_test] Khong doc duoc camera.")
            quit_early = True
            break
        # Bấm giờ từ lúc NHẬN được khung hình: đây cũng là mốc "tư thế xuất hiện trong
        # khung hình" dùng để tính độ trễ hệ thống.
        perf.start_frame()
        frame_start = time.perf_counter()
        frame = cv2.flip(frame, 1)       # lật gương như chương trình chính
        perf.start_ai()
        hands = tracker.process(frame)
        perf.end_ai()
        pipe.update(hands)
        t_now = time.perf_counter()

        for hand in hands:
            for (x, y) in hand["pixels"]:
                cv2.circle(frame, (x, y), 2, (140, 140, 145), -1, cv2.LINE_AA)
        status = f"L: {pipe.left_g or '-'}   R: {pipe.right_g or '-'}   AI {perf.last_ai_ms:.0f} ms"

        # ---------------- máy trạng thái ----------------
        done_count = len([t for t in session.trials if not t["void"]])
        progress_text = f"Luot {min(done_count + 1, session.total_planned)}/{session.total_planned}"
        if session.paused:
            draw_banner(frame, [("TAM DUNG - bam p de chay tiep", 1.0)])
        elif session.phase == "INTRO":
            draw_banner(frame, [("CHE DO TU KIEM TRA - " + PARTICIPANT_ID, 1.0),
                                (f"{session.total_planned} luot cu chi + {REST_PHASE_S}s nghi tu nhien", 0.7),
                                ("Lam dung cu chi duoc yeu cau. Lam sai de -> bam z de huy luot", 0.6),
                                ("Bam SPACE de bat dau  |  p tam dung  |  q thoat", 0.6)])
        elif session.phase == "READY":
            name = GESTURE_INFO[session.current["target"]][0]
            draw_banner(frame, [(progress_text + "  -  CHUAN BI:", 0.7), (name, 1.0)],
                        progress=1 - session._elapsed() / READY_TIME_S)
            if session._elapsed() >= READY_TIME_S:
                session._go(pipe)
        elif session.phase == "GO":
            hit, cmds = session._evaluate_frame(pipe, frame_start, t_now)
            session.current.setdefault("cmds_seen", Counter()).update(cmds)
            name = GESTURE_INFO[session.current["target"]][0]
            hint = "" if session.current["armed"] else "  (tha tay roi lam lai)"
            draw_banner(frame, [(progress_text + "  -  LAM NGAY!" + hint, 0.7), (name, 1.0)],
                        color=COLOR_OK, progress=1 - session._elapsed() / TRIAL_TIMEOUT_S)
            if hit:
                session._finish_trial(True, session.current["target"], t_decision=time.perf_counter())
            elif session._elapsed() >= TRIAL_TIMEOUT_S:
                label = session._miss_label(session.current.get("cmds_seen", Counter()))
                session._finish_trial(False, label)
        elif session.phase == "RESULT":
            r = session.last_result
            if r["result"] == "OK":
                draw_banner(frame, [(f"DUNG  -  {r['response_s']:.2f} s", 1.0)], color=COLOR_OK)
            else:
                draw_banner(frame, [(f"BO SOT  (may nhan: {r['detected']})", 0.9), ("lam sai de? bam z", 0.6)],
                            color=COLOR_BAD)
            if session._elapsed() >= RESULT_SHOW_S:
                if session.queue:
                    session._start_trial(pipe)
                else:
                    session._set_phase("REST_INTRO")
        elif session.phase == "REST_INTRO":
            draw_banner(frame, [("PHAN NGHI TU NHIEN", 1.0),
                                (f"{REST_PHASE_S}s: cu dong tay tu nhien, noi chuyen, chi tro...", 0.7),
                                ("KHONG co y ra lenh. Bam SPACE de bat dau.", 0.7)])
        elif session.phase == "REST":
            session._rest_frame(pipe)
            left = REST_PHASE_S - session._elapsed()
            prot = sum(session.rest_counts["protected"].values())
            raw = sum(session.rest_counts["raw"].values())
            draw_banner(frame, [(f"NGHI TU NHIEN - con {left:.0f}s - dung ra lenh", 0.8),
                                (f"lenh nham: khong chong nham {raw} | co chong nham {prot}", 0.6)],
                        progress=left / REST_PHASE_S)
            if left <= 0:
                session._finish_rest()
                session._set_phase("DONE_PENDING")
        elif session.phase == "DONE_PENDING":
            draw_banner(frame, [("Dang luu ket qua...", 1.0)])
            session._set_phase("DONE")
        elif session.phase == "DONE":
            valid = [t for t in session.trials if not t["void"]]
            acc = (sum(t["result"] == "OK" for t in valid) / len(valid) * 100) if valid else 0
            rest = session.rest or {}
            draw_banner(frame, [("XONG! Ket qua nhanh:", 1.0),
                                (f"Do chinh xac chung: {acc:.1f}% ({len(valid)} luot)", 0.7),
                                (f"Kich hoat nham/phut: {rest.get('raw', {}).get('per_min', '-')} (khong chong) -> "
                                 f"{rest.get('protected', {}).get('per_min', '-')} (co chong) -> "
                                 f"{rest.get('context', {}).get('per_min', '-')} (ngu canh)", 0.55),
                                ("Bam SPACE hoac q de luu va thoat", 0.6)], color=COLOR_OK)

        cv2.putText(frame, status, (10, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_TEXT, 1, cv2.LINE_AA)
        cv2.imshow("Self test", frame)
        perf.end_frame()

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            quit_early = session.phase != "DONE"
            break
        if key == ord('p'):
            session.toggle_pause()
        elif key == ord('z'):
            session.void_last()
        elif key == ord(' '):
            if session.phase == "INTRO":
                session._start_trial(pipe)
            elif session.phase == "REST_INTRO":
                session._start_rest()
            elif session.phase == "DONE":
                break

    cap.release()
    cv2.destroyAllWindows()
    tracker.close()

    if session.phase == "REST" and session.rest is None:
        session._finish_rest()               # thoát giữa phần nghỉ vẫn lưu phần đã đo
    session.run_iot()
    summary = session.summary(perf)
    summary["finished"] = not quit_early
    session.csv.write("SESSION", "END", detail=f"finished={int(not quit_early)}")
    summary["final_row_hash"] = session.csv.final_hash
    session.csv.close()
    with open(session.base + "_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print_summary(summary)
    print(f"[self_test] Da luu: {session.csv.path}")
    print(f"[self_test] Tom tat: {session.base}_summary.json")
    return summary


def print_summary(s):
    print("=" * 64)
    print(f"KET QUA TU KIEM TRA - {s['participant_id']} - dieu kien: {s['conditions']}")
    print(f"{'Cu chi':<12}{'Dung/Tong':>10}{'Ti le':>8}{'KTC 95%':>16}{'Tre TB ms':>11}{'Tre P95':>9}")
    for g, d in s["per_gesture"].items():
        if not d["n"]:
            continue
        ci = d["accuracy_ci95"]
        lat = d["system_latency_ms"]
        print(f"{g:<12}{str(d['ok']) + '/' + str(d['n']):>10}{d['accuracy'] * 100:>7.0f}%"
              f"{f'{ci[0] * 100:.0f}-{ci[1] * 100:.0f}%':>16}{lat.get('mean', '-'):>11}{lat.get('p95', '-'):>9}")
    if s["overall_accuracy"] is not None:
        print(f"Chung: {s['overall_accuracy'] * 100:.1f}%  (KTC 95%: {s['overall_accuracy_ci95']})")
    if s["rest_false_triggers"]:
        r = s["rest_false_triggers"]
        print(f"Kich hoat nham/phut: khong chong nham {r['raw']['per_min']} | co chong nham "
              f"{r['protected']['per_min']} | them ngu canh {r['context']['per_min']}")
    p = s["performance"]
    print(f"FPS trung binh: {p['fps_average']} | AI ms TB {p['ai_ms'].get('mean')} P95 {p['ai_ms'].get('p95')}")
    if s["iot"]:
        print(f"IoT: thanh cong {s['iot']['success']}/{s['iot']['n']} | tre {s['iot']['latency_ms_ok']}")
    print("=" * 64)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--verify":
        ok, bad, n = verify_csv(sys.argv[2])
        print(f"[OK] File toan ven: {n} dong, chuoi bam khop." if ok
              else f"[CANH BAO] File BI SUA/HONG tu dong {bad} (da doc {n} dong hop le).")
        sys.exit(0 if ok else 1)
    try:
        run()
    except Exception:
        import traceback
        report = traceback.format_exc()
        with open("crash_report.txt", "w", encoding="utf-8") as f:
            f.write(report)
        cv2.destroyAllWindows()
        print("CHUONG TRINH BI LOI. Xem crash_report.txt. Dong loi cuoi:")
        print("   " + report.strip().splitlines()[-1])
        sys.exit(1)