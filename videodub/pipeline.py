"""Luồng chính: video gốc → video hoàn thiện (làm mờ sub gốc + phụ đề mới + lồng tiếng)."""
import json, os, shutil, tempfile, time
from . import ocr_subs, asr, translate, tts, render
from .utils import probe, run, ffmpeg_bin, log

def process(video, out_dir, cfg, segments_json=None, fresh=False, retranslate=False, mode="both", progress_cb=None):
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(video))[0]
    tmp = tempfile.mkdtemp(prefix=f"vd_{name}_")
    info = probe(video)
    log.info("[%s] %dx%d %.1fs | Chế độ: %s", name, info["width"], info["height"], info["duration"], mode)

    def _notify(step, pct, msg):
        if progress_cb:
            try:
                progress_cb(step, pct, msg)
            except Exception:
                pass

    _notify("Khởi động", 0.05, f"Đang chuẩn bị video {name}...")

    # 1. Lấy nội dung gốc. Có cache: chạy lại sẽ không phải OCR / dịch lại (dùng --fresh để làm lại từ đầu)
    seg_path = os.path.join(out_dir, f"{name}.segments.json")
    ocr_path = os.path.join(out_dir, f"{name}.ocr.json")
    if not segments_json and not fresh and os.path.exists(seg_path):
        segments_json = seg_path
    segs = None
    if segments_json:
        with open(segments_json, encoding="utf-8") as f:
            segs = json.load(f)
        if retranslate or not all(s.get("dst") for s in segs):
            segs = [{k: v for k, v in s.items() if k != "dst"} for s in segs]  # chưa dịch xong → dịch lại
            if retranslate:
                log.info("[%s] Dịch lại (giữ kết quả OCR)", name)
        else:
            log.info("[%s] Dùng lại bản dịch trong %s", name, segments_json)
    if segs is None and not fresh and os.path.exists(ocr_path):
        with open(ocr_path, encoding="utf-8") as f:
            segs = json.load(f)
        log.info("[%s] Dùng lại kết quả OCR đã lưu (%d câu)", name, len(segs))
    if segs is None:
        src_mode = cfg.get("source_text", "ocr")
        if src_mode == "ocr":
            _notify("Đọc phụ đề gốc (OCR)", 0.08, "Bắt đầu quét phụ đề tiếng Trung...")
            segs = ocr_subs.extract(video, info, cfg, progress_cb=_notify)
        else:
            _notify("Nhận diện giọng nói (Whisper)", 0.08, "Đang trích xuất âm thanh và nhận diện giọng nói...")
            wav = os.path.join(tmp, "src16k.wav")
            run([ffmpeg_bin(), "-y", "-i", video, "-ac", "1", "-ar", "16000", wav])
            segs = asr.transcribe(wav, cfg, progress_cb=_notify)
        with open(ocr_path, "w", encoding="utf-8") as f:
            json.dump(segs, f, ensure_ascii=False, indent=1)
        log.info("[%s] %d câu gốc (nguồn: %s)", name, len(segs), src_mode)
    _notify("Trích xuất câu gốc", 0.35, f"Đã có {len(segs)} câu gốc")

    # 2. Dịch
    if segs and not all(s.get("dst") for s in segs):
        _notify("Dịch thuật", 0.38, "Bắt đầu dịch sang tiếng Việt...")
        gpath = os.path.join(out_dir, f"{name}.glossary.json")
        if fresh and os.path.exists(gpath):
            os.replace(gpath, gpath + ".bak")          # làm lại từ đầu → phân tích ngữ cảnh lại
        dst = translate.translate(segs, cfg, gpath, progress_cb=_notify)
        for s, d in zip(segs, dst):
            s["dst"] = d
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False, indent=1)
    _notify("Dịch thuật", 0.55, f"Đã dịch xong {len(segs)} câu")

    # 3. Lồng tiếng (bỏ qua nếu mode == 'vietsub')
    dub = None
    report = []
    do_tts = (mode in ("dubbing", "both")) and (cfg["tts"]["provider"] != "none") and bool(segs)
    if do_tts:
        _notify("Lồng tiếng", 0.58, "Đang sinh giọng đọc...")
        utts = tts.synth_all(segs, tmp, cfg, os.path.join(out_dir, ".cache", "tts"), progress_cb=_notify)
        _notify("Lồng tiếng", 0.75, "Đang ghép các lượt đọc vào timeline...")
        dub, report = tts.build_dub_track(segs, utts, info["duration"], tmp, cfg)
    elif mode == "vietsub":
        log.info("[%s] Chế độ 'Chỉ Vietsub' → bỏ qua bước lồng tiếng, giữ âm thanh gốc", name)

    # 4. Tách giọng gốc (tuỳ chọn, nặng): giữ nhạc nền
    cfg_run = dict(cfg)
    cfg_run["original_audio"] = dict(cfg.get("original_audio", {}))
    if mode == "vietsub":
        # Giữ nguyên 100% âm lượng gốc khi chỉ vietsub
        cfg_run["original_audio"]["volume"] = 1.0

    if cfg_run["original_audio"].get("mode") == "remove_voice" and info["has_audio"]:
        _notify("Tách giọng", 0.80, "Đang tách giọng gốc bằng Demucs...")
        run(["demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", tmp, video])
        bg = os.path.join(tmp, "htdemucs", name, "no_vocals.wav")
        cfg_run["original_audio"]["_bg_path"] = bg

    # 5. Phụ đề + làm mờ + xuất
    _notify("Xuất video", 0.85, "Đang làm mờ và kết xuất video...")
    box = render.blur_box(segs, info, cfg_run)
    ass = None
    do_sub = (mode in ("vietsub", "both")) and cfg_run["subtitle"].get("enabled", True)
    if do_sub:
        ass = os.path.join(tmp, "sub.ass")
        render.write_ass(segs, ass, info, box, cfg_run)
        if cfg_run["output"]["export_srt"]:
            render.write_srt(segs, os.path.join(out_dir, f"{name}.{cfg_run['target_lang']}.srt"))
    else:
        log.info("[%s] Chế độ 'Chỉ lồng tiếng' → không chèn phụ đề tiếng Việt (vẫn làm mờ sub gốc)", name)

    t_lang = cfg_run.get("target_lang", "vi")
    suffix = f"_{t_lang}" if mode == "both" else (f"_{t_lang}_sub" if mode == "vietsub" else f"_{t_lang}_dub")
    out = os.path.join(out_dir, f"{name}{suffix}.mp4")
    render.render(video, segs, info, dub, ass, out, box, cfg_run)

    if not cfg_run["output"]["keep_temp"]:
        shutil.rmtree(tmp, ignore_errors=True)
    secs = time.time() - t0
    _notify("Hoàn tất", 1.0, f"Đã xuất xong video thành công trong {secs:.1f}s!")
    log.info("[%s] Xong trong %.1fs → %s", name, secs, out)
    return {"output": out, "segments": seg_path, "blur_box": box, "seconds": round(secs, 1),
            "mode": mode, "overflow_lines": [r for r in report if r["overflow"] > 0.05]}
