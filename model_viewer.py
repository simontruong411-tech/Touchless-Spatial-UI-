"""
model_viewer.py
--------------------
Màn "XƯƠNG 3D" — xem và xoay MÔ HÌNH 3D bộ xương (cột sống, lồng ngực, khung
chậu) bằng cử chỉ tay, không chạm. Dựa trên 2 ý tưởng trong các tài liệu đã
đọc:
  - Manolova (CEMA'14): xoay/zoom/di chuyển mô hình 3D xương-cơ quan dựng từ CT
    (phần mềm MITO) ngay trong phòng mổ, không cần trợ lý.
  - O'Hara và cộng sự (CACM): thao tác với mô hình 3D = xoay, zoom, và chỉnh
    "độ trong suốt/độ đậm" để lộ ra từng lớp (xương, mô, mạch máu).

CÁCH HOẠT ĐỘNG (không cần cài thêm thư viện — chỉ dùng numpy + OpenCV đã có):
  - Mô hình là các ĐOẠN THẲNG (khung dây) trong không gian 3D. Mỗi frame: xoay
    mô hình theo yaw/pitch (do bạn kéo tay), chiếu phối cảnh xuống 2D, rồi vẽ
    đoạn xa trước - đoạn gần sau, đoạn xa mờ hơn đoạn gần (tạo cảm giác chiều sâu).
  - MẶC ĐỊNH dùng bộ xương MÔ PHỎNG tự dựng bằng code (24 đốt sống, 12 đôi
    xương sườn, xương ức, xương đòn, khung chậu, sọ). Đây là mô hình MINH HỌA,
    KHÔNG phải dữ liệu chụp từ bệnh nhân và KHÔNG dùng để chẩn đoán.
  - MUỐN DÙNG MÔ HÌNH THẬT (dựng từ CT, tải từ nguồn công khai): đặt file .obj
    vào thư mục "medical_models/" (cùng thư mục với file này). Viewer sẽ dùng
    file .obj đầu tiên (theo tên) và hiện dạng ĐÁM ĐIỂM (point cloud) từ các
    đỉnh (v ...) của file. Thư mục trống/không có -> dùng bộ xương mô phỏng.

CỬ CHỈ (nhất quán với màn ẢNH):
  - Pinch + kéo tay phải (không hover nút, tay trái KHÔNG xòe) -> XOAY mô hình
  - 2 tay xa/gần nhau -> ZOOM
  - XÒE tay trái + Pinch kéo DỌC tay phải -> CẮT LỚP: ẩn dần các lớp phía
    TRƯỚC để nhìn thấy cấu trúc phía sau (vd bỏ lồng ngực phía trước để thấy
    cột sống) — tương tự "độ trong suốt" trong CACM
  - Nút: LOP (đổi lớp hiển thị: TẤT CẢ / CỘT SỐNG / LỒNG NGỰC / KHUNG CHẬU),
         GOC (góc nhìn: trước -> bên -> sau), RESET, BACK

HỆ TỌA ĐỘ MÔ HÌNH: x sang phải, y XUỐNG dưới (như ảnh), z hướng RA PHÍA NGƯỜI
XEM = phía trước cơ thể. Đơn vị tương đối: toàn bộ bộ xương cao khoảng 1.27.
GHI CHÚ MÀU SẮC: OpenCV dùng BGR (Blue, Green, Red), không phải RGB.
"""

import math
import os

import cv2
import numpy as np

# --- Bảng màu (BGR) — cùng tông với image_viewer.py ---
COLOR_BG = (20, 20, 22)
COLOR_TOOLBAR_BORDER = (75, 75, 80)
COLOR_ACCENT = (55, 150, 210)
COLOR_TEXT = (225, 225, 225)
COLOR_TEXT_HINT = (150, 150, 155)

# Màu xương theo từng bộ phận (hơi khác nhau để dễ phân biệt khi hiện tất cả)
PART_COLORS = {
    "SPINE": (205, 225, 235),
    "RIBS": (195, 205, 205),
    "PELVIS": (170, 200, 225),
}

BUTTON_SIZE = (110, 44)
BUTTON_MARGIN = 20
BUTTON_GAP = 10
BUTTON_LABELS = ["LOP", "GOC", "RESET", "BACK"]

MIN_ZOOM = 0.6
MAX_ZOOM = 3.5

# (Tên hiển thị, tập bộ phận được hiện; None = hiện tất cả)
LAYERS = [
    ("TAT CA", None),
    ("COT SONG", {"SPINE"}),
    ("LONG NGUC", {"RIBS"}),
    ("KHUNG CHAU", {"PELVIS"}),
]

# (Tên góc nhìn, yaw, pitch) — yaw quay quanh trục dọc (trái/phải)
VIEWS = [
    ("TRUOC", 0.0, 0.0),
    ("BEN", math.pi / 2, 0.0),
    ("SAU", math.pi, 0.0),
]
DEFAULT_YAW = 0.45      # hơi nghiêng một chút để thấy ngay đây là mô hình 3D
DEFAULT_PITCH = -0.08

CAMERA_DISTANCE = 3.0   # khoảng cách "camera ảo" tới mô hình, dùng cho phối cảnh
ROTATE_SENSITIVITY = 0.012   # radian xoay cho mỗi pixel kéo tay
CLIP_SENSITIVITY = 0.004     # độ cắt lớp (0..1) cho mỗi pixel kéo dọc
MAX_CLIP = 0.92
MAX_OBJ_POINTS = 60000


# =====================================================================
# DỰNG BỘ XƯƠNG MÔ PHỎNG
# =====================================================================
def _ring(center, radius_x, radius_z, n=11):
    """Vòng elip nằm ngang (mặt phẳng x-z) quanh `center`, khép kín."""
    th = np.linspace(0, 2 * np.pi, n)
    pts = np.stack([radius_x * np.cos(th), np.zeros_like(th), radius_z * np.sin(th)], axis=1)
    return pts + np.array(center, dtype=float)


def _build_spine(polys):
    n = 24
    t = np.arange(n) / (n - 1)
    ys = -0.45 + 0.80 * t
    # Đường cong sinh lý của cột sống: ưỡn cổ, gù ngực, ưỡn thắt lưng
    zs = np.interp(t, [0, 0.12, 0.3, 0.5, 0.7, 0.85, 1.0],
                   [0.0, 0.03, 0.0, -0.05, -0.02, 0.035, 0.0])
    radii = np.interp(np.arange(n), [0, 6, 7, 18, 19, 23],
                      [0.022, 0.026, 0.030, 0.043, 0.048, 0.055])
    h = 0.011
    for y, z, r in zip(ys, zs, radii):
        top = _ring((0, y - h, z), r, r * 0.8)
        bottom = _ring((0, y + h, z), r, r * 0.8)
        polys.append(("SPINE", top))
        polys.append(("SPINE", bottom))
        for k in (0, 3, 5, 8):  # 4 gờ nối vòng trên-dưới -> thân đốt sống
            polys.append(("SPINE", np.array([top[k], bottom[k]])))
        # gai sau (hướng ra phía lưng = -z) và 2 mỏm ngang
        polys.append(("SPINE", np.array([[0, y, z - r * 0.8],
                                         [0, y + 0.015, z - r * 0.8 - 0.045 - 0.1 * r]])))
        for s in (-1, 1):
            polys.append(("SPINE", np.array([[s * r * 0.8, y, z - r * 0.4],
                                             [s * (r + 0.05), y, z - r * 0.7]])))
    # Sọ: elip khung dây + 2 hốc mắt (để biết đâu là phía trước)
    c = np.array([0.0, -0.45 - 0.095, 0.02])
    rx, ry, rz = 0.075, 0.088, 0.09
    for v in np.radians([-60, -25, 10, 40, 65]):
        th = np.linspace(0, 2 * np.pi, 17)
        pts = np.stack([rx * np.cos(v) * np.cos(th), np.full_like(th, ry * np.sin(v) * -1),
                        rz * np.cos(v) * np.sin(th)], axis=1) + c
        polys.append(("SPINE", pts))
    for u in np.radians([0, 45, 90, 135]):
        vv = np.linspace(-np.pi / 2, np.pi / 2, 13)
        pts = np.stack([rx * np.cos(vv) * np.cos(u), -ry * np.sin(vv),
                        rz * np.cos(vv) * np.sin(u)], axis=1) + c
        polys.append(("SPINE", pts))
        pts2 = np.stack([-rx * np.cos(vv) * np.cos(u), -ry * np.sin(vv),
                         -rz * np.cos(vv) * np.sin(u)], axis=1) + c
        polys.append(("SPINE", pts2))
    th = np.linspace(0, 2 * np.pi, 13)
    for s in (-1, 1):  # hốc mắt: vòng nhỏ nằm trong mặt phẳng x-y, ở mặt trước sọ
        orbit = np.stack([s * 0.03 + 0.016 * np.cos(th), c[1] + 0.012 + 0.012 * np.sin(th),
                          np.full_like(th, c[2] + 0.088)], axis=1)
        polys.append(("SPINE", orbit))
    return ys, zs, radii


def _build_ribcage(polys, ys, zs, radii):
    Zs = 0.13  # mặt phẳng xương ức (phía trước ngực)
    ends_sternum = []
    margin_ends = {1: [], -1: []}
    for k in range(12):
        vi = 7 + k  # đốt sống ngực T(k+1)
        y_v, z_v, r_v = ys[vi], zs[vi], radii[vi]
        a = 0.065 + 0.095 * math.sin(math.pi * (k + 1.2) / 13.5)
        slope = 0.05 + 0.006 * k
        u_end = 1.0 if k < 7 else (0.88 if k < 10 else 0.55)
        u = np.linspace(0, u_end, 22)
        for s in (-1, 1):
            x = s * (a * np.sin(np.pi * u) + r_v * (1 - u))
            z = z_v + (Zs - z_v) * (1 - np.cos(np.pi * u)) / 2
            y = y_v + slope * u
            pts = np.stack([x, y, z], axis=1)
            polys.append(("RIBS", pts))
            if 7 <= k < 10:
                margin_ends[s].append(pts[-1])
        if k < 7:
            ends_sternum.append(y_v + slope)
    # Xương ức (thẳng đứng) + xương đòn
    y_top, y_bot = ends_sternum[0] - 0.02, ends_sternum[-1] + 0.035
    polys.append(("RIBS", np.array([[0, y_top, Zs], [0, y_bot, Zs]])))
    polys.append(("RIBS", np.array([[-0.025, y_top + 0.015, Zs - 0.005],
                                    [0.025, y_top + 0.015, Zs - 0.005]])))
    for s in (-1, 1):
        polys.append(("RIBS", np.array([[0, y_top, Zs],
                                        [s * 0.07, y_top - 0.015, Zs - 0.02],
                                        [s * 0.14, y_top - 0.005, Zs - 0.07],
                                        [s * 0.21, y_top + 0.01, -0.01]])))
        # bờ sườn: nối đầu các sườn 8-10 về phía xương ức
        chain = [np.array([0, y_bot, Zs])] + margin_ends[s]
        polys.append(("RIBS", np.array(chain)))


def _build_pelvis(polys):
    # Xương cùng (hình tam giác ngược) — viền ngoài + viền trong
    sacrum = np.array([[-0.05, 0.37, -0.045], [0.05, 0.37, -0.045], [0.04, 0.45, -0.075],
                       [0.0, 0.54, -0.095], [-0.04, 0.45, -0.075], [-0.05, 0.37, -0.045]])
    polys.append(("PELVIS", sacrum))
    polys.append(("PELVIS", sacrum + np.array([0, 0, 0.035])))
    for i in range(4):
        polys.append(("PELVIS", np.array([sacrum[i], sacrum[i] + np.array([0, 0, 0.035])])))
    outline = np.array([
        [0.055, 0.375, -0.045], [0.11, 0.315, -0.05], [0.19, 0.305, -0.02], [0.235, 0.345, 0.03],
        [0.225, 0.395, 0.075], [0.175, 0.425, 0.085], [0.150, 0.465, 0.075], [0.145, 0.51, 0.06],
        [0.135, 0.55, 0.04], [0.10, 0.62, -0.02], [0.07, 0.625, -0.03], [0.055, 0.585, 0.0],
        [0.04, 0.60, 0.045], [0.012, 0.575, 0.085],
    ])
    for s in (-1, 1):
        o = outline * np.array([s, 1, 1])
        polys.append(("PELVIS", o))
        # hố chậu trong (tạo chiều sâu cho cánh chậu)
        polys.append(("PELVIS", np.array([[s * 0.19, 0.305, -0.02], [s * 0.12, 0.34, 0.03],
                                          [s * 0.10, 0.40, 0.045], [s * 0.15, 0.465, 0.075]])))
        # ổ cối (vòng) + chỏm xương đùi + cổ/thân xương đùi
        th = np.linspace(0, 2 * np.pi, 15)
        acet = np.stack([np.full_like(th, s * 0.14), 0.52 + 0.035 * np.cos(th), 0.055 + 0.035 * np.sin(th)], axis=1)
        polys.append(("PELVIS", acet))
        head = np.stack([np.full_like(th, s * 0.17), 0.52 + 0.028 * np.cos(th), 0.055 + 0.028 * np.sin(th)], axis=1)
        polys.append(("PELVIS", head))
        polys.append(("PELVIS", np.array([[s * 0.17, 0.52, 0.055], [s * 0.215, 0.565, 0.05],
                                          [s * 0.205, 0.63, 0.045]])))
    polys.append(("PELVIS", np.array([[-0.012, 0.575, 0.085], [0.012, 0.575, 0.085]])))


def build_skeleton_segments():
    """Trả về (P0, P1, part_ids, part_names): các đoạn thẳng 3D của bộ xương
    mô phỏng. P0/P1 là mảng (M,3) điểm đầu/cuối mỗi đoạn."""
    polys = []
    ys, zs, radii = _build_spine(polys)
    _build_ribcage(polys, ys, zs, radii)
    n_before = len(polys)
    _build_pelvis(polys)
    # Khung chậu thật có bề ngang xấp xỉ lồng ngực -> thu hẹp trục x cho đúng tỉ lệ
    for i in range(n_before, len(polys)):
        part, pts = polys[i]
        pts = np.asarray(pts, dtype=float).copy()
        pts[:, 0] *= 0.68
        polys[i] = (part, pts)

    names = ["SPINE", "RIBS", "PELVIS"]
    p0, p1, ids = [], [], []
    for part, pts in polys:
        pts = np.asarray(pts, dtype=float)
        if len(pts) < 2:
            continue
        p0.append(pts[:-1])
        p1.append(pts[1:])
        ids.append(np.full(len(pts) - 1, names.index(part)))
    return np.vstack(p0), np.vstack(p1), np.concatenate(ids), names


def load_obj_points(path, max_points=MAX_OBJ_POINTS):
    """Đọc các đỉnh 'v x y z' của file .obj, căn giữa và co giãn cho vừa khung
    (chiều lớn nhất = 1.2). Trả về mảng (N,3) hoặc None nếu lỗi/quá ít điểm.
    Lưu ý: mô hình xương dựng từ CT thường có trục y hướng LÊN — nếu thấy mô
    hình bị ngược đầu, đổi dấu cột y bên dưới."""
    pts = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("v "):
                    parts = line.split()
                    pts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    except (OSError, ValueError, IndexError):
        return None
    if len(pts) < 50:
        return None
    arr = np.array(pts, dtype=float)
    if len(arr) > max_points:
        rng = np.random.default_rng(0)
        arr = arr[rng.choice(len(arr), max_points, replace=False)]
    arr -= (arr.max(axis=0) + arr.min(axis=0)) / 2
    extent = float((arr.max(axis=0) - arr.min(axis=0)).max())
    arr *= 1.2 / max(extent, 1e-9)
    arr[:, 1] *= -1  # OBJ: y lên -> hệ của viewer: y xuống
    return arr


# =====================================================================
# VIEWER
# =====================================================================
class Model3DViewer:
    def __init__(self, frame_width, frame_height, model_dir="medical_models"):
        self.width = frame_width
        self.height = frame_height

        bw, bh = BUTTON_SIZE
        n = len(BUTTON_LABELS)
        total_w = bw * n + BUTTON_GAP * (n - 1)
        start_x = (frame_width - total_w) // 2
        y = frame_height - bh - BUTTON_MARGIN
        self.buttons = {label: (start_x + i * (bw + BUTTON_GAP), y, bw, bh)
                        for i, label in enumerate(BUTTON_LABELS)}

        # Nạp mô hình: .obj thật nếu có, không thì bộ xương mô phỏng
        self.points = None       # (N,3) nếu dùng .obj
        self.source_name = "Bo xuong mo phong (minh hoa)"
        self._load_model(model_dir)
        if self.points is None:
            self.p0, self.p1, self.part_ids, self.part_names = build_skeleton_segments()

        self.layer_index = 0
        self.view_index = -1     # -1 = góc mặc định; >=0 = đang ở góc preset
        self.reset_view()

    def _load_model(self, model_dir):
        if not os.path.isdir(model_dir):
            return
        for f in sorted(os.listdir(model_dir)):
            if f.lower().endswith(".obj"):
                pts = load_obj_points(os.path.join(model_dir, f))
                if pts is not None:
                    self.points = pts
                    self.source_name = f"Mo hinh: {f}"
                    return

    # -- Điều khiển ---------------------------------------------------------
    def reset_view(self):
        self.yaw = DEFAULT_YAW
        self.pitch = DEFAULT_PITCH
        self.zoom = 1.0
        self.clip = 0.0          # 0 = không cắt, 1 = cắt gần hết
        self.view_index = -1

    def rotate(self, dx, dy):
        """Xoay theo chuyển động tay (pixel). Kéo ngang = xoay trái/phải, kéo
        dọc = ngả lên/xuống (giới hạn để không lật ngược)."""
        self.yaw += dx * ROTATE_SENSITIVITY
        self.pitch = max(-1.5, min(1.5, self.pitch + dy * ROTATE_SENSITIVITY))
        self.view_index = -1

    def set_zoom(self, new_zoom):
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))

    def adjust_clip(self, dy_pixels):
        """Kéo tay XUỐNG (dy > 0) = cắt thêm (ẩn thêm lớp phía trước), kéo
        LÊN = trả lại."""
        self.clip = max(0.0, min(MAX_CLIP, self.clip + dy_pixels * CLIP_SENSITIVITY))

    def cycle_layer(self):
        if self.points is not None:
            return  # mô hình .obj không chia lớp
        self.layer_index = (self.layer_index + 1) % len(LAYERS)

    def cycle_view(self):
        self.view_index = (self.view_index + 1) % len(VIEWS)
        _, self.yaw, self.pitch = VIEWS[self.view_index]

    def get_hover_button(self, cursor_pos):
        if cursor_pos is None:
            return None
        x, y = cursor_pos
        for label, (bx, by, bw, bh) in self.buttons.items():
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return label
        return None

    # -- Phép chiếu ---------------------------------------------------------
    def _rotation_matrix(self):
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cx, sx = math.cos(self.pitch), math.sin(self.pitch)
        ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        return rx @ ry

    def _project(self, pts3d):
        """Xoay rồi chiếu phối cảnh. Trả về (screen_xy (N,2) float, z_view (N,))."""
        rot = pts3d @ self._rotation_matrix().T
        z = rot[:, 2]
        persp = CAMERA_DISTANCE / (CAMERA_DISTANCE - z)
        avail_h = self.height - BUTTON_SIZE[1] - BUTTON_MARGIN * 2 - 62
        scale = avail_h / 1.3 * self.zoom
        sx = self.width / 2 + rot[:, 0] * persp * scale
        sy = 62 + avail_h / 2 + rot[:, 1] * persp * scale
        return np.stack([sx, sy], axis=1), z

    def _clip_z(self):
        # clip=0 -> ngưỡng cao hơn mọi điểm (không ẩn gì); clip tăng -> ẩn dần
        # các điểm có z_view lớn (= gần người xem).
        return 0.32 - 0.62 * self.clip

    # -- Hiển thị -----------------------------------------------------------
    def draw(self, cursor_pos=None, is_pinching_now=False):
        display = np.full((self.height, self.width, 3), COLOR_BG, dtype=np.uint8)
        if self.points is not None:
            self._draw_points(display)
        else:
            self._draw_skeleton(display)
        self._draw_ui(display, cursor_pos, is_pinching_now)
        return display

    def _draw_skeleton(self, display):
        layer_name, allowed = LAYERS[self.layer_index]
        mask = np.ones(len(self.p0), dtype=bool)
        if allowed is not None:
            ok_ids = [i for i, nme in enumerate(self.part_names) if nme in allowed]
            mask = np.isin(self.part_ids, ok_ids)
        p0, p1, ids = self.p0[mask], self.p1[mask], self.part_ids[mask]

        s0, z0 = self._project(p0)
        s1, z1 = self._project(p1)
        zm = (z0 + z1) / 2
        visible = zm <= self._clip_z()
        order = np.argsort(zm[visible])        # xa -> gần
        s0, s1, zm, ids = s0[visible][order], s1[visible][order], zm[visible][order], ids[visible][order]

        for a, b, z, pid in zip(s0, s1, zm, ids):
            fade = 0.32 + 0.68 * float(np.clip((z + 0.3) / 0.6, 0, 1))
            base = PART_COLORS[self.part_names[pid]]
            color = (int(base[0] * fade), int(base[1] * fade), int(base[2] * fade))
            cv2.line(display, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])),
                     color, 2 if z > 0.0 else 1, cv2.LINE_AA)

    def _draw_points(self, display):
        s, z = self._project(self.points)
        visible = z <= self._clip_z()
        s, z = s[visible], z[visible]
        order = np.argsort(z)
        s, z = s[order], z[order]
        fade = 0.25 + 0.75 * np.clip((z + 0.6) / 1.2, 0, 1)
        colors = (np.array(PART_COLORS["SPINE"])[None, :] * fade[:, None]).astype(np.uint8)
        xs, ys = s[:, 0].astype(int), s[:, 1].astype(int)
        for dx in (0, 1):
            for dy in (0, 1):
                xx, yy = xs + dx, ys + dy
                ok = (xx >= 0) & (xx < self.width) & (yy >= 0) & (yy < self.height)
                display[yy[ok], xx[ok]] = colors[ok]

    def _draw_ui(self, display, cursor_pos, is_pinching_now):
        hovered = self.get_hover_button(cursor_pos)
        for label, (bx, by, bw, bh) in self.buttons.items():
            is_hover = label == hovered
            border = COLOR_ACCENT if is_hover else COLOR_TOOLBAR_BORDER
            tcolor = COLOR_ACCENT if is_hover else COLOR_TEXT
            cv2.rectangle(display, (bx, by), (bx + bw, by + bh), border, 2)
            ts = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0]
            cv2.putText(display, label, (bx + (bw - ts[0]) // 2, by + (bh + ts[1]) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, tcolor, 1, cv2.LINE_AA)

        layer_name = LAYERS[self.layer_index][0] if self.points is None else "TAT CA"
        view_name = VIEWS[self.view_index][0] if self.view_index >= 0 else "TU DO"
        info = (f"{self.source_name}  |  Lop: {layer_name}  |  Goc: {view_name}  |  "
                f"Zoom: {self.zoom:.1f}x  |  Cat lop: {int(self.clip / MAX_CLIP * 100)}%")
        cv2.putText(display, info, (BUTTON_MARGIN, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_TEXT_HINT, 1, cv2.LINE_AA)
        cv2.putText(display, "Mo hinh MINH HOA, khong dung de chan doan", (BUTTON_MARGIN, 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_ACCENT, 1, cv2.LINE_AA)

        # Thanh trượt "cắt lớp" bên phải
        bx = self.width - 28
        top, bottom = 70, self.height - BUTTON_SIZE[1] - BUTTON_MARGIN * 2 - 20
        cv2.line(display, (bx, top), (bx, bottom), COLOR_TOOLBAR_BORDER, 2)
        ky = int(top + (bottom - top) * (self.clip / MAX_CLIP))
        cv2.circle(display, (bx, ky), 6, COLOR_ACCENT, -1, cv2.LINE_AA)
        cv2.putText(display, "CAT", (bx - 14, top - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    COLOR_TEXT_HINT, 1, cv2.LINE_AA)

        LINE_H = 18
        hint_bottom_y = self.height - BUTTON_MARGIN - BUTTON_SIZE[1] - 12
        hints = ["Pinch + keo: xoay",
                 "2 tay xa/gan: zoom",
                 "Tay trai xoe + Pinch",
                 "keo doc: cat lop",
                 "Snap: thoat"]
        for i, text in enumerate(hints):
            cv2.putText(display, text, (BUTTON_MARGIN, hint_bottom_y - (len(hints) - 1 - i) * LINE_H),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_TEXT_HINT, 1, cv2.LINE_AA)

        if cursor_pos is not None:
            cx, cy = int(cursor_pos[0]), int(cursor_pos[1])
            color = COLOR_ACCENT if (hovered is not None or is_pinching_now) else COLOR_TEXT
            if is_pinching_now:
                cv2.circle(display, (cx, cy), 6, color, -1, cv2.LINE_AA)
            else:
                overlay = display.copy()
                cv2.circle(overlay, (cx, cy), 10, color, 1, cv2.LINE_AA)
                cv2.addWeighted(overlay, 0.55, display, 0.45, 0, display)


# --- Test nhanh: python model_viewer.py (xoay tự động, bấm q để thoát) ---
if __name__ == "__main__":
    viewer = Model3DViewer(640, 480)
    while True:
        viewer.rotate(2, 0)
        cv2.imshow("Model 3D test", viewer.draw())
        if cv2.waitKey(30) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()
