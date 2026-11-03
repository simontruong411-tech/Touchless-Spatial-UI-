"""
notepad.py
--------------------
"KY TEN": bảng ký tên/viết/vẽ bằng ngón tay trong không khí. Bác sĩ có thể phác nhanh một
sơ đồ hay vài chữ (ví dụ đánh dấu vị trí rạch, ghi một lưu ý cho cả kíp) mà KHÔNG phải
chạm bút/chuột, rồi lưu thành ảnh PNG. Đây là chức năng được đưa LẠI từ nhánh cũ
(archive/notepad.py), chỉnh cho khớp với phòng mổ: thêm nút BACK và thanh tiến trình
cho thao tác xóa.

Class chính: Notepad
  - start_stroke(pos) / draw_to(pos) / end_stroke() : vẽ 1 nét liên tục
  - clear()                                          : xóa sạch bảng vẽ
  - save()                                           : lưu bảng vẽ thành PNG (None nếu trống)
  - get_hover_button(cursor_pos)                     : "SAVE" / "BACK" / None
  - draw(cursor_pos, is_pinching_now, clear_progress): trả về 1 frame để hiển thị

Class phụ: PalmHoldClear
  - update(is_open) : đếm thời gian tay trái giữ Open palm; báo "đã đủ lâu" đúng MỘT
                      lần cho mỗi lần giữ (xem giải thích ở class)

CÁCH DÙNG TRONG main_spatial_ui_demo.py
  Tay phải: Pinch (chụm) = hạ bút và vẽ, thả Pinch = nhấc bút. Pinch lên nút SAVE =
  lưu, nút BACK = về menu. Tay trái: Snap = thoát về camera (giống các màn khác);
  GIỮ Open palm 0,8 giây = xóa hết (giữ lâu để vẫy tay ngang qua không xóa nhầm).

THIẾT KẾ (giữ nguyên từ bản cũ):
  - Canvas là 1 "tờ giấy" riêng (không phải video camera), cùng kích thước khung hình
    camera, để tọa độ con trỏ khớp nhau.
  - self.canvas chỉ chứa NÉT VẼ THẬT (không có cursor/toolbar) — để khi lưu file ra,
    ảnh sạch, không dính con trỏ hay chữ hướng dẫn.
  - Mỗi frame, draw() tạo 1 BẢN SAO của canvas rồi mới vẽ thêm toolbar + cursor + chữ
    hướng dẫn lên bản sao — canvas gốc không đổi.

QUYỀN RIÊNG TƯ: ảnh lưu vào thư mục "drawings/". Đừng viết tên/mã bệnh nhân thật vào
ghi chú. Kho GitHub là công khai nên thêm "drawings/" vào .gitignore.

GHI CHÚ MÀU SẮC: OpenCV dùng BGR (Blue, Green, Red), không phải RGB.
Chữ trên màn hình dùng ASCII không dấu vì cv2.putText không vẽ được dấu tiếng Việt.
"""

import os
import time

import cv2
import numpy as np

# --- Bảng màu (BGR) — cùng tông trầm với spatial_ui.py / image_viewer.py ---
COLOR_CANVAS_BG = (35, 34, 32)        # nền giấy: charcoal hơi ấm, không phải đen tuyền
COLOR_PEN = (225, 225, 225)           # màu nét vẽ: off-white
PEN_THICKNESS = 4

COLOR_TOOLBAR_BORDER = (75, 75, 80)
COLOR_ACCENT = (55, 150, 210)         # màu nhấn ấm (muted amber) khi hover/thông báo
COLOR_TEXT_HINT = (150, 150, 155)     # chữ hướng dẫn, màu dịu để không chiếm chú ý

BUTTON_SIZE = (110, 44)               # (width, height) của nút SAVE / BACK
BUTTON_MARGIN = 20
BUTTON_GAP = 12                       # khoảng cách giữa 2 nút

# Giữ Open palm bao lâu thì xóa hết. 0,8 s đủ lâu để một cú vẫy tay hay đổi tư thế
# thoáng qua không xóa mất bản vẽ, nhưng vẫn đủ nhanh để không bực mình.
CLEAR_HOLD_SECONDS = 0.8


class PalmHoldClear:
    """
    Đo thời gian tay trái GIỮ Open palm liên tục để làm lệnh "xóa hết".

    Vì sao cần class riêng: nếu xóa ngay khi vừa thấy Open palm thì mỗi lần tay trái
    xòe thoáng qua là mất bản vẽ. Bắt buộc giữ đủ CLEAR_HOLD_SECONDS mới xóa. Sau khi
    đã xóa, phải thả Open palm ra (is_open = False) rồi mới giữ lại được — nếu không,
    cứ giữ mãi thì cứ mỗi 0,8 s lại xóa một lần.

    update() trả về (đã_kích_hoạt, tiến_độ):
      đã_kích_hoạt : True ĐÚNG MỘT frame, lúc đủ thời gian giữ
      tiến_độ      : 0.0 -> 1.0, để vẽ thanh tiến trình cho người dùng thấy
    """

    def __init__(self, hold_seconds=CLEAR_HOLD_SECONDS):
        self.hold_seconds = hold_seconds
        self._start = None        # thời điểm bắt đầu giữ; None = chưa/không đang giữ
        self._fired = False       # đã xóa trong lần giữ này chưa

    def reset(self):
        self._start = None
        self._fired = False

    def update(self, is_open, now=None):
        if now is None:
            now = time.perf_counter()
        if not is_open:
            self.reset()
            return False, 0.0
        if self._start is None:
            self._start = now
        if self._fired:
            return False, 1.0     # đã xóa rồi: chờ thả tay ra mới xóa lại được
        progress = min(1.0, (now - self._start) / self.hold_seconds)
        if progress >= 1.0:
            self._fired = True
            return True, 1.0
        return False, progress


class Notepad:
    def __init__(self, frame_width, frame_height, save_dir="drawings"):
        self.width = frame_width
        self.height = frame_height
        self.save_dir = save_dir

        # canvas: chỉ chứa nét vẽ thật, KHÔNG vẽ cursor/toolbar lên đây
        self.canvas = np.full((frame_height, frame_width, 3), COLOR_CANVAS_BG, dtype=np.uint8)

        self._prev_point = None   # điểm trước đó của nét đang vẽ, None = chưa "hạ bút"
        self._has_ink = False     # đã có nét nào chưa (để không lưu tờ giấy trống)

        # Hai nút ở góc trên-trái: SAVE rồi BACK bên cạnh. Cùng dạng (x, y, w, h) với
        # self.buttons của image_viewer.py / model_viewer.py để dễ đọc code.
        bw, bh = BUTTON_SIZE
        self.buttons = {
            "SAVE": (BUTTON_MARGIN, BUTTON_MARGIN, bw, bh),
            "BACK": (BUTTON_MARGIN + bw + BUTTON_GAP, BUTTON_MARGIN, bw, bh),
        }
        self.save_button_rect = self.buttons["SAVE"]   # giữ tên cũ cho tương thích

        self._message = ""
        self._message_until = 0.0

    # -- Vẽ nét --------------------------------------------------------------
    def start_stroke(self, pos):
        """Gọi khi Pinch VỪA bắt đầu (bắt đầu 1 nét mới). Chấm 1 điểm tại chỗ để một
        cú chạm nhanh (chụm rồi thả) vẫn để lại dấu chấm, không bị mất nét."""
        point = (int(pos[0]), int(pos[1]))
        cv2.circle(self.canvas, point, PEN_THICKNESS // 2, COLOR_PEN, -1, cv2.LINE_AA)
        self._prev_point = point
        self._has_ink = True

    def draw_to(self, pos):
        """Gọi mỗi frame trong lúc đang giữ Pinch để vẽ tiếp nét hiện tại."""
        current_point = (int(pos[0]), int(pos[1]))
        if self._prev_point is not None:
            cv2.line(self.canvas, self._prev_point, current_point,
                     COLOR_PEN, PEN_THICKNESS, cv2.LINE_AA)
            self._has_ink = True
        self._prev_point = current_point

    def end_stroke(self):
        """Gọi khi Pinch VỪA thả ra (kết thúc nét hiện tại)."""
        self._prev_point = None

    def clear(self):
        """Xóa sạch bảng vẽ — dùng cho thao tác 'giữ Open palm 0,8 giây'."""
        self.canvas[:] = COLOR_CANVAS_BG
        self._prev_point = None
        self._has_ink = False
        self._show_message("Da xoa")

    # -- Lưu file -------------------------------------------------------------
    def save(self):
        """Lưu canvas (chỉ nét vẽ) thành PNG. Trả về đường dẫn file, hoặc None nếu bảng
        còn trống (không tạo file rác)."""
        if not self._has_ink:
            self._show_message("Chua co gi de luu")
            return None
        os.makedirs(self.save_dir, exist_ok=True)
        # Thêm phần lẻ giây để hai lần lưu trong cùng 1 giây không đè lên nhau.
        stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"
        filename = f"notepad_{stamp}.png"
        path = os.path.join(self.save_dir, filename)
        cv2.imwrite(path, self.canvas)
        self._show_message(f"Da luu: {filename}")
        return path

    def _show_message(self, text, seconds=2.5):
        self._message = text
        self._message_until = time.time() + seconds

    # -- Tương tác với nút -----------------------------------------------------
    def get_hover_button(self, cursor_pos):
        """Trả về "SAVE" / "BACK" nếu con trỏ đang ở trên nút đó, không thì None."""
        if cursor_pos is None:
            return None
        x, y = cursor_pos
        for label, (bx, by, bw, bh) in self.buttons.items():
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return label
        return None

    def get_hover_save_button(self, cursor_pos):
        """Giữ lại từ bản cũ (tương thích)."""
        return self.get_hover_button(cursor_pos) == "SAVE"

    # -- Hiển thị ---------------------------------------------------------------
    def draw(self, cursor_pos=None, is_pinching_now=False, clear_progress=0.0):
        """
        Trả về 1 frame để cv2.imshow(), gồm: bản sao canvas + 2 nút + cursor (bút) +
        thanh tiến trình xóa + vài dòng chữ hướng dẫn ở dưới cùng.
        KHÔNG sửa self.canvas — canvas gốc chỉ chứa nét vẽ thật.

        is_pinching_now : đang Pinch (hạ bút). Pinch lên nút thì là bấm nút chứ không phải
                          vẽ, nên chỉ coi là "đang vẽ" khi con trỏ KHÔNG ở trên nút.
        clear_progress  : 0.0 -> 1.0 từ PalmHoldClear, > 0 thì vẽ thanh tiến trình.
        """
        display = self.canvas.copy()
        hovered = self.get_hover_button(cursor_pos)
        is_drawing = is_pinching_now and hovered is None

        # -- Hai nút --
        for label, (bx, by, bw, bh) in self.buttons.items():
            is_hover = label == hovered
            border_color = COLOR_ACCENT if is_hover else COLOR_TOOLBAR_BORDER
            text_color = COLOR_ACCENT if is_hover else COLOR_PEN
            cv2.rectangle(display, (bx, by), (bx + bw, by + bh), border_color, 2)
            size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0]
            cv2.putText(display, label, (bx + (bw - size[0]) // 2, by + (bh + size[1]) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_color, 1, cv2.LINE_AA)

        # -- Cursor (bút) --
        if cursor_pos is not None:
            cx, cy = int(cursor_pos[0]), int(cursor_pos[1])
            if is_drawing:
                # Đang vẽ: chấm đặc để thấy rõ "đầu bút đang chạm giấy"
                cv2.circle(display, (cx, cy), PEN_THICKNESS, COLOR_ACCENT, -1, cv2.LINE_AA)
            else:
                # Không vẽ: vòng tròn viền mảnh, bán trong suốt ("tàng hình")
                overlay = display.copy()
                cv2.circle(overlay, (cx, cy), 10, COLOR_PEN, 1, cv2.LINE_AA)
                cv2.addWeighted(overlay, 0.55, display, 0.45, 0, display)

        # -- Thanh tiến trình "đang giữ Open palm để xóa" (chạy từ trái sang phải) --
        if clear_progress > 0.0:
            bar_x, bar_y, bar_w, bar_h = BUTTON_MARGIN, self.height - 60, 200, 8
            cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), COLOR_TOOLBAR_BORDER, 1)
            fill = int(bar_w * min(1.0, clear_progress))
            if fill > 0:
                cv2.rectangle(display, (bar_x, bar_y), (bar_x + fill, bar_y + bar_h), COLOR_ACCENT, -1)
            cv2.putText(display, "Giu de xoa het", (bar_x, bar_y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_ACCENT, 1, cv2.LINE_AA)

        # -- Chữ thông báo ("Da luu: ...") hiện tạm vài giây rồi tự ẩn --
        if self._message and time.time() < self._message_until:
            _, by0, _, bh0 = self.buttons["SAVE"]
            cv2.putText(display, self._message, (BUTTON_MARGIN, by0 + bh0 + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_ACCENT, 1, cv2.LINE_AA)

        # -- Chữ hướng dẫn nhỏ ở dưới cùng, để không quên thao tác --
        hint = "Phai: Pinch = ve | Trai: Snap = thoat, giu Open palm 0.8s = xoa het"
        cv2.putText(display, hint, (BUTTON_MARGIN, self.height - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_TEXT_HINT, 1, cv2.LINE_AA)

        return display


# --- Test nhanh: python notepad.py (vẽ một nét tự động, bấm q để thoát) ---
if __name__ == "__main__":
    pad = Notepad(640, 480, save_dir="drawings_test")
    pad.start_stroke((100, 200))
    for i in range(60):
        pad.draw_to((100 + i * 7, 200 + int(60 * np.sin(i / 6.0))))
    pad.end_stroke()
    while True:
        cv2.imshow("notepad test", pad.draw(cursor_pos=(300, 250)))
        if cv2.waitKey(30) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()
