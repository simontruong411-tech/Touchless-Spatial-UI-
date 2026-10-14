"""
spatial_ui.py
--------------------
"Màn hình ảo trong không khí" — vẽ (các) nút bấm lên frame video, quản lý
trạng thái đóng/mở của menu, và biết nút nào đang được con trỏ (cursor)
hover vào.

Class chính: SpatialMenu
  - open()/close()/toggle()  : quản lý trạng thái menu
  - get_hover(cursor_pos)    : trả về label của nút đang bị hover, hoặc None
  - draw(frame, cursor_pos)  : vẽ toàn bộ menu + cursor lên frame OpenCV

BẢN NÂNG CẤP SO VỚI BẢN TRƯỚC (đã chốt cùng bạn):
  - Chỉ còn 1 nút mặc định: LIGHT (đã bỏ FAN và SETTINGS để tập trung làm
    cho thật chính xác/mượt trước khi mở rộng thêm thiết bị sau này). Class
    vẫn nhận list `buttons` như cũ (để sau này dễ thêm lại nút khác), nhưng
    bạn nên gọi SpatialMenu(buttons=["LIGHT"], ...) ở bản hiện tại.
  - Panel chuyển sang góc màn hình (compact corner panel), thu nhỏ nhiều so
    với bản cũ (mỗi nút to 220x70 nằm giữa màn hình) — nên constructor giờ
    cần biết frame_width/frame_height để tự tính vị trí góc trên-phải, thay
    vì nhận tọa độ tuyệt đối (start_x, start_y) như bản cũ.
  - Bảng màu đổi sang tông trầm, hiện đại: nền charcoal (xám than) bán trong
    suốt, viền xám đậm, chữ off-white, và 1 màu nhấn ấm (muted amber) để báo
    trạng thái đang hover — thay cho bảng màu xám/cam/xanh lá/đỏ chói bản cũ.
  - Cursor đổi từ hình tròn đặc sang dạng viền mảnh, bán trong suốt ("tàng
    hình") — đỡ che khuất hình ảnh và trông hiện đại hơn.

GHI CHÚ MÀU SẮC: OpenCV dùng thứ tự màu BGR (Blue, Green, Red), KHÔNG phải
RGB. Các tuple màu bên dưới viết theo thứ tự (B, G, R).
"""

import cv2

# --- Bảng màu (BGR) — tông trầm, hiện đại ---
COLOR_PANEL_BG = (45, 45, 48)         # charcoal - nền panel
PANEL_BG_ALPHA = 0.75                 # độ "đục" của nền panel (1.0 = đục hoàn toàn)

COLOR_BORDER_IDLE = (75, 75, 80)      # viền nút khi không hover
COLOR_TEXT = (225, 225, 225)          # chữ off-white
COLOR_ACCENT = (55, 150, 210)         # màu nhấn ấm (muted amber) khi hover

COLOR_CURSOR = (225, 225, 225)        # màu vòng cursor khi không hover nút nào


class SpatialMenu:
    def __init__(self, buttons, frame_width, frame_height,
                 panel_width=170, button_height=56, margin=24, gap=8,
                 vertical_bias=0.5):
        """
        buttons      : list các label, ví dụ ["LIGHT"] (bản hiện tại chỉ nên
                       dùng đúng 1 phần tử; để list vì sau này có thể mở
                       rộng thêm thiết bị)
        frame_width  : chiều rộng khung hình (frame.shape[1])
        frame_height : chiều cao khung hình (frame.shape[0])
        vertical_bias: panel vẫn luôn nằm bên PHẢI màn hình, tham số này chỉ
                       quyết định vị trí THEO CHIỀU DỌC bên trong khoảng
                       không gian cho phép (từ margin trên tới margin dưới):
                       0.0 = dán sát mép trên (kiểu bản cũ), 1.0 = dán sát
                       mép dưới, 0.5 = canh giữa theo chiều dọc màn hình
                       (MẶC ĐỊNH — theo yêu cầu dời panel vào giữa thay vì
                       dồn hẳn lên góc trên). Muốn dịch lên/xuống chút nữa
                       thì chỉnh số này (ví dụ 0.4 hoặc 0.6).
        Các nút được xếp dọc trong 1 panel nhỏ ở bên PHẢI màn hình.
        """
        self.is_open = False
        self._buttons = []  # list dict: {"label":.., "rect": (x,y,w,h)}

        x1 = frame_width - panel_width - margin

        num_buttons = len(buttons)
        total_buttons_height = num_buttons * button_height + max(0, num_buttons - 1) * gap
        # Khoảng không gian dọc "được phép" đặt panel vào (trừ margin trên/dưới),
        # rồi dùng vertical_bias để chọn điểm bắt đầu bên trong khoảng đó.
        available_height = frame_height - 2 * margin
        y_start = margin + max(0, available_height - total_buttons_height) * vertical_bias

        y = y_start
        for label in buttons:
            self._buttons.append({
                "label": label,
                "rect": (x1, int(y), panel_width, button_height),
            })
            y += button_height + gap

        # Bounding box của toàn bộ panel (dùng để vẽ 1 nền chung phía sau các nút)
        panel_bottom = y - gap
        self._panel_rect = (x1, int(y_start), panel_width, int(panel_bottom - y_start))

    def open(self):
        self.is_open = True

    def close(self):
        self.is_open = False

    def toggle(self):
        self.is_open = not self.is_open

    def get_hover(self, cursor_pos):
        """cursor_pos: (x, y) pixel. Trả về label nút đang hover, hoặc None."""
        if not self.is_open or cursor_pos is None:
            return None

        cx, cy = cursor_pos
        for btn in self._buttons:
            x, y, w, h = btn["rect"]
            if x <= cx <= x + w and y <= cy <= y + h:
                return btn["label"]
        return None

    def draw(self, frame, cursor_pos=None, is_clicking=False):
        """Vẽ menu (nếu đang mở) + con trỏ (nếu có) lên frame."""
        hovered_label = self.get_hover(cursor_pos) if self.is_open else None

        if self.is_open:
            # Vẽ nền bán trong suốt cho cả panel: vẽ hình chữ nhật đặc lên 1
            # bản sao của frame, rồi trộn (blend) bản sao đó với frame gốc.
            px, py, pw, ph = self._panel_rect
            overlay = frame.copy()
            cv2.rectangle(overlay, (px, py), (px + pw, py + ph), COLOR_PANEL_BG, -1)
            cv2.addWeighted(overlay, PANEL_BG_ALPHA, frame, 1 - PANEL_BG_ALPHA, 0, frame)

            for btn in self._buttons:
                x, y, w, h = btn["rect"]
                is_hover = btn["label"] == hovered_label
                border_color = COLOR_ACCENT if is_hover else COLOR_BORDER_IDLE
                text_color = COLOR_ACCENT if is_hover else COLOR_TEXT

                cv2.rectangle(frame, (x, y), (x + w, y + h), border_color, 2)

                text_size = cv2.getTextSize(btn["label"], cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                text_x = x + (w - text_size[0]) // 2
                text_y = y + (h + text_size[1]) // 2
                cv2.putText(frame, btn["label"], (text_x, text_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 1, cv2.LINE_AA)

        if cursor_pos is not None:
            # Cursor "tàng hình": vòng tròn viền mảnh, bán trong suốt, thay vì
            # hình tròn đặc như bản cũ.
            cx, cy = int(cursor_pos[0]), int(cursor_pos[1])
            color = COLOR_ACCENT if hovered_label is not None else COLOR_CURSOR

            overlay = frame.copy()
            cv2.circle(overlay, (cx, cy), 10, color, 1, cv2.LINE_AA)  # vòng ngoài, viền mảnh
            cv2.circle(overlay, (cx, cy), 2, color, -1, cv2.LINE_AA)  # chấm nhỏ ở tâm
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

        return hovered_label