import os, re, subprocess
import requests
import yt_dlp
from .utils import ffmpeg_bin, log

def extract_url(text: str) -> str:
    """Trích xuất liên kết HTTP/HTTPS từ chuỗi chia sẻ (hỗ trợ văn bản copy từ app Douyin/TikTok)."""
    match = re.search(r"https?://[^\s'\"<>]+", text.strip())
    if match:
        url = match.group(0).rstrip(".,;!?:，。、！'\"")
        return url
    return text.strip()

def _find_browser_executable() -> str:
    """Tìm trình duyệt Google Chrome hoặc Microsoft Edge đã cài đặt trên máy tính."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None

def _parse_netscape_cookies(cookie_file: str) -> list:
    """Đọc cookie từ định dạng Netscape cookies.txt để nạp vào Playwright."""
    cookies = []
    if not cookie_file or not os.path.exists(cookie_file):
        return cookies
    try:
        with open(cookie_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookies.append({
                        "name": parts[5],
                        "value": parts[6],
                        "domain": parts[0],
                        "path": parts[2],
                        "secure": parts[3].lower() == "true",
                        "httpOnly": False,
                        "sameSite": "Lax",
                    })
    except Exception as e:
        log.warning("Lỗi đọc file cookie: %s", e)
    return cookies

def _download_stream_to_file(stream_url: str, dest_path: str, label: str = "video", progress_cb=None, base_pct=0.4, span_pct=0.35):
    """Tải trực tiếp luồng stream CDN qua HTTP streaming chunk, tránh timeout Playwright 30s và tràn RAM."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
        "Accept": "*/*",
    }
    with requests.get(stream_url, headers=headers, stream=True, timeout=(20, 300)) as resp:
        resp.raise_for_status()
        total_size = int(resp.headers.get("content-length") or 0)
        downloaded = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total_size > 0:
                        frac = downloaded / total_size
                        mb_done = downloaded / (1024 * 1024)
                        mb_total = total_size / (1024 * 1024)
                        progress_cb("Tải Douyin", min(0.99, base_pct + frac * span_pct), f"Đang tải {label}: {mb_done:.1f}/{mb_total:.1f} MB ({int(frac*100)}%)")

def _resolve_douyin_url(raw_url: str) -> tuple[str, str]:
    """Phân giải mọi định dạng link Douyin (short link v.douyin.com, mobile share, jingxuan, video ID)
    thành (vid_id, target_url).
    """
    clean_url = extract_url(raw_url)

    # Nếu là link rút gọn v.douyin.com, gọi GET để lấy URL chuyển hướng thực tế
    if "v.douyin.com" in clean_url:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            }
            resp = requests.get(clean_url, headers=headers, allow_redirects=False, timeout=10)
            if "Location" in resp.headers:
                clean_url = resp.headers["Location"]
            elif resp.history:
                clean_url = resp.url
            else:
                resp2 = requests.get(clean_url, headers=headers, allow_redirects=True, timeout=10)
                clean_url = resp2.url
        except Exception as e:
            log.warning("Lỗi phân giải link rút gọn Douyin: %s", e)

    # Trích xuất ID video
    vid_id = None
    m = re.search(r"(?:/video/|modal_id=|aweme_id=)(\d+)", clean_url)
    if m:
        vid_id = m.group(1)
    else:
        m_digits = re.search(r"(\d{15,25})", clean_url)
        if m_digits:
            vid_id = m_digits.group(1)

    if vid_id:
        target_url = f"https://www.douyin.com/video/{vid_id}"
    else:
        vid_id = "douyin"
        target_url = clean_url

    return vid_id, target_url

def _download_douyin_playwright(url: str, output_dir: str, progress_cb=None) -> dict:
    """Ngách tải video Douyin tốc độ cao bằng headless Chrome:
    Vượt qua triệt để tường lửa ArgusSecurityPlugin 403 Forbidden của ByteDance
    bằng cách lắng nghe trực tiếp luồng stream CDN (video + audio) và ghép lại với FFmpeg.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Chưa cài đặt thư viện playwright. Hãy cài đặt: pip install playwright")

    browser_path = _find_browser_executable()
    vid_id, target_url = _resolve_douyin_url(url)
    log.info("Douyin resolved: ID=%s, URL=%s", vid_id, target_url)

    if progress_cb:
        progress_cb("Tải Douyin", 0.1, "Đang kết nối trình duyệt ngầm để phân tích video Douyin...")

    video_stream_url = None
    audio_stream_url = None
    single_stream_url = None
    page_title = "douyin_video"

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--mute-audio",
        "--no-sandbox",
        "--disable-gpu",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-web-security",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=browser_path,
            headless=True,
            args=launch_args,
        )

        # Sử dụng clean context không nạp cookie cũ để tránh bị Douyin redirect vào '验证码中间页' (Captcha)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        def on_response(response):
            nonlocal video_stream_url, audio_stream_url, single_stream_url
            u = response.url

            # Bỏ qua tài nguyên tĩnh (placeholder dummy video, hình ảnh preview, etc.)
            if any(k in u for k in ["douyinstatic.com", "douyinpic.com", "iesdouyin.com/share", "uuu_265.mp4"]):
                return

            if any(k in u for k in ["zjcdn.com", "douyinvod.com", "bytevcloud", "snssdk.com", "amemv.com", "tiktokcdn.com"]):
                if "media-video" in u and not video_stream_url:
                    video_stream_url = u
                    log.info("Đã bắt được luồng hình ảnh Douyin (video)")
                elif "media-audio" in u and not audio_stream_url:
                    audio_stream_url = u
                    log.info("Đã bắt được luồng âm thanh Douyin (audio)")
                elif ("video/tos" in u or ".mp4" in u or "mime_type=video_mp4" in u) and not single_stream_url and not video_stream_url:
                    if "media-audio" not in u:
                        single_stream_url = u
                        log.info("Đã bắt được luồng video đơn Douyin (mp4)")

        page.on("response", on_response)

        if progress_cb:
            progress_cb("Tải Douyin", 0.25, "Đang nạp video và giải mã luồng phát Douyin...")

        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e_nav:
            log.warning("Playwright goto cảnh báo: %s", e_nav)

        # Chờ tối đa 25 giây (50 x 500ms) để bắt được luồng stream phát
        for i in range(50):
            if (video_stream_url and audio_stream_url) or (single_stream_url and i >= 10):
                break

            # Tự động tắt popup đăng nhập / hướng dẫn và kích hoạt video play
            try:
                page.evaluate("""() => {
                    const closeBtns = document.querySelectorAll('.dy-account-close, [aria-label="Close"], .login-guide-container svg, .semi-modal-close, .dy-modal-close');
                    closeBtns.forEach(b => b.click());
                    const vids = document.querySelectorAll('video');
                    vids.forEach(v => {
                        v.muted = true;
                        v.play().catch(() => {});
                    });
                }""")
            except Exception:
                pass

            page.wait_for_timeout(500)

        # Trích xuất tiêu đề video
        try:
            pt = page.title().replace(" - 抖音", "").strip()
            if pt and "验证码" not in pt and pt != "抖音":
                page_title = pt
            else:
                extra_title = page.evaluate("""() => {
                    const h1 = document.querySelector('h1, [data-e2e="video-desc"], .video-info-detail');
                    if (h1 && h1.innerText && h1.innerText.trim()) return h1.innerText.trim();
                    const m = document.querySelector('meta[name="description"]');
                    if (m && m.content && m.content.trim()) return m.content.split(',')[0].trim();
                    return '';
                }""")
                if extra_title and "验证码" not in extra_title:
                    page_title = extra_title
            vid_match = re.search(r"/video/(\d+)", page.url)
            if vid_match:
                vid_id = vid_match.group(1)
        except Exception:
            pass

        try:
            browser.close()
        except Exception:
            pass

    if not video_stream_url and not single_stream_url:
        raise RuntimeError("Không bắt được luồng phát từ video Douyin này (có thể video bị riêng tư hoặc giới hạn).")

    # Khử toàn bộ ký tự cấm và ký tự điều khiển (newline, carriage return) trên Windows
    s_title = re.sub(r"[\r\n\t\x00-\x1f\x7f-\x9f]", " ", page_title)
    s_title = re.sub(r'[\\/*?:"<>|#]', "_", s_title)
    clean_title = re.sub(r"\s+", " ", s_title).strip(". ")[:50].strip() or "douyin_video"

    final_filename = f"{clean_title}_{vid_id}.mp4"
    final_path = os.path.join(output_dir, final_filename)
    ffmpeg_exe = ffmpeg_bin()

    import uuid
    uid_str = uuid.uuid4().hex[:6]

    if video_stream_url and audio_stream_url:
        raw_v = os.path.join(output_dir, f"_temp_v_{vid_id}_{uid_str}.mp4")
        raw_a = os.path.join(output_dir, f"_temp_a_{vid_id}_{uid_str}.mp4")
        try:
            if progress_cb:
                progress_cb("Tải Douyin", 0.4, "Đang tải dữ liệu hình ảnh gốc...")
            _download_stream_to_file(video_stream_url, raw_v, label="hình ảnh gốc", progress_cb=progress_cb, base_pct=0.4, span_pct=0.35)

            if progress_cb:
                progress_cb("Tải Douyin", 0.75, "Đang tải âm thanh gốc...")
            _download_stream_to_file(audio_stream_url, raw_a, label="âm thanh gốc", progress_cb=progress_cb, base_pct=0.75, span_pct=0.1)

            if progress_cb:
                progress_cb("Tải Douyin", 0.88, "Đang ghép hình ảnh và âm thanh...")

            cmd = [
                ffmpeg_exe, "-y",
                "-i", raw_v,
                "-i", raw_a,
                "-c:v", "copy",
                "-c:a", "aac",
                final_path
            ]
            res_merge = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            if res_merge.returncode != 0:
                log.error("Lỗi ghép ffmpeg (code %s): %s", res_merge.returncode, res_merge.stderr)
                raise RuntimeError(f"Lỗi ghép video/audio: {res_merge.stderr[-200:].strip() or 'Unknown ffmpeg error'}")
        finally:
            if os.path.exists(raw_v):
                try: os.remove(raw_v)
                except Exception: pass
            if os.path.exists(raw_a):
                try: os.remove(raw_a)
                except Exception: pass

    elif single_stream_url or video_stream_url:
        st = single_stream_url or video_stream_url
        if progress_cb:
            progress_cb("Tải Douyin", 0.5, "Đang tải luồng video trực tiếp...")
        _download_stream_to_file(st, final_path, label="video trực tiếp", progress_cb=progress_cb, base_pct=0.5, span_pct=0.4)

    duration = 0.0
    try:
        ffprobe_exe = os.path.join(os.path.dirname(ffmpeg_exe), "ffprobe.exe")
        if os.path.exists(ffprobe_exe):
            cmd_probe = [
                ffprobe_exe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                final_path
            ]
            res_p = subprocess.run(cmd_probe, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            if res_p.stdout.strip():
                duration = float(res_p.stdout.strip())
    except Exception:
        pass

    res = {
        "path": os.path.abspath(final_path),
        "title": page_title,
        "duration": duration,
        "thumbnail": None,
        "id": vid_id,
        "webpage_url": url,
    }
    log.info("Vượt tường lửa Douyin thành công! File: %s (%.1fs)", res["path"], res["duration"])
    if progress_cb:
        progress_cb("Tải Douyin", 1.0, f"Đã tải xong video Douyin: {clean_title[:35]}")
    return res

def download_video(url_or_text: str, output_dir: str = "input", progress_cb=None) -> dict:
    """Tải video từ link về thư mục output_dir. Trả về dict {path, title, duration, id}."""
    url = extract_url(url_or_text)
    if not url.startswith("http"):
        if re.match(r"^\d{15,25}$", url.strip()):
            url = f"https://www.douyin.com/video/{url.strip()}"
        else:
            raise ValueError(f"Liên kết không hợp lệ: '{url}'")

    os.makedirs(output_dir, exist_ok=True)
    bin_dir = os.path.dirname(ffmpeg_bin())

    # Tự động nạp cookies nếu có trong thư mục VideoDub
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cookie_file = None
    has_session = False

    cookie_candidates = []
    for search_dir in [root_dir, output_dir]:
        if not os.path.exists(search_dir):
            continue
        for fname in os.listdir(search_dir):
            if "cookie" in fname.lower() and fname.lower().endswith(".txt"):
                cand = os.path.join(search_dir, fname)
                if os.path.exists(cand) and os.path.getsize(cand) > 10:
                    cand_session = False
                    try:
                        with open(cand, "r", encoding="utf-8", errors="ignore") as cf:
                            c_content = cf.read()
                            if "sessionid" in c_content.lower() or "passport_auth" in c_content.lower():
                                cand_session = True
                    except Exception:
                        pass
                    cookie_candidates.append({
                        "path": cand,
                        "has_session": cand_session,
                        "is_douyin": "douyin" in fname.lower(),
                        "mtime": os.path.getmtime(cand)
                    })

    if cookie_candidates:
        cookie_candidates.sort(key=lambda x: (x["has_session"], x["is_douyin"], x["mtime"]), reverse=True)
        best = cookie_candidates[0]
        cookie_file = best["path"]
        has_session = best["has_session"]

    is_douyin = "douyin.com" in url or "iesdouyin.com" in url

    # Nếu là link Douyin, kích hoạt bộ giải mã trực tiếp Playwright Headless Browser
    if is_douyin:
        log.info("Phát hiện link Douyin, kích hoạt bộ giải mã trực tiếp Playwright Headless Browser...")
        try:
            return _download_douyin_playwright(url, output_dir, progress_cb=progress_cb)
        except Exception as e_pw:
            log.error("Lỗi khi tải video Douyin: %s", e_pw)
            raise RuntimeError(
                f"Không thể tải video từ link Douyin ({e_pw}). Bạn có thể mở video trên Douyin tải về máy tính và kéo thả vào tab '📁 Kéo Thả File' để hệ thống xử lý ngay!"
            ) from e_pw

    def _hook(d):
        if progress_cb and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            pct = (downloaded / total * 100) if total > 0 else 0
            speed = d.get("speed") or 0
            speed_mb = speed / (1024 * 1024) if speed else 0
            progress_cb("Tải video", min(0.99, pct / 100.0), f"Đang tải: {pct:.1f}% ({speed_mb:.1f} MB/s)")
        elif progress_cb and d.get("status") == "finished":
            progress_cb("Tải video", 1.0, "Tải xong, đang hoàn tất file...")

    ydl_opts = {
        "outtmpl": os.path.join(output_dir, "%(title).60s_%(id)s.%(ext)s"),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "ffmpeg_location": bin_dir,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_hook],
    }

    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file
        log.info("Đã nạp file cookie: %s (Có session: %s)", os.path.basename(cookie_file), has_session)

    log.info("Bắt đầu tải video từ link: %s", url)
    if progress_cb:
        progress_cb("Tải video", 0.05, f"Đang phân tích link video {url[:45]}...")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            target_file = filename if os.path.exists(filename) else f"{base}.mp4"
            if not os.path.exists(target_file):
                for ext in (".mp4", ".mkv", ".webm", ".mov"):
                    cand = f"{base}{ext}"
                    if os.path.exists(cand):
                        target_file = cand
                        break

            if not os.path.exists(target_file):
                raise FileNotFoundError(f"Không tìm thấy file video sau khi tải từ {url}")

            res = {
                "path": os.path.abspath(target_file),
                "title": info.get("title", os.path.basename(target_file)),
                "duration": info.get("duration", 0),
                "thumbnail": info.get("thumbnail"),
                "id": info.get("id", ""),
                "webpage_url": info.get("webpage_url", url),
            }
            log.info("Tải video thành công: %s (%.1fs)", res["path"], res["duration"])
            if progress_cb:
                progress_cb("Tải video", 1.0, f"Đã tải xong: {res['title'][:40]}")
            return res
    except Exception as e:
        log.warning("Lỗi yt-dlp khi tải video: %s", e)
        raise

if __name__ == "__main__":
    import json, sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) > 1:
        target = sys.argv[1]
        out_d = sys.argv[2] if len(sys.argv) > 2 else "input"
        res = download_video(target, output_dir=out_d)
        print("__RESULT_JSON__" + json.dumps(res, ensure_ascii=False))
