"""
swipe_replay.py
---------------
PHÁT LẠI các cú vẩy tay ĐÃ GHI THẬT qua bộ nhận diện swipe.py với tham số khác nhau, để chọn tham số
bằng DỮ LIỆU THẬT thay vì mô phỏng tự dựng.

VÌ SAO CẦN: CSV của swipe_test/self_test chỉ có bản tóm tắt mỗi lượt, nên khi một lượt hỏng ta chỉ
ĐOÁN nguyên nhân (cú lấy đà nhanh hơn hay chậm hơn cú vẩy thật?). File vết (_trace.csv) do
swipe_test.py ghi giữ lại từng khung hình, nên ta chạy lại ĐÚNG chuỗi chuyển động đó với "chờ xác
nhận" 0 s, 0,15 s, 0,3 s... và đếm xem cấu hình nào cho nhiều lượt đúng nhất, ít vẩy nhầm khi nghỉ nhất.

CÁCH DÙNG
  python swipe_replay.py logs/swipetest_XXXX_trace.csv
        Quét confirm_hold_s = 0, 0.15, 0.3, 0.45 (mặc định). Gộp nhiều file: liệt kê nhiều đường dẫn.
  python swipe_replay.py a_trace.csv b_trace.csv --sweep confirm_hold_s=0,0.2,0.3 --sweep min_distance_hs=1.8,2.0,2.2
        Quét lưới tham số (tên tham số = tên đối số của SwipeDetector trong swipe.py).
  python swipe_replay.py a_trace.csv --detail
        In thêm từng lượt: kết quả lúc ghi, kết quả phát lại, và cấu hình nào khác nhau.

ĐỌC KẾT QUẢ CHO ĐÚNG (trung thực):
  * Dòng "KIEM TRA TRUNG THUC": phát lại bằng đúng cấu hình lúc ghi PHẢI cho ra kết quả giống lúc ghi.
    Nếu lệch nhiều thì phát lại không đáng tin (swipe.py đã đổi sau khi ghi, hoặc file vết hỏng).
  * Số lượt ít (20 lượt/phiên) nên mọi khác biệt vài lượt đều NẰM TRONG khoảng nhiễu. Chỉ tin khi
    có nhiều phiên gộp lại và khác biệt rõ.
  * TÍNH TRÊN CÙNG DỮ LIỆU ĐÃ DÙNG ĐỂ CHỌN tham số thì số đẹp hơn thực tế (học thuộc lòng). Muốn chắc
    thì chọn tham số bằng phiên A rồi ĐO LẠI bằng phiên B mới.
  * Phát lại không tái tạo được việc người thử sẽ vẩy KHÁC đi khi biết phần mềm chờ xác nhận.
  * Cột "tre them" là độ trễ tăng thêm của lệnh so với cấu hình đầu bảng (cùng lượt, đều đúng).

File vết chỉ chứa tọa độ tay (không hình ảnh, không thông tin cá nhân), có chuỗi băm; chương trình
kiểm tra chuỗi băm trước khi dùng.
"""

import csv
import hashlib
import itertools
import math
import sys
from types import SimpleNamespace as NS

from swipe import SwipeDetector, SWIPE_CONFIRM_HOLD

DEFAULT_SWEEP = {"confirm_hold_s": [0.0, 0.15, 0.3, 0.45]}
DEFAULT_TIMEOUT_S = 4.0


# ============================ TIỆN ÍCH ============================
def wilson_ci(ok, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def make_hand(cx, cy, size):
    """Dựng lại tay giả từ (tâm x, tâm y, kích thước). SwipeDetector chỉ dùng palm_center (trung bình
    điểm 0,5,9,13,17) và hand_apparent_size (khoảng cổ tay-gốc ngón giữa, điểm 0 và 9). Đặt điểm
    0 và 9 lệch đối xứng quanh tâm, các điểm còn lại đúng tại tâm -> hai đại lượng này khớp CHÍNH XÁC."""
    a = size / 2.0
    pts = [NS(x=cx, y=cy, z=0.0) for _ in range(21)]
    pts[0] = NS(x=cx, y=cy + a, z=0.0)
    pts[9] = NS(x=cx, y=cy - a, z=0.0)
    return {"type": "Left", "landmarks": pts, "world_landmarks": pts, "pixels": []}


def parse_kv(text):
    out = {}
    for part in (text or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


# ============================ ĐỌC FILE VẾT ============================
def load_trace(path):
    """Đọc 1 file vết. Trả về (meta, trials, rest). Kiểm tra chuỗi băm; nếu sai thì báo và dừng."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    prev = "0" * 12
    for i, r in enumerate(rows, start=2):
        text = prev + "|" + "|".join(str(r[k]) for k in fields if k != "row_hash")
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        if h != r["row_hash"]:
            sys.exit(f"[LOI] {path}: chuoi bam sai o dong {i} - file da bi sua hoac hong, khong dung de ket luan.")
        prev = h
    meta, trials, rest = {}, {}, []
    order = []
    for r in rows:
        if r["section"] == "SESSION":
            meta = parse_kv(r["detail"])
            continue
        frame = (float(r["t"]), int(r["present"]), int(r["fed"]),
                 float(r["cx"]) if r["cx"] != "" else 0.0, float(r["cy"]) if r["cy"] != "" else 0.0,
                 float(r["size"]) if r["size"] != "" else 0.0, int(r["palm_open"]), r["cmd"])
        if r["section"] == "REST":
            rest.append(frame)
        else:
            key = int(r["trial"])
            if key not in trials:
                trials[key] = {"trial": key, "target": r["target"], "frames": []}
                order.append(key)
            trials[key]["frames"].append(frame)
    return meta, [trials[k] for k in order], rest


# ============================ PHÁT LẠI ============================
def run_frames(frames, kwargs):
    """Chạy bộ nhận diện qua các khung đã ghi; trả về danh sách (t, lệnh)."""
    det = SwipeDetector(**kwargs)
    cmds = []
    for (t, present, fed, cx, cy, size, palm, _rec) in frames:
        hand = make_hand(cx, cy, size) if (present and fed) else None
        cmd = det.update(hand, now=t, palm_open=bool(palm))
        if cmd:
            cmds.append((t, cmd))
    return cmds


def deadline_of(frames, timeout_s):
    """Thời điểm khung hình ĐẦU TIÊN có t >= timeout. Trong swipe_test, khung đó vẫn còn được nhận lệnh
    (kiểm tra lệnh trước kiểm tra hết giờ); lệnh ra SAU khung đó thì lượt đã kết thúc là BO SOT."""
    for f in frames:
        if f[0] >= timeout_s:
            return f[0]
    return float("inf")


def score_first(cmds, target, deadline):
    """Chấm giống swipe_test: chỉ tính lệnh ĐẦU TIÊN trong lượt."""
    if not cmds or cmds[0][0] > deadline + 1e-9:
        return "BO SOT", None, None
    t, cmd = cmds[0]
    return ("DUNG" if cmd == target else "SAI HUONG"), cmd, t


def recorded_cmds(frames):
    return [(f[0], f[7]) for f in frames if f[7]]


def baseline_kwargs(meta):
    hold = meta.get("confirm_hold_s")
    return {"confirm_hold_s": float(hold) if hold not in (None, "") else SWIPE_CONFIRM_HOLD}


def recorded_value(name, base):
    """Giá trị tham số `name` lúc ghi: lấy từ meta nếu có (confirm_hold_s), không thì mặc định của swipe.py."""
    return base[name] if name in base else getattr(SwipeDetector(), name)


def evaluate(trials, rests, kwargs, timeout_s):
    res = []
    for tr in trials:
        cmds = run_frames(tr["frames"], kwargs)
        r, d, t = score_first(cmds, tr["target"], deadline_of(tr["frames"], timeout_s))
        res.append({"trial": tr["trial"], "target": tr["target"], "result": r, "detected": d, "t": t,
                    "extra": max(0, len(cmds) - 1)})
    rest_cmds, rest_dur = 0, 0.0
    for rf in rests:
        if rf:
            rest_cmds += len(run_frames(rf, kwargs))
            rest_dur += rf[-1][0] - rf[0][0]
    return res, rest_cmds, rest_dur


def fmt_cfg(cfg):
    return ", ".join(f"{k}={v:g}" if isinstance(v, (int, float)) else f"{k}={v}" for k, v in cfg.items())


def main():
    sweeps = {}
    detail = "--detail" in sys.argv
    argv = sys.argv[1:]
    i = 0
    paths = []
    while i < len(argv):
        a = argv[i]
        if a == "--sweep" and i + 1 < len(argv):
            name, vals = argv[i + 1].split("=", 1)
            if not hasattr(SwipeDetector(), name):
                sys.exit(f"[LOI] SwipeDetector khong co tham so '{name}' (xem __init__ trong swipe.py)")
            sweeps[name] = [float(v) for v in vals.split(",")]
            i += 2
            continue
        if a.startswith("--"):
            i += 1
            continue
        paths.append(a)
        i += 1
    if not paths:
        print(__doc__)
        return
    if not sweeps:
        sweeps = dict(DEFAULT_SWEEP)

    trials, rests, metas = [], [], []
    for p in paths:
        meta, tr, rest = load_trace(p)
        metas.append(meta)
        for t in tr:
            t = dict(t)
            t["trial"] = f"{len(metas)}:{t['trial']}" if len(paths) > 1 else t["trial"]
            trials.append(t)
        if rest:
            rests.append(rest)
    timeout_s = float(metas[0].get("timeout_s", DEFAULT_TIMEOUT_S))
    base = baseline_kwargs(metas[0])
    holds = {m.get("confirm_hold_s") for m in metas}
    if len(holds) > 1:
        print(f"[CHU Y] cac file ghi voi confirm_hold_s khac nhau: {sorted(h for h in holds if h)}; "
              "dong 'luc ghi' chi dung cho file dau.")

    # --- Kiểm tra trung thực: phát lại bằng cấu hình lúc ghi có giống kết quả lúc ghi không? ---
    rec = {tr["trial"]: score_first(recorded_cmds(tr["frames"]), tr["target"],
                                    deadline_of(tr["frames"], timeout_s))[0] for tr in trials}
    rep, _, _ = evaluate(trials, [], base, timeout_s)
    same = sum(1 for r in rep if r["result"] == rec[r["trial"]])
    print(f"KIEM TRA TRUNG THUC: phat lai bang cau hinh luc ghi ({fmt_cfg(base)}) khop {same}/{len(rep)} luot "
          f"voi ket qua luc ghi.")
    if same < len(rep):
        diff = [str(r["trial"]) for r in rep if r["result"] != rec[r["trial"]]]
        print(f"   Luot lech: {', '.join(diff)}  -> swipe.py da doi sau khi ghi? Nho tham so khac mac dinh khong?")

    # --- Quét lưới tham số ---
    names = list(sweeps)
    configs = [dict(zip(names, combo)) for combo in itertools.product(*[sweeps[n] for n in names])]
    ref = None
    table = []
    for cfg in configs:
        kw = dict(cfg)
        res, rest_n, rest_dur = evaluate(trials, rests, kw, timeout_s)
        row = {"cfg": cfg, "res": res, "rest_n": rest_n, "rest_dur": rest_dur}
        if ref is None:
            ref = row
        table.append(row)

    w = max(36, max(len(fmt_cfg(r['cfg'])) for r in table))
    print()
    print(f"{'cau hinh':{w}s} | TRAI dung | PHAI dung | tong (CI95)         | sai huong | bo sot | nghi (lenh/phut) | tre them")
    print("-" * (w + 104))
    for row in table:
        res = row["res"]
        out = {}
        for d in ("left", "right"):
            rs = [r for r in res if r["target"] == d]
            out[d] = (sum(1 for r in rs if r["result"] == "DUNG"), len(rs))
        ok = out["left"][0] + out["right"][0]
        n = out["left"][1] + out["right"][1]
        lo, hi = wilson_ci(ok, n)
        wrong = sum(1 for r in res if r["result"] == "SAI HUONG")
        miss = sum(1 for r in res if r["result"] == "BO SOT")
        rest = "-" if not row["rest_dur"] else f"{row['rest_n']} / {row['rest_dur']:.0f}s ({60 * row['rest_n'] / row['rest_dur']:.1f})"
        # độ trễ thêm so với dòng đầu bảng: chỉ lượt ĐÚNG ở cả hai
        dts = []
        for a, b in zip(ref["res"], res):
            if a["result"] == "DUNG" and b["result"] == "DUNG":
                dts.append(b["t"] - a["t"])
        late = f"{sum(dts) / len(dts):+.2f}s" if dts else "-"
        mark = "  <-- luc ghi" if all(abs(v - recorded_value(k, base)) < 1e-9 for k, v in row["cfg"].items()) else ""
        print(f"{fmt_cfg(row['cfg']):{w}s} | {out['left'][0]:>4d}/{out['left'][1]:<4d} | {out['right'][0]:>4d}/{out['right'][1]:<4d} | "
              f"{ok:>3d}/{n:<3d} ({100 * lo:3.0f}-{100 * hi:3.0f}%)  | {wrong:^9d} | {miss:^6d} | {rest:^16s} | {late:>7s}{mark}")

    if detail:
        print("\nTUNG LUOT  (luc ghi -> phat lai theo tung cau hinh; * = khac luc ghi)")
        head = "lượt".ljust(8) + "dich".ljust(6) + "luc ghi".ljust(11) + " ".join(fmt_cfg(r["cfg"])[:24].ljust(26) for r in table)
        print(head)
        for k, tr in enumerate(trials):
            cells = []
            for row in table:
                r = row["res"][k]
                tag = r["result"] + (f"({r['detected']})" if r["detected"] and r["result"] != "DUNG" else "")
                cells.append((tag + ("*" if r["result"] != rec[tr["trial"]] else "")).ljust(26))
            print(str(tr["trial"]).ljust(8) + tr["target"].ljust(6) + rec[tr["trial"]].ljust(11) + " ".join(cells))
    print("\nNHAC LAI: so lieu it, cung du lieu dung de chon tham so -> chi la goi y; hay do lai bang phien moi.")


if __name__ == "__main__":
    main()
