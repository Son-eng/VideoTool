"""Giao diện đồ họa Desktop cho VideoDub (CustomTkinter + TkinterDnD)
Hỗ trợ kéo thả video, chọn chế độ (Chỉ Vietsub, Chỉ Lồng tiếng, Cả hai),
thanh tiến trình trực quan theo thời gian thực và quản lý xuất video.
"""
import copy, os, re, sys, threading, time
import customtkinter as ctk
from tkinter import filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES

from .config import load_config
from .pipeline import process
from .utils import probe, log

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi")

class DnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
    """Lớp kết hợp CustomTkinter với TkinterDnD để hỗ trợ kéo thả."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)

class VideoDubApp(DnDCTk):
    def __init__(self):
        super().__init__()

        # Cài đặt giao diện
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("VideoDub — Công Cụ Vietsub & Lồng Tiếng Video Trung Quốc")
        self.geometry("860x740")
        self.minsize(800, 680)

        self.cfg = load_config("config.yaml")
        self.selected_files = []
        self.is_processing = False
        self.last_output = None

        self._build_ui()

    def _build_ui(self):
        # 1. Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=25, pady=(20, 10))

        title = ctk.CTkLabel(header, text="VideoDub Studio", font=ctk.CTkFont(size=24, weight="bold"))
        title.pack(anchor="w")
        subtitle = ctk.CTkLabel(header, text="Tự động hóa làm mờ sub gốc, dịch theo ngữ cảnh & lồng tiếng cho video ngắn Douyin/TikTok",
                                font=ctk.CTkFont(size=13), text_color="#94a3b8")
        subtitle.pack(anchor="w")

        # 2. Main content container (Scrollable)
        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.main_scroll.pack(fill="both", expand=True, padx=25, pady=5)

        # 3. Kéo thả file / Chọn file (Drop Zone)
        self.drop_frame = ctk.CTkFrame(self.main_scroll, fg_color="#1e293b", corner_radius=12,
                                       border_width=2, border_color="#334155")
        self.drop_frame.pack(fill="x", pady=10, ipady=15)

        # Kích hoạt Drag and Drop trên drop_frame
        try:
            self.drop_frame.drop_target_register(DND_FILES)
            self.drop_frame.dnd_bind("<<Drop>>", self._on_drop_file)
            self.drop_frame.dnd_bind("<<DragEnter>>", lambda e: self.drop_frame.configure(border_color="#3b82f6"))
            self.drop_frame.dnd_bind("<<DragLeave>>", lambda e: self.drop_frame.configure(border_color="#334155"))
        except Exception as e:
            log.warning("Không đăng ký được DnD trên drop_frame: %s", e)

        self.icon_label = ctk.CTkLabel(self.drop_frame, text="📁", font=ctk.CTkFont(size=36))
        self.icon_label.pack(pady=(10, 5))

        self.drop_text = ctk.CTkLabel(self.drop_frame, text="KÉO THẢ VIDEO VÀO ĐÂY HOẶC NHẤN ĐỂ CHỌN",
                                      font=ctk.CTkFont(size=14, weight="bold"))
        self.drop_text.pack()

        self.drop_sub = ctk.CTkLabel(self.drop_frame, text="Hỗ trợ các định dạng: MP4, MOV, MKV, WEBM, AVI",
                                     font=ctk.CTkFont(size=12), text_color="#94a3b8")
        self.drop_sub.pack(pady=(2, 10))

        btn_row = ctk.CTkFrame(self.drop_frame, fg_color="transparent")
        btn_row.pack(pady=5)

        self.btn_select_file = ctk.CTkButton(btn_row, text="Chọn video lẻ", width=140, command=self._choose_files,
                                             fg_color="#3b82f6", hover_color="#2563eb")
        self.btn_select_file.pack(side="left", padx=8)

        self.btn_select_folder = ctk.CTkButton(btn_row, text="Chọn thư mục batch", width=160, command=self._choose_folder,
                                               fg_color="#475569", hover_color="#334155")
        self.btn_select_folder.pack(side="left", padx=8)

        # File list display
        self.file_info_frame = ctk.CTkFrame(self.main_scroll, fg_color="#0f172a", corner_radius=8)
        self.file_info_frame.pack(fill="x", pady=(5, 10))
        self.lbl_selected_info = ctk.CTkLabel(self.file_info_frame, text="Chưa có video nào được chọn",
                                              text_color="#64748b", font=ctk.CTkFont(size=12))
        self.lbl_selected_info.pack(padx=15, pady=8, anchor="w")

        # 4. Lựa chọn Chế độ (Mode Selection)
        mode_section = ctk.CTkFrame(self.main_scroll, fg_color="#1e293b", corner_radius=12)
        mode_section.pack(fill="x", pady=10, padx=0)

        lbl_mode_title = ctk.CTkLabel(mode_section, text="CHỌN HƯỚNG XỬ LÝ (CHẾ ĐỘ):",
                                      font=ctk.CTkFont(size=13, weight="bold"), text_color="#e2e8f0")
        lbl_mode_title.pack(anchor="w", padx=15, pady=(12, 6))

        self.mode_var = ctk.StringVar(value="vietsub")
        self.mode_seg = ctk.CTkSegmentedButton(
            mode_section,
            values=["📝 Chỉ Vietsub", "🎙️ Chỉ Lồng Tiếng", "⚡ Cả Hai (Sub + Voice)"],
            variable=self.mode_var,
            command=self._on_mode_change,
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            selected_color="#3b82f6",
            selected_hover_color="#2563eb"
        )
        self.mode_seg.set("📝 Chỉ Vietsub")
        self.mode_seg.pack(fill="x", padx=15, pady=6)

        self.lbl_mode_desc = ctk.CTkLabel(
            mode_section,
            text="• Chỉ Vietsub: Tự động làm mờ sub gốc tiếng Trung + Chèn phụ đề tiếng Việt. Giữ nguyên 100% âm thanh gốc, không lồng tiếng.",
            font=ctk.CTkFont(size=12), text_color="#38bdf8", justify="left"
        )
        self.lbl_mode_desc.pack(anchor="w", padx=15, pady=(2, 12))

        # 5. Cài đặt nhanh (Settings)
        settings_frame = ctk.CTkFrame(self.main_scroll, fg_color="#1e293b", corner_radius=12)
        settings_frame.pack(fill="x", pady=10)

        lbl_opt = ctk.CTkLabel(settings_frame, text="TÙY CHỌN & THIẾT LẬP:", font=ctk.CTkFont(size=13, weight="bold"))
        lbl_opt.pack(anchor="w", padx=15, pady=(10, 6))

        # Thư mục xuất
        out_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        out_row.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(out_row, text="Thư mục xuất:", width=110, anchor="w").pack(side="left")
        self.entry_out = ctk.CTkEntry(out_row, placeholder_text="output")
        self.entry_out.insert(0, "output")
        self.entry_out.pack(side="left", fill="x", expand=True, padx=6)
        btn_browse_out = ctk.CTkButton(out_row, text="Duyệt...", width=75, command=self._choose_out_dir,
                                       fg_color="#475569", hover_color="#334155")
        btn_browse_out.pack(side="right")

        # Kiểu làm mờ sub gốc
        self.blur_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        self.blur_row.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(self.blur_row, text="Kiểu che sub:", width=110, anchor="w").pack(side="left")
        self.blur_mode_var = ctk.StringVar(value="Khung chữ tự động (Box)")
        self.cmb_blur = ctk.CTkOptionMenu(
            self.blur_row,
            values=["Khung chữ tự động (Box)", "Dải ngang che kín (Band)"],
            variable=self.blur_mode_var,
            width=220
        )
        self.cmb_blur.pack(side="left", padx=6)
        self.lbl_blur_hint = ctk.CTkLabel(
            self.blur_row,
            text="(Box: ôm sát từng câu | Band: dải mờ ngang 100% video sạch sẽ)",
            font=ctk.CTkFont(size=11), text_color="#94a3b8"
        )
        self.lbl_blur_hint.pack(side="left", padx=6)

        # Tùy chọn giọng đọc (khi bật lồng tiếng)
        self.voice_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        self.voice_row.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(self.voice_row, text="Động cơ TTS:", width=110, anchor="w").pack(side="left")
        self.tts_provider_var = ctk.StringVar(value=self.cfg.get("tts", {}).get("provider", "supertonic"))
        self.cmb_tts = ctk.CTkOptionMenu(
            self.voice_row,
            values=["supertonic", "edge"],
            variable=self.tts_provider_var,
            width=220
        )
        self.cmb_tts.pack(side="left", padx=6)

        self.lbl_tts_hint = ctk.CTkLabel(
            self.voice_row,
            text="(supertonic: offline | edge: giọng đọc TikTok tự nhiên)",
            font=ctk.CTkFont(size=11), text_color="#94a3b8"
        )
        # Cấu hình Gemini API Key
        self.key_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        self.key_row.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(self.key_row, text="Gemini API Key:", width=110, anchor="w").pack(side="left")
        self.entry_key = ctk.CTkEntry(self.key_row, placeholder_text="Dán API Key AIzaSy... vào đây", show="*")
        curr_key = self._load_current_key()
        if curr_key:
            self.entry_key.insert(0, curr_key)
        self.entry_key.pack(side="left", fill="x", expand=True, padx=6)

        self.btn_save_key = ctk.CTkButton(self.key_row, text="Lưu Key", width=75, command=self._save_key,
                                          fg_color="#3b82f6", hover_color="#2563eb")
        self.btn_save_key.pack(side="right", padx=(4, 0))

        self.btn_get_key = ctk.CTkButton(self.key_row, text="Lấy Key Free ↗", width=105, command=self._open_key_url,
                                         fg_color="#334155", hover_color="#475569")
        self.btn_get_key.pack(side="right", padx=(0, 4))

        # 6. Khu vực Tiến trình (Progress & Action)
        action_frame = ctk.CTkFrame(self, fg_color="#1e293b", corner_radius=12)
        action_frame.pack(fill="x", padx=25, pady=(5, 15))

        prog_header = ctk.CTkFrame(action_frame, fg_color="transparent")
        prog_header.pack(fill="x", padx=15, pady=(12, 4))

        self.lbl_status = ctk.CTkLabel(prog_header, text="Sẵn sàng thực hiện", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_status.pack(side="left")

        self.lbl_pct = ctk.CTkLabel(prog_header, text="0%", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8")
        self.lbl_pct.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(action_frame, height=12, progress_color="#3b82f6")
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=15, pady=6)

        # Nút Thực hiện chính & Nút xem kết quả
        btn_action_row = ctk.CTkFrame(action_frame, fg_color="transparent")
        btn_action_row.pack(fill="x", padx=15, pady=(6, 12))

        self.btn_run = ctk.CTkButton(
            btn_action_row,
            text="🚀 BẮT ĐẦU XUẤT VIDEO",
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            command=self._start_process
        )
        self.btn_run.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_open_out = ctk.CTkButton(
            btn_action_row,
            text="📂 Mở Thư Mục Kết Quả",
            height=42,
            width=180,
            fg_color="#475569",
            hover_color="#334155",
            command=self._open_output_folder
        )
        self.btn_open_out.pack(side="right", padx=(6, 0))

    def _on_drop_file(self, event):
        """Xử lý sự kiện kéo thả file vào cửa sổ."""
        self.drop_frame.configure(border_color="#334155")
        paths = self._parse_dropped_paths(event.data)
        valid = [p for p in paths if os.path.isfile(p) and p.lower().endswith(VIDEO_EXTS)]
        if valid:
            self.selected_files = valid
            self._update_selected_ui()
        else:
            messagebox.showwarning("Định dạng không hợp lệ", f"Vui lòng kéo thả file video ({', '.join(VIDEO_EXTS)}).")

    def _parse_dropped_paths(self, raw_data):
        return [f1 or f2 for f1, f2 in re.findall(r'\{([^}]+)\}|(\S+)', raw_data)]

    def _choose_files(self):
        files = filedialog.askopenfilenames(
            title="Chọn video tiếng Trung",
            filetypes=[("Video files", "*.mp4;*.mov;*.mkv;*.webm;*.avi"), ("All files", "*.*")]
        )
        if files:
            self.selected_files = list(files)
            self._update_selected_ui()

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="Chọn thư mục chứa video (Batch)")
        if folder:
            files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(VIDEO_EXTS)]
            if files:
                self.selected_files = sorted(files)
                self._update_selected_ui()
            else:
                messagebox.showinfo("Thông báo", "Không tìm thấy file video nào trong thư mục đã chọn.")

    def _choose_out_dir(self):
        d = filedialog.askdirectory(title="Chọn thư mục xuất video")
        if d:
            self.entry_out.delete(0, "end")
            self.entry_out.insert(0, d)

    def _update_selected_ui(self):
        n = len(self.selected_files)
        if n == 1:
            f = self.selected_files[0]
            size_mb = os.path.getsize(f) / (1024 * 1024)
            self.lbl_selected_info.configure(
                text=f"Đã chọn: {os.path.basename(f)} ({size_mb:.1f} MB)\nĐường dẫn: {f}",
                text_color="#f8fafc"
            )
        elif n > 1:
            self.lbl_selected_info.configure(
                text=f"Đã chọn {n} video để xử lý hàng loạt (Batch Mode).",
                text_color="#f8fafc"
            )
        else:
            self.lbl_selected_info.configure(text="Chưa có video nào được chọn", text_color="#64748b")

    def _on_mode_change(self, val):
        if "Vietsub" in val:
            self.lbl_mode_desc.configure(
                text="• Chỉ Vietsub: Tự động làm mờ sub gốc tiếng Trung + Chèn phụ đề tiếng Việt. Giữ nguyên 100% âm thanh gốc, không lồng tiếng."
            )
        elif "Lồng Tiếng" in val:
            self.lbl_mode_desc.configure(
                text="• Chỉ Lồng Tiếng: Lồng tiếng tiếng Việt + Làm mờ sub gốc tiếng Trung để video sạch sẽ. Không chèn chữ phụ đề."
            )
        else:
            self.lbl_mode_desc.configure(
                text="• Cả Hai: Vừa làm mờ sub gốc + Chèn phụ đề tiếng Việt + Lồng tiếng đa giọng hoàn chỉnh."
            )

    def _get_target_mode(self):
        val = self.mode_var.get()
        if "Vietsub" in val:
            return "vietsub"
        elif "Lồng Tiếng" in val:
            return "dubbing"
        return "both"

    def _progress_callback(self, step, pct, msg):
        """Được gọi từ pipeline trong tiến trình chạy."""
        def update():
            self.progress_bar.set(pct)
            self.lbl_pct.configure(text=f"{int(pct * 100)}%")
            self.lbl_status.configure(text=f"[{step}] {msg}")
        self.after(0, update)

    def _start_process(self):
        if self.is_processing:
            return
        if not self.selected_files:
            messagebox.showwarning("Chưa chọn video", "Vui lòng kéo thả hoặc chọn ít nhất 1 video để xử lý.")
            return

        out_dir = self.entry_out.get().strip() or "output"
        os.makedirs(out_dir, exist_ok=True)
        mode = self._get_target_mode()

        # Áp dụng cấu hình TTS và Blur người dùng chọn
        run_cfg = copy.deepcopy(self.cfg)
        run_cfg["tts"]["provider"] = self.tts_provider_var.get()
        blur_val = self.blur_mode_var.get()
        run_cfg["blur"]["mode"] = "band" if "Band" in blur_val else "box"
        run_cfg["blur"]["cover_new_sub"] = True

        self.is_processing = True
        self.btn_run.configure(state="disabled", text="⏳ Đang xử lý video...", fg_color="#64748b")
        self.progress_bar.set(0.0)
        self.lbl_pct.configure(text="0%")

        threading.Thread(target=self._worker, args=(self.selected_files, out_dir, run_cfg, mode), daemon=True).start()

    def _worker(self, files, out_dir, cfg, mode):
        total = len(files)
        done = []
        errors = []
        for i, file_path in enumerate(files, 1):
            name = os.path.splitext(os.path.basename(file_path))[0]
            def sub_prog(step, pct, msg):
                overall = ((i - 1) + pct) / total
                file_hint = f"({i}/{total}) " if total > 1 else ""
                self._progress_callback(f"{file_hint}{step}", overall, msg)

            try:
                sub_prog("Bắt đầu", 0.0, f"Đang xử lý {name}...")
                res = process(file_path, out_dir, cfg, mode=mode, progress_cb=sub_prog)
                done.append(res)
                self.last_output = res.get("output")
            except Exception as e:
                log.exception("Lỗi khi xử lý %s", file_path)
                errors.append((name, str(e)))

        def finished():
            self.is_processing = False
            self.btn_run.configure(state="normal", text="🚀 BẮT ĐẦU XUẤT VIDEO", fg_color="#10b981")
            self.progress_bar.set(1.0)
            self.lbl_pct.configure(text="100%")

            if errors:
                err_msg = "\n".join(f"- {n}: {err}" for n, err in errors[:5])
                self.lbl_status.configure(text=f"Hoàn thành {len(done)}/{total} video (Lỗi {len(errors)})")
                messagebox.showwarning("Xử lý có lỗi", f"Hoàn thành {len(done)} video.\nCó {len(errors)} video bị lỗi:\n{err_msg}")
            else:
                self.lbl_status.configure(text=f"Đã xuất xong {len(done)} video thành công!")
                messagebox.showinfo("Thành công", f"Đã xuất xong {len(done)} video vào thư mục '{out_dir}'!")

        self.after(0, finished)

    def _open_output_folder(self):
        out_dir = self.entry_out.get().strip() or "output"
        os.makedirs(out_dir, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(os.path.abspath(out_dir))
        else:
            import subprocess
            subprocess.run(["xdg-open", out_dir])

    def _load_current_key(self):
        try:
            from .utils import ROOT
            import yaml
            p = os.path.join(ROOT, "secrets.yaml")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    return str((yaml.safe_load(f) or {}).get("gemini_api_key", "")).strip()
        except Exception:
            pass
        return ""

    def _save_key(self):
        k = self.entry_key.get().strip()
        if not k:
            messagebox.showwarning("Chưa nhập key", "Vui lòng dán Gemini API Key trước khi lưu.")
            return
        try:
            from .utils import ROOT
            import yaml
            p = os.path.join(ROOT, "secrets.yaml")
            data = {}
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            data["gemini_api_key"] = k
            with open(p, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f)
            messagebox.showinfo("Thành công", "Đã lưu Gemini API Key thành công!")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể lưu key: {e}")

    def _open_key_url(self):
        import webbrowser
        webbrowser.open("https://aistudio.google.com/apikey")

def main():
    app = VideoDubApp()
    app.mainloop()

if __name__ == "__main__":
    main()
