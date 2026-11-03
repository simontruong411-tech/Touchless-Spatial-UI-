"""
swipe.py
--------
NHẬN DIỆN VẨY TAY bản cuối (SwipeDetector) + công cụ ghi chẩn đoán (SwipeTrace), GỘP trong
MỘT file. Thay thế SwipeDetector cũ trong hand_utils.py (bản cũ vẫn nằm ở hand_utils.py nhưng
main không còn dùng; có thể xóa sau khi bạn đã đo xong).

Gộp những điểm tốt nhất của các bản trước:
  - Quãng đường tính theo "KÍCH THƯỚC BÀN TAY" (hs), không phụ thuộc xa/gần camera.
  - Tìm ĐOẠN CHUYỂN ĐỘNG MỘT CHIỀU bằng cách quét ngược từ điểm mới nhất -> cú LẤY ĐÀ ngược
    không trừ vào quãng đường; cắt phần tay còn đứng yên trước cú vẩy (onset).
  - Chặn chiều NGƯỢC sau khi báo vẩy tới khi tay dừng -> cú VUNG VỀ không thành lệnh thứ hai.
  - Chịu nhãn Open palm rớt (PALM_GRACE) và mất dấu tay ngắn (LOST_GRACE); cửa sổ tự giãn theo FPS.
  - Báo vẩy NGAY giữa cú vẩy (phản hồi nhanh).
  - Sửa riêng VẨY TRÁI: ngưỡng quãng riêng (tay trái vẩy ra ngoài thường ngắn hơn).
  - "RA KHỎI KHUNG": tay biến mất khi đang chạy nhanh về mép -> vẫn tính là vẩy theo hướng mép.
Vẩy phải giữ ngưỡng đã tốt (2,2 hs).

CÁCH DÙNG:
    swipe = SwipeDetector()
    direction = swipe.update(hand_or_None, palm_open=(left_gesture == "Open palm"))
    # -> "left" / "right" / "up" / "down" / None;  swipe.last_diag = chẩn đoán lần gọi gần nhất

LƯU Ý: các ngưỡng là giá trị khởi đầu chọn bằng MÔ PHỎNG; phải chỉnh lại bằng số đo webcam
thật (self_test + swipe_analyze.py) rồi mới chốt vào báo cáo.
"""

import math
import time
from collections import deque

from hand_utils import palm_center, hand_apparent_size

# =====================================================================
# HẰNG SỐ CẤU HÌNH (đơn vị "hs" = 1 kích thước bàn tay trên ảnh, ~9-10 cm thật)
# =====================================================================
# Quãng đường tối thiểu của đoạn chuyển động một chiều. Bản cũ: 0,25 khung hình
# ~ 1,9-2,3 hs ở 80 cm. Chọn 2,2 hs (~21 cm): tương đương bản cũ nhưng KHÔNG đổi theo khoảng cách.
SWIPE_MIN_DISTANCE_HS = 2.0
# Vận tốc trung bình tối thiểu (hs/giây), tính từ lúc bắt đầu cử động. Loại tay trôi chậm / đổi
# tư thế. Chọn 5,0 theo bài quét ngưỡng mô phỏng (xem swipe_sim_test.py): 3,0 làm số vẩy nhầm
# khi "đổi tư thế" cao gấp 2 lần bản cũ, 5,0 thì thấp hơn bản cũ mà vẫn nhận đủ các cú vẩy thử.
SWIPE_MIN_SPEED_HS = 5.0
# Thời lượng tối đa của đoạn vẩy (giây). Dài hơn = di chuyển tay, không phải vẩy.
SWIPE_MAX_DURATION = 0.7
# Độ dài lịch sử giữ lại (giây); tự giãn theo FPS (xem _window_for_fps).
SWIPE_WINDOW = 0.9
# Trục chính phải lớn hơn trục phụ bao nhiêu lần (giữ như bản cũ).
SWIPE_AXIS_RATIO = 2.0
# Dung sai "đi lùi nhẹ" (hs) khi tìm đoạn một chiều: rung tay không cắt đứt đoạn vẩy.
SWIPE_REVERSE_TOLERANCE_HS = 0.15
# Số điểm tối thiểu và thời lượng tối thiểu của đoạn vẩy (loại nhiễu 1-2 khung).
SWIPE_MIN_POINTS = 3
SWIPE_MIN_RUN_TIME = 0.08
# Nghỉ tối thiểu giữa 2 lần báo vẩy (giây). Ngắn hơn bản cũ (0,8) vì việc chặn cú vung về
# đã do REVERSE_LOCK đảm nhiệm.
SWIPE_COOLDOWN = 0.5
# Sau khi báo vẩy, chặn chiều NGƯỢC tối đa bấy nhiêu giây, hoặc tới khi tay dừng.
SWIPE_REVERSE_LOCK = 0.8
# "Tay dừng" = vận tốc (hs/giây) dưới ngưỡng này liên tục SETTLE_TIME giây.
SWIPE_SETTLE_SPEED_HS = 0.8
SWIPE_SETTLE_TIME = 0.25
# "Điểm bắt đầu cử động" = điểm đầu tiên tay đã đi được chừng này phần quãng đường của cú vẩy.
# Loại phần tay còn ĐỨNG YÊN (chỉ rung nhẹ) nằm trước cú vẩy, nếu không thời lượng bị tính dài
# ra và vận tốc trung bình bị kéo thấp xuống (phát hiện nhờ bài thử mô phỏng: vẩy chậm bị bỏ sót).
SWIPE_ONSET_FRACTION = 0.10
# Cho phép nhãn Open palm rớt / mất dấu tay tối đa bấy nhiêu giây mà không xóa lịch sử.
SWIPE_PALM_GRACE = 0.35   # xoay nghiêng lòng bàn tay khi vẩy ra ngoài làm nhãn rớt lâu hơn
SWIPE_GAP_S = 0.2         # khoảng cách thời gian giữa 2 điểm liên tiếp lớn hơn mức này = tay vừa mất dấu
SWIPE_LOST_GRACE = 0.7    # đo thật: tay hay mất 0,3-1 s khi vẩy trái ra sát mép khung
# Máy chậm (~9-11 FPS khi đang vẩy): cú vẩy chỉ còn 2 điểm. Cho phép 2 điểm nếu quãng RẤT dài.
SWIPE_SPARSE_DISTANCE_HS = 2.6

# --- Phân biệt cú LẤY ĐÀ với cú vẩy thật (đo thật 01/11: 5/7 lượt hỏng là cú lấy đà ngược chiều bị
# tính thành vẩy, rồi chiều thật bị khóa) ---
# Khi một cú vẩy đủ điều kiện, KHÔNG báo ngay mà chờ tối đa CONFIRM_HOLD giây. Trong lúc chờ, nếu tay
# quay đầu >= BACKSWING_REV_HS và cú quay đầu NHANH hơn (>= tỉ lệ BACKSWING_SPEED_RATIO x tốc độ đỉnh
# của cú đang chờ) thì cú đang chờ chỉ là lấy đà -> bỏ, và cú quay đầu sẽ được xét như cú vẩy thật.
# Quay đầu chậm hơn (thu tay về) -> báo cú đang chờ như cũ. Đặt CONFIRM_HOLD = 0 để tắt.
SWIPE_CONFIRM_HOLD = 0.3
SWIPE_BACKSWING_REV_HS = 0.8
SWIPE_BACKSWING_SPEED_RATIO = 1.0

# --- Riêng cho vẩy TRÁI và luật "ra khỏi khung" ---
SWIPE_LEFT_MIN_DISTANCE_HS = 1.8   # vẩy trái đi ngắn hơn (vẩy phải vẫn dùng SWIPE_MIN_DISTANCE_HS)
SWIPE_LEFT_MIN_SPEED_HS = 5.0
SWIPE_EDGE_MARGIN = 0.35           # lần cuối thấy tay cách mép khung < 35% bề rộng = "sát mép" (đo thật: tay mất dấu ở x~0.2-0.35)
SWIPE_EDGE_MIN_DISTANCE_HS = 0.8   # tay biến mất: đoạn đã thấy phải dài tối thiểu thế này
SWIPE_EDGE_MIN_SPEED_HS = 6.0      # ...và khung cuối phải đang chạy NHANH về mép (hs/giây)

# Tỉ lệ cao/rộng của khung hình (480/640): quy trục y về cùng đơn vị với trục x.
SWIPE_ASPECT_HW = 0.75
# Hệ số làm mượt kích thước bàn tay (0-1, càng nhỏ càng mượt).
SWIPE_SIZE_SMOOTHING = 0.3

_OPPOSITE = {"left": "right", "right": "left", "up": "down", "down": "up"}


class SwipeDetector:
    """
    Nhận diện VẨY TAY theo 4 hướng "left"/"right"/"up"/"down" (hình đã lật gương), cùng
    quy ước đầu ra với SwipeDetector cũ. Xem giải thích đầy đủ ở docstring đầu file.

    Cách chạy mỗi khung:
      1. Đổi vị trí tâm lòng bàn tay sang đơn vị "kích thước bàn tay" rồi lưu vào lịch sử.
      2. Quét ngược từ điểm mới nhất tìm đoạn chuyển động MỘT CHIỀU (theo từng trục).
      3. Đoạn đó đủ dài, đủ nhanh, đủ ngắn thời gian, đủ "thẳng trục" -> báo vẩy.
      4. Chiều ngược bị chặn cho tới khi tay dừng (chống tính cú vung về).
    """

    def __init__(self,
                 min_distance_hs=SWIPE_MIN_DISTANCE_HS, min_speed_hs=SWIPE_MIN_SPEED_HS,
                 max_duration=SWIPE_MAX_DURATION, window=SWIPE_WINDOW,
                 axis_ratio=SWIPE_AXIS_RATIO, reverse_tolerance_hs=SWIPE_REVERSE_TOLERANCE_HS,
                 min_points=SWIPE_MIN_POINTS, min_run_time=SWIPE_MIN_RUN_TIME,
                 cooldown=SWIPE_COOLDOWN, reverse_lock=SWIPE_REVERSE_LOCK,
                 settle_speed_hs=SWIPE_SETTLE_SPEED_HS, settle_time=SWIPE_SETTLE_TIME,
                 palm_grace=SWIPE_PALM_GRACE, lost_grace=SWIPE_LOST_GRACE,
                 aspect_hw=SWIPE_ASPECT_HW, size_smoothing=SWIPE_SIZE_SMOOTHING,
                 onset_fraction=SWIPE_ONSET_FRACTION,
                 left_min_distance_hs=SWIPE_LEFT_MIN_DISTANCE_HS, left_min_speed_hs=SWIPE_LEFT_MIN_SPEED_HS,
                 edge_margin=SWIPE_EDGE_MARGIN, edge_min_distance_hs=SWIPE_EDGE_MIN_DISTANCE_HS,
                 edge_min_speed_hs=SWIPE_EDGE_MIN_SPEED_HS, sparse_distance_hs=SWIPE_SPARSE_DISTANCE_HS, gap_s=SWIPE_GAP_S,
                 confirm_hold_s=SWIPE_CONFIRM_HOLD, backswing_rev_hs=SWIPE_BACKSWING_REV_HS,
                 backswing_speed_ratio=SWIPE_BACKSWING_SPEED_RATIO):
        self.min_distance_hs = min_distance_hs
        self.min_speed_hs = min_speed_hs
        self.max_duration = max_duration
        self.window = window
        self.axis_ratio = axis_ratio
        self.reverse_tolerance_hs = reverse_tolerance_hs
        self.min_points = min_points
        self.min_run_time = min_run_time
        self.cooldown = cooldown
        self.reverse_lock = reverse_lock
        self.settle_speed_hs = settle_speed_hs
        self.settle_time = settle_time
        self.palm_grace = palm_grace
        self.lost_grace = lost_grace
        self.aspect_hw = aspect_hw
        self.size_smoothing = size_smoothing
        self.onset_fraction = onset_fraction
        self.left_min_distance_hs = left_min_distance_hs
        self.left_min_speed_hs = left_min_speed_hs
        self.edge_margin = edge_margin
        self.edge_min_distance_hs = edge_min_distance_hs
        self.edge_min_speed_hs = edge_min_speed_hs
        self.sparse_distance_hs = sparse_distance_hs
        self.gap_s = gap_s
        self.confirm_hold_s = confirm_hold_s
        self.backswing_rev_hs = backswing_rev_hs
        self.backswing_speed_ratio = backswing_speed_ratio

        self.best_diag = {}              # chẩn đoán "xa nhất" kể từ reset_best(): xem docstring last_diag
        self.last_diag = {}
        self.reset()

    # last_diag là chẩn đoán của khung GẦN NHẤT; sau cú vẩy tay đã dừng nên nó chỉ báo "short"
    # (vô ích khi tìm lý do hỏng). best_diag giữ chẩn đoán có quãng dài nhất kể từ lần
    # reset_best() -> đúng lúc cú vẩy mạnh nhất. self_test ghi best_diag vào log.
    @property
    def last_diag(self):
        return self._last_diag

    @last_diag.setter
    def last_diag(self, d):
        self._last_diag = d
        if d.get("dist_hs", -1) >= self.best_diag.get("dist_hs", -1) and "dist_hs" in d:
            self.best_diag = dict(d)

    def reset_best(self):
        self.best_diag = {}

    # ------------------------------------------------------------------
    def reset(self):
        """Xóa toàn bộ trạng thái (kể cả thời gian nghỉ và khóa chiều ngược)."""
        self._clear_history()
        self._cooldown_until = 0.0
        self._block_dir = None
        self._block_until = 0.0
        self._last_sample_time = None
        self._palm_lost_since = None
        self._last_raw_x = None
        self._dts = deque(maxlen=15)

    def _release_block(self):
        """Gỡ khóa chiều ngược. Đồng thời XÓA lịch sử: phần cú vung về đang nằm trong lịch sử
        không được phép tính thành vẩy ngay khi vừa hết khóa (bài thử mô phỏng cho thấy nếu
        không xóa thì cú vung về vẫn bị báo thành vẩy ngược chiều đúng lúc hết khóa)."""
        if self._block_dir is not None:
            self._block_dir = None
            last = self._history[-1] if self._history else None
            self._history.clear()
            if last is not None:
                self._history.append(last)

    def _clear_history(self):
        self._pending = None
        self._history = deque()          # (thời gian, x_hs, y_hs)
        self._size_ema = None
        self._speed_ema = None
        self._slow_since = None
        self._open_dropped = 0

    # ------------------------------------------------------------------
    def update(self, hand, now=None, palm_open=True):
        now = time.perf_counter() if now is None else now

        # --- Tay vừa biến mất khi đang chạy nhanh về mép khung -> có thể là vẩy ---
        if hand is None:
            fired = self._edge_exit(now)
            if fired:
                return fired
            if self._pending is not None:        # tay biến mất ngay sau cú vẩy: coi như cú vẩy đã kết thúc
                return self._fire(self._pending["dir"], self._pending["diag"], now)
        else:
            self._last_raw_x = palm_center(hand)[0]

        # --- Không có tay: chỉ xóa lịch sử nếu mất dấu QUÁ LÂU (chịu được 1-2 khung mất dấu) ---
        if hand is None:
            if self._last_sample_time is None or now - self._last_sample_time > self.lost_grace:
                self._clear_history()
                self._block_dir = None
                self._last_sample_time = None
                self._palm_lost_since = None
            self.last_diag = {"reason": "no_hand"}
            return None

        # --- Nhãn Open palm rớt: cho phép ngắn hạn (ảnh nhòe khi tay chạy nhanh) ---
        if palm_open:
            self._palm_lost_since = None
        else:
            if self._palm_lost_since is None:
                self._palm_lost_since = now
            if now - self._palm_lost_since > self.palm_grace:
                if self._pending is not None:    # nhãn Open palm rớt ngay sau cú vẩy: báo cú đang chờ
                    return self._fire(self._pending["dir"], self._pending["diag"], now)
                self._clear_history()
                self._block_dir = None
                self._last_sample_time = None
                self.last_diag = {"reason": "palm_closed"}
                return None
            self._open_dropped += 1

        # --- Ghi điểm mới (đổi sang đơn vị kích thước bàn tay) ---
        x, y = palm_center(hand)
        size = max(hand_apparent_size(hand), 1e-6)
        if self._size_ema is None:
            self._size_ema = size
        else:
            self._size_ema += self.size_smoothing * (size - self._size_ema)
        px, py = x / self._size_ema, y * self.aspect_hw / self._size_ema

        if self._last_sample_time is not None:
            dt = now - self._last_sample_time
            if dt > 0:
                self._dts.append(dt)
                if self._history:
                    _, lx, ly = self._history[-1]
                    inst = math.hypot(px - lx, py - ly) / dt
                    self._speed_ema = inst if self._speed_ema is None else 0.5 * inst + 0.5 * self._speed_ema
        self._last_sample_time = now
        self._history.append((now, px, py))

        # --- Cập nhật "tay đã dừng" -> gỡ khóa chiều ngược ---
        if self._speed_ema is not None and self._speed_ema < self.settle_speed_hs:
            if self._slow_since is None:
                self._slow_since = now
            if now - self._slow_since >= self.settle_time:
                self._release_block()
        else:
            self._slow_since = None
        if self._block_dir is not None and now >= self._block_until:
            self._release_block()

        # --- Cắt lịch sử theo cửa sổ (tự giãn theo FPS) ---
        window, max_duration = self._window_for_fps()
        while self._history and now - self._history[0][0] > window:
            self._history.popleft()

        if len(self._history) < 2:
            self.last_diag = {"reason": "few_points", "n": len(self._history)}
            return None

        if self._pending is not None:
            res = self._resolve_pending(now, px, py)
            if res is not None:
                return res
            if self._pending is not None:
                self.last_diag = {"reason": "hold", "dir": self._pending["dir"]}
                return None

        diag = self._evaluate(max_duration)
        diag["open_dropped"] = self._open_dropped
        diag["fps"] = round(self.fps_est(), 1)
        direction = diag.pop("_direction", None)

        if direction is None:
            self.last_diag = diag
            return None
        if now < self._cooldown_until:
            diag["reason"] = "cooldown"
            self.last_diag = diag
            return None
        if self._block_dir == direction:
            diag["reason"] = "reverse_lock"
            self.last_diag = diag
            return None

        if self.confirm_hold_s > 0:
            # Chờ xác nhận: ghi nhớ cú vẩy, chưa báo (xem _resolve_pending)
            axis_is_x = direction in ("left", "right")
            sign = 1 if direction in ("right", "down") else -1
            cur = px if axis_is_x else py
            self._pending = {"dir": direction, "diag": diag, "since": now, "sign": sign, "axis_x": axis_is_x,
                             "peak": max(diag.get("peak_hs", 0.0), 1e-6), "extreme": sign * cur,
                             "rev_peak": 0.0, "prev": (now, cur)}
            diag["reason"] = "hold"
            self.last_diag = diag
            return None
        return self._fire(direction, diag, now)

    def _resolve_pending(self, now, px, py):
        """Xử lý cú vẩy đang chờ xác nhận. Trả về hướng nếu báo vẩy; None nếu tiếp tục chờ hoặc đã hủy."""
        p = self._pending
        cur = px if p["axis_x"] else py
        progress = p["sign"] * cur
        p["extreme"] = max(p["extreme"], progress)
        t0, v0 = p["prev"]
        dt = now - t0
        if dt > 0:
            rev_speed = p["sign"] * (v0 - cur) / dt            # > 0 khi tay đang đi NGƯỢC chiều cú vẩy
            p["rev_peak"] = max(p["rev_peak"], rev_speed)
        p["prev"] = (now, cur)
        reversed_by = p["extreme"] - progress

        if reversed_by >= self.backswing_rev_hs:
            if p["rev_peak"] >= self.backswing_speed_ratio * p["peak"]:
                self._pending = None                           # cú đang chờ chỉ là lấy đà -> bỏ
                self.last_diag = {"reason": "backswing_dropped", "dir": p["dir"]}
                return None
            return self._fire(p["dir"], p["diag"], now)       # quay đầu chậm = thu tay về -> báo cú vẩy
        if now - p["since"] >= self.confirm_hold_s:
            return self._fire(p["dir"], p["diag"], now)
        return None

    def _fire(self, direction, diag, now):
        """Báo vẩy: ghi nhận, đặt thời gian nghỉ, khóa chiều ngược, xóa lịch sử."""
        diag["reason"] = "ok"
        self.last_diag = diag
        self._pending = None
        self._cooldown_until = now + self.cooldown
        self._block_dir = _OPPOSITE[direction]
        self._block_until = now + self.reverse_lock
        self._history.clear()
        self._speed_ema = None
        self._slow_since = None
        self._open_dropped = 0
        return direction

    # ------------------------------------------------------------------
    def fps_est(self):
        """FPS ước lượng từ khoảng cách thời gian giữa các khung (trung vị)."""
        if not self._dts:
            return 0.0
        dts = sorted(self._dts)
        med = dts[len(dts) // 2]
        return 1.0 / med if med > 0 else 0.0

    def _window_for_fps(self):
        """Độ dài cửa sổ và thời lượng tối đa, giãn ra khi máy chậm để vẫn đủ điểm."""
        fps = self.fps_est()
        if fps <= 0:
            return self.window, self.max_duration
        frame_time = 1.0 / fps
        window = max(self.window, (self.min_points + 3) * frame_time)
        max_duration = max(self.max_duration, (self.min_points + 1) * frame_time)
        return window, max_duration

    def _limits_for(self, direction):
        """(quãng tối thiểu, tốc độ tối thiểu) cho từng hướng: vẩy trái có ngưỡng riêng."""
        if direction == "left":
            return self.left_min_distance_hs, self.left_min_speed_hs
        return self.min_distance_hs, self.min_speed_hs

    def _best_run(self, values):
        """Tìm đoạn chuyển động MỘT CHIỀU kết thúc ở điểm mới nhất. `values` là tọa độ theo 1
        trục (đơn vị hs). Trả về (độ_dịch_có_dấu, chỉ_số_điểm_bắt_đầu).
        Quét ngược: với mỗi chiều (+/-), độ dịch từ điểm i tới điểm mới nhất tăng dần khi
        lùi về điểm quay đầu; nếu nó tụt xuống quá dung sai so với đỉnh đã thấy nghĩa là đã
        đi qua điểm quay đầu (phía trước là cú lấy đà ngược) -> dừng."""
        n = len(values)
        best = (0.0, n - 1)
        for sign in (1, -1):
            top, top_i = 0.0, n - 1
            for i in range(n - 2, -1, -1):
                d = sign * (values[-1] - values[i])
                if d >= top:
                    top, top_i = d, i
                elif top - d > self.reverse_tolerance_hs:
                    break
            if top > abs(best[0]):
                best = (sign * top, top_i)
        return best

    def _evaluate(self, max_duration):
        ts = [p[0] for p in self._history]
        xs = [p[1] for p in self._history]
        ys = [p[2] for p in self._history]
        dx, ix = self._best_run(xs)
        dy, iy = self._best_run(ys)

        if abs(dx) >= abs(dy):
            axis, disp, start, vals = "x", dx, ix, xs
            direction = "right" if dx > 0 else "left"
        else:
            axis, disp, start, vals = "y", dy, iy, ys
            direction = "down" if dy > 0 else "up"

        # Bỏ phần tay còn đứng yên đầu đoạn: tính từ lúc BẮT ĐẦU cử động thật
        sign = 1 if disp > 0 else -1
        onset = start
        while onset < len(ts) - 1 and sign * (vals[onset] - vals[start]) < self.onset_fraction * abs(disp):
            onset += 1
        other = ys if axis == "x" else xs
        cross = other[-1] - other[onset]
        duration = ts[-1] - ts[onset]
        # Khoảng MẤT DẤU TAY giữa chừng (> SWIPE_GAP_S giữa 2 điểm liên tiếp) không phải lúc tay
        # chuyển động chậm: tay chỉ biến mất rồi hiện lại ở xa hơn. Trừ bớt để không bị loại "too_long".
        for k in range(onset + 1, len(ts)):
            gap = ts[k] - ts[k - 1]
            if gap > self.gap_s:
                duration -= gap - self.gap_s
        npts = len(ts) - onset
        speed = abs(disp) / duration if duration > 0 else 0.0
        ratio = abs(disp) / abs(cross) if abs(cross) > 1e-9 else 99.0

        # Lấy đà ngược: tay đã đi bao xa NGƯỢC chiều vẩy trước điểm bắt đầu đoạn vẩy
        windup = max([0.0] + [sign * (vals[j] - vals[start]) for j in range(start)])
        # Vận tốc đỉnh (chênh 2 khung để bớt nhiễu)
        peak = 0.0
        step = 2 if npts >= 3 else 1
        for j in range(start, len(ts) - step):
            dt = ts[j + step] - ts[j]
            if dt > 0:
                peak = max(peak, abs(vals[j + step] - vals[j]) / dt)

        diag = {"axis": axis, "dist_hs": round(abs(disp), 2), "duration": round(duration, 3),
                "speed_hs": round(speed, 2), "peak_hs": round(peak, 2), "ratio": round(min(ratio, 99.0), 1),
                "n": npts, "windup_hs": round(windup, 2), "dir": direction}

        min_dist, min_speed = self._limits_for(direction)
        if abs(disp) < min_dist:
            diag["reason"] = "short"
        elif ((npts < self.min_points and not (npts >= 2 and abs(disp) >= self.sparse_distance_hs))
              or duration < self.min_run_time):
            diag["reason"] = "few_points"
        elif duration > max_duration:
            diag["reason"] = "too_long"
        elif speed < min_speed:
            diag["reason"] = "slow"
        elif ratio < self.axis_ratio:
            diag["reason"] = "diagonal"
        else:
            diag["reason"] = "candidate"
            diag["_direction"] = direction
        return diag

    def _edge_exit(self, now):
        """Tay vừa biến mất khi đang chạy NHANH về một mép khung -> báo vẩy theo hướng mép đó.
        Điều kiện (đều phải đúng): tâm tay lần cuối thấy cách mép < edge_margin; có >= 2 điểm
        trong 0,3 s gần nhất; đoạn chạy về phía mép dài >= edge_min_distance_hs; tốc độ khung
        cuối >= edge_min_speed_hs; đi chủ yếu theo trục ngang."""
        if (self._last_sample_time is None or self._last_raw_x is None
                or now - self._last_sample_time > self.lost_grace
                or len(self._history) < 2):
            return None
        if self._last_raw_x <= self.edge_margin:
            edge_dir = "left"
        elif self._last_raw_x >= 1.0 - self.edge_margin:
            edge_dir = "right"
        else:
            return None
        recent = [p for p in self._history if self._last_sample_time - p[0] <= 0.3]
        if len(recent) < 2:
            return None
        xs = [p[1] for p in recent]
        ys = [p[2] for p in recent]
        disp, _ = self._best_run(xs)
        direction = "right" if disp > 0 else "left"
        dt_last = recent[-1][0] - recent[-2][0]
        last_speed = abs(xs[-1] - xs[-2]) / dt_last if dt_last > 0 else 0.0
        cross = abs(ys[-1] - ys[0])
        diag = {"edge": edge_dir, "dist_hs": round(abs(disp), 2), "last_speed_hs": round(last_speed, 2),
                "dir": direction}
        if direction != edge_dir:
            diag["reason"] = "edge_wrong_dir"
        elif abs(disp) < self.edge_min_distance_hs:
            diag["reason"] = "edge_short"
        elif last_speed < self.edge_min_speed_hs:
            diag["reason"] = "edge_slow"
        elif cross > 0 and abs(disp) / cross < self.axis_ratio:
            diag["reason"] = "edge_diagonal"
        else:
            diag["reason"] = "edge_candidate"
        if diag["reason"] != "edge_candidate":
            self.last_diag = diag
            return None
        direction = edge_dir
        if now < self._cooldown_until:
            diag["reason"] = "cooldown"
            self.last_diag = diag
            return None
        if self._block_dir == direction:
            diag["reason"] = "reverse_lock"
            self.last_diag = diag
            return None
        diag["reason"] = "ok_edge"
        self._pending = None
        self.last_diag = diag
        self._cooldown_until = now + self.cooldown
        self._block_dir = _OPPOSITE[direction]
        self._block_until = now + self.reverse_lock
        self._history.clear()
        self._speed_ema = None
        self._slow_since = None
        self._open_dropped = 0
        self._last_raw_x = None
        return direction


# =====================================================================
# GHI CHẨN ĐOÁN CHO MỖI LƯỢT VẨY (dùng trong self_test.py, KHÔNG phụ thuộc bản thuật toán)
# =====================================================================
class SwipeTrace:
    """
    Ghi lại chuyển động tay trái trong MỘT lượt thử vẩy rồi tóm tắt thành 1 chuỗi
    "khóa=giá_trị;..." để bỏ vào cột detail của log. Mục đích: biết VÌ SAO một lượt vẩy
    thất bại (ngắn? chậm? lấy đà ngược? nhãn Open palm rớt?) thay vì đoán.

    Cách dùng trong self_test.py (mỗi lượt thử):
        trace = SwipeTrace()                      # đầu lượt
        trace.add(left_hand_or_None, palm_open)   # mỗi khung hình trong lượt
        detail = trace.summary()                  # cuối lượt -> ghi vào cột detail

    Các số trong summary():
      n_frames, fps, hand_missing       : số khung, FPS trung bình, số khung mất dấu tay
      open_dropped                      : số khung tay có mặt nhưng nhãn KHÔNG phải Open palm
      size                              : kích thước tay trung bình trên ảnh (to = gần camera)
      best_dx_frame, best_dx_hs         : dịch chuyển ngang lớn nhất trong 0,5 s (có dấu: + = sang
                                          phải; đơn vị: phần khung hình / kích thước bàn tay)
      best_dy_frame                     : dịch chuyển dọc trong cùng cửa sổ đó
      dxdy                              : tỉ lệ |dx|/|dy| (bản cũ cần > 2)
      peak_speed_hs                     : vận tốc đỉnh (kích thước bàn tay / giây)
      n_in_window                       : số điểm trong cửa sổ 0,5 s tốt nhất (bản cũ cần >= 3)
      opp_before_frame / opp_after_frame: tay đi NGƯỢC chiều chính bao xa TRƯỚC / SAU cú vẩy
                                          (trước = lấy đà, sau = vung về)
    """

    WINDOW = 0.5

    def __init__(self, aspect_hw=SWIPE_ASPECT_HW):
        self.aspect_hw = aspect_hw
        self._samples = []        # (t, x, y, size, palm_open)
        self._missing = 0

    def add(self, hand, palm_open=True, now=None):
        now = time.perf_counter() if now is None else now
        if hand is None:
            self._missing += 1
            return
        x, y = palm_center(hand)
        self._samples.append((now, x, y, hand_apparent_size(hand), bool(palm_open)))

    def summary(self):
        s = self._samples
        out = {"n_frames": len(s) + self._missing, "hand_missing": self._missing}
        if len(s) < 2:
            return self._fmt(out)
        total_t = s[-1][0] - s[0][0]
        out["fps"] = round((len(s) - 1) / total_t, 1) if total_t > 0 else 0
        out["open_dropped"] = sum(1 for p in s if not p[4])
        size = sum(p[3] for p in s) / len(s)
        out["size"] = round(size, 3)

        # Cửa sổ 0,5 s có dịch chuyển ngang (đầu -> cuối) lớn nhất
        best = None
        for i in range(len(s)):
            j = i
            while j + 1 < len(s) and s[j + 1][0] - s[i][0] <= self.WINDOW:
                j += 1
            if j > i:
                d = s[j][1] - s[i][1]
                if best is None or abs(d) > abs(best[0]):
                    best = (d, i, j)
        if best is None:
            return self._fmt(out)
        dx, i, j = best
        dy = s[j][2] - s[i][2]
        out["best_dx_frame"] = round(dx, 3)
        out["best_dx_hs"] = round(dx / size, 2) if size > 0 else 0
        out["best_dy_frame"] = round(dy, 3)
        out["dxdy"] = round(abs(dx) / abs(dy * self.aspect_hw), 1) if abs(dy) > 1e-9 else 99.0
        out["n_in_window"] = j - i + 1

        peak = 0.0
        for k in range(i, j - 1):
            dt = s[k + 2][0] - s[k][0]
            if dt > 0 and size > 0:
                peak = max(peak, abs(s[k + 2][1] - s[k][1]) / size / dt)
        out["peak_speed_hs"] = round(peak, 2)
        # Vị trí ngang thô (0 = mép trái, 1 = mép phải của hình đã lật gương): để kiểm tra giả
        # thuyết "tay chạy ra mép rồi mất dấu". x_start/x_end = đầu/cuối cửa sổ vẩy tốt nhất,
        # x_min/x_max = nhỏ/lớn nhất cả lượt, last_seen_x = điểm CUỐI cùng còn thấy tay.
        out["x_start"] = round(s[i][1], 3)
        out["x_end"] = round(s[j][1], 3)
        out["x_min"] = round(min(p[1] for p in s), 3)
        out["x_max"] = round(max(p[1] for p in s), 3)
        out["last_seen_x"] = round(s[-1][1], 3)

        # Chuyển động NGƯỢC chiều chính trước / sau cửa sổ vẩy
        sign = 1 if dx > 0 else -1
        before = max([0.0] + [sign * (s[k][1] - s[i][1]) for k in range(0, i)])
        after = max([0.0] + [-sign * (s[k][1] - s[j][1]) for k in range(j, len(s))])
        out["opp_before_frame"] = round(before, 3)
        out["opp_after_frame"] = round(after, 3)
        return self._fmt(out)

    @staticmethod
    def _fmt(d):
        return ";".join(f"{k}={v}" for k, v in d.items())