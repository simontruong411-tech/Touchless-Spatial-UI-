"""
swipe_test.py
-------------
CHƯƠNG TRÌNH RIÊNG CHỈ ĐỂ TEST VẨY TAY (lật ảnh) - không có menu, không có ảnh, không IoT.
Mục đích: tập trung chỉnh swipe.py cho xong rồi mới chuyển sang các thông số khác, khỏi
mất thời gian chạy cả self_test (70 lượt, 5 phút) mỗi lần.

CHẠY:   python swipe_test.py          (webcam thật)
        python swipe_test.py --sim    (mô phỏng, KHÔNG cần webcam: kiểm tra chương trình chạy được)

CÁC CHẾ ĐỘ (bấm phím trên cửa sổ video):
  [p] TAP LUYEN  : tự do vẩy, màn hình hiện hướng phần mềm nhận + tay đang ở đâu. Không ghi log.
  [s] DO CHINH THUC : 10 lượt TRÁI + 10 lượt PHẢI xen kẽ ngẫu nhiên (chỉnh REPS_PER_DIRECTION),
        mỗi lượt: CHUAN BI -> VAY! -> kết quả + lời khuyên. Sau đó (nếu DO_REST_PHASE) 60 giây
        ngồi nghỉ tự nhiên để đếm vẩy nhầm. Kết thúc ghi CSV + JSON vào thư mục logs/.
  [q] thoát (hoặc ESC).

TRÊN MÀN HÌNH:
  - Vùng ĐỎ hai bên mép = vùng NGUY HIỂM, tay vào đó dễ bị mất dấu (số đo thật 01/11: các cú vẩy
    trái hỏng vì tay chạy tới mép trái). Đường XANH LÁ = nên xuất phát, đường VÀNG = nên dừng.
  - Chấm tròn = tâm lòng bàn tay trái (xanh = thấy tay, không có chấm = MẤT TAY).

CÁCH CHẤM (giống self_test): chỉ tính LỆNH ĐẦU TIÊN trong lượt. Đúng hướng = ĐÚNG; ngược hướng =
SAI HUONG; không có lệnh trong TRIAL_TIMEOUT_S giây = BO SOT. Lệnh thứ hai ngay sau đó (thường là
cú thu tay về bị tính thành vẩy ngược) được đếm riêng ở cột extra_after.

TIÊU CHÍ ĐẠT (đã đặt từ trước, chưa phải kết quả): mỗi hướng >= 90%, 0 lượt SAI HUONG, phản hồi
trung bình <= 1,0 s, vẩy nhầm khi nghỉ <= 5 lần/60 s.

GHI CHÚ TRUNG THỰC: người thử là chính tác giả nên kết quả thường tốt hơn người mới. Chữ trên
màn hình KHÔNG DẤU vì OpenCV không vẽ được dấu tiếng Việt.

GHI VẾT TỪNG KHUNG HÌNH (MỚI, để chỉnh swipe.py bằng DỮ LIỆU THẬT thay vì mô phỏng tự dựng):
  Cùng với CSV/JSON, mỗi phiên đo còn ghi  logs/swipetest_<giờ>_trace.csv : mỗi dòng là MỘT khung hình
  (thời gian, có thấy tay không, tay có được đưa vào bộ vẩy không, tâm bàn tay x/y, kích thước tay,
  nhãn Open palm, lệnh vừa ra). CHỈ là con số tọa độ - không có hình ảnh, không có thông tin cá nhân.
  File này có chuỗi băm như CSV chính. Dùng  python swipe_replay.py logs/swipetest_..._trace.csv
  để chạy lại đúng các cú vẩy thật qua bộ nhận diện với tham số khác (vd chờ xác nhận 0 / 0,2 / 0,3 s).
  Muốn tắt: python swipe_test.py --no-trace
"""

import csv
import hashlib
import json
import math
import os
import random
import sys
import time
from collections import deque
from datetime import datetime

import cv2

from hand_utils import (
    HandTracker, detect_gesture, is_pinching,
    GestureStabilizer, LandmarkSmoother, select_primary_hand, palm_center, hand_apparent_size,
)
import swipe as swipe_module
from swipe import SwipeDetector, SwipeTrace

# ============================ CẤU HÌNH ============================
PARTICIPANT_ID = "P01"
CONDITION_NOTE = "sang, 80cm, khong gang"     # ghi điều kiện phiên này (không dấu cho gọn)
REPS_PER_DIRECTION = 10                       # số lượt mỗi hướng
DO_REST_PHASE = True                          # sau 20 lượt: 60 s nghỉ để đếm vẩy nhầm
REST_PHASE_S = 60
READY_TIME_S = 1.2
ARM_MAX_WAIT_S = 8.0          # chờ tối đa bấy nhiêu giây cho tay vào đúng vạch xuất phát rồi mới vào GO
ARM_TOLERANCE_X = 0.15        # tay phải cách vạch xuất phát không quá 0,15 bề rộng khung...
ARM_STILL_X = 0.04            # ...và đứng yên (dao động < 0,04) trong ARM_STILL_S giây
ARM_STILL_S = 0.35
TRIAL_TIMEOUT_S = 4.0
RESULT_SHOW_S = 1.6                           # thời gian hiện kết quả (cũng là lúc đếm lệnh thứ hai)
CAMERA_INDEX = 0
LOG_DIR = "logs"
# So sánh có/không "chờ xác nhận lấy đà": chạy  python swipe_test.py --hold=0  (tắt)  hoặc --hold=0.3
HOLD_OVERRIDE = None
for _a in sys.argv[1:]:
    if _a.startswith("--hold="):
        HOLD_OVERRIDE = float(_a.split("=", 1)[1])
# Ghi vết từng khung hình để phát lại bằng swipe_replay.py (mặc định BẬT; tắt bằng --no-trace)
TRACE_ENABLED = "--no-trace" not in sys.argv
TRACE_FIELDS = ["section", "trial", "target", "t", "present", "fed", "cx", "cy", "size", "palm_open",
                "cmd", "detail", "row_hash"]

# Giống chương trình chính / self_test (để số đo đại diện cho phần mềm thật)
STABILIZER_HISTORY, STABILIZER_AGREEMENT = 6, 4
LANDMARK_SMOOTHING = 0.5
MAX_MISSING_RIGHT_FRAMES = 5

# Vị trí gợi ý (tỉ lệ bề rộng khung, hình đã lật gương): xuất phát -> dừng, và vùng nguy hiểm.
# Quãng gợi ý ~0,4 bề rộng khung = 2,1-3 kích thước bàn tay (tay to 0,13-0,19 khung ở 80 cm): đủ vượt
# ngưỡng 2,2 (phải) / 1,8 (trái) của swipe.py nhưng vẫn dừng trước vùng đỏ.
GUIDE = {"left": {"start": 0.65, "stop": 0.25}, "right": {"start": 0.30, "stop": 0.72}}
DANGER_MARGIN = 0.18

# Ngưỡng dùng cho LỜI KHUYÊN sau mỗi lượt (chỉ để gợi ý, không ảnh hưởng chấm điểm)
ADVICE_EDGE_X = 0.15
ADVICE_MISSING_PCT = 25.0
ADVICE_MIN_HS = 2.2

COL_TEXT = (240, 240, 240)
COL_OK = (90, 210, 90)
COL_BAD = (70, 70, 235)
COL_WARN = (60, 200, 235)
COL_GUIDE = (80, 220, 80)
COL_STOP = (60, 210, 230)


# ============================ TIỆN ÍCH ============================
def wilson_ci(ok, n, z=1.96):
    """Khoảng tin cậy 95% (Wilson) cho tỉ lệ ok/n. Mẫu nhỏ nên khoảng này RỘNG - đó là thật."""
    if n == 0:
        return (0.0, 0.0)
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def smoothed_copy(hand, landmark_smoother):
    out = dict(hand)
    out["world_landmarks"] = landmark_smoother.update(hand["world_landmarks"])
    return out


def put(img, text, org, scale=0.6, color=COL_TEXT, thick=1):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def open_camera(index=CAMERA_INDEX):
    """Mở webcam: thử DirectShow+MJPG, DirectShow, MSMF, mặc định; đọc tới khi có hình thật."""
    ways = [("DirectShow+MJPG", cv2.CAP_DSHOW, True), ("DirectShow", cv2.CAP_DSHOW, False),
            ("MSMF", cv2.CAP_MSMF, False), ("mac dinh", None, False)]
    for name, backend, mjpg in ways:
        cap = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            continue
        if mjpg:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        good = 0
        for _ in range(60):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                good += 1
                if good >= 8:
                    print(f"[camera] camera so {index}, cach mo {name}")
                    return cap
            else:
                time.sleep(0.05)
        cap.release()
    return None


# ============================ BỘ NHẬN DIỆN (giống chương trình chính) ============================
class Pipeline:
    """Từ danh sách tay của MỘT khung hình -> lệnh vẩy (hoặc None). Dùng đúng cách gọi của
    main_spatial_ui_demo.py: tay trái đưa vào SwipeDetector (kèm nhãn Open palm), bỏ qua khi
    tay phải đang chụm (Pinch)."""

    def __init__(self):
        self.left_stab = GestureStabilizer(STABILIZER_HISTORY, STABILIZER_AGREEMENT)
        self.right_stab = GestureStabilizer(STABILIZER_HISTORY, STABILIZER_AGREEMENT)
        self.left_lm = LandmarkSmoother(LANDMARK_SMOOTHING)
        self.right_lm = LandmarkSmoother(LANDMARK_SMOOTHING)
        self.swipe = SwipeDetector() if HOLD_OVERRIDE is None else SwipeDetector(confirm_hold_s=HOLD_OVERRIDE)
        self.was_pinching = False
        self.missing_right = 0
        self.left_hand = None
        self.left_g = None
        self.palm_open = False
        self.swipe_ready = False      # khung này tay trái có được đưa vào bộ vẩy không (để ghi vết)

    def reset_swipe(self):
        self.swipe.reset()
        self.swipe.reset_best()

    def update(self, hands, now):
        right = select_primary_hand(hands, "Right")
        left = select_primary_hand(hands, "Left")
        self.left_hand = left
        if left is not None:
            self.left_g = self.left_stab.update(detect_gesture(smoothed_copy(left, self.left_lm)))
        else:
            self.left_lm.reset()
            self.left_g = None
        pinch_now = False
        if right is not None:
            self.missing_right = 0
            pinch_now = is_pinching(smoothed_copy(right, self.right_lm), self.was_pinching)
        else:
            self.missing_right += 1
            pinch_now = self.was_pinching if self.missing_right <= MAX_MISSING_RIGHT_FRAMES else False
            if self.missing_right > MAX_MISSING_RIGHT_FRAMES:
                self.right_lm.reset()
        self.was_pinching = pinch_now
        swipe_ready = left is not None and not pinch_now
        self.swipe_ready = swipe_ready
        self.palm_open = self.left_g == "Open palm"
        return self.swipe.update(left if swipe_ready else None, now=now, palm_open=self.palm_open)


# ============================ GHI LOG CÓ CHUỖI BĂM ============================
class ChainCsv:
    """CSV mà mỗi dòng có row_hash = SHA-256(hash dòng trước + nội dung dòng) rút gọn: sửa tay
    một dòng thì các dòng sau không còn khớp."""
    FIELDS = ["timestamp", "section", "trial", "target", "result", "detected", "response_s",
              "extra_after", "hand_missing_pct", "x_min", "x_max", "best_dx_hs", "fps", "advice",
              "detail", "row_hash"]

    def __init__(self, path, fields=None):
        self.path = path
        if fields is not None:               # file vết dùng bộ cột riêng; CSV chính giữ nguyên bộ cột cũ
            self.FIELDS = fields
        self.prev = "0" * 12
        self.f = open(path, "w", newline="", encoding="utf-8")
        self.w = csv.DictWriter(self.f, fieldnames=self.FIELDS)
        self.w.writeheader()

    def write(self, **row):
        row = {k: row.get(k, "") for k in self.FIELDS if k != "row_hash"}
        text = self.prev + "|" + "|".join(str(row[k]) for k in self.FIELDS if k != "row_hash")
        row["row_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        self.prev = row["row_hash"]
        self.w.writerow(row)
        self.f.flush()

    def close(self):
        self.f.close()


# ============================ PHIÊN TEST ============================
class SwipeTestSession:
    """Máy trạng thái: PRACTICE -> (bấm s) READY -> GO -> RESULT -> ... -> REST -> DONE."""

    def __init__(self, sim=False):
        self.pipe = Pipeline()
        self.mode = "PRACTICE"
        self.sim = sim
        self.plan = []
        self.trial_i = 0
        self.phase_start = 0.0
        self.results = []            # mỗi phần tử: dict một lượt
        self.rest_events = 0
        self.rest_start = 0.0
        self.csv = None
        self.summary_path = None
        self.fps_times = deque(maxlen=30)
        self.last_dir_shown = ("", 0.0)
        self.armed_xs = deque()
        self.trace_csv = None        # file vết từng khung hình (None = không ghi)
        self.frame_buf = []          # khung hình của lượt đang chạy (ghi ra file khi hết lượt, để không làm chậm vòng lặp)
        self.rest_buf = []           # khung hình của pha nghỉ
        self._new_trial_state()

    # ---------- chuẩn bị ----------
    def start_test(self, now):
        dirs = ["left"] * REPS_PER_DIRECTION + ["right"] * REPS_PER_DIRECTION
        random.shuffle(dirs)
        self.plan = dirs
        self.trial_i = 0
        self.results = []
        self.rest_events = 0
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.summary_path = os.path.join(LOG_DIR, f"swipetest_{stamp}_summary.json")
        self.csv = ChainCsv(os.path.join(LOG_DIR, f"swipetest_{stamp}.csv"))
        self.csv.write(timestamp=datetime.now().isoformat(timespec="milliseconds"), section="SESSION",
                       detail=f"participant={PARTICIPANT_ID};note={CONDITION_NOTE};reps={REPS_PER_DIRECTION}")
        self.trace_csv = None
        self.frame_buf, self.rest_buf = [], []
        if TRACE_ENABLED:
            self.trace_csv = ChainCsv(os.path.join(LOG_DIR, f"swipetest_{stamp}_trace.csv"), fields=TRACE_FIELDS)
            # Dòng đầu ghi tham số đang dùng, để swipe_replay biết "lúc ghi" là cấu hình nào
            self.trace_csv.write(section="SESSION",
                                 detail=f"confirm_hold_s={self.pipe.swipe.confirm_hold_s};participant={PARTICIPANT_ID};"
                                        f"note={CONDITION_NOTE};timeout_s={TRIAL_TIMEOUT_S}")
        self._begin_ready(now)

    def _new_trial_state(self):
        self.trace = SwipeTrace()
        self.xs = []
        self.frames = 0
        self.missing = 0
        self.first_cmd = None
        self.first_time = None
        self.extra_after = 0
        self.fps_in_trial = []

    def _begin_ready(self, now):
        self.mode = "READY"
        self.phase_start = now
        self.armed_xs = deque()
        self.pipe.reset_swipe()
        self._new_trial_state()

    # ---------- mỗi khung hình ----------
    def update(self, hands, now):
        self.fps_times.append(now)
        cmd = self.pipe.update(hands, now)
        hand = self.pipe.left_hand
        if cmd:
            self.last_dir_shown = (cmd, now)
        if self.trace_csv is not None and self.mode in ("GO", "RESULT", "REST"):
            self._record_frame(now, hand, cmd)     # mode lúc này là mode ĐẦU khung: khung chuyển READY->GO chưa tính

        if self.mode == "PRACTICE":
            return cmd
        if self.mode == "READY":
            if now - self.phase_start >= READY_TIME_S and self._armed(hand, now):
                self.mode = "GO"
                self.phase_start = now
                self.pipe.reset_swipe()
                self._new_trial_state()
            return cmd
        if self.mode in ("GO", "RESULT"):
            self.frames += 1
            if hand is None:
                self.missing += 1
            else:
                self.xs.append(palm_center(hand)[0])
            self.trace.add(hand, palm_open=self.pipe.palm_open, now=now)
            self.fps_in_trial.append(self.fps())

        if self.mode == "GO":
            if cmd and self.first_cmd is None:
                self.first_cmd, self.first_time = cmd, now
                self.mode = "RESULT"
                self.result_start = now
            elif now - self.phase_start >= TRIAL_TIMEOUT_S:
                self.first_cmd = None
                self.mode = "RESULT"
                self.result_start = now
            if self.mode == "RESULT":
                self._judge(now)
        elif self.mode == "RESULT":
            if cmd:
                self.extra_after += 1
                self.current["extra_after"] = self.extra_after
            if now - self.result_start >= RESULT_SHOW_S:
                self._log_current()
                self.trial_i += 1
                if self.trial_i >= len(self.plan):
                    if DO_REST_PHASE:
                        self.mode = "REST"
                        self.rest_start = now
                        self.pipe.reset_swipe()
                    else:
                        self._finish()
                else:
                    self._begin_ready(now)
        elif self.mode == "REST":
            if cmd:
                self.rest_events += 1
            if now - self.rest_start >= REST_PHASE_S:
                self._finish()
        return cmd

    def _armed(self, hand, now):
        """Cho vào GO khi tay đã đứng YÊN gần vạch xuất phát (hoặc đã chờ quá ARM_MAX_WAIT_S).
        Vì sao: lượt 3 của phiên đo đầu tiên, tay còn ở mép trái lúc bắt đầu rồi đưa sang vạch xuất phát;
        động tác ĐƯA TAY VỀ VẠCH bị tính thành một cú vẩy phải (SAI HUONG) dù không phải lỗi bộ nhận diện."""
        if now - self.phase_start >= READY_TIME_S + ARM_MAX_WAIT_S:
            return True
        if hand is None:
            self.armed_xs.clear()
            return False
        x = palm_center(hand)[0]
        self.armed_xs.append((now, x))
        while self.armed_xs and now - self.armed_xs[0][0] > ARM_STILL_S:
            self.armed_xs.popleft()
        span = now - self.armed_xs[0][0]
        xs = [p[1] for p in self.armed_xs]
        start = GUIDE[self.plan[self.trial_i]]["start"]
        return (span >= ARM_STILL_S * 0.9 and max(xs) - min(xs) <= ARM_STILL_X
                and abs(x - start) <= ARM_TOLERANCE_X)

    # ---------- ghi vết từng khung hình ----------
    def _record_frame(self, now, hand, cmd):
        """Lưu đúng những con số mà SwipeDetector dùng: tâm bàn tay (x, y), kích thước tay, nhãn
        Open palm, và khung này tay có được đưa vào bộ vẩy không (tay trái thấy VÀ tay phải không
        chụm). Thời gian tính từ lúc bắt đầu GO (hoặc bắt đầu pha nghỉ). Chỉ cần bấy nhiêu để
        swipe_replay.py dựng lại tay giả và chạy lại bộ nhận diện y hệt."""
        resting = self.mode == "REST"
        t = round(now - (self.rest_start if resting else self.phase_start), 4)
        if hand is not None:
            cx, cy = palm_center(hand)
            row = (t, 1, int(self.pipe.swipe_ready), round(cx, 5), round(cy, 5),
                   round(hand_apparent_size(hand), 5), int(self.pipe.palm_open), cmd or "")
        else:
            # LƯU Ý: lệnh vẫn có thể ra đúng khung mất tay (vẩy ra khỏi mép khung / cú đang chờ xác nhận)
            row = (t, 0, 0, "", "", "", 0, cmd or "")
        (self.rest_buf if resting else self.frame_buf).append(row)

    def _flush_trace(self, section, trial, target, rows):
        if self.trace_csv is None:
            return
        for (t, present, fed, cx, cy, size, palm, cmd) in rows:
            self.trace_csv.write(section=section, trial=trial, target=target, t=t, present=present, fed=fed,
                                 cx=cx, cy=cy, size=size, palm_open=palm, cmd=cmd)

    def fps(self):
        if len(self.fps_times) < 2:
            return 0.0
        span = self.fps_times[-1] - self.fps_times[0]
        return (len(self.fps_times) - 1) / span if span > 0 else 0.0

    # ---------- chấm một lượt ----------
    def _judge(self, now):
        target = self.plan[self.trial_i]
        if self.first_cmd is None:
            result, detected = "BO SOT", ""
        elif self.first_cmd == target:
            result, detected = "DUNG", self.first_cmd
        else:
            result, detected = "SAI HUONG", self.first_cmd
        resp = round(self.first_time - self.phase_start, 3) if self.first_time else ""
        miss_pct = 100.0 * self.missing / self.frames if self.frames else 0.0
        x_min = min(self.xs) if self.xs else None
        x_max = max(self.xs) if self.xs else None
        best = self.pipe.swipe.best_diag
        advice = self._advice(target, result, x_min, x_max, miss_pct, best)
        diag = ";".join(f"v2_{k}={best[k]}" for k in
                        ("reason", "dist_hs", "speed_hs", "peak_hs", "ratio", "duration", "dir", "edge", "last_speed_hs")
                        if k in best)
        self.current = {
            "target": target, "result": result, "detected": detected, "response_s": resp,
            "extra_after": 0, "hand_missing_pct": round(miss_pct, 1),
            "x_min": round(x_min, 3) if x_min is not None else "",
            "x_max": round(x_max, 3) if x_max is not None else "",
            "fps": round(sum(self.fps_in_trial) / len(self.fps_in_trial), 1) if self.fps_in_trial else "",
            "advice": advice, "detail": self.trace.summary() + ";" + diag,
        }

    @staticmethod
    def _advice(target, result, x_min, x_max, miss_pct, best):
        """Lời khuyên NGẮN, dựa trên số đo của lượt này (gợi ý, không phải kết luận chắc chắn)."""
        if result == "DUNG":
            return "Tot"
        tips = []
        edge_x = x_min if target == "left" else (None if x_max is None else 1.0 - x_max)
        if edge_x is not None and edge_x < ADVICE_EDGE_X:
            tips.append("tay cham mep " + ("trai" if target == "left" else "phai") + " -> dung som hon")
        if miss_pct > ADVICE_MISSING_PCT:
            tips.append("hay mat tay -> giu long ban tay huong camera")
        if best.get("dist_hs", 99) < ADVICE_MIN_HS and best.get("reason") == "short":
            tips.append("vay chua du dai")
        if best.get("reason") == "slow":
            tips.append("vay nhanh va dut khoat hon")
        if result == "SAI HUONG":
            tips.append("dung vung tay ve ngay sau khi vay")
        return "; ".join(tips) if tips else "xem cot detail"

    def _log_current(self):
        c = self.current
        self.results.append(c)
        self.csv.write(timestamp=datetime.now().isoformat(timespec="milliseconds"), section="TRIAL",
                       trial=self.trial_i + 1, **c)
        self._flush_trace("TRIAL", self.trial_i + 1, c["target"], self.frame_buf)
        self.frame_buf = []

    # ---------- tổng kết ----------
    def _finish(self):
        self.mode = "DONE"
        self.summary = build_summary(self.results, self.rest_events if DO_REST_PHASE else None)
        self.csv.write(timestamp=datetime.now().isoformat(timespec="milliseconds"), section="REST",
                       detail=f"swipe_commands={self.rest_events};duration_s={REST_PHASE_S}")
        self.csv.write(timestamp=datetime.now().isoformat(timespec="milliseconds"), section="SESSION",
                       detail="finished=1")
        self.csv.close()
        if self.trace_csv is not None:
            self._flush_trace("REST", 0, "rest", self.rest_buf)
            self.rest_buf = []
            self.trace_csv.close()
            self.summary["trace_csv"] = os.path.basename(self.trace_csv.path)
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(self.summary, f, ensure_ascii=False, indent=2)
        print_summary(self.summary)
        print(f"\nDa luu: {self.csv.path}\n        {self.summary_path}")
        if self.trace_csv is not None:
            print(f"        {self.trace_csv.path}   (vet tung khung hinh - gui kem de chinh bang du lieu that)")


def build_summary(results, rest_events):
    out = {"participant_id": PARTICIPANT_ID, "note": CONDITION_NOTE, "confirm_hold_override": HOLD_OVERRIDE,
           "swipe_settings": {k: v for k, v in vars(__import__("swipe")).items() if k.startswith("SWIPE_")},
           "directions": {}}
    for d in ("left", "right"):
        rows = [r for r in results if r["target"] == d]
        n = len(rows)
        ok = sum(1 for r in rows if r["result"] == "DUNG")
        wrong = sum(1 for r in rows if r["result"] == "SAI HUONG")
        resp = [r["response_s"] for r in rows if r["result"] == "DUNG" and r["response_s"] != ""]
        xm = [r["x_min"] for r in rows if r["x_min"] != ""]
        xM = [r["x_max"] for r in rows if r["x_max"] != ""]
        out["directions"][d] = {
            "n": n, "ok": ok, "wrong_direction": wrong, "miss": n - ok - wrong,
            "accuracy": round(ok / n, 3) if n else None, "accuracy_ci95": wilson_ci(ok, n),
            "response_mean_s": round(sum(resp) / len(resp), 3) if resp else None,
            "extra_after_total": sum(r["extra_after"] for r in rows),
            "hand_missing_pct_mean": round(sum(r["hand_missing_pct"] for r in rows) / n, 1) if n else None,
            "x_min_mean": round(sum(xm) / len(xm), 3) if xm else None,
            "x_max_mean": round(sum(xM) / len(xM), 3) if xM else None,
        }
    out["rest_swipe_commands_per_60s"] = rest_events
    tot_n = sum(v["n"] for v in out["directions"].values())
    tot_ok = sum(v["ok"] for v in out["directions"].values())
    out["overall_accuracy"] = round(tot_ok / tot_n, 3) if tot_n else None
    # Đối chiếu tiêu chí đạt (đặt trước khi đo)
    crit = {}
    for d, v in out["directions"].items():
        crit[f"{d}_accuracy_ge_90pct"] = bool(v["accuracy"] is not None and v["accuracy"] >= 0.9)
        crit[f"{d}_zero_wrong_direction"] = v["wrong_direction"] == 0
        crit[f"{d}_response_le_1s"] = bool(v["response_mean_s"] is not None and v["response_mean_s"] <= 1.0)
    if rest_events is not None:
        crit["rest_le_5_per_60s"] = rest_events <= 5
    out["criteria"] = crit
    out["note_honesty"] = ("Nguoi thu la tac gia, kiem thu ky thuat; mau nho nen khoang tin cay rong. "
                           "Khong chua thong tin ca nhan.")
    return out


def print_summary(s):
    print("\n" + "=" * 60)
    print("KET QUA TEST VAY TAY  (P=" + s["participant_id"] + ")")
    print("=" * 60)
    for d, v in s["directions"].items():
        lo, hi = v["accuracy_ci95"]
        resp = f"{v['response_mean_s']:.2f}s" if v["response_mean_s"] is not None else "-"
        print(f"{d.upper():5s}: dung {v['ok']}/{v['n']}  sai huong {v['wrong_direction']}  bo sot {v['miss']}"
              f"  | chinh xac {100 * (v['accuracy'] or 0):.0f}% (CI95 {100 * lo:.0f}-{100 * hi:.0f}%)"
              f" | phan hoi TB {resp} | mat tay TB {v['hand_missing_pct_mean']}% | x_min TB {v['x_min_mean']}"
              f" | lenh thu 2 {v['extra_after_total']}")
    if s["rest_swipe_commands_per_60s"] is not None:
        print(f"NGHI 60 s: vay nham {s['rest_swipe_commands_per_60s']} lan")
    print("Tieu chi:", "  ".join(f"{k}={'DAT' if ok else 'CHUA'}" for k, ok in s["criteria"].items()))


# ============================ VẼ MÀN HÌNH ============================
def draw(display, ses, now):
    h, w = display.shape[:2]
    # vùng nguy hiểm hai bên mép
    overlay = display.copy()
    cv2.rectangle(overlay, (0, 0), (int(DANGER_MARGIN * w), h), (0, 0, 200), -1)
    cv2.rectangle(overlay, (int((1 - DANGER_MARGIN) * w), 0), (w, h), (0, 0, 200), -1)
    cv2.addWeighted(overlay, 0.25, display, 0.75, 0, display)

    target = ses.plan[ses.trial_i] if ses.plan and ses.trial_i < len(ses.plan) else None
    if target and ses.mode in ("READY", "GO", "RESULT"):
        g = GUIDE[target]
        cv2.line(display, (int(g["start"] * w), 60), (int(g["start"] * w), h - 40), COL_GUIDE, 2)
        cv2.line(display, (int(g["stop"] * w), 60), (int(g["stop"] * w), h - 40), COL_STOP, 2)
        put(display, "BAT DAU", (int(g["start"] * w) - 38, h - 20), 0.45, COL_GUIDE)
        put(display, "DUNG", (int(g["stop"] * w) - 20, h - 20), 0.45, COL_STOP)

    hand = ses.pipe.left_hand
    if hand is not None:
        cx, cy = palm_center(hand)
        cv2.circle(display, (int(cx * w), int(cy * h)), 10, COL_OK, -1)
    put(display, "TAY TRAI: " + ("THAY" if hand is not None else "MAT TAY"), (10, h - 50), 0.5,
        COL_OK if hand is not None else COL_BAD)
    put(display, f"FPS {ses.fps():.0f}  nhan: {ses.pipe.left_g or '-'}", (10, h - 28), 0.5)

    # lệnh vừa nhận
    d, t = ses.last_dir_shown
    if d and now - t < 1.2:
        put(display, "NHAN: VAY " + ("TRAI" if d == "left" else "PHAI" if d == "right" else d.upper()),
            (w // 2 - 120, 100), 0.9, COL_WARN, 2)

    if ses.mode == "PRACTICE":
        put(display, "TAP LUYEN (khong ghi log)   [s] do chinh thuc   [q] thoat", (10, 24), 0.55)
    elif ses.mode in ("READY", "GO"):
        name = "TRAI" if target == "left" else "PHAI"
        arrow = "<<<<" if target == "left" else ">>>>"
        put(display, f"Luot {ses.trial_i + 1}/{len(ses.plan)}", (10, 24), 0.55)
        if ses.mode == "READY":
            put(display, f"CHUAN BI: VAY {name}  {arrow}", (w // 2 - 190, 60), 0.9, COL_WARN, 2)
            put(display, "dua tay toi vach XANH va giu yen", (w // 2 - 150, 90), 0.5, COL_GUIDE)
        else:
            left = max(0.0, TRIAL_TIMEOUT_S - (now - ses.phase_start))
            put(display, f"VAY {name}!  {arrow}   ({left:.1f}s)", (w // 2 - 190, 60), 1.0, COL_OK, 2)
    elif ses.mode == "RESULT":
        c = ses.current
        col = COL_OK if c["result"] == "DUNG" else COL_BAD
        put(display, f"{c['result']}", (w // 2 - 90, 60), 1.1, col, 2)
        put(display, c["advice"][:70], (10, 100 if False else 130), 0.5, COL_WARN)
    elif ses.mode == "REST":
        left = max(0.0, REST_PHASE_S - (now - ses.rest_start))
        put(display, f"NGHI TU NHIEN {left:.0f}s: ngoi yen, dat tay truoc camera, dung vay", (10, 24), 0.55, COL_WARN)
        put(display, f"vay nham: {ses.rest_events}", (10, 50), 0.6, COL_BAD if ses.rest_events > 5 else COL_TEXT)
    elif ses.mode == "DONE":
        put(display, "XONG - xem ket qua o cua so lenh. [q] thoat", (10, 24), 0.6, COL_OK)


# ============================ CHẠY ============================
class _SimRig:
    """Giả webcam + MediaPipe để kiểm tra chương trình chạy được khi KHÔNG có webcam.
    Tay giả tự làm đúng yêu cầu của từng lượt (có chút ngẫu nhiên: lúc vẩy hỏng, lúc mất tay)."""

    def __init__(self, ses):
        self.ses = ses
        self.rnd = random.Random(5)
        self.t0 = None

    def hands(self, now):
        from types import SimpleNamespace as NS
        ses = self.ses
        x, y, size = 0.5, 0.5, 0.15
        if ses.mode in ("READY", "GO", "RESULT") and ses.plan and ses.trial_i < len(ses.plan):
            d = ses.plan[ses.trial_i]
            sgn = -1 if d == "left" else 1
            t = now - ses.phase_start - 0.5
            g = GUIDE[d]
            f = max(0.0, min(1.0, t / 0.3))
            f = 10 * f ** 3 - 15 * f ** 4 + 6 * f ** 5
            x = g["start"] + f * (g["stop"] - g["start"])
        pts = [NS(x=x, y=y, z=0.0) for _ in range(21)]
        pts[0] = NS(x=x, y=y + 0.5 * size, z=0.0)
        pts[9] = NS(x=x, y=y - 0.5 * size, z=0.0)
        pts[5] = NS(x=x - 0.3 * size, y=y - 0.45 * size, z=0.0)
        pts[13] = NS(x=x + 0.3 * size, y=y - 0.40 * size, z=0.0)
        pts[17] = NS(x=x + 0.5 * size, y=y - 0.30 * size, z=0.0)
        if self.rnd.random() < 0.05:
            return []
        return [{"type": "Left", "landmarks": pts, "world_landmarks": pts, "pixels": []}]


def main():
    sim = "--sim" in sys.argv
    ses = SwipeTestSession(sim=sim)
    tracker = cap = rig = None
    if sim:
        global detect_gesture
        detect_gesture = lambda hand: "Open palm"    # bàn tay giả không có đủ điểm để nhận tư thế
        rig = _SimRig(ses)
        random.seed(1)
        clock = [0.0]
        ses.start_test(0.0)
        while ses.mode != "DONE":
            clock[0] += 1 / 15                      # 15 FPS ảo
            ses.update(rig.hands(clock[0]), clock[0])
        return
    tracker = HandTracker(model_path="hand_landmarker.task")
    cap = open_camera()
    if cap is None:
        print("Khong mo duoc webcam. Thu dong app khac dang dung camera, roi chay lai.")
        return
    print("[p] tap luyen   [s] do chinh thuc   [q] thoat")
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        frame = cv2.flip(frame, 1)
        now = time.perf_counter()
        ses.update(tracker.process(frame), now)
        draw(frame, ses, now)
        cv2.imshow("swipe_test", frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("s") and ses.mode in ("PRACTICE", "DONE"):
            ses.start_test(now)
        if key == ord("p") and ses.mode in ("PRACTICE", "DONE"):
            ses.mode = "PRACTICE"
    cap.release()
    cv2.destroyAllWindows()
    if ses.csv and ses.mode != "DONE":
        ses.csv.close()
        if ses.trace_csv is not None:
            ses.trace_csv.close()
        print(f"Phien chua xong, log luu do tai {ses.csv.path}")


if __name__ == "__main__":
    main()