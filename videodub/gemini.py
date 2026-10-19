"""Dịch phụ đề bằng Gemini theo ngữ cảnh cả phim.

Bước 1 (phân tích): gửi toàn bộ kịch bản → Gemini tóm tắt nội dung, liệt kê nhân vật, tên riêng, cách xưng hô.
         Kết quả lưu ra <tên>.glossary.json để bạn xem / sửa tay rồi chạy lại.
Bước 2 (dịch): dịch từng lô câu, kèm bản tóm tắt + bảng tên riêng + vài câu dịch trước đó để giữ mạch,
         và giới hạn độ dài theo thời lượng câu để lồng tiếng không bị đọc dồn.
"""
import json, os, time
from .utils import log, ROOT

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
LANG_NAME = {"zh": "tiếng Trung", "vi": "tiếng Việt", "en": "tiếng Anh", "th": "tiếng Thái",
             "id": "tiếng Indonesia", "ja": "tiếng Nhật", "ko": "tiếng Hàn"}
SYLLABLES_PER_SEC = 4.0   # tốc độ đọc tiếng Việt thoải mái của giọng lồng tiếng


def api_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k:
        path = os.path.join(ROOT, "secrets.yaml")
        if os.path.exists(path):
            import yaml
            with open(path, encoding="utf-8") as f:
                k = str((yaml.safe_load(f) or {}).get("gemini_api_key", "")).strip()
    if not k:
        raise RuntimeError("Chưa có Gemini API key. Tạo key tại https://aistudio.google.com/apikey rồi dán vào "
                           "file secrets.yaml (dòng gemini_api_key: ...) trong thư mục VideoDub.")
    return k


_BUSY = set()

def _call(prompt, tc, schema=None):
    import requests
    fb = tc.get("gemini_fallback_models") or ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest", "gemini-3.1-flash-lite"]
    models = [tc["gemini_model"]] + [m for m in fb if m != tc["gemini_model"]]
    models.sort(key=lambda m: m in _BUSY)               # model vừa bị quá tải → dùng model khác trước
    gen = {"temperature": 0.35, "responseMimeType": "application/json"}
    if schema:
        gen["responseSchema"] = schema
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}
    last = None
    timeout = tc.get("gemini_timeout", 45)             # 45s timeout (tránh ngâm socket quá lâu dẫn đến đứt SSL ngầm)
    for model in models:
        for attempt in range(tc.get("gemini_retries", 2)):
            try:
                r = requests.post(API.format(model=model), json=body, timeout=timeout,
                                  headers={"x-goog-api-key": api_key(), "Content-Type": "application/json"})
                if r.status_code == 404:
                    raise LookupError(f"model {model} không tồn tại")
                if r.status_code in (429, 500, 503):
                    raise ConnectionError(f"HTTP {r.status_code}: {r.text[:200]}")
                if r.status_code == 400 and "API key" in r.text:
                    raise PermissionError("API key không hợp lệ — kiểm tra lại secrets.yaml")
                r.raise_for_status()
                parts = r.json()["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                return json.loads(text)
            except PermissionError:
                raise
            except LookupError as e:
                log.warning("Gemini: %s → thử model khác", e); last = e; break
            except Exception as e:
                last = e
                wait = 2 * (attempt + 1)
                log.warning("Gemini (%s) lỗi: %s — đợi %ds", model, " ".join(str(e).split())[:100], wait); time.sleep(wait)
        else:
            log.warning("Gemini: %s quá tải hoặc gián đoạn mạng → chuyển model dự phòng", model); _BUSY.add(model)
    raise RuntimeError(f"Gemini thất bại: {last}")


def analyze(segs, cfg):
    tc = cfg["translate"]; src = LANG_NAME.get(cfg["source_lang"], cfg["source_lang"])
    tgt = LANG_NAME.get(cfg["target_lang"], cfg["target_lang"])
    script = "\n".join(s["src"] for s in segs)
    prompt = f"""Bạn là chuyên gia biên kịch và biên dịch lồng tiếng phim/video ngắn xuất sắc. Dưới đây là toàn bộ phụ đề {src} trích xuất từ video (qua OCR nên có thể dính một số ký tự sai hoặc ngắt nhịp câu).
{('CHỦ ĐỀ & NGỮ CẢNH VIDEO: ' + tc['context']) if tc.get('context') else ''}

Hãy phân tích kỹ lưỡng để chuẩn bị dịch sang {tgt}:
- summary: tóm tắt nội dung chính, thể loại video (phim ngắn, công nghệ/AI, tin tức, đời sống, hài hước), văn phong và bối cảnh (2-4 câu, bằng {tgt}).
- tone_pronouns: đại từ xưng hô chuẩn xác nhất cho toàn bộ video (ví dụ video chia sẻ kiến thức/công nghệ: 'mình - các bạn' hoặc 'tôi - mọi người'; phim kiếm hiệp: 'ta - ngươi / huynh - đệ'; phim gia đình: 'anh - em').
- characters: danh sách nhân vật/người nói chính — tên gốc, tên dịch thuần Việt (dùng tên Hán Việt quen thuộc nếu là nhân vật nổi tiếng, ví dụ 孙悟空 = Tôn Ngộ Không, hoặc tên thương hiệu/sản phẩm), phong cách nói và giới tính.
- terms: thuật ngữ chuyên ngành, tên riêng, địa danh, tổ chức cần dịch thống nhất (gốc → dịch).
- ocr_fixes: các từ/cụm từ OCR đọc nhầm cần sửa lại chính xác (gốc sai → từ đúng).

PHỤ ĐỀ TOÀN BỘ:
{script}"""
    schema = {"type": "OBJECT", "properties": {
        "summary": {"type": "STRING"},
        "tone_pronouns": {"type": "STRING"},
        "characters": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "original": {"type": "STRING"}, "translated": {"type": "STRING"}, "speech_style": {"type": "STRING"},
            "gender": {"type": "STRING", "enum": ["male", "female", "unknown"]}},
            "required": ["original", "translated"]}},
        "terms": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "original": {"type": "STRING"}, "translated": {"type": "STRING"}}, "required": ["original", "translated"]}},
        "ocr_fixes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "wrong": {"type": "STRING"}, "correct": {"type": "STRING"}}, "required": ["wrong", "correct"]}},
    }, "required": ["summary", "characters", "terms"]}
    log.info("Gemini: phân tích ngữ cảnh toàn bộ %d câu...", len(segs))
    return _call(prompt, tc, schema)


def _glossary_text(g, user_glossary):
    lines = [f"TÓM TẮT & BỐI CẢNH: {g.get('summary', '')}"]
    if g.get("tone_pronouns"):
        lines.append(f"XƯNG HÔ CHUẨN: {g['tone_pronouns']}")
    for c in g.get("characters", []):
        lines.append(f"- Nhân vật {c['original']} → {c['translated']}" + (f" [{c['gender']}]" if c.get("gender") else "")
                     + (f" ({c['speech_style']})" if c.get("speech_style") else ""))
    for t in g.get("terms", []):
        lines.append(f"- {t['original']} → {t['translated']}")
    for k, v in (user_glossary or {}).items():
        lines.append(f"- {k} → {v} (BẮT BUỘC dùng)")
    for f in g.get("ocr_fixes", []) or []:
        lines.append(f"- Sửa lỗi OCR: '{f['wrong']}' → '{f['correct']}'")
    return "\n".join(lines)


def translate(segs, cfg, glossary_path=None, progress_cb=None):
    tc = cfg["translate"]
    tgt = LANG_NAME.get(cfg["target_lang"], cfg["target_lang"])
    # 1. Phân tích ngữ cảnh (có cache, sửa tay được)
    g = None
    if glossary_path and os.path.exists(glossary_path):
        with open(glossary_path, encoding="utf-8") as f:
            g = json.load(f)
        log.info("Gemini: dùng bảng ngữ cảnh có sẵn %s", glossary_path)
    elif tc.get("gemini_analyze", True):
        if progress_cb:
            progress_cb("Dịch thuật (Gemini)", 0.38, "Gemini đang phân tích toàn bộ kịch bản và nhân vật...")
        try:
            g = analyze(segs, cfg)
            if glossary_path:
                with open(glossary_path, "w", encoding="utf-8") as f:
                    json.dump(g, f, ensure_ascii=False, indent=1)
        except Exception as e:
            log.warning("Gemini: phân tích kịch bản gặp lỗi mạng (%s) → tiếp tục dịch trực tiếp", e)
            g = {}

    # Tự động sửa lỗi OCR trực tiếp vào các câu nguồn segs
    ocr_fixes = (g or {}).get("ocr_fixes", [])
    if ocr_fixes:
        n_fixed = 0
        for fix in ocr_fixes:
            w, c = fix.get("wrong", "").strip(), fix.get("correct", "").strip()
            if w and c and w != c:
                for s in segs:
                    if w in s["src"]:
                        s["src"] = s["src"].replace(w, c)
                        n_fixed += 1
        if n_fixed > 0:
            log.info("Gemini: Đã tự động vá %d vị trí lỗi chính tả OCR trong phụ đề gốc", n_fixed)

    gtext = _glossary_text(g or {}, tc.get("glossary"))

    # 2. Dịch theo lô
    out, bs = [], tc.get("batch_size", 40)
    for i in range(0, len(segs), bs):
        chunk = []
        for j in range(i, min(i + bs, len(segs))):
            s = segs[j]
            nxt = segs[j + 1]["start"] if j + 1 < len(segs) else s["end"] + 1.5
            slot = max(0.6, nxt - s["start"])
            chunk.append({"id": j, "text": s["src"], "seconds": round(slot, 1),
                          "max_syllables": max(3, int(slot * SYLLABLES_PER_SEC * tc.get("length_factor", 1.0)))})
        prev = [{"src": segs[k]["src"], "vi": out[k]} for k in range(max(0, i - 8), i)]
        prompt = f"""Bạn là biên dịch viên lồng tiếng hàng đầu. Dịch danh sách câu phụ đề sang {tgt} dùng cho đọc lồng tiếng và hiển thị phụ đề.

NGỮ CẢNH TOÀN BỘ & BẢNG THUẬT NGỮ:
{gtext}

NGUYÊN TẮC DỊCH LỒNG TIẾNG ĐẲNG CẤP:
1. Dịch chuẩn nghĩa, thoát ý, câu văn thuần Việt tự nhiên, giàu nhạc điệu, đúng phong cách video và xưng hô nhất quán theo bảng ngữ cảnh trên. Tuyệt đối không dịch thô cứng kiểu word-by-word (Google dịch).
2. Tối ưu thời lượng đọc: Mỗi câu dịch KHÔNG VƯỢT QUÁ max_syllables âm tiết (để giọng đọc lồng tiếng vừa vặn trong 'seconds' giây mà không phải tua nhanh gây méo tiếng). Rút gọn gãy gọn từ ngữ thừa nếu cần nhưng giữ trọn ý cốt lõi.
3. Câu gốc bị thiếu chữ hoặc ngắt giữa chừng do phụ đề video cắt nhịp: Hãy dựa vào ngữ cảnh câu trước/sau để dịch thành câu văn hoàn chỉnh, mượt mà.
4. Gán speaker (tên người nói tiếng Việt) và gender (male / female / unknown) để hệ thống tự động gán giọng lồng tiếng nam/nữ phù hợp. Người dẫn chuyện/thuyết minh video hoặc loa thông báo ghi "Người dẫn" hoặc "Hệ thống".
5. Trả về đúng đủ mọi id được cung cấp trong danh sách.
{('CÁC CÂU VỪA DỊCH TRƯỚC ĐÓ (để giữ mạch xưng hô và văn phong): ' + json.dumps(prev, ensure_ascii=False)) if prev else ''}

DANH SÁCH CÂU CẦN DỊCH:
{json.dumps(chunk, ensure_ascii=False)}"""
        schema = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "id": {"type": "INTEGER"}, "vi": {"type": "STRING"}, "speaker": {"type": "STRING"},
            "gender": {"type": "STRING", "enum": ["male", "female", "unknown"]}}, "required": ["id", "vi"]}}
        got = {}
        try:
            res = _call(prompt, tc, schema)
            got = {int(r["id"]): str(r.get("dst") or r.get("vi") or r.get("en") or "").strip()
                   for r in res if str(r.get("dst") or r.get("vi") or r.get("en") or "").strip()}
            for r in res:                                  # gắn người nói + giới tính để chọn giọng
                j = int(r.get("id", -1))
                if 0 <= j < len(segs):
                    segs[j]["speaker"] = str(r.get("speaker") or "").strip()
                    segs[j]["gender"] = r.get("gender") if r.get("gender") in ("male", "female") else ""
        except Exception as e:
            log.warning("Gemini gián đoạn mạng ở câu %d-%d (%s) → Tự động dịch lô này bằng Google Translate để không dừng video",
                        i + 1, min(i + bs, len(segs)), e)
            from .translate import _google
            sub_texts = [segs[c["id"]]["src"] for c in chunk]
            sub_res = _google(sub_texts, cfg["source_lang"], cfg["target_lang"], 40)
            for c, text in zip(chunk, sub_res):
                got[c["id"]] = text

        missing = [c["id"] for c in chunk if c["id"] not in got]
        if missing:
            log.warning("Gemini thiếu %d câu (%s) → dịch bù bằng Google", len(missing), missing)
            from .translate import _google
            for idx, t in zip(missing, _google([segs[m]["src"] for m in missing], cfg["source_lang"], cfg["target_lang"], 40)):
                got[idx] = t
        out += [got.get(c["id"], segs[c["id"]]["src"]) for c in chunk]
        if progress_cb:
            progress_cb("Dịch thuật", min(0.55, 0.40 + 0.15 * (len(out) / len(segs))),
                        f"Đã dịch {len(out)}/{len(segs)} câu...")
        log.info("  Đã dịch %d/%d câu", len(out), len(segs))
    return out
