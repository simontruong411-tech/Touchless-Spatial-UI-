"""
or_workflow.py
--------------------
Màn "QUY TRINH" — dẫn bác sĩ đi hết MỘT CA MỔ MÔ PHỎNG bằng cử chỉ tay, theo các
giai đoạn của Bảng kiểm an toàn phẫu thuật WHO (WHO Surgical Safety Checklist):

    SIGN IN  ->  TIME OUT  ->  MO (phẫu thuật)  ->  SIGN OUT  ->  HOAN TAT

  - SIGN IN  (trước khi gây mê): xác nhận danh tính/thủ thuật/đồng ý, vị trí mổ,
              kiểm tra an toàn gây mê, máy đo SpO2, dị ứng, nguy cơ đường thở/mất máu.
  - TIME OUT (trước khi rạch da): "tạm dừng" cả kíp — giới thiệu, xác nhận lại
              bệnh nhân/vị trí/thủ thuật, dự kiến biến cố, vô trùng, kháng sinh,
              ảnh chẩn đoán đã hiển thị. KHÔNG được sang giai đoạn mổ khi còn mục chưa
              xác nhận (đúng tinh thần của bước "pause" trong bảng kiểm).
  - MO      : đồng hồ phẫu thuật + các nút ĐÁNH DẤU MỐC (rạch da, bộ phận chính...).
              Bác sĩ vẫn mở ảnh/xương 3D, gọi y tá... ở menu như bình thường (BACK ->
              menu); đồng hồ và giai đoạn vẫn chạy, mọi sự kiện được ghi đúng giai đoạn.
  - SIGN OUT (trước khi người bệnh rời phòng mổ): ghi nhận tên thủ thuật, ĐẾM dụng
              cụ/gạc/kim, dán nhãn bệnh phẩm, sự cố thiết bị, dặn dò hậu phẫu.

LƯU Ý QUAN TRỌNG:
  - Đây là MÔ PHỎNG phục vụ nghiên cứu giao diện không chạm, KHÔNG phải hệ thống
    lâm sàng. Trong thực tế các mục bảng kiểm do CẢ KÍP xác nhận BẰNG LỜI; phần mềm
    này chỉ là nơi bấm "tick" và ghi thời gian. Danh sách mục dưới đây là bản RÚT GỌN
    theo cấu trúc 3 giai đoạn của WHO (bệnh viện thường tùy chỉnh thêm) — cần bác sĩ/
    điều dưỡng rà soát nếu dùng cho mục đích khác ngoài thí nghiệm.
  - KHÔNG nhập hay lưu thông tin định danh bệnh nhân. Mã ca (case id) chỉ là mã giả
    sinh tự động theo giờ.
  - Nhãn chữ KHÔNG DẤU vì OpenCV (cv2.putText) không vẽ được chữ có dấu tiếng Việt.

CÁCH THAO TÁC: giống mọi màn khác — tay phải Point để di con trỏ, Pinch để bấm.
Các nút đủ lớn để bấm bằng cử chỉ. Bấm lại 1 mục đã tick = bỏ tick.
"""

import time

import cv2
import numpy as np

# --- Bảng màu (BGR), cùng tông với các màn khác ---
COLOR_BG = (20, 20, 22)
COLOR_BORDER = (75, 75, 80)
COLOR_ACCENT = (55, 150, 210)
COLOR_OK = (120, 180, 90)
COLOR_TEXT = (225, 225, 225)
COLOR_HINT = (150, 150, 155)

# ---------------------------------------------------------------------------
# NỘI DUNG BẢNG KIỂM (rút gọn theo cấu trúc WHO, chữ không dấu, <= ~50 ký tự)
# Muốn đổi/thêm/bớt mục: sửa trực tiếp các list này — giao diện tự co theo
# (tối đa 7 mục mỗi giai đoạn để vừa màn hình 480px).
# ---------------------------------------------------------------------------
CHECKLISTS = {
    "SIGN_IN": [
        "Xac nhan danh tinh BN, thu thuat, dong y",
        "Vi tri mo da danh dau (hoac khong ap dung)",
        "Kiem tra an toan gay me da hoan tat",
        "May do SpO2 da gan va hoat dong",
        "Da hoi/xac nhan di ung cua BN",
        "Nguy co kho tho / hit sac: da chuan bi",
        "Nguy co mat mau lon: da chuan bi",
    ],
    "TIME_OUT": [
        "Ca kip da gioi thieu ten va vai tro",
        "Xac nhan lai: BN, vi tri mo, thu thuat",
        "PTV neu buoc nguy hiem, mat mau du kien",
        "Gay me neu luu y rieng cua BN",
        "Dieu duong xac nhan vo trung, thiet bi",
        "Khang sinh du phong da dung (<60 phut)",
        "Anh chan doan can thiet da hien thi",
    ],
    "SIGN_OUT": [
        "Ten thu thuat da duoc ghi nhan",
        "Dem dung cu, gac, kim: DUNG",
        "Mau benh pham da dan nhan dung",
        "Su co thiet bi can xu ly: da bao cao",
        "Ca kip thong nhat luu y hau phau",
    ],
}

# Các mốc có thể đánh dấu trong lúc mổ (đổi theo thủ thuật cụ thể nếu cần)
SURGERY_MILESTONES = ["RACH DA", "PHAU TICH CHINH", "CAM MAU", "DONG VET MO"]

PHASE_LABEL = {"SIGN_IN": "SIGN IN", "TIME_OUT": "TIME OUT", "SURGERY": "MO", "SIGN_OUT": "SIGN OUT"}
TAB_ORDER = ["SIGN_IN", "TIME_OUT", "SURGERY", "SIGN_OUT"]
NEXT_PHASE = {"SIGN_IN": "TIME_OUT", "TIME_OUT": "SURGERY", "SURGERY": "SIGN_OUT", "SIGN_OUT": "COMPLETE"}
NEXT_LABEL = {
    "SIGN_IN": "TIEP: TIME OUT >",
    "TIME_OUT": "BAT DAU MO >",
    "SURGERY": "KET THUC MO >",
    "SIGN_OUT": "HOAN TAT CA >",
}


def fmt_time(seconds):
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class WorkflowScreen:
    def __init__(self, frame_width, frame_height, logger=None):
        self.width = frame_width
        self.height = frame_height
        self.logger = logger
        self.buttons = {}
        self.reset(log=False)

    # -- Trạng thái ca mổ -----------------------------------------------------
    def reset(self, log=True):
        if log and self.logger is not None and self.phase != "READY":
            self._log("WF_CASE_RESET", self.phase)
        self.phase = "READY"
        self.ticks = {k: set() for k in CHECKLISTS}
        self.case_id = ""
        self.case_start = None
        self.phase_start = None
        self.phase_seconds = {}
        self.milestones = {}            # tên -> giây kể từ đầu ca
        self._message = ""
        self._message_until = 0.0
        self._layout()
        if log and self.logger is not None:
            self.logger.set_phase("SETUP")

    def _log(self, event, detail=""):
        if self.logger is not None:
            self.logger.log_event("WORKFLOW", event, detail=detail)

    def _say(self, text, seconds=2.5):
        self._message = text
        self._message_until = time.perf_counter() + seconds

    def _go_phase(self, new_phase):
        now = time.perf_counter()
        if self.phase in TAB_ORDER:
            self.phase_seconds[self.phase] = self.phase_seconds.get(self.phase, 0.0) + (now - self.phase_start)
        self.phase = new_phase
        self.phase_start = now
        if self.logger is not None:
            self.logger.set_phase(new_phase)
        self._layout()

    # -- Bố cục nút ---------------------------------------------------------------
    def _layout(self):
        w, h = self.width, self.height
        self.buttons = {}
        bottom_y = h - 64
        self.buttons["BACK"] = (20, bottom_y, 110, 44, "BACK")

        if self.phase == "READY":
            self.buttons["START"] = ((w - 380) // 2, h // 2 - 20, 380, 70, "BAT DAU CA (SIGN IN)")
        elif self.phase in CHECKLISTS:
            items = CHECKLISTS[self.phase]
            y = 62
            for i, label in enumerate(items):
                self.buttons[f"ITEM:{i}"] = (20, y, w - 40, 40, label)
                y += 45
            self.buttons["NEXT"] = (w - 20 - 230, bottom_y, 230, 44, NEXT_LABEL[self.phase])
        elif self.phase == "SURGERY":
            for i, name in enumerate(SURGERY_MILESTONES):
                col, row = i % 2, i // 2
                self.buttons[f"MS:{i}"] = (20 + col * 310, 150 + row * 85, 290, 70, name)
            self.buttons["NEXT"] = (w - 20 - 230, bottom_y, 230, 44, NEXT_LABEL["SURGERY"])
        elif self.phase == "COMPLETE":
            self.buttons["NEW"] = (w - 20 - 230, bottom_y, 230, 44, "CA MOI")

    def get_hover(self, cursor_pos):
        if cursor_pos is None:
            return None
        x, y = cursor_pos
        for bid, (bx, by, bw, bh, _) in self.buttons.items():
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return bid
        return None

    # -- Xử lý bấm ----------------------------------------------------------------
    def click(self, button_id):
        """Xử lý 1 lần bấm. Trả về "BACK" nếu người dùng muốn rời màn quy trình
        (trạng thái ca mổ vẫn được giữ nguyên), ngược lại trả về None."""
        if button_id == "BACK":
            return "BACK"

        if button_id == "START":
            self.case_start = time.perf_counter()
            self.case_id = "CASE-" + time.strftime("%Y%m%d-%H%M%S")
            if self.logger is not None:
                self.logger.case_ids.append(self.case_id)
            self._log("WF_CASE_START", self.case_id)
            self._go_phase("SIGN_IN")

        elif button_id.startswith("ITEM:"):
            i = int(button_id.split(":")[1])
            ticks = self.ticks[self.phase]
            label = CHECKLISTS[self.phase][i]
            if i in ticks:
                ticks.discard(i)
                self._log("WF_UNTICK", f"{self.phase}#{i + 1}")
            else:
                ticks.add(i)
                self._log("WF_TICK", f"{self.phase}#{i + 1}")

        elif button_id.startswith("MS:"):
            name = SURGERY_MILESTONES[int(button_id.split(":")[1])]
            if name in self.milestones:
                self._say(f"Moc '{name}' da ghi luc {fmt_time(self.milestones[name])}")
            else:
                self.milestones[name] = time.perf_counter() - self.case_start
                self._log("WF_MILESTONE", f"{name};t={self.milestones[name]:.1f}s")
                self._say(f"Da ghi moc: {name}")

        elif button_id == "NEXT":
            self._next()

        elif button_id == "NEW":
            self.reset(log=True)

        return None

    def _next(self):
        if self.phase in CHECKLISTS:
            missing = len(CHECKLISTS[self.phase]) - len(self.ticks[self.phase])
            if missing > 0:
                self._log("WF_NEXT_BLOCKED", f"{self.phase};missing={missing}")
                self._say(f"Con {missing} muc chua xac nhan - khong the tiep tuc")
                return
        nxt = NEXT_PHASE[self.phase]
        if self.phase == "TIME_OUT":
            self._log("WF_SURGERY_START", self.case_id)
        elif self.phase == "SURGERY":
            self._log("WF_SURGERY_END", f"milestones={len(self.milestones)}")
        self._go_phase(nxt)
        if nxt == "COMPLETE":
            total = time.perf_counter() - self.case_start
            parts = ";".join(f"{p}_s={self.phase_seconds.get(p, 0):.0f}" for p in TAB_ORDER)
            ticks = sum(len(v) for v in self.ticks.values())
            self._log("WF_CASE_COMPLETE", f"{self.case_id};total_s={total:.0f};{parts};ticks={ticks}")

    # -- Thông tin cho phần còn lại của chương trình -------------------------------
    def elapsed(self):
        return 0.0 if self.case_start is None else time.perf_counter() - self.case_start

    def status_text(self):
        """Chuỗi ngắn hiện ở mép trên MỌI màn hình, vd 'CA MO | MO | 12:34'."""
        if self.phase == "READY":
            return ""
        if self.phase == "COMPLETE":
            return f"CA XONG | {fmt_time(sum(self.phase_seconds.values()))}"
        return f"CA MO | {PHASE_LABEL[self.phase]} | {fmt_time(self.elapsed())}"

    # -- Hiển thị -----------------------------------------------------------------
    def draw(self, cursor_pos=None, is_pinching_now=False):
        display = np.full((self.height, self.width, 3), COLOR_BG, dtype=np.uint8)
        hovered = self.get_hover(cursor_pos)

        self._draw_header(display)
        if self.phase == "READY":
            self._draw_ready(display)
        elif self.phase == "SURGERY":
            self._draw_surgery(display)
        elif self.phase == "COMPLETE":
            self._draw_complete(display)

        for bid, (bx, by, bw, bh, label) in self.buttons.items():
            self._draw_button(display, bid, (bx, by, bw, bh), label, bid == hovered)

        if self._message and time.perf_counter() < self._message_until:
            cv2.putText(display, self._message, (20, self.height - 76),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_ACCENT, 1, cv2.LINE_AA)

        cv2.putText(display, "MO PHONG - khong phai he thong lam sang", (self.width - 300, self.height - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_HINT, 1, cv2.LINE_AA)

        if cursor_pos is not None:
            cx, cy = int(cursor_pos[0]), int(cursor_pos[1])
            color = COLOR_ACCENT if (hovered is not None or is_pinching_now) else COLOR_TEXT
            if is_pinching_now:
                cv2.circle(display, (cx, cy), 6, color, -1, cv2.LINE_AA)
            else:
                overlay = display.copy()
                cv2.circle(overlay, (cx, cy), 10, color, 1, cv2.LINE_AA)
                cv2.addWeighted(overlay, 0.55, display, 0.45, 0, display)
        return display

    def _draw_header(self, display):
        # 4 "tab" giai đoạn: đã xong = xanh, đang ở = cam, chưa tới = xám
        tab_w, x0, y0 = min(120, (self.width - 190) // 4 - 6), 20, 18
        current = TAB_ORDER.index(self.phase) if self.phase in TAB_ORDER else (
            len(TAB_ORDER) if self.phase == "COMPLETE" else -1)
        for i, p in enumerate(TAB_ORDER):
            x = x0 + i * (tab_w + 6)
            if i < current:
                color, thick = COLOR_OK, 1
            elif i == current:
                color, thick = COLOR_ACCENT, 2
            else:
                color, thick = COLOR_BORDER, 1
            cv2.rectangle(display, (x, y0), (x + tab_w, y0 + 28), color, thick)
            ts = cv2.getTextSize(PHASE_LABEL[p], cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            cv2.putText(display, PHASE_LABEL[p], (x + (tab_w - ts[0]) // 2, y0 + 19),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color if i != current else COLOR_ACCENT, 1, cv2.LINE_AA)
        if self.case_start is not None and self.phase != "COMPLETE":
            cv2.putText(display, f"Tong {fmt_time(self.elapsed())}", (self.width - 120, y0 + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_TEXT, 1, cv2.LINE_AA)

    def _draw_button(self, display, bid, rect, label, is_hover):
        bx, by, bw, bh = rect
        border = COLOR_ACCENT if is_hover else COLOR_BORDER
        text_color = COLOR_ACCENT if is_hover else COLOR_TEXT

        if bid.startswith("ITEM:"):
            i = int(bid.split(":")[1])
            ticked = i in self.ticks[self.phase]
            cv2.rectangle(display, (bx, by), (bx + bw, by + bh), COLOR_OK if ticked else border, 2 if is_hover else 1)
            cb = (bx + 10, by + 9, 22, 22)
            cv2.rectangle(display, (cb[0], cb[1]), (cb[0] + cb[2], cb[1] + cb[3]),
                          COLOR_OK if ticked else COLOR_HINT, -1 if ticked else 1)
            if ticked:
                cv2.line(display, (cb[0] + 5, cb[1] + 12), (cb[0] + 10, cb[1] + 17), COLOR_BG, 2, cv2.LINE_AA)
                cv2.line(display, (cb[0] + 10, cb[1] + 17), (cb[0] + 18, cb[1] + 6), COLOR_BG, 2, cv2.LINE_AA)
            cv2.putText(display, f"{i + 1}. {label}", (bx + 44, by + 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, COLOR_OK if ticked else text_color, 1, cv2.LINE_AA)
            return

        if bid.startswith("MS:"):
            done = label in self.milestones
            border = COLOR_OK if done else border
            cv2.rectangle(display, (bx, by), (bx + bw, by + bh), border, 2)
            cv2.putText(display, label, (bx + 14, by + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        COLOR_OK if done else text_color, 1, cv2.LINE_AA)
            sub = f"da ghi luc {fmt_time(self.milestones[label])}" if done else "bam de danh dau moc"
            cv2.putText(display, sub, (bx + 14, by + 55), cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_HINT, 1, cv2.LINE_AA)
            return

        enabled = True
        if bid == "NEXT" and self.phase in CHECKLISTS:
            enabled = len(self.ticks[self.phase]) == len(CHECKLISTS[self.phase])
            if not enabled:
                border, text_color = COLOR_BORDER, COLOR_HINT
                missing = len(CHECKLISTS[self.phase]) - len(self.ticks[self.phase])
                label = f"Con {missing} muc"
            elif not is_hover:
                border = COLOR_OK
        cv2.rectangle(display, (bx, by), (bx + bw, by + bh), border, 2)
        ts = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0]
        cv2.putText(display, label, (bx + (bw - ts[0]) // 2, by + (bh + ts[1]) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_color, 1, cv2.LINE_AA)

    def _draw_ready(self, display):
        lines = ["QUY TRINH CA MO (mo phong)",
                 "Theo Bang kiem an toan phau thuat WHO:",
                 "SIGN IN  ->  TIME OUT  ->  MO  ->  SIGN OUT",
                 "Cac muc do CA KIP xac nhan bang loi; phan mem chi ghi tick va thoi gian."]
        y = 85
        for i, t in enumerate(lines):
            cv2.putText(display, t, (self.width // 2 - 280, y + i * 24), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6 if i == 0 else 0.5, COLOR_TEXT if i < 3 else COLOR_HINT, 1, cv2.LINE_AA)

    def _draw_surgery(self, display):
        t = fmt_time(time.perf_counter() - self.phase_start) if self.phase_start else "00:00"
        ts = cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 1.8, 3)[0]
        cv2.putText(display, t, ((self.width - ts[0]) // 2, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.8,
                    COLOR_ACCENT, 3, cv2.LINE_AA)
        cv2.putText(display, "Thoi gian phau thuat", (self.width // 2 - 85, 132), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, COLOR_HINT, 1, cv2.LINE_AA)
        cv2.putText(display, "BACK -> menu de xem anh / xuong 3D / goi y ta; dong ho van chay.",
                    (20, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_HINT, 1, cv2.LINE_AA)

    def _draw_complete(self, display):
        cv2.putText(display, "CA MO HOAN TAT", (self.width // 2 - 130, 95), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, COLOR_OK, 2, cv2.LINE_AA)
        total = sum(self.phase_seconds.values())
        lines = [f"Ma ca (gia): {self.case_id}", f"Tong thoi gian: {fmt_time(total)}"]
        lines += [f"{PHASE_LABEL[p]:<9}: {fmt_time(self.phase_seconds.get(p, 0))}" for p in TAB_ORDER]
        lines += [f"Moc da ghi: {len(self.milestones)}/{len(SURGERY_MILESTONES)}"]
        for i, t in enumerate(lines):
            cv2.putText(display, t, (self.width // 2 - 140, 135 + i * 28), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, COLOR_TEXT, 1, cv2.LINE_AA)
        cv2.putText(display, "Nhat ky da ghi vao thu muc logs/ (khong chua thong tin benh nhan)",
                    (20, self.height - 84), cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_HINT, 1, cv2.LINE_AA)
