"""
selftest_report.py
--------------------
GỘP KẾT QUẢ nhiều phiên tự kiểm tra (self_test.py) thành các bảng mở được bằng Excel,
để đưa thẳng vào báo cáo / slide.

CÁCH DÙNG (trong Terminal của PyCharm, ở thư mục dự án):
    python selftest_report.py            # đọc mọi logs/selftest_*_summary.json
    python selftest_report.py logs_cu    # hoặc chỉ định thư mục khác

TẠO RA 4 FILE trong thư mục đó (mở bằng Excel; nếu Excel hiện chữ lỗi, dùng
Data > From Text/CSV và chọn UTF-8):
  1. bao_cao_phien.csv           : 1 dòng = 1 phiên: điều kiện, độ chính xác chung,
                                   kích hoạt nhầm/phút 3 mức, FPS, thời gian AI, IoT,
                                   và cột toan_ven (file nhật ký có bị sửa không).
  2. bao_cao_cu_chi.csv          : 1 dòng = 1 cử chỉ trong 1 phiên.
  3. bao_cao_theo_dieu_kien.csv  : GỘP các phiên cùng điều kiện -> độ chính xác từng
                                   cử chỉ theo từng điều kiện (bảng chính cho báo cáo:
                                   "ánh sáng/khoảng cách/găng tay ảnh hưởng thế nào").
  4. ma_tran_nham_lan.csv        : ma trận nhầm lẫn gộp tất cả các phiên (hàng = cử chỉ
                                   được yêu cầu, cột = phần mềm nhận thành gì).

CHỈ GỘP CÁC PHIÊN CÓ FILE NHẬT KÝ TOÀN VẸN; phiên có file bị sửa vẫn được liệt kê ở
bảng 1 (toan_ven = KHONG) nhưng KHÔNG được tính vào bảng 3 và 4.
"""

import csv
import glob
import json
import os
import sys
from collections import defaultdict, OrderedDict

from self_test import verify_csv, wilson_interval

CONDITION_KEYS = ["anh_sang", "khoang_cach_cm", "gang_tay", "nguoi_di_ngang"]


def pct(x):
    return "" if x is None else round(x * 100, 1)


def get(d, *keys, default=""):
    for k in keys:
        if not isinstance(d, dict) or k not in d or d[k] is None:
            return default
        d = d[k]
    return d


def load_sessions(folder):
    sessions = []
    for path in sorted(glob.glob(os.path.join(folder, "selftest_*_summary.json"))):
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        csv_path = os.path.join(folder, s.get("csv_file", ""))
        ok = os.path.exists(csv_path) and verify_csv(csv_path)[0]
        s["_intact"] = ok
        s["_file"] = os.path.basename(path)
        sessions.append(s)
    return sessions


def write_csv(path, header, rows):
    # utf-8-sig để Excel trên Windows tự nhận đúng bảng mã
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  -> {path} ({len(rows)} dong)")


def main(folder="logs"):
    sessions = load_sessions(folder)
    if not sessions:
        print(f"Khong tim thay file selftest_*_summary.json trong thu muc '{folder}'.")
        return
    print(f"Doc {len(sessions)} phien tu '{folder}':")

    # ---------- 1. bảng phiên ----------
    rows = []
    for s in sessions:
        c = s.get("conditions", {})
        rows.append([s["_file"], s.get("participant_id", ""), *[c.get(k, "") for k in CONDITION_KEYS],
                     s.get("condition_note", ""), "CO" if s["_intact"] else "KHONG",
                     "CO" if s.get("finished") else "KHONG", s.get("trials_valid", ""),
                     pct(s.get("overall_accuracy")), pct(get(s, "overall_accuracy_ci95")[0] if get(s, "overall_accuracy_ci95") else None),
                     pct(get(s, "overall_accuracy_ci95")[1] if get(s, "overall_accuracy_ci95") else None),
                     get(s, "system_latency_ms_all", "mean"), get(s, "system_latency_ms_all", "p95"),
                     s.get("other_commands_during_trials", ""),
                     get(s, "rest_false_triggers", "raw", "per_min"),
                     get(s, "rest_false_triggers", "protected", "per_min"),
                     get(s, "rest_false_triggers", "context", "per_min"),
                     get(s, "performance", "fps_average"), get(s, "performance", "ai_ms", "mean"),
                     get(s, "performance", "ai_ms", "p95"), get(s, "performance", "frame_ms", "p95"),
                     pct(get(s, "iot", "success_rate", default=None)), get(s, "iot", "latency_ms_ok", "mean"),
                     get(s, "iot", "latency_ms_ok", "p95")])
    write_csv(os.path.join(folder, "bao_cao_phien.csv"),
              ["file", "nguoi_thu", *CONDITION_KEYS, "ghi_chu", "toan_ven", "hoan_thanh", "so_luot",
               "do_chinh_xac_%", "KTC95_thap_%", "KTC95_cao_%", "tre_he_thong_TB_ms", "tre_he_thong_P95_ms",
               "lenh_nham_trong_luot", "nham_per_phut_KHONG_chong", "nham_per_phut_CO_chong",
               "nham_per_phut_NGU_CANH", "FPS_TB", "AI_ms_TB", "AI_ms_P95", "xu_ly_khung_ms_P95",
               "IoT_thanh_cong_%", "IoT_tre_TB_ms", "IoT_tre_P95_ms"], rows)

    # ---------- 2. bảng cử chỉ từng phiên ----------
    rows = []
    for s in sessions:
        c = s.get("conditions", {})
        for g, d in s.get("per_gesture", {}).items():
            if not d.get("n"):
                continue
            ci = d.get("accuracy_ci95") or [None, None]
            rows.append([s["_file"], s.get("participant_id", ""), *[c.get(k, "") for k in CONDITION_KEYS],
                         g, d["n"], d["ok"], d["miss"], pct(d["accuracy"]), pct(ci[0]), pct(ci[1]),
                         get(d, "system_latency_ms", "mean"), get(d, "system_latency_ms", "p95"),
                         get(d, "response_s", "mean"), d.get("hand_visible_pct_mean", ""),
                         d.get("other_commands", "")])
    write_csv(os.path.join(folder, "bao_cao_cu_chi.csv"),
              ["file", "nguoi_thu", *CONDITION_KEYS, "cu_chi", "so_luot", "dung", "bo_sot", "do_chinh_xac_%",
               "KTC95_thap_%", "KTC95_cao_%", "tre_he_thong_TB_ms", "tre_he_thong_P95_ms",
               "phan_hoi_TB_s", "thay_tay_%", "lenh_khac_trong_luot"], rows)

    # ---------- 3. gộp theo điều kiện (chỉ phiên toàn vẹn) ----------
    pooled = OrderedDict()
    for s in sessions:
        if not s["_intact"]:
            continue
        c = s.get("conditions", {})
        key = tuple(c.get(k, "") for k in CONDITION_KEYS)
        for g, d in s.get("per_gesture", {}).items():
            slot = pooled.setdefault(key, OrderedDict()).setdefault(g, {"n": 0, "ok": 0, "sessions": 0})
            slot["n"] += d.get("n", 0)
            slot["ok"] += d.get("ok", 0)
            slot["sessions"] += 1
    rows = []
    for key, gestures in pooled.items():
        tot_n = sum(v["n"] for v in gestures.values())
        tot_ok = sum(v["ok"] for v in gestures.values())
        for g, v in list(gestures.items()) + [("TAT_CA", {"n": tot_n, "ok": tot_ok, "sessions": ""})]:
            if not v["n"]:
                continue
            lo, hi = wilson_interval(v["ok"], v["n"])
            rows.append([*key, g, v["sessions"], v["n"], v["ok"], pct(v["ok"] / v["n"]), pct(lo), pct(hi)])
    write_csv(os.path.join(folder, "bao_cao_theo_dieu_kien.csv"),
              [*CONDITION_KEYS, "cu_chi", "so_phien", "so_luot", "dung", "do_chinh_xac_%",
               "KTC95_thap_%", "KTC95_cao_%"], rows)

    # ---------- 4. ma trận nhầm lẫn gộp ----------
    matrix = defaultdict(lambda: defaultdict(int))
    columns = []
    for s in sessions:
        if not s["_intact"]:
            continue
        for target, detected in s.get("confusion", {}).items():
            for label, n in detected.items():
                matrix[target][label] += n
                if label not in columns:
                    columns.append(label)
    order = [g for g in ["POINT", "PINCH", "SNAP", "FIST", "OPEN_PALM", "SWIPE_LEFT", "SWIPE_RIGHT", "ZOOM"]]
    columns = [g for g in order if g in columns] + sorted(c for c in columns if c not in order)
    rows = [[t, *[matrix[t].get(col, 0) for col in columns]] for t in order if t in matrix]
    write_csv(os.path.join(folder, "ma_tran_nham_lan.csv"), ["yeu_cau \\ nhan_thanh", *columns], rows)

    bad = [s["_file"] for s in sessions if not s["_intact"]]
    if bad:
        print("CANH BAO: cac phien co file nhat ky KHONG toan ven (khong duoc gop):", ", ".join(bad))
    print("Xong. Mo cac file .csv bang Excel de ve bieu do.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "logs")
