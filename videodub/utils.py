import json, logging, os, shutil, subprocess

log = logging.getLogger("videodub")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = _ROOT  # thư mục VideoDub

def ffmpeg_bin(name="ffmpeg"):
    """Tìm ffmpeg/ffprobe: biến môi trường FFMPEG_DIR → thư mục bin/ của project → PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    for d in (os.environ.get("FFMPEG_DIR"), os.path.join(_ROOT, "bin")):
        if d and os.path.isfile(os.path.join(d, exe)):
            return os.path.join(d, exe)
    p = shutil.which(name)
    if not p:
        raise RuntimeError(f"Không tìm thấy {name}. Bỏ {exe} vào thư mục bin/ hoặc cài ffmpeg và thêm vào PATH.")
    return p

def run(cmd):
    log.debug(" ".join(map(str, cmd)))
    r = subprocess.run(list(map(str, cmd)), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"Lệnh lỗi: {cmd[0]}\n{r.stderr[-2000:]}")
    return r.stdout

def probe(path):
    out = run([ffmpeg_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path])
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    num, den = v.get("r_frame_rate", "30/1").split("/")
    return {
        "width": int(v["width"]), "height": int(v["height"]),
        "fps": float(num) / float(den or 1),
        "duration": float(d["format"]["duration"]),
        "has_audio": any(s["codec_type"] == "audio" for s in d["streams"]),
    }

def audio_duration(path):
    out = run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.strip())

def fmt_srt_time(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
