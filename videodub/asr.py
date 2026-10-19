"""Nhận dạng giọng nói trích xuất phụ đề (Whisper AI / Faster-Whisper / OpenAI Whisper API)."""
import os, time
from .utils import log, ROOT

_WHISPER_MODELS = {}

def transcribe(audio_path, cfg, progress_cb=None):
    """Trích xuất phụ đề từ file âm thanh: trả về danh sách [{'start': t0, 'end': t1, 'src': text, 'bbox': None}]."""
    ac = cfg.get("asr", {})
    provider = ac.get("provider", "local")
    model_name = ac.get("model", "small")

    # 1. Tùy chọn sử dụng OpenAI Whisper Cloud API (Siêu tốc ~5-10s)
    if provider == "openai" or model_name == "openai":
        return _transcribe_openai(audio_path, cfg, progress_cb=progress_cb)

    # 2. Mặc định: Chạy Faster-Whisper cục bộ trên máy (offline, miễn phí)
    return _transcribe_local(audio_path, cfg, progress_cb=progress_cb)

def _transcribe_local(audio_path, cfg, progress_cb=None):
    from faster_whisper import WhisperModel
    import soundfile as sf
    ac = cfg.get("asr", {})
    model_name = ac.get("model", "small")
    if model_name == "openai":
        model_name = "small"

    device = ac.get("device", "auto")
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"

    compute_type = "float16" if device == "cuda" else ac.get("compute_type", "int8")
    cpu_threads = int(ac.get("cpu_threads", 4))

    cache_key = (model_name, device, compute_type)
    if cache_key not in _WHISPER_MODELS:
        log.info("Đang nạp mô hình Whisper '%s' trên %s (%s, %d threads)...", model_name, device, compute_type, cpu_threads)
        if progress_cb:
            progress_cb("Whisper AI", 0.08, f"Đang nạp mô hình Whisper ({model_name})...")
        _WHISPER_MODELS[cache_key] = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads
        )

    model = _WHISPER_MODELS[cache_key]

    # Đọc audio bằng soundfile thành numpy float32 để bypass lỗi PyAV metadata_errors và tăng tốc giải mã
    audio_data = None
    total_dur = 0.0
    try:
        data, sr = sf.read(audio_path, dtype="float32")
        total_dur = len(data) / sr
        if len(data.shape) > 1 and data.shape[1] > 1:
            data = data.mean(axis=1)
        audio_data = data
    except Exception as e_read:
        log.warning("Không đọc được bằng soundfile (%s) → dùng đường dẫn trực tiếp", e_read)
        audio_data = audio_path

    log.info("Whisper: Bắt đầu nhận diện giọng nói (ngôn ngữ: %s, audio: %.1fs)...", cfg["source_lang"], total_dur)
    if progress_cb:
        progress_cb("Whisper AI", 0.12, "Đang nghe và chuyển giọng nói thành văn bản...")

    t0 = time.time()
    segments_gen, info = model.transcribe(
        audio_data,
        language=cfg.get("source_lang", "zh"),
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=450)
    )

    out = []
    for s in segments_gen:
        text = s.text.strip()
        if not text:
            continue
        out.append({
            "start": round(s.start, 3),
            "end": round(s.end, 3),
            "src": text,
            "bbox": None
        })
        if total_dur > 0 and progress_cb:
            pct = min(0.35, 0.12 + 0.23 * (s.end / total_dur))
            progress_cb("Whisper AI", pct, f"Đã nhận diện {s.end:.1f}s/{total_dur:.1f}s ({len(out)} câu)...")

    elapsed = time.time() - t0
    log.info("Whisper hoàn tất: %d câu trong %.1fs (tốc độ %.1fx realtime)",
             len(out), elapsed, (total_dur / elapsed) if elapsed > 0 and total_dur > 0 else 1.0)
    return out

def _transcribe_openai(audio_path, cfg, progress_cb=None):
    """Trích xuất phụ đề qua OpenAI Whisper API (whisper-1). Tốc độ 5-10s cho cả video."""
    import requests
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        path = os.path.join(ROOT, "secrets.yaml")
        if os.path.exists(path):
            import yaml
            with open(path, encoding="utf-8") as f:
                key = str((yaml.safe_load(f) or {}).get("openai_api_key", "")).strip()

    if not key:
        log.warning("Chưa có openai_api_key trong secrets.yaml → tự động chuyển sang Faster-Whisper cục bộ")
        return _transcribe_local(audio_path, cfg, progress_cb=progress_cb)

    if progress_cb:
        progress_cb("Whisper API", 0.12, "Đang gửi âm thanh lên OpenAI Whisper API...")

    log.info("Whisper: Đang gửi audio lên OpenAI Whisper API...")
    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {key}"}

    with open(audio_path, "rb") as f:
        files = {"file": (os.path.basename(audio_path), f, "audio/wav")}
        data = {
            "model": "whisper-1",
            "language": cfg.get("source_lang", "zh"),
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment"
        }
        try:
            r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
            if r.status_code == 200:
                res = r.json()
                raw_segs = res.get("segments", [])
                out = []
                for s in raw_segs:
                    txt = s.get("text", "").strip()
                    if txt:
                        out.append({
                            "start": round(float(s["start"]), 3),
                            "end": round(float(s["end"]), 3),
                            "src": txt,
                            "bbox": None
                        })
                log.info("OpenAI Whisper API thành công: %d câu", len(out))
                return out
            else:
                log.warning("OpenAI Whisper API lỗi HTTP %d: %s → chuyển sang local", r.status_code, r.text[:100])
        except Exception as e:
            log.warning("OpenAI Whisper API lỗi kết nối: %s → chuyển sang local", e)

    return _transcribe_local(audio_path, cfg, progress_cb=progress_cb)
