import asyncio, hashlib, json, os, re, time
import numpy as np
import soundfile as sf
from .utils import ffmpeg_bin, run, audio_duration, log, ROOT

SR = 44100

def _voice_map(segs, tc):
    """Chọn giọng cho từng câu theo nhân vật / giới tính (Gemini gắn sẵn speaker + gender khi dịch).
    Mỗi nhân vật giữ cố định 1 giọng suốt video; câu không rõ người nói dùng giọng mặc định."""
    p = tc["provider"]
    pv = tc.get(p, {}) if isinstance(tc.get(p), dict) else {}
    default = pv.get("voice", tc.get("voice"))
    male = pv.get("male_voices") or ([tc.get("male_voice")] if tc.get("male_voice") else [])
    female = pv.get("female_voices") or ([tc.get("female_voice")] if tc.get("female_voice") else [])
    fixed = {k: v for k, v in (tc.get("speaker_voices") or {}).items()}   # gán tay: {"Tôn Ngộ Không": "M2"}
    assigned, used = dict(fixed), {"male": 0, "female": 0}
    out = []
    for sg in segs:
        spk, g = (sg.get("speaker") or "").strip(), (sg.get("gender") or "").lower()
        if not tc.get("multi_voice", True) or not spk:
            out.append(default if not g or not tc.get("multi_voice", True) else
                       (male[0] if g == "male" and male else female[0] if g == "female" and female else default))
            continue
        if spk not in assigned:
            pool = male if g == "male" else female if g == "female" else []
            if pool:
                assigned[spk] = pool[used[g] % len(pool)]; used[g] += 1
            else:
                assigned[spk] = default
        out.append(assigned[spk])
    if len(set(assigned.values())) > 1:
        log.info("Giọng theo nhân vật: %s", assigned)
    return out

def synth_all(segs, tmp, cfg, cache_dir=None, progress_cb=None):
    """Sinh giọng từng câu. Có cache theo nội dung câu + giọng → chạy lại không phải gọi TTS lại câu đã làm."""
    tc = cfg["tts"]; p = tc["provider"]
    cache_dir = cache_dir or tmp
    os.makedirs(cache_dir, exist_ok=True)
    voices = _voice_map(segs, tc)
    items = []
    for u in group_utterances(segs, voices, tc):
        key = hashlib.sha1(f"{p}|{u['voice']}|{tc.get('rate')}|{json.dumps((tc.get(p) or {}), sort_keys=True) if p == 'supertonic' else ''}|{u['text']}"
                           .encode("utf-8")).hexdigest()[:16]
        u["path"] = os.path.join(cache_dir, f"{key}.{'mp3' if p in ('edge', 'openai') else 'wav'}")
        items.append(u)
    todo = [it for it in items if it["text"].strip() and not _ok(it["path"])]
    log.info("Lồng tiếng %d câu (%d câu có sẵn trong cache)", len(todo), len(items) - len(todo))
    if progress_cb:
        progress_cb("Lồng tiếng", 0.55, f"Bắt đầu lồng tiếng {len(todo)} câu...")
    failed = []
    if p == "supertonic":
        failed = _supertonic_all(todo, cfg, progress_cb=progress_cb)
        if failed and tc.get("fallback"):            # Supertonic lỗi (chưa cài / thiếu model) → dùng Edge cho các câu đó
            log.warning("Supertonic lỗi %d câu → dùng %s", len(failed), tc["fallback"])
            rest = [it for it in todo if it["text"] in failed]
            failed = _edge_with_retry(rest, tc, cfg) if tc["fallback"] == "edge" else _gtts_all(rest, cfg["target_lang"])
    elif p == "edge":
        failed = _edge_with_retry(todo, tc, cfg)
    elif p == "openai":
        failed = _openai_all(todo, tc, cfg, progress_cb=progress_cb)
    elif p == "gtts":
        failed = _gtts_all(todo, cfg["target_lang"])
    elif p == "espeak":
        for it in todo:
            run(["espeak-ng", "-v", cfg["target_lang"], "-s", "165", "-w", it["path"], it["text"]])
    else:
        raise ValueError(f"tts.provider không hợp lệ: {p}")
    if failed:
        log.warning("%d câu không tạo được giọng (để trống, video vẫn xuất): %s", len(failed), failed)
    return items

_PUNCT_END = ".,!?…;:"
def clean_tts_text(t):
    """Chuẩn hoá câu trước khi đọc: bỏ '...', ngoặc kép, ký tự lạ làm TTS ngắt nghỉ sai."""
    t = re.sub(r"\.{2,}|…", ",", t)
    t = re.sub(r"[\"“”'‘’«»()\[\]*_~]", "", t)
    t = re.sub(r"\s*,\s*(,\s*)+", ", ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    return t

def group_utterances(segs, voices, tc):
    """Gộp các câu ngắn liền nhau của CÙNG một người nói thành 1 lượt đọc.
    TTS đọc cả cụm sẽ có ngữ điệu liền mạch hơn đọc rời từng mảnh 0.75s (đỡ lủng củng, đỡ chồng chéo)."""
    gc = tc.get("group", {})
    max_gap, max_span, max_words = gc.get("max_gap", 0.35), gc.get("max_span", 6.0), gc.get("max_words", 22)
    utts = []
    for i, (sg, v) in enumerate(zip(segs, voices)):
        text = clean_tts_text(sg.get("dst", ""))
        if not text:
            continue
        cur = utts[-1] if utts else None
        who = sg.get("speaker") or v
        if (gc.get("enabled", True) and cur and cur["who"] == who and cur["text"][-1:] not in "?!"
                and sg["start"] - cur["end"] <= max_gap
                and sg["end"] - cur["start"] <= max_span and len((cur["text"] + " " + text).split()) <= max_words):
            sep = " " if cur["text"][-1:] in _PUNCT_END else ", "
            cur["text"] += sep + text; cur["end"] = sg["end"]; cur["idx"].append(i)
        else:
            utts.append({"idx": [i], "start": sg["start"], "end": sg["end"], "text": text, "voice": v, "who": who})
    for k, u in enumerate(utts):                      # khung giờ = tới lúc lượt đọc sau bắt đầu
        nxt = utts[k + 1]["start"] if k + 1 < len(utts) else u["end"] + 1.0
        u["slot"] = max(0.4, nxt - u["start"] - 0.08)
    merged = sum(len(u["idx"]) - 1 for u in utts)
    if merged:
        log.info("Gộp %d câu ngắn liền nhau → %d lượt đọc", len(segs), len(utts))
    return utts

def _edge_with_retry(todo, tc, cfg):
    ec = dict(tc, **(tc.get("edge") or {}))
    t_lang = cfg.get("target_lang", "vi")
    for it in todo:                                   # giọng Supertonic (M1/F1) không dùng được cho Edge
        if not str(it["voice"]).startswith(t_lang):
            if t_lang == "en":
                it["voice"] = "en-US-GuyNeural" if str(it["voice"]).startswith("M") else "en-US-JennyNeural"
            else:
                it["voice"] = "vi-VN-NamMinhNeural" if str(it["voice"]).startswith("M") else "vi-VN-HoaiMyNeural"
    failed = asyncio.run(_edge_all(todo, ec))
    if failed:                                        # lượt 2: Edge hay chặn tạm thời → nghỉ rồi thử lại từng câu
        pause = ec.get("retry_pause", 20)
        log.info("Edge-TTS lỗi %d câu, nghỉ %ds rồi thử lại từng câu...", len(failed), pause)
        import time; time.sleep(pause)
        failed = asyncio.run(_edge_all([it for it in todo if it["text"] in failed], dict(ec, concurrency=1, gap=1.5)))
    if failed and ec.get("fallback") in ("gtts", "edge"):   # lượt 3: giọng Google
        failed = _gtts_all([it for it in todo if it["text"] in failed], cfg["target_lang"])
    return failed

def _trim(w, sr, db=-40, keep=0.04):
    """Cắt khoảng lặng đầu/cuối (để đo đúng độ dài câu nói thật)."""
    if not len(w):
        return w
    thr = np.abs(w).max() * (10 ** (db / 20))
    idx = np.where(np.abs(w) > thr)[0]
    if not len(idx):
        return w
    k = int(keep * sr)
    return w[max(0, idx[0] - k): idx[-1] + k]

_ST = {}
def _supertonic_all(todo, cfg, progress_cb=None):
    """Supertonic 3 (chạy offline bằng ONNX trên CPU, có tiếng Việt, giọng M1–M5 / F1–F5).
    Câu dài hơn khung giờ → đọc lại với tốc độ cao hơn ngay trong model (tự nhiên hơn tua nhanh bằng ffmpeg)."""
    tc = cfg["tts"]; sc = tc.get("supertonic") or {}
    try:
        if "tts" not in _ST:
            from supertonic import TTS
            log.info("Đang nạp Supertonic (lần đầu tự tải model ~400MB)...")
            _ST["tts"] = TTS(model=sc.get("model", "supertonic-3"), auto_download=True)
        tts = _ST["tts"]
    except Exception as e:
        log.warning("Không nạp được Supertonic: %s", e)
        return [it["text"] for it in todo]
    base = float(sc.get("speed", 1.5)); top = float(sc.get("max_speed", 2.0)); steps = int(sc.get("steps", 8))
    failed = []
    for n, it in enumerate(todo, 1):
        try:
            style = _ST.setdefault(("style", it["voice"]), tts.get_voice_style(voice_name=it["voice"]))
            def say(speed):
                w, _ = tts.synthesize(it["text"], voice_style=style, lang=cfg["target_lang"], speed=speed,
                                      total_steps=steps, silence_duration=0.1)
                return _trim(np.asarray(w, dtype=np.float32).ravel(), tts.sample_rate)
            wav = say(base)
            d = len(wav) / tts.sample_rate
            if d > it["slot"] and base < top:          # quá khung giờ → model đọc nhanh hơn (tự nhiên hơn tua bằng ffmpeg)
                wav = say(min(top, base * d / it["slot"] * 1.03))
            sf.write(it["path"] + ".part.wav", wav, tts.sample_rate)
            os.replace(it["path"] + ".part.wav", it["path"])
            if progress_cb:
                progress_cb("Lồng tiếng", min(0.75, 0.55 + 0.20 * (n / max(1, len(todo)))),
                            f"Supertonic: đã đọc {n}/{len(todo)} lượt...")
            if n % 10 == 0:
                log.info("  Supertonic: xong %d/%d lượt đọc", n, len(todo))
        except Exception as e:
            log.warning("  Supertonic lỗi câu '%s': %s", it["text"][:30], e); failed.append(it["text"])
    return failed

def _ok(path):
    return os.path.exists(path) and os.path.getsize(path) > 500

async def _edge_all(todo, tc):
    """Gửi Edge-TTS. Mỗi câu thử nhanh 3 lần (1s, 3s); câu vẫn lỗi trả về để xử lý ở lượt sau, không chờ lâu."""
    import edge_tts
    sem = asyncio.Semaphore(tc.get("concurrency", 1))
    gap = tc.get("gap", 0.3)
    failed, done = [], [0]
    async def one(it):
        text, path = it["text"], it["path"]
        async with sem:
            for attempt, wait in enumerate((1, 3, 0)):
                rate = tc["rate"] if attempt < 2 else "+0%"   # lần cuối bỏ tham số tốc độ
                try:
                    # Edge đôi khi treo kết nối không trả lời → giới hạn 30s/câu thay vì chờ mãi
                    await asyncio.wait_for(edge_tts.Communicate(text, it.get("voice") or tc["voice"], rate=rate).save(path + ".part"),
                                           timeout=tc.get("timeout", 30))
                    if _ok(path + ".part"):
                        os.replace(path + ".part", path)
                        done[0] += 1
                        if done[0] % 10 == 0:
                            log.info("  Edge-TTS: xong %d/%d câu", done[0], len(todo))
                        await asyncio.sleep(gap)
                        return
                    raise RuntimeError("file rỗng")
                except Exception as e:
                    if wait:
                        log.info("  Edge-TTS lỗi '%s' (%s), thử lại", text[:30], (str(e) or type(e).__name__)[:60])
                        await asyncio.sleep(wait)
            log.warning("  Edge-TTS chưa được câu: '%s'", text[:40])
            failed.append(text)
    await asyncio.gather(*(one(it) for it in todo))
    return failed

def _gtts_all(todo, lang):
    """Giọng Google Translate (free, dự phòng khi Edge-TTS lỗi). Cần: pip install gtts"""
    try:
        from gtts import gTTS
    except ImportError:
        log.warning("Chưa cài gtts (pip install gtts) → bỏ qua giọng dự phòng")
        return [it["text"] for it in todo]
    failed = []
    for it in todo:
        text, path = it["text"], it["path"]
        try:
            gTTS(text, lang=lang).save(path + ".part"); os.replace(path + ".part", path)
            log.info("  Dùng giọng Google cho câu: '%s'", text[:40])
        except Exception as e:
            log.warning("gTTS lỗi '%s': %s", text[:30], e); failed.append(text)
    return failed

def _openai_all(todo, tc, cfg, progress_cb=None):
    """Lồng tiếng siêu tốc bằng OpenAI TTS API (tts-1 / tts-1-hd).
    Giọng đọc cực kỳ tự nhiên, đa luồng chạy mất ~10-15s cho cả video 6 phút.
    Cần openai_api_key trong secrets.yaml hoặc biến môi trường OPENAI_API_KEY."""
    import requests
    from concurrent.futures import ThreadPoolExecutor
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        path = os.path.join(ROOT, "secrets.yaml")
        if os.path.exists(path):
            import yaml
            with open(path, encoding="utf-8") as f:
                key = str((yaml.safe_load(f) or {}).get("openai_api_key", "")).strip()
    if not key:
        log.warning("Chưa có openai_api_key trong secrets.yaml → tự động chuyển sang Edge-TTS")
        return _edge_with_retry(todo, tc, cfg)

    model = tc.get("openai", {}).get("model", "tts-1")
    speed = float(tc.get("openai", {}).get("speed", 1.05))
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    failed = []
    done_count = [0]

    def _call_one(it):
        spk = str(it.get("voice") or "")
        if spk not in ("alloy", "echo", "fable", "onyx", "nova", "shimmer"):
            is_male = str(it.get("who", "")).startswith("M") or it.get("gender") == "male"
            spk = "onyx" if is_male else "nova"
        body = {
            "model": model,
            "input": it["text"],
            "voice": spk,
            "response_format": "mp3",
            "speed": speed
        }
        for attempt in range(2):
            try:
                r = requests.post("https://api.openai.com/v1/audio/speech", json=body, headers=headers, timeout=25)
                if r.status_code == 200:
                    with open(it["path"], "wb") as f:
                        f.write(r.content)
                    done_count[0] += 1
                    if progress_cb:
                        progress_cb("Lồng tiếng (OpenAI)", min(0.75, 0.55 + 0.20 * (done_count[0] / max(1, len(todo)))),
                                    f"OpenAI TTS: {done_count[0]}/{len(todo)} lượt...")
                    return True
                elif r.status_code == 429:
                    time.sleep(1.5)
            except Exception:
                pass
        failed.append(it["text"])
        return False

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(_call_one, todo))

    if failed:
        log.warning("OpenAI TTS lỗi %d câu → dịch dự phòng bằng Edge-TTS", len(failed))
        rest = [it for it in todo if it["text"] in failed]
        _edge_with_retry(rest, tc, cfg)
    return [it["text"] for it in todo if not _ok(it["path"])]

_TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
         "silenceremove=start_periods=1:start_threshold=-45dB,areverse,")   # cắt khoảng lặng đầu/cuối của file TTS

def build_dub_track(segs, utts, total_dur, tmp, cfg):
    """Xếp các lượt đọc lên timeline, không bao giờ để 2 lượt chồng tiếng lên nhau:
    - dài hơn khung giờ → tua nhanh nhẹ bằng ffmpeg (tối đa tts.max_speed; Supertonic đã tự đọc nhanh trước đó)
    - vẫn dài → lượt sau lùi lại một chút (trễ dần được bù ở các khoảng lặng)."""
    track = np.zeros(int((total_dur + 5) * SR), dtype=np.float32)
    max_speed = cfg["tts"]["max_speed"]
    gap = 0.08
    cursor = 0.0
    report = []
    for k, u in enumerate(utts):
        raw = u["path"]
        if not os.path.exists(raw):
            continue
        start = max(u["start"], cursor + gap)
        nxt = utts[k + 1]["start"] if k + 1 < len(utts) else total_dur
        slot = max(0.4, nxt - start - gap)
        wav0 = os.path.join(tmp, f"trim_{k:05}.wav")
        run([ffmpeg_bin(), "-y", "-i", raw, "-af", f"{_TRIM}aresample={SR}", "-ac", "1", wav0])
        dur = audio_duration(wav0)
        speed = min(max_speed, dur / slot) if dur > slot else 1.0
        if speed > 1.01:
            wav = os.path.join(tmp, f"fit_{k:05}.wav")
            run([ffmpeg_bin(), "-y", "-i", wav0, "-af", f"atempo={speed:.3f}", "-ac", "1", wav])
        else:
            wav = wav0
        data, _ = sf.read(wav, dtype="float32")
        fade = min(len(data) // 4, int(0.01 * SR))      # fade 10ms 2 đầu, tránh tiếng "bụp"
        if fade > 0:
            data[:fade] *= np.linspace(0, 1, fade); data[-fade:] *= np.linspace(1, 0, fade)
        a0 = int(start * SR); b0 = min(len(track), a0 + len(data))
        track[a0:b0] += data[: b0 - a0]
        final = len(data) / SR
        cursor = start + final
        delay = start - u["start"]
        report.append({"i": u["idx"], "speed": round(speed, 2), "delay": round(delay, 2), "overflow": round(max(0, final - slot), 2)})
    lag = [r for r in report if r["delay"] > 0.5]
    if lag:
        log.info("  %d lượt đọc phải lùi >0.5s (lớn nhất %.1fs) — nếu nhiều, tăng supertonic.speed hoặc giảm translate.length_factor",
                 len(lag), max(r["delay"] for r in lag))
    track = np.clip(track * cfg["dub_volume"], -1, 1)
    out = os.path.join(tmp, "dub.wav")
    sf.write(out, track[: int(total_dur * SR)], SR)
    return out, report
