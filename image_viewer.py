"""
image_viewer.py
--------------------
"Bộ xem ảnh chẩn đoán không chạm" — cho bác sĩ xem, phóng to/thu nhỏ (zoom)
và di chuyển (pan) ảnh y khoa (X-quang, CT, MRI...) bằng cử chỉ tay, không
cần chạm chuột/bàn phím trong lúc đang vô trùng.

QUAN TRỌNG VỀ "TẢI ẢNH LÊN": hệ thống KHÔNG có nút "tải ảnh" bằng cử chỉ
tay — vì bản chất việc chọn file trên máy tính đòi hỏi click chuột/gõ bàn
phím, đi ngược lại đúng mục tiêu "không chạm" của đề tài. Thay vào đó, ảnh
cần XEM được ĐẶT SẴN vào 1 thư mục (mặc định "medical_images/") TRƯỚC khi
ca mổ bắt đầu — do bác sĩ/trợ lý chuẩn bị lúc chưa vô trùng. Trong lúc mổ,
bác sĩ chỉ ĐIỀU HƯỚNG (ảnh trước/sau, zoom, kéo) bằng tay.

Class chính: ImageViewer
  - Khởi tạo: tự load danh sách file ảnh (.jpg/.jpeg/.png/.bmp) trong thư
    mục image_dir, sắp xếp theo tên file.
  - next_image() / prev_image() : chuyển sang ảnh kế/trước, tự reset_view()
  - pan(dx, dy)                 : dịch ảnh theo (dx, dy) pixel màn hình
  - set_zoom(new_zoom)          : đặt mức zoom trực tiếp (tự giới hạn trong
                                   khoảng MIN_ZOOM..MAX_ZOOM)
  - adjust_brightness(delta)    : tăng/giảm độ sáng (tự giới hạn khoảng
                                   MIN_BRIGHTNESS..MAX_BRIGHTNESS)
  - adjust_contrast(delta)      : tăng/giảm tương phản (tự giới hạn khoảng
                                   MIN_CONTRAST..MAX_CONTRAST)
  - reset_view()                : về mặc định (zoom 1x, căn giữa, sáng/
                                   tương phản mặc định)
  - get_hover_button(cursor_pos): trả về nhãn nút đang hover (TRUOC/SAU/
                                   RESET/BACK), hoặc None
  - draw(cursor_pos, is_pinching_now) : vẽ 1 frame để hiển thị (ảnh đã
    zoom/pan/sáng/tương phản + toolbar 4 nút + cursor + chữ hướng dẫn)

CHỈNH SÁNG/TƯƠNG PHẢN (window/level — đúng thuật ngữ PACS thật): kích hoạt
bằng cách XÒE BÀN TAY TRÁI (Open palm) trong lúc Pinch+kéo tay phải, thay
vì kéo ảnh (pan) như bình thường. Kéo NGANG = chỉnh tương phản (contrast),
kéo DỌC = chỉnh độ sáng (brightness) — đúng quy ước "window width/level"
quen thuộc với bác sĩ X-quang. Thả xòe tay ra (nắm lại hoặc đổi cử chỉ
khác) = quay lại kéo ảnh (pan) bình thường. Logic phát hiện Open palm +
gọi 2 hàm adjust_*() nằm ở main_spatial_ui_demo.py, KHÔNG nằm trong class
này — class này chỉ cung cấp 2 hàm điều chỉnh, không tự đọc cử chỉ tay.

THIẾT KẾ ẢNH: ảnh gốc luôn được giữ nguyên trong bộ nhớ (self.current_image
đọc từ file bằng cv2.imread, chỉ đọc lại khi đổi sang ảnh khác — "lazy
loading" để đỡ tốn RAM nếu thư mục có nhiều ảnh). Mỗi frame, draw() CẮT một
vùng trên ảnh gốc theo đúng zoom/pan hiện tại, áp dụng sáng/tương phản, rồi
resize vừa khung hình để hiển thị — ảnh gốc trên đĩa không bao giờ bị sửa.

GHI CHÚ MÀU SẮC: OpenCV dùng BGR (Blue, Green, Red), không phải RGB.
"""

import os

import cv2
import numpy as np

# --- Bảng màu (BGR) — giữ cùng tông trầm/hiện đại với spatial_ui.py ---
COLOR_BG = (20, 20, 22)               # nền khi không có ảnh / viền ngoài ảnh
COLOR_TOOLBAR_BORDER = (75, 75, 80)
COLOR_ACCENT = (55, 150, 210)         # màu nhấn ấm khi hover/đang pinch
COLOR_TEXT = (225, 225, 225)
COLOR_TEXT_HINT = (150, 150, 155)

BUTTON_SIZE = (110, 44)               # (width, height) mỗi nút
BUTTON_MARGIN = 20
BUTTON_GAP = 10
# Thứ tự nút hiển thị trái->phải. Có thể đổi/thêm nút bằng cách sửa list
# này — __init__ tự tính vị trí, không cần sửa gì khác.
BUTTON_LABELS = ["TRUOC", "SAU", "RESET", "BACK"]

# Giới hạn mức zoom: 1.0 = nhìn toàn bộ ảnh gốc, càng lớn càng "nhìn gần".
MIN_ZOOM = 1.0
MAX_ZOOM = 5.0

# Giới hạn độ sáng (beta trong công thức OpenCV: anh_moi = anh_goc*contrast
# + brightness) — cộng thẳng vào giá trị pixel, 0 = không đổi.
MIN_BRIGHTNESS = -100.0
MAX_BRIGHTNESS = 100.0

# Giới hạn tương phản (alpha trong công thức trên) — nhân với giá trị
# pixel, 1.0 = không đổi, <1 = giảm tương phản, >1 = tăng tương phản.
MIN_CONTRAST = 0.3
MAX_CONTRAST = 3.0


class ImageViewer:
    def __init__(self, frame_width, frame_height, image_dir="medical_images"):
        self.width = frame_width
        self.height = frame_height
        self.image_dir = image_dir

        self.image_paths = self._find_images(image_dir)
        self.index = 0

        # current_image: ảnh GỐC (chưa zoom/pan) của ảnh đang xem, load lười
        # (chỉ đọc lại file khi index đổi sang ảnh khác, không đọc lại mỗi
        # frame — đọc ảnh từ đĩa khá tốn thời gian so với 1 frame camera).
        self.current_image = None
        self._loaded_index = None

        self.zoom = 1.0
        # pan_x/pan_y: độ lệch tâm khung nhìn so với tâm ảnh gốc, tính theo
        # đơn vị PIXEL TRÊN ẢNH GỐC (không phải pixel màn hình) — nhờ vậy
        # pan không bị "trôi" khi zoom thay đổi.
        self.pan_x = 0.0
        self.pan_y = 0.0

        # brightness (độ sáng, cộng thẳng vào pixel) và contrast (tương
        # phản, nhân với pixel) — công thức chuẩn OpenCV:
        #   pixel_moi = pixel_goc * contrast + brightness
        self.brightness = 0.0
        self.contrast = 1.0

        # Xếp N nút ngang nhau, dưới cùng màn hình, canh giữa theo chiều
        # ngang — số lượng/tên nút lấy từ BUTTON_LABELS, đổi list đó ở đầu
        # file là tự đổi theo, không cần sửa gì ở đây.
        bw, bh = BUTTON_SIZE
        n = len(BUTTON_LABELS)
        total_w = bw * n + BUTTON_GAP * (n - 1)
        start_x = (frame_width - total_w) // 2
        y = frame_height - bh - BUTTON_MARGIN
        self.buttons = {}
        for i, label in enumerate(BUTTON_LABELS):
            x = start_x + i * (bw + BUTTON_GAP)
            self.buttons[label] = (x, y, bw, bh)

    # -- Nạp danh sách ảnh -----------------------------------------------
    def _find_images(self, image_dir):
        if not os.path.isdir(image_dir):
            return []
        exts = (".jpg", ".jpeg", ".png", ".bmp")
        files = sorted(f for f in os.listdir(image_dir) if f.lower().endswith(exts))
        return [os.path.join(image_dir, f) for f in files]

    def has_images(self):
        return len(self.image_paths) > 0

    def _ensure_loaded(self):
        if self._loaded_index != self.index and self.image_paths:
            self.current_image = cv2.imread(self.image_paths[self.index])
            self._loaded_index = self.index

    # -- Chuyển ảnh --------------------------------------------------------
    def next_image(self):
        if not self.image_paths:
            return
        self.index = (self.index + 1) % len(self.image_paths)
        self.reset_view()

    def prev_image(self):
        if not self.image_paths:
            return
        self.index = (self.index - 1) % len(self.image_paths)
        self.reset_view()

    def reset_view(self):
        """Về mặc định: nhìn toàn bộ ảnh, không zoom, không lệch tâm, sáng/
        tương phản mặc định. Tự động gọi mỗi khi đổi ảnh, để ảnh mới luôn
        bắt đầu từ góc nhìn chuẩn thay vì giữ nguyên cài đặt của ảnh trước."""
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.brightness = 0.0
        self.contrast = 1.0

    # -- Pan / Zoom ----------------------------------------------------------
    def pan(self, dx, dy):
        """Dịch khung nhìn theo (dx, dy) PIXEL MÀN HÌNH (từ chuyển động tay
        thật). Chia cho self.zoom để khi đang zoom lớn, cùng 1 khoảng di
        chuyển tay vẫn dịch đúng bấy nhiêu trên MÀN HÌNH (cảm giác kéo nhất
        quán dù đang zoom mức nào)."""
        self.pan_x -= dx / self.zoom
        self.pan_y -= dy / self.zoom

    def set_zoom(self, new_zoom):
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))

    # -- Sáng / Tương phản (window/level) ------------------------------------
    def adjust_brightness(self, delta):
        """delta > 0 = sáng hơn, delta < 0 = tối hơn. Tự giới hạn trong
        khoảng MIN_BRIGHTNESS..MAX_BRIGHTNESS."""
        self.brightness = max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, self.brightness + delta))

    def adjust_contrast(self, delta):
        """delta > 0 = tương phản cao hơn (ảnh 'gắt' hơn), delta < 0 =
        tương phản thấp hơn (ảnh 'phẳng' hơn). Tự giới hạn trong khoảng
        MIN_CONTRAST..MAX_CONTRAST."""
        self.contrast = max(MIN_CONTRAST, min(MAX_CONTRAST, self.contrast + delta))

    # -- Tương tác nút ----------------------------------------------------------
    def get_hover_button(self, cursor_pos):
        if cursor_pos is None:
            return None
        x, y = cursor_pos
        for label, (bx, by, bw, bh) in self.buttons.items():
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return label
        return None

    # -- Hiển thị ---------------------------------------------------------------
    def draw(self, cursor_pos=None, is_pinching_now=False):
        """Trả về 1 frame HOÀN CHỈNH để cv2.imshow() — KHÔNG vẽ đè lên
        camera, giống cách Notepad thay hẳn màn hình camera bằng giấy vẽ."""
        self._ensure_loaded()
        display = np.full((self.height, self.width, 3), COLOR_BG, dtype=np.uint8)

        if self.current_image is not None:
            display = self._composite_image(display)
        else:
            msg = f"Khong tim thay anh nao trong thu muc '{self.image_dir}'"
            cv2.putText(display, msg, (30, self.height // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_TEXT_HINT, 1, cv2.LINE_AA)

        hovered = self.get_hover_button(cursor_pos)
        for label, (bx, by, bw, bh) in self.buttons.items():
            is_hover = label == hovered
            border_color = COLOR_ACCENT if is_hover else COLOR_TOOLBAR_BORDER
            text_color = COLOR_ACCENT if is_hover else COLOR_TEXT
            cv2.rectangle(display, (bx, by), (bx + bw, by + bh), border_color, 2)
            text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0]
            tx = bx + (bw - text_size[0]) // 2
            ty = by + (bh + text_size[1]) // 2
            cv2.putText(display, label, (tx, ty),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_color, 1, cv2.LINE_AA)

        if self.image_paths:
            info = (f"Anh {self.index + 1}/{len(self.image_paths)}  |  Zoom: {self.zoom:.1f}x  |  "
                     f"Sang: {self.brightness:+.0f}  |  Tuong phan: {self.contrast:.1f}x")
            cv2.putText(display, info, (BUTTON_MARGIN, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_TEXT_HINT, 1, cv2.LINE_AA)

        # 3 dòng hint, tính từ DƯỚI LÊN, cách hẳn phía trên toolbar nút
        # (không dùng số cố định đoán chừng — tính thẳng từ tọa độ Y thật
        # của hàng nút, luôn đúng dù sau này đổi BUTTON_SIZE/BUTTON_MARGIN).
        LINE_H = 20
        button_top_y = self.height - BUTTON_MARGIN - BUTTON_SIZE[1]
        hint_bottom_y = button_top_y - 10
        cv2.putText(display, "Pinch + keo = di chuyen anh", (BUTTON_MARGIN, hint_bottom_y - 2 * LINE_H),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_TEXT_HINT, 1, cv2.LINE_AA)
        cv2.putText(display, "2 tay xa/gan nhau = zoom  |  Snap = thoat", (BUTTON_MARGIN, hint_bottom_y - LINE_H),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_TEXT_HINT, 1, cv2.LINE_AA)
        cv2.putText(display, "Xoe long ban tay trai + Pinch keo = chinh sang/tuong phan", (BUTTON_MARGIN, hint_bottom_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_TEXT_HINT, 1, cv2.LINE_AA)

        if cursor_pos is not None:
            cx, cy = int(cursor_pos[0]), int(cursor_pos[1])
            color = COLOR_ACCENT if (hovered is not None or is_pinching_now) else COLOR_TEXT
            if is_pinching_now:
                # Đang Pinch (kéo ảnh hoặc bấm nút): chấm đặc cho thấy rõ
                cv2.circle(display, (cx, cy), 6, color, -1, cv2.LINE_AA)
            else:
                overlay = display.copy()
                cv2.circle(overlay, (cx, cy), 10, color, 1, cv2.LINE_AA)
                cv2.addWeighted(overlay, 0.55, display, 0.45, 0, display)

        return display

    def _composite_image(self, display):
        """Cắt đúng vùng ảnh gốc theo zoom/pan hiện tại, resize giữ nguyên
        tỉ lệ (không kéo méo ảnh), rồi dán vào giữa khung hiển thị."""
        img_h, img_w = self.current_image.shape[:2]

        # Kích thước "khung nhìn" TRÊN ẢNH GỐC ứng với mức zoom hiện tại —
        # zoom càng lớn, khung nhìn càng nhỏ (nhìn gần/chi tiết hơn).
        view_w = img_w / self.zoom
        view_h = img_h / self.zoom

        cx = img_w / 2 + self.pan_x
        cy = img_h / 2 + self.pan_y

        # Giữ khung nhìn không vượt ra ngoài biên ảnh gốc (không kéo lố
        # sang vùng "không có ảnh").
        half_w, half_h = view_w / 2, view_h / 2
        cx = max(half_w, min(img_w - half_w, cx))
        cy = max(half_h, min(img_h - half_h, cy))
        self.pan_x = cx - img_w / 2
        self.pan_y = cy - img_h / 2

        x1, y1 = int(cx - half_w), int(cy - half_h)
        x2, y2 = int(cx + half_w), int(cy + half_h)
        cropped = self.current_image[y1:y2, x1:x2]
        if cropped.size == 0:
            return display

        # Áp dụng sáng/tương phản NGAY TRÊN VÙNG ĐÃ CẮT (không phải cả ảnh
        # gốc) — vừa đúng ý nghĩa (chỉ cần đẹp phần đang xem), vừa nhanh
        # hơn (vùng cắt luôn nhỏ hơn hoặc bằng ảnh gốc). convertScaleAbs()
        # tự làm luôn việc "cắt" giá trị về đúng khoảng 0-255 sau khi nhân/
        # cộng, không cần tự viết code giới hạn tay.
        cropped = cv2.convertScaleAbs(cropped, alpha=self.contrast, beta=self.brightness)

        # Khoảng trống dành để hiển thị ảnh (trừ đi phần toolbar dưới cùng).
        target_w = self.width
        target_h = self.height - BUTTON_SIZE[1] - BUTTON_MARGIN * 2
        scale = min(target_w / cropped.shape[1], target_h / cropped.shape[0])
        new_w = max(1, int(cropped.shape[1] * scale))
        new_h = max(1, int(cropped.shape[0] * scale))
        resized = cv2.resize(cropped, (new_w, new_h))

        x_off = (self.width - new_w) // 2
        y_off = (target_h - new_h) // 2
        display[y_off:y_off + new_h, x_off:x_off + new_w] = resized
        return display
