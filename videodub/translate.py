"""Dịch danh sách câu. Provider: google (free) | gemini | mock."""
import json, os, re, time
from .utils import log

LANG_GOOGLE = {"zh": "zh-CN", "vi": "vi", "en": "en", "th": "th", "id": "id", "ja": "ja", "ko": "ko"}

def translate(segs, cfg, glossary_path=None, progress_cb=None):
    """segs: list câu {start, end, src}. Trả về list bản dịch cùng thứ tự."""
    texts = [s["src"] for s in segs]
    p = cfg["translate"]["provider"]
    src, tgt = cfg["source_lang"], cfg["target_lang"]
    if p == "mock":
        return _mock(texts)
    if p == "google":
        return _google(texts, src, tgt, cfg["translate"]["batch_size"], cfg["translate"].get("google_delay", 1.0), progress_cb=progress_cb)
    if p == "gemini":
        from . import gemini
        try:
            return gemini.translate(segs, cfg, glossary_path, progress_cb=progress_cb)
        except Exception as e:
            log.warning("Gemini gặp lỗi (%s) → Tự động chuyển toàn bộ sang Google Translate để hoàn tất video", e)
            if progress_cb:
                progress_cb("Dịch thuật", 0.38, "Gemini gián đoạn, tự động chuyển sang Google Translate...")
            return _google(texts, src, tgt, cfg["translate"]["batch_size"], cfg["translate"].get("google_delay", 1.0), progress_cb=progress_cb)
    raise ValueError(f"translate.provider không hợp lệ: {p}")

def _google(texts, src, tgt, bs, delay=1.0, progress_cb=None):
    """Gộp nhiều câu thành 1 request (mỗi câu 1 dòng) → ít request, không bị Google chặn (giới hạn 5 request/giây)."""
    import requests
    sl, tl = LANG_GOOGLE.get(src, src), LANG_GOOGLE.get(tgt, tgt)
    url = "https://translate.googleapis.com/translate_a/single"

    def call(text):
        for attempt in range(5):
            try:
                time.sleep(delay)
                r = requests.get(url, params={"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": text}, timeout=30)
                r.raise_for_status()
                return "".join(seg[0] for seg in r.json()[0] if seg and seg[0])
            except Exception as e:
                wait = 5 * (attempt + 1)
                log.warning("Google dịch lỗi (%s), đợi %ds rồi thử lại...", str(e)[:80], wait); time.sleep(wait)
        raise RuntimeError("Google Translate thất bại sau 5 lần thử. Đợi vài phút rồi chạy lại, hoặc đổi provider: gemini")

    out = []
    i = 0
    while i < len(texts):
        chunk = []                                   # gom tối đa bs câu và < 1500 ký tự (giới hạn của Google)
        while i < len(texts) and len(chunk) < bs and sum(len(c) + 1 for c in chunk) + len(texts[i]) < 1500:
            chunk.append(texts[i].replace("\n", " ")); i += 1
        if not chunk:                                # 1 câu quá dài
            chunk = [texts[i][:1500]]; i += 1
        lines = [l.strip() for l in call("\n".join(chunk)).split("\n") if l.strip()]
        if len(lines) != len(chunk):                 # Google gộp/tách dòng → dịch từng câu
            log.info("  Số dòng không khớp, dịch lẻ từng câu (%d câu)", len(chunk))
            lines = [call(c) for c in chunk]
        out += lines
        if progress_cb:
            progress_cb("Dịch thuật", min(0.55, 0.35 + 0.20 * (len(out) / len(texts))),
                        f"Đã dịch {len(out)}/{len(texts)} câu...")
        log.info("  Đã dịch %d/%d câu", len(out), len(texts))
    return out

_MOCK = {"这款按摩仪真的太好用了": "Máy massage này dùng thích thật sự",
         "每天只需要十分钟": "Mỗi ngày chỉ cần mười phút",
         "肩膀和脖子都放松了": "Vai và cổ đều thư giãn hẳn",
         "现在下单还有优惠哦": "Đặt hàng ngay bây giờ còn được ưu đãi nhé"}
def _mock(texts):
    return [_MOCK.get(re.sub(r"\s", "", t), f"[VI] {t}") for t in texts]
