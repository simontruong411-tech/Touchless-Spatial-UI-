"""
perf_monitor.py
--------------------
Đo HIỆU NĂNG của phần mềm trong lúc chạy, để có số liệu cho báo cáo (tiêu chí TC4
"phản hồi nhanh") mà không cần người quan sát bấm tay:

  - FPS (frames per second): số khung hình phần mềm xử lý được mỗi giây.
    Webcam thường cho tối đa khoảng 30 FPS; FPS càng gần 30 thì con trỏ càng mượt.
  - frame_ms: thời gian phần mềm xử lý TRỌN 1 khung hình, tính từ lúc nhận được
    hình từ camera (AI -> nhận diện cử chỉ -> vẽ màn hình), đơn vị mili-giây
    (ms, 1 giây = 1000 ms). Không tính thời gian chờ camera chụp khung tiếp theo.
  - ai_ms: riêng thời gian MediaPipe tìm 21 điểm trên bàn tay (bước tốn nhất).

VÌ SAO BÁO CÁO CẢ "TRUNG BÌNH" VÀ "P95":
  Trung bình (mean) cho biết bình thường máy chạy nhanh cỡ nào. Nhưng người dùng
  khó chịu nhất là những lần GIẬT bất thường — trung bình không thấy được. P95
  (phân vị 95%) = mức mà 95% số khung hình nhanh hơn; nói cách khác chỉ 5% số
  khung hình chậm hơn mức này. Giám khảo yêu cầu cả hai con số.

CÁCH DÙNG (xem main_spatial_ui_demo.py và self_test.py):
    perf = PerfMonitor()
    while True:
        ...đọc camera (cap.read)...
        perf.start_frame()                 # ngay sau khi có khung hình
        perf.start_ai(); hands = tracker.process(frame); perf.end_ai()
        ...xử lý, vẽ...
        perf.end_frame()                   # cuối vòng lặp (trước cv2.waitKey)
        if perf.should_report():           # mỗi REPORT_EVERY_S giây
            logger.log_event(mode, "PERF", detail=perf.window_detail())
    logger.extra_summary["performance"] = perf.summary()

Module này KHÔNG cần cài thêm thư viện nào (chỉ dùng thư viện có sẵn của Python).
"""

import time

# Mỗi bao nhiêu giây thì ghi 1 dòng PERF vào nhật ký (không ghi mỗi khung hình
# để file nhật ký không quá dài: 30 FPS x 10 phút = 18.000 dòng).
REPORT_EVERY_S = 10.0

# Giữ tối đa ngần này giá trị gần nhất để tính tóm tắt cả phiên (đủ ~1 giờ ở
# 30 FPS); quá thì bỏ bớt giá trị cũ nhất để không tốn bộ nhớ.
MAX_SAMPLES = 120_000


def percentile(values, p):
    """Phân vị p (0-100) theo cách "nội suy tuyến tính" — giống hàm PERCENTILE
    của Excel, để số liệu tự tính bằng Excel khớp với số phần mềm in ra.
    Ví dụ percentile([10, 20, 30, 40], 95) = 38.5."""
    if not values:
        return None
    data = sorted(values)
    if len(data) == 1:
        return float(data[0])
    k = (len(data) - 1) * p / 100.0
    lower = int(k)
    upper = min(lower + 1, len(data) - 1)
    return data[lower] + (data[upper] - data[lower]) * (k - lower)


def describe(values, digits=1):
    """Thống kê mô tả của 1 dãy số: n, trung bình, trung vị, P95, nhỏ nhất, lớn nhất."""
    if not values:
        return {"n": 0}
    n = len(values)
    mean = sum(values) / n
    return {
        "n": n,
        "mean": round(mean, digits),
        "median": round(percentile(values, 50), digits),
        "p95": round(percentile(values, 95), digits),
        "min": round(min(values), digits),
        "max": round(max(values), digits),
    }


class PerfMonitor:
    def __init__(self, report_every_s=REPORT_EVERY_S):
        self.report_every_s = report_every_s
        self.frame_ms = []          # thời gian xử lý từng khung (cả phiên)
        self.ai_ms = []             # thời gian AI từng khung (cả phiên)
        self.frame_starts = []      # thời điểm bắt đầu từng khung -> tính FPS
        self._window_frame_ms = []  # chỉ trong cửa sổ REPORT_EVERY_S hiện tại
        self._window_ai_ms = []
        self._window_start = time.perf_counter()
        self._t_frame = None
        self._t_ai = None
        self.last_ai_ms = 0.0       # thời gian AI của khung vừa xong (self_test dùng)
        self.last_frame_ms = 0.0

    # -- Gọi trong vòng lặp ---------------------------------------------------------
    def start_frame(self):
        self._t_frame = time.perf_counter()
        self.frame_starts.append(self._t_frame)

    def start_ai(self):
        self._t_ai = time.perf_counter()

    def end_ai(self):
        if self._t_ai is None:
            return
        ms = (time.perf_counter() - self._t_ai) * 1000.0
        self._t_ai = None
        self.last_ai_ms = ms
        self.ai_ms.append(ms)
        self._window_ai_ms.append(ms)

    def end_frame(self):
        if self._t_frame is None:
            return
        ms = (time.perf_counter() - self._t_frame) * 1000.0
        self._t_frame = None
        self.last_frame_ms = ms
        self.frame_ms.append(ms)
        self._window_frame_ms.append(ms)
        # Giới hạn bộ nhớ
        for lst in (self.frame_ms, self.ai_ms, self.frame_starts):
            if len(lst) > MAX_SAMPLES:
                del lst[: len(lst) - MAX_SAMPLES]

    # -- Báo cáo định kỳ --------------------------------------------------------------
    def should_report(self):
        return time.perf_counter() - self._window_start >= self.report_every_s

    def window_detail(self):
        """Chuỗi ngắn ghi vào cột detail của nhật ký, rồi bắt đầu cửa sổ mới.
        Ví dụ: "fps=28.6;frame_ms_mean=31.2;frame_ms_p95=38.0;ai_ms_mean=18.4;ai_ms_p95=24.9"."""
        now = time.perf_counter()
        seconds = max(now - self._window_start, 1e-9)
        fps = len(self._window_frame_ms) / seconds
        f = describe(self._window_frame_ms)
        a = describe(self._window_ai_ms)
        self._window_frame_ms = []
        self._window_ai_ms = []
        self._window_start = now
        return (f"fps={fps:.1f};frame_ms_mean={f.get('mean', 0)};frame_ms_p95={f.get('p95', 0)};"
                f"ai_ms_mean={a.get('mean', 0)};ai_ms_p95={a.get('p95', 0)}")

    def fps_values(self):
        """FPS tức thời giữa 2 khung liên tiếp = 1 / khoảng cách thời gian."""
        out = []
        for t0, t1 in zip(self.frame_starts, self.frame_starts[1:]):
            if t1 > t0:
                out.append(1.0 / (t1 - t0))
        return out

    def summary(self):
        """Tóm tắt cả phiên (ghi vào file _meta.json / _summary.json)."""
        total_s = (self.frame_starts[-1] - self.frame_starts[0]) if len(self.frame_starts) > 1 else 0.0
        return {
            "frames": len(self.frame_ms),
            "fps_average": round((len(self.frame_starts) - 1) / total_s, 1) if total_s > 0 else None,
            "fps_instant": describe(self.fps_values()),
            "frame_ms": describe(self.frame_ms),
            "ai_ms": describe(self.ai_ms),
        }
