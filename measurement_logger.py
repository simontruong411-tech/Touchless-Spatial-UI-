"""
measurement_logger.py  (BẢN 2 — theo quy trình phẫu thuật + chuẩn ghi dữ liệu nghiên cứu)
--------------------
Ghi lại MỌI sự kiện thao tác của bác sĩ kèm thời gian, để vừa (1) làm số liệu
đánh giá đề tài (Response Time, số lần kích hoạt nhầm, độ trễ lệnh IoT...), vừa
(2) giữ một NHẬT KÝ CA MỔ có cấu trúc theo các giai đoạn của quy trình phẫu
thuật an toàn (Bảng kiểm an toàn phẫu thuật WHO: SIGN IN -> TIME OUT -> MỔ ->
SIGN OUT).

BẢN NÀY GIỮ NGUYÊN CÁCH GỌI CŨ:   logger.log_event("MENU_MAIN", "OPEN_ANH")
và THÊM (không bắt buộc dùng):
    logger = MeasurementLogger(participant_id="P01", scenario="demo",
                               conditions={"anh_sang": "den mo", "gang_tay": "co"})
    logger.log_event("MENU_MAIN", "GOI_Y_TA", latency_ms=85)   # độ trễ lệnh IoT
    logger.set_phase("TIME_OUT")           # đổi giai đoạn quy trình (tự ghi thời lượng)
    logger.start_task("MO_ANH_VA_DO")      # đo thời gian hoàn thành 1 nhiệm vụ thí nghiệm
    logger.end_task(success=True)
    logger.close()                         # ghi file tóm tắt (meta) + in kết quả

CÁC FILE TẠO RA (trong thư mục logs/):
    session_<giờ>.csv        : nhật ký sự kiện, 1 dòng = 1 sự kiện
    session_<giờ>_meta.json  : thông tin phiên (người thử, kịch bản, điều kiện thí
                               nghiệm, phần mềm) + TÓM TẮT số liệu (đếm sự kiện,
                               thời lượng từng giai đoạn, thống kê nhiệm vụ, độ trễ)

CỘT TRONG FILE CSV:
    timestamp_real         : giờ thật KÈM múi giờ (ISO 8601), để đối chiếu video/ghi chú
    seconds_since_start    : giây kể từ lúc bắt đầu phiên (mốc 0)
    delta_since_last_event : giây kể từ sự kiện TRƯỚC (Response Time thô giữa 2 thao tác)
    phase                  : giai đoạn quy trình lúc đó (SETUP/SIGN_IN/TIME_OUT/SURGERY/
                             SIGN_OUT/COMPLETE) -> lọc/so sánh số liệu theo giai đoạn
    mode                   : màn hình đang mở
    category               : nhóm sự kiện (NAVIGATION/IMAGE/MODEL/DEVICE/ALERT/SAFETY/
                             WORKFLOW/OBSERVER/SESSION) -> thống kê nhanh theo nhóm
    event                  : tên sự kiện
    detail                 : ghi chú thêm (vd latency_ms=85, tên nhiệm vụ, thứ tự ảnh)
    row_hash               : mã băm nối chuỗi (xem "TOÀN VẸN DỮ LIỆU" bên dưới)

NGUYÊN TẮC DỮ LIỆU (đúng thông lệ nghiên cứu y tế):
  - KHÔNG ghi bất kỳ thông tin định danh bệnh nhân nào (tên, ngày sinh, mã bệnh
    án, tên file ảnh có thể chứa tên bệnh nhân). Chỉ dùng mã ẩn danh của người
    thử (participant_id) và mã ca giả (case id) — chỉ thử với dữ liệu mô phỏng.
  - Nhật ký chỉ GHI THÊM (mở bằng chế độ "w" một lần cho mỗi phiên, mỗi sự kiện
    được flush ngay xuống đĩa, không sửa dòng cũ).
  - TOÀN VẸN DỮ LIỆU: mỗi dòng có row_hash = SHA-256(hash dòng trước + nội dung dòng
    này). Sửa/xóa/chèn 1 dòng bất kỳ sẽ làm hỏng chuỗi -> phát hiện được bằng:
        python measurement_logger.py logs/session_xxx.csv
    (lệnh này cũng in luôn bản tóm tắt số liệu từ file CSV).

LƯU Ý: delta_since_last_event đo khoảng cách giữa 2 LẦN GỌI log_event() bất kỳ.
Muốn đo thời gian hoàn thành một nhiệm vụ có chủ đích, dùng start_task()/end_task()
— kết quả (duration_s, success) ghi sẵn, không phải tự trừ tay.
"""

import csv
import hashlib
import json
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime

SOFTWARE_VERSION = "touchless-or-spatial-ui 2.0"
STANDARD_REFERENCE = "WHO Surgical Safety Checklist (Sign In / Time Out / Sign Out) - mo phong"

COLUMNS = ["timestamp_real", "seconds_since_start", "delta_since_last_event",
           "phase", "mode", "category", "event", "detail", "row_hash"]

PHASES = ["SETUP", "SIGN_IN", "TIME_OUT", "SURGERY", "SIGN_OUT", "COMPLETE"]


def categorize(event):
    """Suy ra nhóm sự kiện từ tên sự kiện (quy ước đặt tên trong chương trình chính)."""
    e = event.upper()
    if e.startswith("SESSION_"):
        return "SESSION"
    if e.startswith("PHASE_"):
        return "WORKFLOW"
    if e.startswith("WF_"):
        return "WORKFLOW"
    if e.startswith(("FALSE_TRIGGER", "MISSED_GESTURE", "TASK_")):
        return "OBSERVER"
    if e.startswith(("LOCK", "UNLOCK", "HAND_OUT_OF_ZONE")):
        return "SAFETY"
    if e in ("GOI_Y_TA", "KHAN_CAP"):
        return "ALERT"
    if e.startswith("DEN_"):
        return "DEVICE"
    if e.startswith("IMG_"):
        return "IMAGE"
    if e.startswith("MODEL_"):
        return "MODEL"
    if e.startswith(("OPEN_", "BACK_", "SNAP_", "FIST_")):
        return "NAVIGATION"
    return "OTHER"


def _row_hash(prev_hash, fields):
    payload = "|".join(str(x) for x in fields)
    return hashlib.sha256((prev_hash + "|" + payload).encode("utf-8")).hexdigest()[:12]


class MeasurementLogger:
    def __init__(self, log_dir="logs", participant_id="", scenario="", conditions=None):
        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = f"session_{stamp}"
        self.path = os.path.join(log_dir, f"{self.session_id}.csv")
        self.meta_path = os.path.join(log_dir, f"{self.session_id}_meta.json")

        self.participant_id = participant_id
        self.scenario = scenario
        self.conditions = dict(conditions or {})

        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(COLUMNS)

        # time.perf_counter() chính xác hơn time.time() cho việc ĐO KHOẢNG CÁCH
        # thời gian (không bị đồng hồ hệ thống tự chỉnh làm lệch).
        self._start_time = time.perf_counter()
        self._started_real = datetime.now().astimezone()
        self._last_event_time = None
        self._prev_hash = "GENESIS"
        self._closed = False

        # Thống kê tích lũy (để tóm tắt khi đóng phiên)
        self.phase = "SETUP"
        self._phase_start = self._start_time
        self._phase_durations = {p: 0.0 for p in PHASES}
        self._counts = Counter()
        self._category_counts = Counter()
        self._latencies = {}              # event -> [ms, ...]
        self._tasks = []                  # [{"name","duration_s","success"}]
        self._open_task = None            # (name, t0)
        self._task_counter = 0
        self.case_ids = []

        print(f"[MeasurementLogger] Dang ghi log vao: {self.path}")
        self.log_event("SESSION", "SESSION_START",
                       detail=f"participant={participant_id};scenario={scenario}")

    # -- Ghi sự kiện -----------------------------------------------------------
    def log_event(self, mode, event, detail="", latency_ms=None):
        if self._closed:
            return
        now = time.perf_counter()
        seconds_since_start = now - self._start_time
        delta = (now - self._last_event_time) if self._last_event_time is not None else 0.0
        self._last_event_time = now

        if latency_ms is not None:
            detail = (detail + ";" if detail else "") + f"latency_ms={latency_ms:.0f}"
            self._latencies.setdefault(event, []).append(float(latency_ms))

        category = categorize(event)
        fields = [
            datetime.now().astimezone().isoformat(timespec="milliseconds"),
            f"{seconds_since_start:.3f}",
            f"{delta:.3f}",
            self.phase, mode, category, event, detail,
        ]
        row_hash = _row_hash(self._prev_hash, fields)
        self._prev_hash = row_hash
        self._writer.writerow(fields + [row_hash])
        # flush ngay xuống đĩa sau MỖI sự kiện, phòng trường hợp chương trình bị
        # tắt đột ngột (crash, rút camera...) vẫn không mất log đã ghi.
        self._file.flush()

        self._counts[event] += 1
        self._category_counts[category] += 1

    # -- Giai đoạn quy trình -------------------------------------------------------
    def set_phase(self, new_phase, mode="WORKFLOW"):
        """Chuyển sang giai đoạn mới của quy trình; tự cộng thời lượng giai đoạn cũ
        và ghi sự kiện PHASE_CHANGE (có ghi thời lượng giai đoạn vừa xong)."""
        if new_phase == self.phase or self._closed:
            return
        now = time.perf_counter()
        old = self.phase
        spent = now - self._phase_start
        self._phase_durations[old] = self._phase_durations.get(old, 0.0) + spent
        self._phase_start = now
        self.log_event(mode, "PHASE_CHANGE", detail=f"{old}->{new_phase};{old}_s={spent:.1f}")
        self.phase = new_phase

    # -- Nhiệm vụ thí nghiệm (đo thời gian hoàn thành) ---------------------------------
    def start_task(self, name=None):
        if self._open_task is not None:      # nhiệm vụ trước chưa kết thúc -> đóng là thất bại
            self.end_task(success=False, note="auto_closed")
        self._task_counter += 1
        name = name or f"TASK_{self._task_counter}"
        self._open_task = (name, time.perf_counter())
        self.log_event("OBSERVER", "TASK_START", detail=name)
        return name

    def end_task(self, success=True, note=""):
        if self._open_task is None:
            return None
        name, t0 = self._open_task
        self._open_task = None
        duration = time.perf_counter() - t0
        self._tasks.append({"name": name, "duration_s": round(duration, 3), "success": bool(success)})
        detail = f"{name};duration_s={duration:.2f};success={int(success)}" + (f";{note}" if note else "")
        self.log_event("OBSERVER", "TASK_END", detail=detail)
        return duration

    # -- Tóm tắt -------------------------------------------------------------------
    @staticmethod
    def _stats(values):
        if not values:
            return {"n": 0}
        return {"n": len(values), "mean": round(statistics.mean(values), 2),
                "median": round(statistics.median(values), 2),
                "min": round(min(values), 2), "max": round(max(values), 2)}

    def summary(self):
        now = time.perf_counter()
        durations = dict(self._phase_durations)
        durations[self.phase] = durations.get(self.phase, 0.0) + (now - self._phase_start)
        task_times = [t["duration_s"] for t in self._tasks if t["success"]]
        minutes = max((now - self._start_time) / 60.0, 1e-9)
        return {
            "duration_s": round(now - self._start_time, 1),
            "events": sum(self._counts.values()),
            "events_by_category": dict(self._category_counts),
            "events_by_name": dict(self._counts),
            "phase_seconds": {p: round(s, 1) for p, s in durations.items() if s > 0.05},
            "tasks": {"n": len(self._tasks),
                      "success_rate": (round(sum(t["success"] for t in self._tasks) / len(self._tasks), 3)
                                       if self._tasks else None),
                      "completion_time_s": self._stats(task_times)},
            "iot_latency_ms": {ev: self._stats(v) for ev, v in self._latencies.items()},
            "false_triggers": self._counts.get("FALSE_TRIGGER", 0),
            "false_triggers_per_min": round(self._counts.get("FALSE_TRIGGER", 0) / minutes, 3),
            "missed_gestures": self._counts.get("MISSED_GESTURE", 0),
            "hand_out_of_zone_events": self._counts.get("HAND_OUT_OF_ZONE", 0),
            "locks": self._counts.get("LOCK", 0),
        }

    def close(self):
        if self._closed:
            return
        self.log_event("SESSION", "SESSION_END")
        summary = self.summary()
        self._closed = True
        self._file.close()

        meta = {
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "scenario": self.scenario,
            "conditions": self.conditions,
            "software": SOFTWARE_VERSION,
            "standard_reference": STANDARD_REFERENCE,
            "started_at": self._started_real.isoformat(timespec="seconds"),
            "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "case_ids": self.case_ids,
            "data_note": "Khong chua thong tin dinh danh benh nhan; chi dung du lieu mo phong.",
            "csv_file": os.path.basename(self.path),
            "final_row_hash": self._prev_hash,
            "summary": summary,
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"[MeasurementLogger] Da dong file log: {self.path}")
        print(f"[MeasurementLogger] Tom tat phien: {self.meta_path}")


# =====================================================================
# KIỂM TRA TOÀN VẸN + TÓM TẮT TỪ FILE CSV CÓ SẴN
# =====================================================================
def verify_log(path):
    """Tính lại chuỗi băm của file CSV. Trả về (ok, dòng_lỗi_đầu_tiên_hoặc_None, số_dòng)."""
    prev = "GENESIS"
    n = 0
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != COLUMNS:
            return False, 1, 0
        for i, row in enumerate(reader, start=2):
            if len(row) != len(COLUMNS):
                return False, i, n
            expected = _row_hash(prev, row[:-1])
            if expected != row[-1]:
                return False, i, n
            prev = row[-1]
            n += 1
    return True, None, n


def summarize_csv(path):
    """Tóm tắt nhanh từ file CSV (đếm sự kiện, nhiệm vụ, độ trễ) — dùng khi chỉ
    còn file CSV mà không có file meta."""
    counts, cats, lat, tasks = Counter(), Counter(), {}, []
    phase_s = {}
    with open(path, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            counts[row["event"]] += 1
            cats[row["category"]] += 1
            for part in row["detail"].split(";"):
                if part.startswith("latency_ms="):
                    lat.setdefault(row["event"], []).append(float(part.split("=")[1]))
            if row["event"] == "TASK_END":
                d = dict(p.split("=", 1) for p in row["detail"].split(";") if "=" in p)
                tasks.append((float(d.get("duration_s", 0)), d.get("success") == "1"))
            if row["event"] == "PHASE_CHANGE":
                d = row["detail"].split(";")
                if len(d) >= 2 and "_s=" in d[1]:
                    name, val = d[1].split("_s=")
                    phase_s[name] = phase_s.get(name, 0.0) + float(val)
    return {"events_by_category": dict(cats), "events_by_name": dict(counts),
            "phase_seconds": phase_s,
            "tasks": {"n": len(tasks),
                      "success_rate": (sum(1 for _, s in tasks if s) / len(tasks)) if tasks else None,
                      "completion_time_s": MeasurementLogger._stats([t for t, s in tasks if s])},
            "iot_latency_ms": {k: MeasurementLogger._stats(v) for k, v in lat.items()}}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Cach dung: python measurement_logger.py logs/session_xxx.csv")
        sys.exit(0)
    csv_path = sys.argv[1]
    ok, bad_line, n = verify_log(csv_path)
    if ok:
        print(f"[OK] Nhat ky toan ven: {n} su kien, chuoi bam khop.")
    else:
        print(f"[CANH BAO] Nhat ky BI SUA/HONG tu dong {bad_line} (da doc {n} dong hop le).")
    print(json.dumps(summarize_csv(csv_path), ensure_ascii=False, indent=2))
