"""
snap_detector.py
--------------------
Phát hiện gesture "Snap" (búng ngón tay) — dùng để mở/đóng Spatial UI menu.

CẢNH BÁO QUAN TRỌNG (đọc trước khi dùng):
  Snap thật ngoài đời là ngón cái ép vào ngón giữa rồi bật ra thật nhanh,
  tạo tiếng "tách". MediaPipe chỉ cho ta landmark hình ảnh, KHÔNG nghe được
  âm thanh, và chuyển động bung ngón tay diễn ra trong một khoảng thời gian
  rất ngắn (vài chục mili-giây) — có thể còn nhanh hơn tốc độ camera bắt
  kịp (webcam thường 30 FPS = 1 frame mỗi ~33ms).
  => Gesture này là gesture KHÓ NHẤT trong 5 gesture, độ chính xác có thể
     không cao. Nếu sau khi test bạn thấy Snap không ổn định (không detect
     được, hoặc detect nhầm liên tục), phương án B đơn giản và chắc chắn
     hơn nhiều là: "giữ Open palm 0.8 giây" để mở menu. Mình để sẵn class
     HoldGestureDetector ở cuối file cho phương án B này, dùng ngay được.

Cách hoạt động của SnapDetector (state machine 2 trạng thái):
  1. "Chưa cock" (chưa ép sát): theo dõi khoảng cách world giữa đầu ngón
     cái (landmark 4) và đầu ngón giữa (landmark 12). Nếu khoảng cách này
     nhỏ hơn cock_dist -> coi như tay đang ở tư thế "chuẩn bị búng"
     (2 ngón ép sát nhau), chuyển sang trạng thái "đã cock" và ghi lại
     thời điểm.
  2. "Đã cock": nếu trong vòng max_release_time giây tiếp theo, khoảng
     cách 2 ngón đột ngột lớn hơn release_dist -> đây là một cú "bung
     ngón tay nhanh" -> báo Snap = True. Nếu quá thời gian mà vẫn chưa
     bung đủ nhanh/đủ xa -> coi như không phải snap thật (có thể người
     dùng chỉ đang giữ tay ở tư thế đó), reset lại trạng thái.
  3. Có cooldown để 1 lần búng tay không bị báo thành nhiều Snap liên tiếp.
"""

import time

THUMB_TIP = 4
MIDDLE_TIP = 12


class SnapDetector:
    def __init__(self, cock_dist=0.025, release_dist=0.07,
                 max_release_time=0.25, cooldown_sec=0.5):
        """
        cock_dist        : khoảng cách (mét) đủ nhỏ để coi là "đã ép sát".
        release_dist     : khoảng cách (mét) đủ lớn để coi là "đã bung ra".
        max_release_time : thời gian tối đa (giây) từ lúc cock đến lúc phải
                            bung ra, để tính là 1 cú búng NHANH (chứ không
                            phải từ từ tách 2 ngón ra).
        cooldown_sec      : sau khi báo Snap, khóa bấy nhiêu giây trước khi
                            có thể báo Snap lần tiếp theo.

        LƯU Ý: 4 con số này gần như chắc chắn phải chỉnh lại sau khi bạn
        test thực tế trên tay và camera của mình. Không có gì sai nếu bạn
        phải thử 5-10 lần để tìm ra bộ số phù hợp.
        """
        self.cock_dist = cock_dist
        self.release_dist = release_dist
        self.max_release_time = max_release_time
        self.cooldown_sec = cooldown_sec

        self._cocked = False
        self._cock_time = 0.0
        self._last_snap_time = 0.0

    def update(self, hand):
        """Gọi mỗi frame với 1 hand dict. Trả về True nếu vừa phát hiện Snap."""
        from hand_utils import distance  # import cục bộ để tránh vòng lặp import

        now = time.time()
        d = distance(hand, THUMB_TIP, MIDDLE_TIP, use_world=True)

        # Đang trong thời gian khóa -> không xét trạng thái cock mới
        if now - self._last_snap_time < self.cooldown_sec:
            return False

        if not self._cocked:
            if d < self.cock_dist:
                self._cocked = True
                self._cock_time = now
            return False

        # Đang ở trạng thái "đã cock", chờ xem có bung nhanh không
        dt = now - self._cock_time
        if dt > self.max_release_time:
            # Bung quá chậm hoặc chưa bung -> không tính là snap, reset
            self._cocked = False
            return False

        if d > self.release_dist:
            self._cocked = False
            self._last_snap_time = now
            return True

        return False

    def reset(self):
        self._cocked = False


class HoldGestureDetector:
    """
    PHƯƠNG ÁN B (đơn giản, chắc chắn hơn Snap nhiều):
    Phát hiện khi một gesture TĨNH (ví dụ Open palm) được giữ liên tục
    trong một khoảng thời gian nhất định -> dùng để mở/đóng menu thay
    cho Snap nếu Snap không ổn định.

    Cách dùng:
        holder = HoldGestureDetector(target_gesture="Open palm", hold_time=0.8)
        ...
        gesture_now = detect_gesture(hand)   # từ hand_utils.py
        if holder.update(gesture_now):
            # đã giữ đủ lâu -> toggle menu
    """

    def __init__(self, target_gesture, hold_time=0.8):
        self.target_gesture = target_gesture
        self.hold_time = hold_time
        self._hold_start = None
        self._triggered = False

    def update(self, current_gesture):
        now = time.time()

        if current_gesture != self.target_gesture:
            self._hold_start = None
            self._triggered = False
            return False

        if self._hold_start is None:
            self._hold_start = now
            return False

        if not self._triggered and (now - self._hold_start) >= self.hold_time:
            self._triggered = True
            return True

        return False