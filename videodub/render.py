"""Làm mờ sub gốc + chèn phụ đề mới (ASS) + trộn âm thanh → video hoàn thiện."""
import os, textwrap
from .utils import ffmpeg_bin, run, fmt_srt_time, log

_qsv_ok = None
def _check_qsv_available() -> bool:
    global _qsv_ok
    if _qsv_ok is None:
        try:
            import subprocess
            r = subprocess.run(
                [ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "nullsrc=s=128x128:d=0.1", "-c:v", "h264_qsv", "-f", "null", "-"],
                capture_output=True
            )
            _qsv_ok = (r.returncode == 0)
        except Exception:
            _qsv_ok = False
    return _qsv_ok

_nvenc_ok = None
def _check_nvenc_available() -> bool:
    global _nvenc_ok
    if _nvenc_ok is None:
        try:
            import subprocess
            r = subprocess.run(
                [ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "nullsrc=s=128x128:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
                capture_output=True
            )
            _nvenc_ok = (r.returncode == 0)
        except Exception:
            _nvenc_ok = False
    return _nvenc_ok

def blur_box(segs, info, cfg):
    boxes = [s["bbox"] for s in segs if s.get("bbox")]
    if not boxes:
        return None
    p = cfg["blur"]["padding"]; W, H = info["width"], info["height"]
    import numpy as np
    b = np.array(boxes)
    x0 = max(0, int(b[:, 0].min()) - p); x1 = min(W, int(b[:, 2].max()) + p)
    y0 = max(0, int(np.median(b[:, 1])) - p); y1 = min(H, int(np.median(b[:, 3])) + p)  # trung vị: không bị 1 câu lạ kéo lệch
    if cfg["blur"]["mode"] == "band":   # dải ngang hết chiều rộng → che cả câu dài/ngắn khác nhau
        x0, x1 = 0, W
    w, h = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
    return [x0, y0, w, h]

def write_srt(segs, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{fmt_srt_time(s['start'])} --> {fmt_srt_time(s['end'])}\n{s['dst']}\n\n")

def _ass_time(t):
    cs = int(round(t * 100)); h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"

def layout(info, box, cfg):
    """Cỡ chữ, số ký tự/dòng, lề dưới của phụ đề mới (dùng chung cho ASS và vùng làm mờ)."""
    sc = cfg["subtitle"]; W, H = info["width"], info["height"]
    size = int(min(W, H) * sc["font_size_ratio"])  # theo cạnh ngắn → video dọc và ngang đều vừa
    mcl = sc["max_chars_per_line"]
    if mcl in (None, "auto", 0):
        mcl = max(16, int(W * 0.85 / (size * 0.55)))   # số ký tự vừa 85% chiều rộng
    if sc["position"] == "on_blur" and box:
        margin_v = max(10, H - (box[1] + box[3]) + max(0, (box[3] - size * 1.3) // 2))
    else:
        margin_v = int(H * 0.08)
    return size, mcl, int(margin_v)

_font_cache = {}
def _text_width(text, size, font_file):
    try:
        from PIL import ImageFont
        key = (font_file, size)
        if key not in _font_cache:
            _font_cache[key] = ImageFont.truetype(font_file, size)
        return _font_cache[key].getlength(text)
    except Exception:
        return len(text) * size * 0.55                 # không có Pillow → ước lượng

def _anchor(s, info, size):
    """Tâm phụ đề Việt = tâm khung sub gốc của chính câu đó → chữ Việt luôn nằm đè lên đúng chỗ đã làm mờ."""
    W = info["width"]
    b = s.get("bbox")
    if not b:
        return None
    return int((b[0] + b[2]) / 2), int((b[1] + b[3]) / 2)

def seg_rects(segs, info, box, cfg):
    """Khung làm mờ riêng cho từng câu = bao cả sub gốc lẫn phụ đề Việt sẽ hiện ở đó (+ lề an toàn)."""
    W, H = info["width"], info["height"]
    size, mcl, margin_v = layout(info, box, cfg)
    sc = cfg["subtitle"]
    pad = int(cfg["blur"].get("padding", 18))
    pad_x = int(pad * 1.35)
    pad_y = max(10, int(pad * 0.95))
    out = []
    for s in segs:
        xs0, ys0, xs1, ys1 = [], [], [], []
        if s.get("bbox"):
            b = s["bbox"]
            xs0.append(b[0]); ys0.append(b[1]); xs1.append(b[2]); ys1.append(b[3])
        if cfg["blur"].get("cover_new_sub", True) and sc.get("enabled", True) and s.get("dst"):
            lines = _balanced_wrap(s["dst"], mcl)
            tw = max(_text_width(l, size, sc["font_file"]) for l in lines) + 2 * sc["outline"]
            th = len(lines) * size * 1.25
            a = _anchor(s, info, size)
            cx, cy = a if a else (W / 2, H - margin_v - th / 2)
            xs0.append(cx - tw / 2); xs1.append(cx + tw / 2)
            ys0.append(cy - th / 2); ys1.append(cy + th / 2)
        if not xs0:
            out.append(None)
            continue
        x0 = max(0, int(min(xs0) - pad_x))
        y0 = max(0, int(min(ys0) - pad_y))
        x1 = min(W, int(max(xs1) + pad_x))
        y1 = min(H, int(max(ys1) + pad_y))
        if (x1 - x0) % 2 != 0:
            x1 = min(W, x1 + 1)
        if (y1 - y0) % 2 != 0:
            y1 = min(H, y1 + 1)
        out.append([x0, y0, x1, y1])
    return out

def write_ass(segs, path, info, box, cfg):
    sc = cfg["subtitle"]; W, H = info["width"], info["height"]
    size, mcl, margin_v = layout(info, box, cfg)
    bc = cfg.get("blur", {})
    blur_enabled = bc.get("enabled", True)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{sc['font_name']},{size},{sc['color']},&H000000FF,{sc['outline_color']},&H80000000,1,0,0,0,100,100,0,0,1,{sc['outline']},1,2,30,30,{int(margin_v)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for s in segs:
            lines = _balanced_wrap(s["dst"], mcl)
            txt = "\\N".join(lines)
            tw = max(_text_width(l, size, sc["font_file"]) for l in lines)
            th = len(lines) * size * 1.25

            if blur_enabled:
                # Che sub cũ: Sub mới hiển thị đè lên đúng dải đã làm mờ
                a = _anchor(s, info, size) if sc["position"] == "on_blur" else None
                if a:
                    cx = min(max(a[0], tw / 2 + 10), W - tw / 2 - 10)
                    txt = f"{{\\an5\\pos({int(cx)},{a[1]})}}" + txt
            else:
                # Không che sub cũ: Sub mới đặt ngay BÊN DƯỚI sub gốc
                b = s.get("bbox")
                if b:
                    cx = int(W / 2)
                    orig_bottom = b[3]
                    # Nếu còn đủ chỗ bên dưới sub gốc:
                    if orig_bottom + th + 10 < H - 15:
                        cy = int(orig_bottom + 8 + th / 2)
                    else:
                        # Nếu sub gốc ở sát đáy màn hình, đặt ngay phía trên sub gốc để không tràn viền
                        cy = int(max(th / 2 + 10, b[1] - 8 - th / 2))
                    cx = min(max(cx, tw / 2 + 10), W - tw / 2 - 10)
                    txt = f"{{\\an5\\pos({int(cx)},{int(cy)})}}" + txt

            f.write(f"Dialogue: 0,{_ass_time(s['start'])},{_ass_time(s['end'])},Default,,0,0,0,,{txt}\n")

def _balanced_wrap(text, max_chars):
    """Ngắt dòng cân đối (tránh dòng 2 chỉ còn 1 chữ)."""
    if len(text) <= max_chars:
        return [text]
    n = -(-len(text) // max_chars)
    return textwrap.wrap(text, -(-len(text) // n) + 2)

def _ff_path(p):
    """Escape đường dẫn cho filter subtitles của ffmpeg (Windows có dấu ':' và '\\')."""
    return os.path.abspath(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

def _box_blur_graph(segs, rects, info, bc):
    """Làm mờ đúng khung từng câu: 1 dải mờ chung + mặt nạ (các ô trắng bật/tắt theo thời gian câu).
    Mặt nạ được làm mềm viền nên khung mờ trông tự nhiên, không bị cạnh cứng."""
    W, H = info["width"], info["height"]
    rs = [r for r in rects if r]
    bx0, by0 = min(r[0] for r in rs), min(r[1] for r in rs)
    bx1, by1 = max(r[2] for r in rs), max(r[3] for r in rs)
    bw, bh = (bx1 - bx0) // 2 * 2, (by1 - by0) // 2 * 2
    feather = max(2, int(bc.get("feather", 6)))
    lead = float(bc.get("lead", 0.12))             # bật sớm một chút để không lộ chữ gốc
    tail = float(bc.get("tail", 0.15))             # giữ thêm một chút để không bị tắt trước khi phụ đề biến mất
    boxes = []
    for s, r in zip(segs, rects):
        if not r:
            continue
        x, y = r[0] - bx0, r[1] - by0
        w, h = min(bw - x, r[2] - r[0]), min(bh - y, r[3] - r[1])
        t0, t1 = max(0, s["start"] - lead), s["end"] + tail
        boxes.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color=white:t=fill:enable='between(t,{t0:.2f},{t1:.2f})'")
    fps = info["fps"] or 30
    dur = info["duration"] + 1
    # Mặt nạ: đen = giữ nguyên, trắng = lấy bản mờ. Trộn bằng maskedmerge trên RGB (không dùng kênh alpha,
    # vì một số bản ffmpeg mới tự bỏ alpha khi overlay → cả dải bị mờ suốt video)
    mask = (f"color=c=black:s={bw}x{bh}:r={fps:.3f}:d={dur:.2f}," + ",".join(boxes) +
            f",format=gray,lut=c0='if(gt(val,100),255,0)',boxblur={feather}:1,format=gbrp[m]")
    if bc["fill"] == "box":
        cover = f"color=c={bc['box_color'].split('@')[0]}:s={bw}x{bh}:r={fps:.3f}:d={dur:.2f},format=gbrp[b]"
    else:
        cover = f"[tb]boxblur={int(bc['strength'])}:2,format=gbrp[b]"
    return (f"[v_src]split[base][t];[t]crop={bw}:{bh}:{bx0}:{by0},split[orig][tb];[orig]format=gbrp[o];"
            + cover + ";" + mask + ";[o][b][m]maskedmerge,format=yuv420p[mm];"
            f"[base][mm]overlay={bx0}:{by0}:eof_action=pass[v1]")

def _ffmpeg_major():
    try:
        import re
        out = run([ffmpeg_bin(), "-hide_banner", "-version"])
        return int(re.search(r"version\D*(\d+)", out).group(1))
    except Exception:
        return 6

def render(video, segs, info, dub_wav, ass_path, out_path, box, cfg):
    vf = []
    inputs = ["-i", video]
    W, H = info["width"], info["height"]

    # 1. Bước xóa/che logo hoặc watermark video gốc (nếu bật)
    lrc = cfg.get("logo_remove", {})
    curr_v = "0:v"
    if lrc.get("enabled", False):
        pos = lrc.get("position", "top_left")
        if pos == "top_left":
            lx, ly, lw, lh = int(W * 0.02), int(H * 0.02), int(W * 0.28), int(H * 0.08)
        elif pos == "top_right":
            lw, lh = int(W * 0.28), int(H * 0.08)
            lx, ly = W - lw - int(W * 0.02), int(H * 0.02)
        elif pos == "bottom_left":
            lx, lw, lh = int(W * 0.02), int(W * 0.28), int(H * 0.08)
            ly = H - lh - int(H * 0.05)
        elif pos == "bottom_right":
            lw, lh = int(W * 0.28), int(H * 0.08)
            lx, ly = W - lw - int(W * 0.02), H - lh - int(H * 0.05)
        else: # custom
            lx = int(lrc.get("x", 20))
            ly = int(lrc.get("y", 20))
            lw = int(lrc.get("w", 180))
            lh = int(lrc.get("h", 60))
        lx, ly, lw, lh = (lx // 2) * 2, (ly // 2) * 2, (lw // 2) * 2, (lh // 2) * 2
        st = int(lrc.get("strength", 25))
        vf.append(f"[{curr_v}]split[v_lbase][v_lcrop];[v_lcrop]crop={lw}:{lh}:{lx}:{ly},boxblur={st}:2[v_lblur];"
                  f"[v_lbase][v_lblur]overlay={lx}:{ly}[v_delogo]")
        curr_v = "v_delogo"

    # Gán luồng nguồn cho phần làm mờ sub
    vf.append(f"[{curr_v}]null[v_src]")

    # 2. Bước làm mờ sub cũ (nếu bật)
    bc = cfg["blur"]
    blur_active = bc.get("enabled", True)
    rects = seg_rects(segs, info, box, cfg) if blur_active and bc.get("mode") == "box" else None
    if blur_active and rects and any(rects):
        vf.append(_box_blur_graph(segs, rects, info, bc))
    elif blur_active and box:
        x, y, w, h = box
        enable = ""
        if bc.get("mode") == "segment":
            enable = ":enable='" + "+".join(f"between(t,{s['start']},{s['end']})" for s in segs) + "'"
        if bc.get("fill") == "box":
            vf.append(f"[v_src]drawbox=x={x}:y={y}:w={w}:h={h}:color={bc['box_color']}:t=fill{enable}[v1]")
        else:
            st = int(bc.get("strength", 20))
            vf.append(f"[v_src]split[base][tmp];[tmp]crop={w}:{h}:{x}:{y},boxblur={st}:2[bl];"
                      f"[base][bl]overlay={x}:{y}{enable}[v1]")
    else:
        # Không che sub cũ -> giữ nguyên video
        vf.append("[v_src]null[v1]")

    # 3. Bước chèn phụ đề mới (ASS)
    curr_v2 = "v1"
    if cfg["subtitle"]["enabled"] and ass_path:
        fontsdir = os.path.dirname(os.path.abspath(cfg["subtitle"]["font_file"]))
        vf.append(f"[{curr_v2}]subtitles='{_ff_path(ass_path)}':fontsdir='{_ff_path(fontsdir)}'[v_sub]")
        curr_v2 = "v_sub"

    # 4. Bước dán logo thương hiệu riêng (nếu có)
    blc = cfg.get("brand_logo", {})
    if blc.get("enabled", False) and blc.get("path") and os.path.exists(blc["path"]):
        logo_input_idx = len(inputs) // 2
        inputs += ["-i", blc["path"]]
        l_corner = blc.get("corner", "top_right")
        l_w = int(blc.get("width", 120))
        l_margin = int(blc.get("margin", 20))
        if l_corner == "top_left":
            loc = f"{l_margin}:{l_margin}"
        elif l_corner == "top_right":
            loc = f"main_w-overlay_w-{l_margin}:{l_margin}"
        elif l_corner == "bottom_left":
            loc = f"{l_margin}:main_h-overlay_h-{l_margin}"
        else: # bottom_right
            loc = f"main_w-overlay_w-{l_margin}:main_h-overlay_h-{l_margin}"
        vf.append(f"[{logo_input_idx}:v]scale={l_w}:-1[scaled_brand_logo];"
                  f"[{curr_v2}][scaled_brand_logo]overlay={loc}[vout]")
    else:
        vf.append(f"[{curr_v2}]null[vout]")

    # 5. Xử lý âm thanh (audio filter graph: lồng tiếng, ducking âm gốc, giữ nhạc nền)
    af = []
    has_orig_audio = info.get("has_audio", False)
    if dub_wav and os.path.exists(dub_wav):
        dub_input_idx = len(inputs) // 2
        inputs += ["-i", dub_wav]
        bg_path = cfg.get("original_audio", {}).get("_bg_path")
        if bg_path and os.path.exists(bg_path):
            bg_input_idx = len(inputs) // 2
            inputs += ["-i", bg_path]
            vol = float(cfg.get("original_audio", {}).get("volume", 0.2))
            af.append(f"[{bg_input_idx}:a]volume={vol}[bg_a];"
                      f"[{dub_input_idx}:a][bg_a]amix=inputs=2:duration=first:dropout_transition=2[aout]")
        elif has_orig_audio:
            orig_mode = cfg.get("original_audio", {}).get("mode", "duck")
            if orig_mode == "mute":
                af.append(f"[{dub_input_idx}:a]volume=1.0[aout]")
            else: # duck
                vol = float(cfg.get("original_audio", {}).get("volume", 0.15))
                af.append(f"[0:a]volume={vol}[orig_ducked];"
                          f"[{dub_input_idx}:a][orig_ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]")
        else:
            af.append(f"[{dub_input_idx}:a]volume=1.0[aout]")
    elif has_orig_audio:
        # Giữ nguyên 100% âm thanh gốc (vietsub mode)
        af.append("[0:a]volume=1.0[aout]")

    graph = ";".join(vf + af)
    oc = cfg["output"]
    # graph dài (phim nhiều câu) → ghi ra file, tránh giới hạn độ dài dòng lệnh của Windows
    gfile = os.path.join(os.path.dirname(os.path.abspath(ass_path or out_path)), "graph.txt")
    with open(gfile, "w", encoding="utf-8") as f:
        f.write(graph)
    fc = ["-/filter_complex", gfile] if _ffmpeg_major() >= 7 else ["-filter_complex_script", gfile]
    cmd = [ffmpeg_bin(), "-y", *inputs, *fc, "-map", "[vout]"]
    if af:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]

    # Tự động phát hiện và kích hoạt tăng tốc phần cứng GPU (Intel QSV / NVIDIA NVENC) để xuất video siêu tốc
    accel_mode = oc.get("hardware_accel", "auto")
    v_encoder = ["-c:v", "libx264", "-preset", oc.get("preset", "veryfast"), "-crf", str(oc.get("crf", 20)), "-pix_fmt", "yuv420p"]
    used_hw = False

    if accel_mode in ("auto", "qsv", "intel") and _check_qsv_available():
        v_encoder = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "22", "-pix_fmt", "nv12"]
        used_hw = True
        log.info("  ⚡ [Tăng tốc GPU] Đã kích hoạt Intel QuickSync Video (h264_qsv) xuất video siêu tốc!")
    elif accel_mode in ("auto", "nvenc", "nvidia") and _check_nvenc_available():
        v_encoder = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22", "-pix_fmt", "yuv420p"]
        used_hw = True
        log.info("  ⚡ [Tăng tốc GPU] Đã kích hoạt NVIDIA NVENC (h264_nvenc) xuất video siêu tốc!")

    cmd += v_encoder + ["-movflags", "+faststart", out_path]
    log.info("Đang xuất video...")
    try:
        run(cmd)
    except Exception as e_enc:
        if used_hw:
            log.warning("Bộ mã hóa GPU gặp lỗi (%s), tự động chuyển sang CPU libx264...", e_enc)
            cmd_fallback = [ffmpeg_bin(), "-y", *inputs, *fc, "-map", "[vout]"]
            if af:
                cmd_fallback += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
            cmd_fallback += ["-c:v", "libx264", "-preset", oc.get("preset", "veryfast"), "-crf", str(oc.get("crf", 20)), "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
            run(cmd_fallback)
        else:
            raise
