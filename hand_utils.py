"""
hand_utils.py
--------------
Module tự viết cho project "Touchless Spatial Interface for IoT Control".
Dùng MediaPipe Tasks API (vision.HandLandmarker) — không phụ thuộc cvzone
hay API cũ mp.solutions.hands.

Chức năng:
  - HandTracker: bọc quanh HandLandmarker, trả về danh sách tay đã xử lý sẵn
  - palm_size(): "kích thước lòng bàn tay" (wrist -> middle_mcp), dùng làm
    thước đo chuẩn để mọi threshold khác tự co giãn theo từng người
  - fingers_up(): đếm ngón đang duỗi (dùng khoảng cách 3D tới cổ tay thay vì
    so trục Y/X, nên không bị sai khi bàn tay xoay nghiêng)
  - distance(): khoảng cách Euclid giữa 2 điểm (dùng landmark chuẩn hóa
    hoặc world landmark tùy nhu cầu)
  - detect_gesture(): map trạng thái ngón tay -> Point / Pinch / Open palm / Fist
  - LandmarkSmoother: làm mượt world_landmarks NGAY TỪ GỐC trước khi nhận
    diện gesture, giúp Pinch/Point/Fist ổn định hơn (dùng riêng cho mỗi tay,
    KHÔNG dùng cho SnapDetector vì Snap cần dữ liệu chuyển động nhanh, chưa
    làm mượt)
  - GestureStabilizer: làm mượt NHÃN gesture theo thời gian (bỏ phiếu đa số),
    chống nhấp nháy khi hiển thị/khi cần 1 nhãn ổn định
  - CursorSmoother: làm mượt vị trí HIỂN THỊ của cursor, chống rung tay

BẢN CẬP NHẬT CHO PHÒNG MỔ (mới thêm — TẤT CẢ đều là phần THÊM, không đổi
cách hoạt động của các hàm cũ nên main_spatial_ui_demo.py cũ vẫn chạy bình thường):
  - detect_gesture() nhận thêm 3 nhãn mới: 'Thumbs up', 'Thumbs down', 'Y sign'
    (các nhãn cũ Point/Pinch/Open palm/Fist giữ nguyên)
  - palm_center(): tâm lòng bàn tay (chuẩn hóa 0-1) — điểm đại diện cho "vị trí tay"
  - SterileZone: "vùng vô trùng" (từ hông tới ngực, theo khuyến nghị của O'Hara
    và cộng sự) — kiểm tra tay có nằm trong vùng cho phép không + vẽ khung hướng dẫn
  - HoldToggle: giữ 1 gesture đủ lâu (vd Open palm 2 giây) để KHÓA/MỞ KHÓA, có
    thanh tiến trình, phải thả ra rồi mới kích hoạt lại được (chống bật-tắt liên tục)
  - SwipeDetector: nhận diện VẨY TAY trái/phải/lên/xuống, có thời gian nghỉ
    (cooldown) để không nhận nhầm cú "vung tay về" thành lệnh thứ hai
  - two_hand_angle() + angle_delta(): góc nối 2 đầu ngón trỏ để XOAY ẢNH bằng 2 tay
  - select_primary_hand(): khi có nhiều tay cùng nhãn (người khác đi ngang
    camera), chọn tay LỚN NHẤT (gần camera nhất) làm tay của người dùng chính

BẢN SỬA LỖI (Fist bị hiểu nhầm thành Pinch):
  Bản trước kiểm tra Pinch TRƯỚC Fist một cách vô điều kiện. Vấn đề: khi bạn
  nắm đấm thật, ngón cái gập lại có thể tình cờ nằm khá gần đầu ngón trỏ (vì
  cả bàn tay đang co lại), khiến pinch_ratio nhỏ hơn ngưỡng và hệ thống háo
  hức trả về "Pinch" dù thực chất bạn đang Fist -> menu.close() (chỉ chạy khi
  gesture = "Fist") không bao giờ được gọi.

  Cách sửa: kiểm tra Fist TRƯỚC — nếu CẢ 5 ngón (kể cả ngón cái) đều đang gập
  (sum(fingers) == 0) thì chắc chắn là Fist, trả về ngay, không cần xét tới
  khoảng cách pinch nữa. Chỉ khi không phải trường hợp "gập hết" mới xét tiếp
  tới Pinch. Vì khi Pinch thật (ngón cái + ngón trỏ chụm lại kiểu OK), 3 ngón
  còn lại (giữa/áp út/út) hầu như vẫn duỗi bình thường, nên sum(fingers) lúc
  đó gần như không bao giờ bằng 0 -> đổi thứ tự này không làm ảnh hưởng tới
  việc nhận Pinch thật.
"""

import math
import time
from collections import deque, Counter
from types import SimpleNamespace

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# Index của 5 đầu ngón tay trong 21 landmarks (thumb, index, middle, ring, pinky)
TIP_IDS = [4, 8, 12, 16, 20]
# Khớp PIP tương ứng — giữ lại hằng số này từ bản cũ để tương thích, nhưng
# fingers_up() không dùng nữa (xem BASE_IDS bên dưới)
PIP_IDS = [3, 6, 10, 14, 18]
# Khớp "gốc ngón" (MCP) tương ứng với từng ngón trong TIP_IDS — dùng làm điểm
# tham chiếu để đo "ngón duỗi bao xa" so với cổ tay. Với ngón cái, landmark 2
# (MCP) đóng vai trò gốc ngón.
BASE_IDS = [2, 5, 9, 13, 17]
WRIST = 0
MIDDLE_MCP = 9

# Ngưỡng "duỗi ngón": đầu ngón phải xa cổ tay hơn gốc ngón ít nhất chừng này
# lần thì mới coi là đang duỗi. Nếu bạn thấy Fist vẫn khó trigger (một vài
# ngón bị coi là "còn duỗi" dù bạn đã nắm chặt), thử GIẢM số này (vd 1.25),
# nghĩa là dễ tính "gập" hơn.
FINGER_EXTEND_RATIO = 1.4

# Ngưỡng pinch mặc định, tính theo TỈ LỆ (khoảng cách ngón cái - ngón trỏ) /
# palm_size, KHÔNG phải số mét cố định — để tự đúng với mọi cỡ tay.
PINCH_RATIO_THRESHOLD = 0.35

# Các landmark ở "nửa cuối" ngón trỏ mà ngón cái có thể chạm vào khi Pinch:
#   6 = PIP (đốt giữa), 7 = DIP (đốt gần đầu), 8 = TIP (đầu ngón)
# Xem giải thích chi tiết trong hàm pinch_ratio() bên dưới.
INDEX_PINCH_TARGETS = [6, 7, 8]


class HandTracker:
    def __init__(self, model_path="hand_landmarker.task", num_hands=2,
                 min_detection_confidence=0.5, min_presence_confidence=0.5,
                 min_tracking_confidence=0.5):
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=model_path),
            num_hands=num_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
            running_mode=vision.RunningMode.VIDEO,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._frame_idx = 0

    def process(self, bgr_frame):
        """Nhận 1 frame OpenCV (BGR), trả về list các tay đã xử lý."""
        h, w = bgr_frame.shape[:2]
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        timestamp_ms = int(self._frame_idx * (1000 / 30))
        result = self._landmarker.detect_for_video(mp_image, timestamp_ms)
        self._frame_idx += 1

        hands = []
        if result.hand_landmarks:
            for landmarks, world_landmarks, handedness in zip(
                result.hand_landmarks, result.hand_world_landmarks, result.handedness
            ):
                raw_label = handedness[0].category_name  # "Left" hoặc "Right" (theo ảnh gốc, CHƯA lật)
                # Nếu bạn lật frame trước khi gọi process() để hiển thị kiểu gương,
                # nhãn trái/phải cũng phải đảo lại để khớp với những gì người dùng nhìn thấy.
                label = "Left" if raw_label == "Right" else "Right"
                pixel_points = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
                hands.append({
                    "type": label,
                    "landmarks": landmarks,            # chuẩn hóa 0.0-1.0 (dùng để vẽ)
                    "world_landmarks": world_landmarks,  # đơn vị mét thật (dùng để đo khoảng cách)
                    "pixels": pixel_points,
                })
        return hands

    def close(self):
        self._landmarker.close()


def distance(hand, idx_a, idx_b, use_world=True):
    """Khoảng cách giữa 2 landmark. Mặc định dùng world_landmarks (mét thật),
    không phụ thuộc khoảng cách người dùng đứng cách camera bao xa."""
    points = hand["world_landmarks"] if use_world else hand["landmarks"]
    a, b = points[idx_a], points[idx_b]
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def palm_size(hand):
    """
    "Kích thước lòng bàn tay" = khoảng cách world (mét thật) từ cổ tay (wrist)
    đến gốc ngón giữa (middle_mcp). Đại lượng này khá ổn định với MỖI người
    (ít đổi khi tay co duỗi/xoay), nên dùng làm "thước đo chuẩn" để chuẩn hóa
    mọi threshold khác (pinch, snap...) thay vì dùng số mét cố định.
    """
    size = distance(hand, WRIST, MIDDLE_MCP, use_world=True)
    return size if size > 1e-6 else 1e-6  # tránh chia cho 0 nếu dữ liệu lỗi


def pinch_ratio(hand):
    """
    Tỉ lệ pinch = khoảng cách NGẮN NHẤT từ đầu ngón cái (landmark 4) tới BẤT
    KỲ điểm nào trong INDEX_PINCH_TARGETS (đốt giữa/đốt cuối/đầu ngón trỏ),
    chia cho palm_size.

    SỬA LỖI: bản trước chỉ đo khoảng cách "đầu ngón cái - đầu ngón trỏ"
    (tip-to-tip). Trên thực tế, nhiều người khi làm động tác Pinch không
    chụm chính xác đầu 2 ngón vào nhau, mà ngón cái gập cong vào tì lên đốt
    giữa của ngón trỏ (tư thế "bấm" tự nhiên hơn — giống ảnh bạn chụp gửi
    mình). Đo tip-to-tip trong trường hợp đó ra khoảng cách khá lớn, khiến
    hệ thống hiểu nhầm thành Point. Đo khoảng cách ngắn nhất tới nhiều điểm
    trên ngón trỏ giúp nhận đúng Pinch với nhiều kiểu chụm tay khác nhau.
    """
    p_size = palm_size(hand)
    min_dist = min(distance(hand, 4, target_id) for target_id in INDEX_PINCH_TARGETS)
    return min_dist / p_size


def is_pinching(hand, currently_pinching,
                 enter_ratio=PINCH_RATIO_THRESHOLD,
                 exit_ratio=PINCH_RATIO_THRESHOLD + 0.15):
    """
    Xác định tay có đang Pinch hay không, có dùng HYSTERESIS (2 ngưỡng khác
    nhau cho lúc BẮT ĐẦU pinch và lúc KẾT THÚC pinch) thay vì chỉ 1 ngưỡng
    duy nhất.

    TẠI SAO CẦN HYSTERESIS (sửa lỗi "đứt nét khi vẽ"):
    Nếu chỉ dùng 1 ngưỡng, khi pinch_ratio dao động qua lại ngay sát ngưỡng
    đó (do tay run nhẹ/nhiễu landmark), is_pinching sẽ nhấp nháy True/False
    liên tục dù tay bạn vẫn đang giữ nguyên tư thế Pinch. Ở Notepad, mỗi lần
    "tắt rồi bật lại" bị hiểu là 1 nét vẽ MỚI (start_stroke() gọi lại), làm
    đường vẽ bị ngắt thành nhiều đoạn rời rạc thay vì 1 nét liền mạch.

    Cách khắc phục: lúc BẮT ĐẦU pinch vẫn dùng đúng ngưỡng cũ (enter_ratio =
    PINCH_RATIO_THRESHOLD, không đổi so với trước — không làm khó hơn việc
    bắt đầu Pinch). Nhưng một khi ĐÃ đang pinch rồi, ngưỡng để "thả ra" được
    nới RỘNG hơn hẳn (exit_ratio = PINCH_RATIO_THRESHOLD + 0.15). Nhờ vậy có
    một "vùng đệm" giữa 2 ngưỡng: nếu pinch_ratio dao động nhẹ quanh mức cũ
    trong lúc bạn đang giữ Pinch, nó vẫn nằm dưới exit_ratio nên KHÔNG bị
    tính là "đã thả tay", giúp Pinch/nét vẽ ổn định liên tục hơn nhiều.

    currently_pinching: trạng thái pinch của FRAME TRƯỚC (thường truyền vào
    biến was_pinching bạn đang giữ ở vòng lặp chính).
    """
    ratio = pinch_ratio(hand)
    if currently_pinching:
        return ratio < exit_ratio
    return ratio < enter_ratio


def fingers_up(hand):
    """
    Trả về list 5 giá trị 0/1 cho [thumb, index, middle, ring, pinky].

    Cách tính: so khoảng cách WORLD (mét thật) từ cổ tay tới đầu ngón với
    khoảng cách từ cổ tay tới gốc ngón. Khi ngón duỗi thẳng, đầu ngón xa cổ
    tay hơn gốc ngón rất nhiều; khi gập lại, đầu ngón gập về gần cổ tay nên
    khoảng cách không tăng thêm bao nhiêu. Cách này không phụ thuộc hướng
    xoay của bàn tay, và cũng không cần biết tay trái/phải.
    """
    world = hand["world_landmarks"]
    wrist = world[WRIST]
    fingers = []
    for tip_id, base_id in zip(TIP_IDS, BASE_IDS):
        dist_wrist_to_base = math.sqrt(
            (world[base_id].x - wrist.x) ** 2
            + (world[base_id].y - wrist.y) ** 2
            + (world[base_id].z - wrist.z) ** 2
        )
        dist_wrist_to_tip = math.sqrt(
            (world[tip_id].x - wrist.x) ** 2
            + (world[tip_id].y - wrist.y) ** 2
            + (world[tip_id].z - wrist.z) ** 2
        )
        fingers.append(1 if dist_wrist_to_tip > dist_wrist_to_base * FINGER_EXTEND_RATIO else 0)
    return fingers


def _thumb_vertical_direction(hand, min_vertical_ratio=1.0):
    """
    Ngón cái đang chỉ LÊN ('up'), XUỐNG ('down') hay không rõ ràng (None).
    Dùng world_landmarks (mét thật, không bị méo theo tỉ lệ khung hình): vector
    từ gốc ngón cái (landmark 2) tới đầu ngón cái (landmark 4). Trục y của
    MediaPipe hướng XUỐNG, nên y nhỏ hơn = cao hơn.
    min_vertical_ratio = 1.0 nghĩa là ngón cái phải lệch không quá 45 độ so với
    phương thẳng đứng (|dy| >= |dx| và |dy| >= |dz|), để tránh nhận nhầm khi
    ngón cái chỉ ngang/chỉ về phía camera.
    """
    world = hand["world_landmarks"]
    dx = world[4].x - world[2].x
    dy = world[4].y - world[2].y
    dz = world[4].z - world[2].z
    if abs(dy) < min_vertical_ratio * max(abs(dx), abs(dz)):
        return None
    return "up" if dy < 0 else "down"


def detect_gesture(hand, pinch_ratio_threshold=PINCH_RATIO_THRESHOLD):
    """
    Trả về 1 trong: 'Point', 'Pinch', 'Open palm', 'Fist',
    'Thumbs up', 'Thumbs down', 'Y sign', None.

    THỨ TỰ KIỂM TRA (quan trọng, xem giải thích ở đầu file):
      1) Fist trước tiên — nếu tất cả 5 ngón đều gập, chắc chắn là Fist,
         không cần xét pinch nữa (tránh bị Pinch "cướp" mất Fist).
      2) Pinch — dựa trên tỉ lệ (khoảng cách ngón cái-ngón trỏ) / palm_size.
      3) Open palm — từ 4 ngón trở lên đang duỗi.
      4) Point — chỉ ngón trỏ duỗi.
    Thumbs up/down và Y sign được kiểm tra ngay sau Fist (trước Pinch), xem
    chú thích trong thân hàm.
    """
    fingers = fingers_up(hand)
    thumb, index, middle, ring, pinky = fingers

    if sum(fingers) == 0:
        return "Fist"

    # Các tư thế mới (kiểm tra TRƯỚC Pinch vì ngón cái duỗi có thể nằm gần
    # ngón trỏ, dễ bị Pinch "cướp" — nhưng chỉ khi ngón cái thật sự chỉ
    # thẳng lên/xuống và không chụm vào ngón trỏ).
    thumb_dir = _thumb_vertical_direction(hand)
    if fingers == [1, 0, 0, 0, 0] and thumb_dir is not None \
            and pinch_ratio(hand) > pinch_ratio_threshold + 0.2:
        return "Thumbs up" if thumb_dir == "up" else "Thumbs down"
    if fingers == [1, 0, 0, 0, 1]:
        return "Y sign"

    if pinch_ratio(hand) < pinch_ratio_threshold:
        return "Pinch"

    if sum(fingers) >= 4:
        return "Open palm"
    if index == 1 and middle == 0 and ring == 0 and pinky == 0:
        return "Point"
    return None


# --- LANDMARK SMOOTHER: làm mượt NGAY TỪ GỐC dữ liệu bàn tay ---
class LandmarkSmoother:
    """
    Làm mượt (EMA) TOÀN BỘ 21 world_landmarks của 1 bàn tay theo thời gian,
    áp dụng NGAY TRƯỚC KHI đưa vào các hàm nhận diện gesture (fingers_up,
    pinch_ratio, detect_gesture, is_pinching...).

    KHÁC với CursorSmoother (chỉ làm mượt vị trí HIỂN THỊ của con trỏ cho mắt
    đỡ giật): LandmarkSmoother làm mượt ngay TỪ GỐC dữ liệu bàn tay, nên chính
    việc NHẬN DIỆN GESTURE cũng ổn định hơn — bớt hẳn tình trạng Pinch/Point
    hoặc pinch-để-click/pinch-để-vẽ bị "nhấp nháy"/nhầm lẫn qua lại do nhiễu
    nhỏ 1-2 frame (rung tay nhẹ, landmark lệch chút xíu) chứ tay thực ra vẫn
    đang giữ nguyên 1 tư thế.

    QUAN TRỌNG — KHÔNG dùng bản đã làm mượt này cho SnapDetector: Snap là một
    chuyển động RẤT NHANH (bung ngón tay trong vài chục mili-giây), làm mượt
    kiểu này sẽ "bào mòn" mất đúng tín hiệu nhanh mà SnapDetector cần để nhận
    diện, khiến Snap khó trigger hơn hẳn. Vì vậy trong main_spatial_ui_demo.py,
    SnapDetector vẫn luôn được gọi với hand dict GỐC (chưa làm mượt), chỉ có
    detect_gesture()/pinch_ratio()/is_pinching() mới dùng bản đã làm mượt.

    Cần 1 instance RIÊNG cho mỗi tay (trái/phải), vì mỗi tay có lịch sử vị trí
    khác nhau — dùng chung 1 instance sẽ khiến 2 tay bị "làm mượt" lẫn dữ
    liệu vào nhau.
    """

    def __init__(self, smoothing_factor=0.5):
        self.alpha = smoothing_factor
        self._smoothed = None  # list 21 SimpleNamespace(x, y, z), hoặc None nếu chưa có dữ liệu

    def update(self, world_landmarks):
        """Nhận vào world_landmarks THẬT của frame hiện tại (list 21 điểm có
        .x/.y/.z), trả về list 21 điểm ĐÃ LÀM MƯỢT (cùng kiểu .x/.y/.z, dùng
        được y hệt như world_landmarks gốc trong mọi hàm khác của file này)."""
        if self._smoothed is None:
            # Lần đầu tiên thấy tay này (hoặc vừa reset) -> chưa có gì để
            # trộn cùng, nhận thẳng giá trị thật làm điểm khởi đầu.
            self._smoothed = [SimpleNamespace(x=p.x, y=p.y, z=p.z) for p in world_landmarks]
        else:
            for smoothed_point, new_point in zip(self._smoothed, world_landmarks):
                smoothed_point.x = self.alpha * new_point.x + (1 - self.alpha) * smoothed_point.x
                smoothed_point.y = self.alpha * new_point.y + (1 - self.alpha) * smoothed_point.y
                smoothed_point.z = self.alpha * new_point.z + (1 - self.alpha) * smoothed_point.z
        return self._smoothed

    def reset(self):
        """Gọi khi tay biến mất khỏi khung hình (hẳn, không phải mất dấu tạm
        thời), để lần xuất hiện kế tiếp không bị "kéo" theo vị trí tay cũ."""
        self._smoothed = None


# --- GESTURE STABILIZER: chống nhấp nháy gesture theo thời gian ---
class GestureStabilizer:
    """
    Vấn đề: detect_gesture() chạy mỗi frame có thể trả về kết quả hơi khác
    nhau do nhiễu nhỏ (tay run nhẹ, landmark lệch 1-2 pixel...), khiến gesture
    hiển thị bị "nhấp nháy" (Point -> None -> Point -> None...).

    Cách xử lý: lưu lại history_size kết quả gần nhất, chỉ "chốt" gesture mới
    khi nó xuất hiện đủ min_agreement lần trong số đó (biểu quyết đa số theo
    thời gian).

    Dùng 1 instance riêng cho mỗi tay (tay trái/tay phải đang làm 2 việc khác
    nhau nên không nên dùng chung 1 stabilizer).
    """

    def __init__(self, history_size=6, min_agreement=4):
        self.history = deque(maxlen=history_size)
        self.min_agreement = min_agreement
        self.stable_gesture = None

    def update(self, new_gesture):
        self.history.append(new_gesture)
        most_common_gesture, count = Counter(self.history).most_common(1)[0]
        if count >= self.min_agreement:
            self.stable_gesture = most_common_gesture
        return self.stable_gesture


# --- CURSOR SMOOTHER: làm mượt vị trí con trỏ ---
class CursorSmoother:
    """
    Vấn đề: vị trí đầu ngón trỏ (pixel) bị rung nhẹ theo từng frame dù tay
    đứng yên, khiến cursor trên màn hình bị giật.

    Cách xử lý: trung bình động có trọng số theo cấp số nhân (Exponential
    Moving Average - EMA):
        vị_trí_mượt_mới = alpha * vị_trí_thật + (1 - alpha) * vị_trí_mượt_cũ

    alpha nhỏ -> mượt hơn nhưng "trễ" hơn (đuổi theo tay chậm hơn).
    alpha lớn -> phản hồi nhanh hơn nhưng đỡ mượt hơn.
    """

    def __init__(self, smoothing_factor=0.4):
        self.alpha = smoothing_factor
        self.smoothed_x = None
        self.smoothed_y = None

    def update(self, x, y):
        if self.smoothed_x is None:
            self.smoothed_x, self.smoothed_y = x, y
        else:
            self.smoothed_x = self.alpha * x + (1 - self.alpha) * self.smoothed_x
            self.smoothed_y = self.alpha * y + (1 - self.alpha) * self.smoothed_y
        return (self.smoothed_x, self.smoothed_y)

    def reset(self):
        """Gọi khi tay biến mất khỏi khung hình, để lần xuất hiện tiếp theo
        cursor không bị "nhảy" từ vị trí cũ về vị trí mới."""
        self.smoothed_x = None
        self.smoothed_y = None


# =====================================================================
# CÁC CÔNG CỤ MỚI CHO PHÒNG MỔ
# =====================================================================

def palm_center(hand):
    """Tâm lòng bàn tay (chuẩn hóa 0.0-1.0, cùng hệ tọa độ với hand["landmarks"]):
    trung bình của cổ tay (0) và 4 gốc ngón (5, 9, 13, 17). Ổn định hơn đầu
    ngón tay (ít rung hơn) nên dùng làm "vị trí của tay" cho vùng vô trùng và
    nhận diện vẩy tay. Trả về (x, y)."""
    pts = hand["landmarks"]
    ids = (0, 5, 9, 13, 17)
    return (sum(pts[i].x for i in ids) / len(ids), sum(pts[i].y for i in ids) / len(ids))


def hand_apparent_size(hand):
    """Kích thước tay TRÊN ẢNH (cổ tay -> gốc ngón giữa, chuẩn hóa). Tay càng gần
    camera càng lớn. Khác palm_size() (mét thật, không đổi theo khoảng cách)."""
    pts = hand["landmarks"]
    return math.hypot(pts[WRIST].x - pts[MIDDLE_MCP].x, pts[WRIST].y - pts[MIDDLE_MCP].y)


def select_primary_hand(hands, label):
    """Trong danh sách hands, chọn tay có nhãn `label` ("Left"/"Right"). Nếu có
    NHIỀU tay cùng nhãn (vd người khác đi ngang camera), chọn tay LỚN NHẤT trên
    ảnh = gần camera nhất = nhiều khả năng là người dùng chính. Trả về None nếu
    không có. Dùng thay cho get_hand_by_label() khi muốn chống nhiễu."""
    candidates = [h for h in hands if h["type"] == label]
    if not candidates:
        return None
    return max(candidates, key=hand_apparent_size)


# --- VÙNG VÔ TRÙNG ---
class SterileZone:
    """
    "Vùng vô trùng": khoảng không phía trước người, từ HÔNG tới NGỰC (khuyến
    nghị trong O'Hara và cộng sự, CACM — tay đưa lên vai/cao hơn ngực hoặc xuống
    thấp hơn hông có nguy cơ chạm vật không vô trùng). Hệ thống chỉ NHẬN lệnh
    từ tay nằm trong vùng này.

    zone = (x_min, y_min, x_max, y_max) theo tỉ lệ 0.0-1.0 của khung hình
    (gốc ở góc trên trái). Mặc định: bỏ 1/3 phía trên (vùng vai/đầu) và chừa lề
    nhỏ hai bên. Chỉnh theo vị trí bạn đặt camera: đặt camera sao cho vùng
    "hông-ngực" của người đứng trước bàn mổ rơi đúng vào khung này.
    """

    def __init__(self, zone=(0.05, 0.33, 0.95, 1.0)):
        self.zone = zone

    def contains(self, hand):
        """True nếu tâm lòng bàn tay nằm trong vùng."""
        x, y = palm_center(hand)
        x0, y0, x1, y1 = self.zone
        return x0 <= x <= x1 and y0 <= y <= y1

    def draw(self, frame, active_hand_inside=True):
        """Vẽ khung vùng vô trùng lên frame OpenCV: xanh khi tay trong vùng,
        cam khi tay ra ngoài (để người dùng biết tay đang bị bỏ qua)."""
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = self.zone
        p1, p2 = (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h) - 2)
        color = (120, 180, 90) if active_hand_inside else (55, 150, 210)  # BGR
        cv2.rectangle(frame, p1, p2, color, 1, cv2.LINE_AA)
        cv2.putText(frame, "VUNG VO TRUNG", (p1[0] + 6, p1[1] + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


# --- GIỮ GESTURE ĐỂ KHÓA / MỞ KHÓA ---
class HoldToggle:
    """
    Giữ 1 gesture đủ `hold_time` giây để kích hoạt (dùng cho KHÓA/MỞ KHÓA màn
    hình ảo, chống kích hoạt nhầm trong phòng mổ).

    Cách dùng mỗi frame:
        if lock_toggle.update(left_gesture):       # True đúng 1 lần khi giữ đủ lâu
            locked = not locked
        progress = lock_toggle.progress            # 0.0-1.0, để vẽ thanh tiến trình

    Thiết kế chống kích hoạt liên tục: sau khi kích hoạt, PHẢI thả gesture ra
    (đổi sang gesture khác hoặc hạ tay) thì mới kích hoạt lại được — nếu không,
    cứ giữ tay xòe mãi sẽ khóa/mở khóa liên tục mỗi 2 giây.
    Mất gesture ngắn vài frame (nhiễu) KHÔNG làm đếm lại từ đầu nhờ `grace`.
    """

    def __init__(self, target_gesture="Open palm", hold_time=2.0, grace=0.25):
        self.target = target_gesture
        self.hold_time = hold_time
        self.grace = grace              # cho phép "đứt" tối đa chừng này giây
        self._start = None
        self._last_seen = None
        self._armed = True              # False sau khi kích hoạt, tới khi thả ra
        self.progress = 0.0

    def update(self, gesture, now=None):
        now = time.perf_counter() if now is None else now
        if gesture == self.target:
            self._last_seen = now
            if self._start is None and self._armed:
                self._start = now
            if self._start is not None:
                self.progress = min(1.0, (now - self._start) / self.hold_time)
                if now - self._start >= self.hold_time:
                    self._start = None
                    self._armed = False
                    self.progress = 0.0
                    return True
            return False
        # gesture khác / không có tay
        if self._last_seen is None or now - self._last_seen > self.grace:
            self._start = None
            self.progress = 0.0
            self._armed = True          # đã thả đủ lâu -> cho phép kích hoạt lại
        return False

    def reset(self):
        self._start = None
        self._last_seen = None
        self._armed = True
        self.progress = 0.0


# --- VẨY TAY (SWIPE) ---
class SwipeDetector:
    """
    Nhận diện VẨY TAY nhanh theo 4 hướng: "left", "right", "up", "down" (theo
    hình người dùng nhìn thấy trên màn hình đã lật gương).

    Cách hoạt động: lưu vị trí tâm lòng bàn tay trong `window` giây gần nhất.
    Nếu tay dịch chuyển ít nhất `min_distance` (tỉ lệ khung hình) và chủ yếu
    theo 1 trục (trục chính > 2 lần trục phụ), coi là vẩy.

    CHỐNG NHẬN NHẦM (vấn đề "gesture bleed"/"chuyển tiếp" trong CACM): sau mỗi
    lần vẩy có `cooldown` giây nghỉ, để cú vung tay VỀ vị trí cũ không bị tính
    thành 1 cú vẩy ngược. Người gọi nên chỉ truyền tay vào khi tay đang xòe
    (Open palm) và nằm trong vùng vô trùng để tránh vẩy nhầm khi đang thao tác.

    Dùng:  direction = swipe.update(hand)   # "left"/"right"/"up"/"down"/None
           (truyền hand=None khi không có tay -> tự xóa lịch sử)
    """

    def __init__(self, min_distance=0.25, window=0.5, cooldown=0.8):
        self.min_distance = min_distance
        self.window = window
        self.cooldown = cooldown
        self._history = deque()          # (thời gian, x, y)
        self._cooldown_until = 0.0

    def update(self, hand, now=None):
        now = time.perf_counter() if now is None else now
        if hand is None:
            self._history.clear()
            return None
        x, y = palm_center(hand)
        self._history.append((now, x, y))
        while self._history and now - self._history[0][0] > self.window:
            self._history.popleft()
        if now < self._cooldown_until or len(self._history) < 3:
            return None

        _, x0, y0 = self._history[0]
        dx, dy = x - x0, y - y0
        direction = None
        if abs(dx) >= self.min_distance and abs(dx) > 2 * abs(dy):
            direction = "right" if dx > 0 else "left"
        elif abs(dy) >= self.min_distance and abs(dy) > 2 * abs(dx):
            direction = "down" if dy > 0 else "up"

        if direction is not None:
            self._history.clear()
            self._cooldown_until = now + self.cooldown
        return direction

    def reset(self):
        self._history.clear()
        self._cooldown_until = 0.0


# --- XOAY ẢNH BẰNG 2 TAY ---
def two_hand_angle(hand_a, hand_b, tip_id=8):
    """Góc (độ, -180..180) của đường nối đầu ngón trỏ tay A -> tay B, tính trên
    pixel. Khi 2 tay xoay quanh nhau (như vặn vô-lăng) góc này đổi; dùng
    angle_delta() giữa 2 frame để biết xoay bao nhiêu độ."""
    ax, ay = hand_a["pixels"][tip_id]
    bx, by = hand_b["pixels"][tip_id]
    return math.degrees(math.atan2(by - ay, bx - ax))


def angle_delta(new_angle, old_angle):
    """Hiệu 2 góc (độ) đã xử lý vòng -180/180 (vd từ 179 sang -179 là +2, không
    phải -358)."""
    d = new_angle - old_angle
    while d > 180:
        d -= 360
    while d < -180:
        d += 360
    return d


# --- Demo chạy thử trực tiếp ---
if __name__ == "__main__":
    tracker = HandTracker(model_path="hand_landmarker.task")
    cap = cv2.VideoCapture(0)
    zone = SterileZone()
    swipe = SwipeDetector()
    lock = HoldToggle(target_gesture="Open palm", hold_time=2.0)
    locked = False
    last_swipe_text, last_swipe_time = "", 0.0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)

        hands = tracker.process(frame)
        main_hand = select_primary_hand(hands, "Right") or select_primary_hand(hands, "Left")
        zone.draw(frame, active_hand_inside=(main_hand is None or zone.contains(main_hand)))

        for hand in hands:
            for (x, y) in hand["pixels"]:
                cv2.circle(frame, (x, y), 4, (0, 255, 0), -1)

            gesture = detect_gesture(hand)
            label = f"{hand['type']}: {gesture or '...'}"
            wrist_x, wrist_y = hand["pixels"][WRIST]
            cv2.putText(frame, label, (wrist_x, wrist_y + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Test khóa (giữ Open palm 2 giây), vẩy tay, chỉ cho tay trong vùng vô trùng
        in_zone_hand = main_hand if (main_hand is not None and zone.contains(main_hand)) else None
        g = detect_gesture(in_zone_hand) if in_zone_hand else None
        if lock.update(g):
            locked = not locked
        direction = swipe.update(in_zone_hand if g == "Open palm" else None)
        if direction:
            last_swipe_text, last_swipe_time = f"SWIPE {direction}", time.time()
        cv2.putText(frame, "KHOA" if locked else "MO", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (55, 150, 210), 2)
        cv2.rectangle(frame, (10, 40), (10 + int(150 * lock.progress), 50), (55, 150, 210), -1)
        if time.time() - last_swipe_time < 1.0:
            cv2.putText(frame, last_swipe_text, (10, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (225, 225, 225), 2)

        cv2.imshow("Hand Tracking", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    tracker.close()