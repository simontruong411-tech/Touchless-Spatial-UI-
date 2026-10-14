"""
upload_tool.py
--------------------
Công cụ TẢI DỮ LIỆU vào hệ thống — dùng CHUỘT/BÀN PHÍM bình thường, KHÔNG
phải touchless. Chạy công cụ này TRƯỚC KHI ca mổ bắt đầu (lúc bác sĩ/trợ lý
còn chưa vô trùng) để chuẩn bị sẵn dữ liệu cho chương trình chính xem bằng
cử chỉ tay trong lúc mổ.

CÓ 2 TAB:
  1) "Anh chan doan"   : tải ảnh (.jpg/.jpeg/.png/.bmp) vào thư mục
                          medical_images/  -> xem ở màn "ANH" (image_viewer.py)
  2) "Mo hinh 3D (.obj)": tải mô hình 3D (.obj) vào thư mục medical_models/
                          -> xem ở màn "XUONG 3D" (model_viewer.py)

VÌ SAO TÁCH RIÊNG THÀNH FILE NÀY: main_spatial_ui_demo.py (chương trình
chính, chạy touchless trong lúc mổ) CHỦ Ý không có nút "tải file" bằng cử
chỉ tay — vì chọn file trên máy tính bắt buộc phải dùng chuột/bàn phím,
đi ngược đúng mục tiêu "không chạm" của đề tài. Việc tải dữ liệu vì vậy phải
xảy ra ở 1 thời điểm KHÁC (trước khi vô trùng), bằng 1 công cụ KHÁC (file
này) — đây là lựa chọn thiết kế có chủ đích, không phải thiếu sót.

CÁCH DÙNG:
    python upload_tool.py
ĐẶT file này CÙNG THƯ MỤC với main_spatial_ui_demo.py để đường dẫn tự đúng.

Trong mỗi tab:
  - Bấm "Chon file..." -> chọn được nhiều file 1 lúc (giữ Ctrl hoặc Shift) ->
    file được COPY vào thư mục tương ứng (file gốc của bạn không bị đụng tới;
    trùng tên thì tự thêm số _1, _2 ...).
  - Danh sách bên dưới hiện các file ĐANG CÓ trong thư mục đó.
  - Chọn 1 file rồi bấm "Xoa file da chon" để gỡ ra khỏi thư mục.

LƯU Ý RIÊNG CHO MÔ HÌNH 3D:
  - model_viewer.py dùng file .obj ĐẦU TIÊN theo thứ tự tên (cũng là dòng đầu
    danh sách, có đánh dấu [DANG DUNG]). Muốn dùng file khác: đổi tên cho nó
    đứng đầu (vd 01_xuongsuon.obj) hoặc xóa các file đứng trước.
  - File .obj phải có ít nhất 50 đỉnh (dòng bắt đầu bằng "v ") mới được nhận.
  - Không có file nào -> chương trình dùng bộ xương MÔ PHỎNG có sẵn (minh họa).
  - Chỉ dùng mô hình từ nguồn công khai, kiểm tra giấy phép; KHÔNG dùng dữ
    liệu bệnh nhân thật.

Không cần cài thêm thư viện gì — tkinter đi kèm sẵn trong Python.
"""

import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

IMAGE_DIR = "medical_images"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")

MODEL_DIR = "medical_models"
MODEL_EXTS = (".obj",)
MIN_OBJ_VERTICES = 50   # khớp với load_obj_points() trong model_viewer.py


def count_obj_vertices(path):
    """Đếm số đỉnh (dòng 'v x y z') trong file .obj để kiểm tra file hợp lệ
    TRƯỚC khi copy vào hệ thống. Trả về -1 nếu không đọc được file."""
    count = 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("v "):
                    count += 1
    except OSError:
        return -1
    return count


class FilePanel:
    """Một tab: tải file vào 1 thư mục + hiện danh sách + xóa file. Dùng chung
    cho cả tab ảnh và tab mô hình 3D, chỉ khác thư mục/đuôi file/lời nhắc."""

    def __init__(self, parent, folder, exts, noun, dialog_filter, extra_hint="", validator=None, mark_first=False):
        self.folder = folder
        self.exts = exts
        self.noun = noun                    # "anh" hoặc "mo hinh" — dùng trong thông báo
        self.dialog_filter = dialog_filter
        self.validator = validator          # hàm kiểm tra file: path -> (ok, lý do)
        self.mark_first = mark_first        # đánh dấu file đầu danh sách là "đang dùng"
        self.files = []                     # tên file thật, cùng thứ tự với Listbox

        os.makedirs(folder, exist_ok=True)

        hint = tk.Label(
            parent,
            text="Cong cu nay dung CHUOT/BAN PHIM binh thuong.\n"
                 "Dung TRUOC khi ca mo bat dau, luc chua vo trung."
                 + (("\n" + extra_hint) if extra_hint else ""),
            fg="#555555", justify="left",
        )
        hint.pack(pady=(10, 5), padx=10, anchor="w")

        tk.Button(parent, text="Chon file...", command=self.choose_files,
                  width=20, height=2).pack(pady=10)

        tk.Label(parent, text=f"File dang co trong thu muc {folder}/:").pack(pady=(10, 0), padx=10, anchor="w")
        self.listbox = tk.Listbox(parent, height=10)
        self.listbox.pack(padx=10, pady=5, fill="both", expand=True)

        tk.Button(parent, text="Xoa file da chon", command=self.delete_selected).pack(pady=(0, 10))

        self.refresh_list()

    def choose_files(self):
        """Mở hộp thoại chọn file (chuẩn của hệ điều hành), cho phép chọn
        nhiều file cùng lúc, rồi copy từng file hợp lệ vào thư mục đích."""
        paths = filedialog.askopenfilenames(
            title=f"Chon {self.noun}",
            filetypes=[self.dialog_filter, ("Tat ca file", "*.*")],
        )
        if not paths:
            return  # người dùng bấm Cancel

        copied, skipped = 0, []
        for src_path in paths:
            filename = os.path.basename(src_path)
            if os.path.splitext(filename)[1].lower() not in self.exts:
                skipped.append(f"{filename} (sai dinh dang)")
                continue
            if self.validator is not None:
                ok, reason = self.validator(src_path)
                if not ok:
                    skipped.append(f"{filename} ({reason})")
                    continue

            dest_path = os.path.join(self.folder, filename)
            # Tránh ghi đè nếu trùng tên -> thêm số đếm (anh1.jpg -> anh1_1.jpg)
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(self.folder, f"{base}_{counter}{ext}")
                    counter += 1

            shutil.copy2(src_path, dest_path)
            copied += 1

        self.refresh_list()

        msg = f"Da tai len {copied} {self.noun}."
        if skipped:
            msg += "\nBo qua:\n - " + "\n - ".join(skipped)
        messagebox.showinfo("Hoan tat", msg)

    def delete_selected(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning("Chua chon file", f"Hay chon 1 {self.noun} trong danh sach truoc khi xoa.")
            return

        filename = self.files[selection[0]]
        if not messagebox.askyesno("Xac nhan xoa", f"Xoa '{filename}' khoi he thong?"):
            return
        try:
            os.remove(os.path.join(self.folder, filename))
        except OSError as e:
            messagebox.showerror("Loi", f"Khong xoa duoc: {e}")
            return
        self.refresh_list()

    def refresh_list(self):
        """Đọc lại thư mục, cập nhật Listbox. Sắp xếp theo tên — TRÙNG với
        cách image_viewer.py / model_viewer.py nạp file (sorted)."""
        self.listbox.delete(0, tk.END)
        self.files = []
        if not os.path.isdir(self.folder):
            return
        self.files = sorted(f for f in os.listdir(self.folder) if f.lower().endswith(self.exts))
        for i, f in enumerate(self.files):
            label = f"[DANG DUNG] {f}" if (self.mark_first and i == 0) else f
            self.listbox.insert(tk.END, label)


def validate_obj(path):
    n = count_obj_vertices(path)
    if n < 0:
        return False, "khong doc duoc file"
    if n < MIN_OBJ_VERTICES:
        return False, f"chi co {n} dinh, can it nhat {MIN_OBJ_VERTICES}"
    return True, ""


class UploadTool:
    def __init__(self, root):
        self.root = root
        self.root.title("Tai du lieu - Upload truoc khi mo (khong phai touchless)")
        self.root.geometry("540x500")

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=5, pady=5)

        tab_images = tk.Frame(notebook)
        tab_models = tk.Frame(notebook)
        notebook.add(tab_images, text="Anh chan doan")
        notebook.add(tab_models, text="Mo hinh 3D (.obj)")

        self.images_panel = FilePanel(
            tab_images, IMAGE_DIR, IMAGE_EXTS, "anh",
            ("Anh", "*.jpg *.jpeg *.png *.bmp"),
        )
        self.models_panel = FilePanel(
            tab_models, MODEL_DIR, MODEL_EXTS, "mo hinh",
            ("Mo hinh 3D", "*.obj"),
            extra_hint="Man XUONG 3D dung file dau tien trong danh sach.\n"
                       "Khong co file nao = dung bo xuong mo phong co san.",
            validator=validate_obj, mark_first=True,
        )


def main():
    root = tk.Tk()
    UploadTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()
