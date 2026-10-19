"""Web Server cho VideoDub Studio sử dụng FastAPI, Uvicorn và Server-Sent Events (SSE).
Hỗ trợ tải video qua link (Douyin/TikTok/YouTube), tải file trực tiếp,
xóa logo/watermark, dán logo thương hiệu, dịch tiếng Việt/Anh,
làm mờ hoặc đặt sub mới bên dưới sub gốc, hiển thị tiến trình ô tròn và stream log trực tiếp.
"""
import asyncio, copy, json, os, re, shutil, subprocess, sys, time, uuid
import webbrowser
from typing import Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .config import load_config
from .pipeline import process
from .downloader import download_video, extract_url
from .utils import ROOT, log, ffmpeg_bin

app = FastAPI(title="VideoDub Studio Web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(ROOT, "static")
INPUT_DIR = os.path.join(ROOT, "input")
OUTPUT_DIR = os.path.join(ROOT, "output")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Mount static và output files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Quản lý trạng thái và hàng đợi tác vụ trong bộ nhớ
# task_id -> { "status": "running"|"completed"|"failed", "percent": 0.0, "step_index": 0, "step_name": "", "message": "", "logs": [], "result": {} }
TASKS: Dict[str, Dict[str, Any]] = {}
TASK_LISTENERS: Dict[str, list] = {}

def _broadcast_event(task_id: str, data: dict):
    if task_id in TASKS:
        t = TASKS[task_id]
        if "percent" in data:
            t["percent"] = data["percent"]
        if "step_index" in data:
            t["step_index"] = data["step_index"]
        if "step_name" in data:
            t["step_name"] = data["step_name"]
        if "message" in data:
            t["message"] = data["message"]
        if "log" in data:
            t["logs"].append(data["log"])
        if "status" in data:
            t["status"] = data["status"]
        if "result" in data:
            t["result"] = data["result"]

    # Đẩy cho SSE listeners
    listeners = TASK_LISTENERS.get(task_id, [])
    for q in listeners:
        try:
            q.put_nowait(data)
        except Exception:
            pass

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>VideoDub Web App: Đang khởi tạo giao diện...</h1>"

@app.get("/api/config")
async def get_config():
    cfg = load_config("config.yaml")
    # Lấy masked API key từ secrets.yaml
    api_key_masked = ""
    secrets_path = os.path.join(ROOT, "secrets.yaml")
    if os.path.exists(secrets_path):
        import yaml
        try:
            with open(secrets_path, "r", encoding="utf-8") as f:
                k = str((yaml.safe_load(f) or {}).get("gemini_api_key", "")).strip()
                if k:
                    api_key_masked = k[:6] + "..." + k[-4:] if len(k) > 10 else "******"
        except Exception:
            pass
    return {"config": cfg, "has_api_key": bool(api_key_masked), "masked_key": api_key_masked}

@app.post("/api/config/key")
async def save_api_key(payload: dict):
    key = str(payload.get("gemini_api_key", "")).strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key không được để trống")
    secrets_path = os.path.join(ROOT, "secrets.yaml")
    data = {}
    if os.path.exists(secrets_path):
        import yaml
        try:
            with open(secrets_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            pass
    data["gemini_api_key"] = key
    import yaml
    with open(secrets_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)
    return {"status": "ok", "message": "Đã lưu API Key Gemini thành công!"}

from pydantic import BaseModel

class DownloadUrlRequest(BaseModel):
    url: str

@app.post("/api/download-url")
async def api_download_url(req: DownloadUrlRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Vui lòng nhập link video")
    try:
        # Chạy downloader trong process độc lập để Playwright có main thread riêng và không bị xung đột event loop
        def _exec_dl():
            return subprocess.run(
                [sys.executable, "-m", "videodub.downloader", url, INPUT_DIR],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT
            )
        proc = await asyncio.to_thread(_exec_dl)
        out_text = proc.stdout
        err_text = proc.stderr

        m = re.search(r"__RESULT_JSON__(.*)", out_text)
        if m:
            res = json.loads(m.group(1).strip())
            return {
                "status": "ok",
                "video_path": res["path"],
                "title": res["title"],
                "duration": res["duration"],
                "thumbnail": res.get("thumbnail"),
                "filename": os.path.basename(res["path"]),
            }
        else:
            log.warning("Lỗi tải video process (exit code %s):\nstdout: %s\nstderr: %s", proc.returncode, out_text, err_text)
            clean_err = "Không thể tải video từ liên kết này."
            for line in (err_text + "\n" + out_text).splitlines():
                if "RuntimeError:" in line or "ValueError:" in line:
                    clean_err = line.split(":", 1)[1].strip()
                    break
            raise HTTPException(status_code=400, detail=clean_err)
    except HTTPException:
        raise
    except Exception as e:
        log.warning("Lỗi tải video từ URL %s: %s", url, e)
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/upload-video")
async def api_upload_video(file: UploadFile = File(...)):
    filename = file.filename
    clean_name = re.sub(r"[^\w\.-]", "_", filename)
    target_path = os.path.join(INPUT_DIR, clean_name)
    with open(target_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {
        "status": "ok",
        "video_path": target_path,
        "filename": clean_name,
        "title": os.path.splitext(clean_name)[0]
    }

@app.post("/api/upload-logo")
async def api_upload_logo(file: UploadFile = File(...)):
    filename = file.filename
    clean_name = "brand_" + re.sub(r"[^\w\.-]", "_", filename)
    target_path = os.path.join(INPUT_DIR, clean_name)
    with open(target_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {
        "status": "ok",
        "logo_path": target_path,
        "filename": clean_name
    }

@app.post("/api/open-folder")
async def api_open_folder():
    if sys.platform == "win32":
        os.startfile(os.path.abspath(OUTPUT_DIR))
        return {"status": "ok", "message": "Đã mở thư mục output"}
    return {"status": "ok", "message": "Hệ thống không hỗ trợ mở cửa sổ tự động"}

@app.api_route("/api/preview-video", methods=["GET", "HEAD"])
async def api_preview_video(filename: str):
    """Phát video trực tiếp trong trình duyệt (HTML5 video player) hỗ trợ cả GET, HEAD và tua Range bytes."""
    import urllib.parse
    clean_name = os.path.basename(urllib.parse.unquote(filename))
    target_path = os.path.join(OUTPUT_DIR, clean_name)
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file: {clean_name}")
    # ĐẶC BIỆT: Không truyền filename vào FileResponse để tránh Starlette tự gắn Content-Disposition: attachment
    # Đảm bảo trình duyệt phát ngay lập tức trên popup player thay vì tải về
    return FileResponse(target_path, media_type="video/mp4", content_disposition_type="inline")

@app.get("/api/download-video")
async def api_download_video(filename: str):
    """Tải video MP4 về máy với Content-Disposition: attachment."""
    import urllib.parse
    clean_name = os.path.basename(urllib.parse.unquote(filename))
    target_path = os.path.join(OUTPUT_DIR, clean_name)
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file: {clean_name}")
    return FileResponse(target_path, media_type="video/mp4", filename=clean_name, content_disposition_type="attachment")

@app.get("/api/download-srt")
async def api_download_srt(filename: str):
    """Tải file phụ đề .SRT về máy."""
    import urllib.parse
    clean_name = os.path.basename(urllib.parse.unquote(filename))
    target_path = os.path.join(OUTPUT_DIR, clean_name)
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file SRT: {clean_name}")
    return FileResponse(target_path, media_type="text/plain; charset=utf-8", filename=clean_name, content_disposition_type="attachment")

@app.get("/api/latest-result")
async def api_latest_result():
    """Lấy thông tin video xuất gần nhất trong thư mục output để xem lại trên popup bất kỳ lúc nào."""
    if not os.path.exists(OUTPUT_DIR):
        raise HTTPException(status_code=404, detail="Chưa có thư mục output")
    
    mp4_files = [f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".mp4")]
    if not mp4_files:
        raise HTTPException(status_code=404, detail="Chưa có video nào trong thư mục output")
    
    mp4_files.sort(key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)), reverse=True)
    latest_mp4 = mp4_files[0]
    
    base_name = os.path.splitext(latest_mp4)[0]
    clean_base = re.sub(r"_(?:vi|en)(?:_sub|_dub)?$", "", base_name)
    
    actual_srt = None
    for cand in [f"{clean_base}.vi.srt", f"{clean_base}.en.srt", f"{clean_base}.srt", f"{base_name}.vi.srt", f"{base_name}.en.srt", f"{base_name}.srt"]:
        if os.path.exists(os.path.join(OUTPUT_DIR, cand)):
            actual_srt = cand
            break
            
    import urllib.parse
    encoded_mp4 = urllib.parse.quote(latest_mp4)
    encoded_srt = urllib.parse.quote(actual_srt) if actual_srt else None
    
    return {
        "output_path": os.path.join(OUTPUT_DIR, latest_mp4),
        "filename": latest_mp4,
        "video_url": f"/api/preview-video?filename={encoded_mp4}",
        "download_url": f"/api/download-video?filename={encoded_mp4}",
        "direct_video_url": f"/output/{encoded_mp4}",
        "srt_url": f"/api/download-srt?filename={encoded_srt}" if actual_srt else None,
        "seconds": 0,
        "mode": "vietsub",
        "target_lang": "vi"
    }



@app.post("/api/start-process")
async def api_start_process(payload: dict, background_tasks: BackgroundTasks):
    video_path = payload.get("video_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=400, detail="Không tìm thấy file video đầu vào")

    task_id = str(uuid.uuid4())[:8]
    TASKS[task_id] = {
        "task_id": task_id,
        "status": "running",
        "percent": 0.05,
        "step_index": 0,
        "step_name": "Chuẩn bị",
        "message": "Đang chuẩn bị video...",
        "logs": [f"[{time.strftime('%H:%M:%S')}] Khởi tạo tác vụ {task_id}..."],
        "result": None,
    }
    TASK_LISTENERS[task_id] = []

    background_tasks.add_task(_run_pipeline_task, task_id, video_path, payload)
    return {"task_id": task_id, "status": "running"}

def _run_pipeline_task(task_id: str, video_path: str, payload: dict):
    """Tiến trình thực thi pipeline xử lý video với mapping 6 ô tròn trực quan."""
    cfg = load_config("config.yaml")

    # Áp dụng các tùy chọn từ Web UI
    target_lang = payload.get("target_lang", "vi")
    cfg["target_lang"] = target_lang

    # Tự động nạp ngữ cảnh từ tiêu đề video và ghi chú người dùng
    user_context = payload.get("context", "").strip()
    video_title = payload.get("title", "").strip()
    if not video_title:
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_title = re.sub(r"_\d{15,25}$", "", base_name).strip()

    ctx_parts = []
    if video_title:
        ctx_parts.append(f"Tiêu đề: {video_title}")
    if user_context and user_context != video_title:
        ctx_parts.append(f"Chủ đề/Ngữ cảnh: {user_context}")
    existing_ctx = cfg["translate"].get("context", "").strip()
    if existing_ctx and existing_ctx not in ctx_parts:
        ctx_parts.append(existing_ctx)
    if ctx_parts:
        cfg["translate"]["context"] = " | ".join(ctx_parts)
        log.info("  🎯 Ngữ cảnh nạp vào Gemini: %s", cfg["translate"]["context"])

    mode = payload.get("mode", "vietsub") # vietsub | dubbing | both

    # Tùy chọn làm mờ sub cũ vs để nguyên sub gốc
    blur_old_sub = payload.get("blur_old_sub", True)
    cfg["blur"]["enabled"] = bool(blur_old_sub)
    if payload.get("blur_mode"):
        cfg["blur"]["mode"] = payload["blur_mode"] # box | band
    if payload.get("blur_padding"):
        cfg["blur"]["padding"] = int(payload["blur_padding"])

    # Tùy chọn nguồn trích xuất phụ đề: ocr (quét hardsub) | asr (nghe giọng Whisper)
    source_text = payload.get("source_text", "ocr")
    cfg["source_text"] = source_text
    if payload.get("whisper_model"):
        cfg["asr"]["model"] = payload["whisper_model"]
    if payload.get("whisper_provider"):
        cfg["asr"]["provider"] = payload["whisper_provider"]

    # Tùy chọn vùng quét nhận diện sub gốc (cho OCR)
    if payload.get("ocr_region_preset"):
        cfg["ocr"]["region_preset"] = payload["ocr_region_preset"] # auto | bottom_tight | bottom_standard | bottom_wide | full
    if payload.get("ocr_fps"):
        cfg["ocr"]["fps"] = float(payload["ocr_fps"])

    # Tùy chọn giọng đọc
    if payload.get("tts_provider"):
        cfg["tts"]["provider"] = payload["tts_provider"] # edge | supertonic | openai

    # Tùy chọn xóa logo video gốc
    logo_remove_enabled = payload.get("logo_remove_enabled", False)
    cfg["logo_remove"] = {
        "enabled": bool(logo_remove_enabled),
        "position": payload.get("logo_remove_pos", "top_left"),
        "strength": int(payload.get("logo_remove_strength", 25))
    }

    # Tùy chọn dán logo thương hiệu riêng
    brand_logo_enabled = payload.get("brand_logo_enabled", False)
    brand_logo_path = payload.get("brand_logo_path", "")
    cfg["brand_logo"] = {
        "enabled": bool(brand_logo_enabled and brand_logo_path and os.path.exists(brand_logo_path)),
        "path": brand_logo_path,
        "corner": payload.get("brand_logo_corner", "top_right"),
        "width": int(payload.get("brand_logo_width", 120)),
        "margin": int(payload.get("brand_logo_margin", 20))
    }

    # 6 Bước trong UI:
    # 0: Nhận Video
    # 1: Quét Sub (OCR)
    # 2: Dịch AI
    # 3: Lồng Tiếng (TTS)
    # 4: Xử lý Logo & Mờ
    # 5: Kết xuất Video (Render)
    def _progress(step_title: str, pct: float, msg: str):
        t_str = time.strftime('%H:%M:%S')
        step_idx = 0
        if "OCR" in step_title or "phụ đề gốc" in step_title or "Whisper" in step_title or "giọng nói" in step_title or "Trích xuất" in step_title:
            step_idx = 1
        elif "Dịch" in step_title or "Gemini" in step_title:
            step_idx = 2
        elif "Lồng tiếng" in step_title or "giọng" in step_title:
            step_idx = 3
        elif "mờ" in step_title or "Logo" in step_title:
            step_idx = 4
        elif "Xuất" in step_title or "kết xuất" in step_title:
            step_idx = 5
        elif "Hoàn tất" in step_title:
            step_idx = 5

        log_line = f"[{t_str}] [{step_title}] {msg}"
        _broadcast_event(task_id, {
            "percent": pct,
            "step_index": step_idx,
            "step_name": step_title,
            "message": msg,
            "log": log_line
        })

    try:
        _progress("Nhận Video", 0.08, f"Đang nạp video {os.path.basename(video_path)}...")
        is_fresh = payload.get("fresh", True)
        res = process(video_path, OUTPUT_DIR, cfg, fresh=is_fresh, mode=mode, progress_cb=_progress)

        out_file = res["output"]
        out_name = os.path.basename(out_file)
        
        # Tìm file SRT tương ứng (hỗ trợ cả suffix ngôn ngữ và tên gốc)
        base_name = os.path.splitext(out_name)[0]
        clean_base = re.sub(r"_(?:vi|en)(?:_sub|_dub)?$", "", base_name)
        
        srt_candidates = [
            f"{clean_base}.{target_lang}.srt",
            f"{clean_base}.srt",
            f"{base_name}.srt",
            f"{base_name}.{target_lang}.srt"
        ]
        actual_srt_name = None
        for cand in srt_candidates:
            cand_path = os.path.join(OUTPUT_DIR, cand)
            if os.path.exists(cand_path):
                actual_srt_name = cand
                break

        import urllib.parse
        encoded_out_name = urllib.parse.quote(out_name)
        encoded_srt_name = urllib.parse.quote(actual_srt_name) if actual_srt_name else None

        result_data = {
            "output_path": out_file,
            "filename": out_name,
            "video_url": f"/api/preview-video?filename={encoded_out_name}",
            "download_url": f"/api/download-video?filename={encoded_out_name}",
            "direct_video_url": f"/output/{encoded_out_name}",
            "srt_url": f"/api/download-srt?filename={encoded_srt_name}" if actual_srt_name else None,
            "seconds": res.get("seconds", 0),
            "mode": mode,
            "target_lang": target_lang
        }

        _broadcast_event(task_id, {
            "status": "completed",
            "percent": 1.0,
            "step_index": 5,
            "step_name": "Hoàn tất",
            "message": f"Đã xuất xong video thành công trong {res.get('seconds', 0)}s!",
            "log": f"[{time.strftime('%H:%M:%S')}] 🎉 HOÀN THÀNH: {out_name}",
            "result": result_data
        })
    except Exception as e:
        log.exception("Lỗi trong quá trình xử lý video: %s", e)
        _broadcast_event(task_id, {
            "status": "failed",
            "message": f"Lỗi: {str(e)}",
            "log": f"[{time.strftime('%H:%M:%S')}] ❌ LỖI: {str(e)}"
        })

@app.get("/api/progress-sse/{task_id}")
async def sse_task_progress(task_id: str, request: Request):
    """Server-Sent Events (SSE) để stream tiến trình và log thời gian thực về trình duyệt."""
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ")

    queue = asyncio.Queue()
    TASK_LISTENERS.setdefault(task_id, []).append(queue)

    async def event_generator():
        # Gửi dữ liệu hiện tại trước
        curr = TASKS[task_id]
        yield f"data: {json.dumps(curr, ensure_ascii=False)}\n\n"

        while True:
            if await request.is_disconnected():
                break
            try:
                # Chờ sự kiện mới hoặc timeout sau 15s để gửi ping giữ kết nối
                data = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("status") in ("completed", "failed"):
                    break
            except asyncio.TimeoutError:
                # Gửi heartbeat
                yield ": ping\n\n"
            except Exception:
                break

        # Dọn dẹp listener khi ngắt kết nối
        if task_id in TASK_LISTENERS and queue in TASK_LISTENERS[task_id]:
            TASK_LISTENERS[task_id].remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

def _get_local_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def start_server(host: Optional[str] = None, port: Optional[int] = None, open_browser: bool = True):
    if host is None:
        host = os.getenv("VIDEODUB_HOST", "0.0.0.0")
    if port is None:
        port = int(os.getenv("VIDEODUB_PORT", "7860"))

    for arg in sys.argv[1:]:
        if arg.startswith("--host="):
            host = arg.split("=", 1)[1]
        elif arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError:
                pass
        elif arg == "--no-browser":
            open_browser = False

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    import uvicorn
    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host

    if open_browser:
        def _open():
            time.sleep(1.5)
            try:
                webbrowser.open(f"http://{browser_host}:{port}")
            except Exception:
                pass
        import threading
        threading.Thread(target=_open, daemon=True).start()

    lan_ip = _get_local_ip()
    print(f"\n========================================================")
    print(f"  VIDEODUB STUDIO WEB APP DANG CHAY")
    print(f"  - May cua ban (Local)        : http://127.0.0.1:{port}")
    if host in ("0.0.0.0", "::") and lan_ip != "127.0.0.1":
        print(f"  - Chia se team (cung Wi-Fi)  : http://{lan_ip}:{port}")
    print(f"========================================================\n")
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    start_server()
