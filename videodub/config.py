"""Cấu hình mặc định. Ghi đè bằng file config.yaml (chỉ cần khai báo key muốn đổi)."""
import copy, os

DEFAULTS = {
    "source_lang": "zh",          # ngôn ngữ video gốc
    "target_lang": "vi",          # ngôn ngữ đầu ra

    # Lấy nội dung gốc: "ocr" (đọc hardsub - khuyên dùng cho video Trung có sub) | "asr" (nghe giọng bằng Whisper)
    "source_text": "ocr",
    "ocr": {
        "fps": 2,                 # số frame/giây đem đi OCR (cao = chính xác hơn, chậm hơn)
        "region": [0.60, 1.0],    # vùng dọc tìm sub gốc (tỉ lệ chiều cao): 60% → 100% = nửa dưới
        "min_score": 0.6,         # độ tin cậy tối thiểu của OCR
        "merge_similarity": 0.7,  # 2 frame liên tiếp giống nhau ≥ ngưỡng này thì coi là cùng 1 câu
        "fast_skip": True,        # bỏ qua frame không có chữ / chữ không đổi (tăng tốc nhiều). Sub màu lạ (đỏ, xanh) thì tắt
        "empty_ratio": 0.002,     # tỉ lệ pixel chữ dưới mức này = không có sub
        "same_ratio": 0.08,       # mặt nạ chữ khác nhau dưới 8% = cùng 1 câu
        "max_width": 540,         # thu nhỏ chiều rộng ảnh trước khi OCR (540px quét nhanh gấp đôi mà vẫn rõ nét)
        "lock_band": True,        # TỰ ĐỘNG KHÓA DẢI PHỤ ĐỀ: chỉ quét dải chữ đối thoại (tăng tốc 5-10x)
        "lock_after": 3,          # số câu phụ đề đầu tiên để định vị dải trước khi khóa
        "band_diff_thresh": 11.0, # ngưỡng phát hiện chữ đổi trong dải sub (để bỏ qua frame lặp)
        "min_duration": 0.4,      # câu ngắn hơn (giây) bị bỏ (thường là nhiễu)
    },
    "asr": {"provider": "local", "model": "small", "device": "auto", "compute_type": "int8", "cpu_threads": 4},

    # Làm mờ sub gốc
    "blur": {
        "enabled": True,
        "mode": "box",            # "box": khung mờ ôm sát từng câu | "band": dải ngang hết chiều rộng | "segment": dải, chỉ hiện lúc có sub
        "cover_new_sub": True,    # khung mờ nới ra cho vừa cả phụ đề Việt (thường dài hơn chữ Trung)
        "feather": 6,             # độ mềm viền khung mờ (px)
        "strength": 20,
        "padding": 18,            # px nới rộng quanh vùng chữ
        "fill": "blur",           # "blur" | "box" (hộp màu đặc, che kín hơn)
        "box_color": "black@0.85",
    },

    # Dịch: "google" (free) | "gemini" (cần GEMINI_API_KEY) | "mock" (test offline)
    "translate": {
        "provider": "google",
        "google_delay": 1.0,
        "batch_size": 40,
        "gemini_model": "gemini-3.8-flash",            # chất lượng tốt nhất dòng Flash
        "gemini_fallback_models": ["gemini-3.5-flash", "gemini-3.5-flash-lite"],  # dùng khi model chính bận hoặc gặp sự cố
        "gemini_analyze": True,   # phân tích cả kịch bản trước (nhân vật, tên riêng, xưng hô) → dịch nhất quán
        "context": "",            # mô tả thêm cho Gemini, vd "Phim AI: Tôn Ngộ Không tỉnh dậy ở thời hiện đại"
        "glossary": {},           # tên riêng bắt buộc, vd {"孙大圣": "Tôn Đại Thánh"}
        "length_factor": 1.0,     # <1 = bắt dịch ngắn hơn (đỡ phải tăng tốc giọng đọc)
    },

    # Lồng tiếng: "supertonic" (offline, model Supertonic 3) | "edge" (Edge-TTS online) | "gtts" | "espeak" (test) | "none"
    "tts": {
        "provider": "supertonic",
        "fallback": "edge",       # câu nào provider chính lỗi thì dùng cái này ("edge" | "gtts" | "")
        "multi_voice": True,      # mỗi nhân vật 1 giọng riêng theo giới tính (Gemini gắn speaker/gender khi dịch)
        "speaker_voices": {},     # gán tay giọng cho nhân vật, vd {"Tôn Ngộ Không": "M2", "Hệ thống": "F3"}
        "max_speed": 1.15,        # tua nhanh thêm tối đa bằng ffmpeg nếu vẫn dài (cao quá nghe méo)
        "group": {"enabled": True, "max_gap": 0.35, "max_span": 6.0, "max_words": 22},  # gộp câu ngắn liền nhau cùng người nói
        "supertonic": {
            "model": "supertonic-3",
            "voice": "F1",                                   # giọng mặc định (người nói không rõ)
            "male_voices": ["M1", "M2", "M3", "M4", "M5"],
            "female_voices": ["F1", "F2", "F3", "F4", "F5"],
            "speed": 1.65,        # tốc độ đọc bình thường (0.7–2.0). Đã chọn qua calibrate_voice.py
            "max_speed": 2.0,     # câu dài hơn khung giờ → model tự đọc nhanh hơn, tối đa mức này
            "steps": 8,           # chất lượng: 5 (nhanh) – 12 (hay hơn, chậm hơn)
        },
        "edge": {
            "voice": "vi-VN-HoaiMyNeural",
            "male_voices": ["vi-VN-NamMinhNeural"],
            "female_voices": ["vi-VN-HoaiMyNeural"],
            "rate": "+10%",
            "concurrency": 2,
            "gap": 0.15,
            "retry_pause": 20,
            "timeout": 30,
            "fallback": "gtts",
        },
        "openai": {
            "model": "tts-1",
            "speed": 1.05,
            "male_voice": "onyx",
            "female_voice": "nova",
        },
        "rate": "+10%",
    },

    # Âm thanh gốc: "duck" (vặn nhỏ giọng gốc) | "remove_voice" (Demucs tách giọng, giữ nhạc nền) | "mute"
    "original_audio": {"mode": "duck", "volume": 0.15},
    "dub_volume": 1.0,

    # Phụ đề mới
    "subtitle": {
        "enabled": True,
        "font_file": "fonts/BeVietnamPro-Bold.ttf",
        "font_name": "Be Vietnam Pro",
        "font_size_ratio": 0.055, # cỡ chữ = tỉ lệ cạnh ngắn của video
        "color": "&H00FFFFFF",    # ASS: &HAABBGGRR
        "outline_color": "&H00000000",
        "outline": 3,
        "max_chars_per_line": "auto",  # hoặc số cụ thể, vd 28
        "position": "on_blur",    # "on_blur": đặt lên dải đã làm mờ | "bottom"
    },

    # Xóa logo / watermark video gốc (Douyin, TikTok...)
    "logo_remove": {
        "enabled": False,
        "position": "top_left",   # "top_left", "top_right", "bottom_left", "bottom_right", "custom"
        "strength": 25,
        "x": 20, "y": 20, "w": 200, "h": 70,
    },

    # Dán logo thương hiệu riêng vào video
    "brand_logo": {
        "enabled": False,
        "path": "",               # đường dẫn file ảnh logo (PNG trong suốt hoặc JPG)
        "corner": "top_right",    # "top_left", "top_right", "bottom_left", "bottom_right"
        "width": 120,             # chiều rộng theo px (chiều cao tự co giãn tỉ lệ)
        "margin": 20,             # khoảng cách từ mép video (px)
    },

    "output": {"crf": 20, "preset": "veryfast", "keep_temp": False, "export_srt": True, "hardware_accel": "auto"},
}

def _merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base

def load_config(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    if path and os.path.exists(path):
        import yaml
        with open(path, encoding="utf-8") as f:
            _merge(cfg, yaml.safe_load(f) or {})
    return cfg
