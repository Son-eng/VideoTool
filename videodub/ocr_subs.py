"""Đọc hardsub gốc bằng OCR: trả về các câu (start, end, text) + vị trí khung chữ để làm mờ chính xác.
Tự động gom cụm theo từng dòng ngang và định vị đúng dải phụ đề đối thoại (Subtitle Band),
loại bỏ triệt để chữ trôi nổi, slide thuyết trình, tiêu đề, watermark hoặc logo bị lệch."""
import difflib, re, time
import cv2
import numpy as np
from .utils import log

_PUNCT = "，。、·—-_:：;；（）()…,.'\"“”‘’|丨《》<>[]【】 "  # ký tự rác hay dính ở 2 đầu câu

_engine = None
def _ocr():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
        _tune(_engine)
    return _engine

def _tune(engine, side=540):
    """Giới hạn cạnh dài ≤ 540px để OCR siêu tốc và tắt xoay góc cho video phụ đề ngang."""
    seen = set()
    def walk(o, depth=0):
        if depth > 3 or id(o) in seen:
            return
        seen.add(id(o))
        for v in (o if isinstance(o, (list, tuple)) else list(getattr(o, "__dict__", {}).values())):
            if hasattr(v, "limit_side_len") and hasattr(v, "limit_type"):
                v.limit_side_len, v.limit_type = side, "max"
            elif hasattr(v, "__dict__") or isinstance(v, (list, tuple)):
                walk(v, depth + 1)
    try:
        walk(getattr(engine, "text_detector", engine))
        if hasattr(engine, "use_angle_cls"):
            engine.use_angle_cls = False
    except Exception as e:
        log.warning("Không tối ưu được RapidOCR (%s)", e)

def _has_cjk_or_text(s):
    return any(ch.isalnum() for ch in s)

def _text_mask(crop, width=320):
    """Mặt nạ phát hiện pixel chữ (trắng / vàng sáng) để bỏ qua frame trống."""
    h = max(8, width * crop.shape[0] // crop.shape[1])
    hsv = cv2.cvtColor(cv2.resize(crop, (width, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV)
    H_, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    white = (V > 185) & (S < 85)
    yellow = (H_ >= 15) & (H_ <= 38) & (S > 85) & (V > 160)
    return white | yellow

def _group_into_rows(items):
    """Gom các cụm từ nằm trên cùng 1 hàng ngang (dòng chữ) lại với nhau.
    items: list of (x0, y0, x1, y1, text)
    """
    if not items:
        return []
    # Sắp xếp theo tâm Y tăng dần
    sorted_its = sorted(items, key=lambda it: (it[1] + it[3]) / 2)
    rows = []
    current_row = [sorted_its[0]]
    for it in sorted_its[1:]:
        last_yc = np.mean([(x[1] + x[3]) / 2 for x in current_row])
        last_h = np.mean([x[3] - x[1] for x in current_row])
        it_yc = (it[1] + it[3]) / 2
        # Cùng một dòng nếu tâm Y chênh lệch không quá 55% chiều cao dòng
        if abs(it_yc - last_yc) <= max(10, last_h * 0.55):
            current_row.append(it)
        else:
            rows.append(current_row)
            current_row = [it]
    if current_row:
        rows.append(current_row)

    merged_rows = []
    for r in rows:
        # Sắp xếp từ trái qua phải
        r.sort(key=lambda x: x[0])
        combined_text = " ".join(x[4] for x in r).strip(_PUNCT)
        # Loại bỏ khoảng trắng thừa giữa các ký tự tiếng Trung / CJK để chữ không bị đứt đoạn
        combined_text = re.sub(r'(?<=[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])\s+(?=[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])', '', combined_text)
        if not combined_text:
            continue
        x0 = min(x[0] for x in r)
        y0 = min(x[1] for x in r)
        x1 = max(x[2] for x in r)
        y1 = max(x[3] for x in r)
        yc = (y0 + y1) / 2
        h = y1 - y0
        merged_rows.append({
            "text": combined_text,
            "items": r,
            "bbox": [x0, y0, x1, y1],
            "yc": yc,
            "h": h
        })
    return merged_rows

def _read_frame_rows(crop, min_score, y_off, scale=1.0):
    """Đọc ảnh crop và trả về danh sách các hàng chữ đã được gom cụm riêng rẽ."""
    img = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else crop
    result, _ = _ocr()(img, use_det=True, use_cls=False, use_rec=True)
    if not result:
        return []
    items = [(box, txt) for box, txt, sc in result if float(sc) >= min_score and _has_cjk_or_text(txt)]
    if not items:
        return []
    its = []
    for b, t in items:
        xs = [p[0] / scale for p in b]; ys = [p[1] / scale + y_off for p in b]
        its.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)), t))
    return _group_into_rows(its)

def extract(video_path, info, cfg, progress_cb=None):
    oc = cfg["ocr"]
    H, W = info["height"], info["width"]

    # Xác định vùng quét theo cấu hình hoặc preset thông minh
    region_mode = oc.get("region_preset", "auto")
    if region_mode == "bottom_tight":
        reg = [0.78, 1.0]
    elif region_mode == "bottom_standard":
        reg = [0.60, 1.0]
    elif region_mode == "bottom_wide":
        reg = [0.45, 1.0]
    elif region_mode == "full":
        reg = [0.0, 1.0]
    else:
        # auto: video dọc (9:16) quét 50%..100%, video ngang (16:9) quét 55%..100%
        reg = [0.50, 1.0] if H > W else [0.55, 1.0]

    # Cho phép ghi đè bằng cấu hình region dạng [y0, y1] nếu có
    if "region" in oc and isinstance(oc["region"], (list, tuple)) and len(oc["region"]) == 2 and region_mode not in ("bottom_tight", "bottom_wide"):
        reg = oc["region"]

    y0, y1 = int(H * reg[0]), int(H * reg[1])
    step = max(1, round(info["fps"] / oc["fps"]))
    total = int(info["duration"] * info["fps"])
    scale = min(1.0, oc.get("max_width", 720) / W)
    cap = cv2.VideoCapture(video_path)

    raw_frames = []   # list of (t, [rows])
    idx = 0
    prev_mask, prev_rows = None, None
    prev_band_gray = None
    n_skip = n_full = 0
    next_log = 0.1
    t_ocr = 0.0

    # Khóa dải phụ đề đối thoại tự động (Dynamic Subtitle Band Locking)
    lock_enabled = oc.get("lock_band", True)
    lock_after = oc.get("lock_after", 3)
    locked = False
    crop_y0, crop_y1 = y0, y1
    calib_rows = []

    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = idx / info["fps"]
            crop = frame[crop_y0:crop_y1]

            # Kiểm tra nhanh thay đổi trong dải sub đã khóa (nếu dải sub không đổi -> bỏ qua OCR)
            is_same = False
            small_band = None
            if locked and oc.get("fast_skip", True):
                small_band = cv2.cvtColor(cv2.resize(crop, (160, 32), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
                if prev_band_gray is not None:
                    diff = float(np.mean(cv2.absdiff(small_band, prev_band_gray)))
                    if diff < oc.get("band_diff_thresh", 11.0):
                        is_same = True

            if is_same:
                rows = prev_rows
                n_skip += 1
            else:
                mask = _text_mask(crop) if (oc.get("fast_skip", True) and not locked) else None
                if mask is not None and mask.mean() < oc.get("empty_ratio", 0.002):
                    rows = []; n_skip += 1
                elif mask is not None and prev_mask is not None and prev_mask.shape == mask.shape and \
                        (mask ^ prev_mask).sum() <= oc.get("same_ratio", 0.08) * max(1, (mask | prev_mask).sum()):
                    rows = prev_rows; n_skip += 1
                else:
                    t1 = time.time()
                    rows = _read_frame_rows(crop, oc.get("min_score", 0.6), crop_y0, scale)
                    t_ocr += time.time() - t1
                    n_full += 1

                    # Tự động hiệu chỉnh và khóa dải phụ đề ngay khi có các câu đầu tiên
                    if lock_enabled and not locked and rows:
                        bottom_thresh = H * (0.55 if H > W else 0.70)
                        for r in rows:
                            if r["yc"] >= bottom_thresh:
                                calib_rows.append(r)
                        if len(calib_rows) >= lock_after:
                            med_h = float(np.median([r["h"] for r in calib_rows]))
                            y_vals = np.array([r["yc"] for r in calib_rows])
                            tgt_y = float(np.percentile(y_vals, 78))
                            n_pts = [y for y in y_vals if abs(y - tgt_y) <= med_h * 1.6]
                            s_yc = float(np.median(n_pts)) if n_pts else tgt_y
                            s_tol = max(24.0, med_h * 1.65)
                            pad = max(18.0, med_h * 0.8)
                            new_y0 = max(y0, int(s_yc - s_tol - pad))
                            new_y1 = min(H, int(s_yc + s_tol + pad))
                            if new_y1 - new_y0 < (y1 - y0) * 0.85:
                                crop_y0, crop_y1 = new_y0, new_y1
                                locked = True
                                prev_band_gray = None
                                log.info("  ⚡ [Tăng tốc siêu cấp] Đã khóa dải phụ đề đối thoại tại Y=%d..%d (cao %dpx thay vì %dpx) → Tăng tốc OCR ~5-10x",
                                         crop_y0, crop_y1, crop_y1 - crop_y0, y1 - y0)
                                if progress_cb:
                                    progress_cb("OCR phụ đề gốc", min(0.35, 0.05 + 0.30 * (idx / total)),
                                                f"⚡ Đã định vị dải phụ đề ({crop_y0}..{crop_y1}px), đang quét siêu tốc...")

            prev_band_gray = small_band if locked else None
            prev_mask, prev_rows = (None if locked else mask), rows
            raw_frames.append((t, rows))

            if total and idx / total >= next_log:
                log.info("  OCR %d%% (đọc %d frame, bỏ qua %d, %.0fs)",
                         int(next_log * 100), n_full, n_skip, t_ocr)
                if progress_cb:
                    progress_cb("OCR phụ đề gốc", min(0.35, 0.05 + 0.30 * (idx / total)),
                                f"Đang nhận diện chữ frame {idx}/{total} ({int(next_log * 100)}%)...")
                next_log += 0.1
        idx += 1
        if total and idx >= total:
            break
    cap.release()
    log.info("OCR hoàn tất: %d frame (đọc %d, bỏ qua %d, %.0fs)", len(raw_frames), n_full, n_skip, t_ocr)

    # Bước 2: Tự động định vị dải phụ đề đối thoại chính (Subtitle Band Calibration)
    all_candidate_rows = [r for _, rows in raw_frames for r in rows if r]
    if not all_candidate_rows:
        return []

    # Đối thoại phụ đề luôn nằm ở tầng dưới của khung hình
    bottom_thresh = H * (0.55 if H > W else 0.70)
    bottom_rows = [r for r in all_candidate_rows if r["yc"] >= bottom_thresh]
    if not bottom_rows:
        bottom_rows = all_candidate_rows

    median_h = float(np.median([r["h"] for r in bottom_rows]))
    ycs = np.array([r["yc"] for r in bottom_rows])

    # Lấy phân vị cao để ưu tiên đúng dòng phụ đề đối thoại ở sát đáy
    target_yc = float(np.percentile(ycs, 78))
    near_points = [y for y in ycs if abs(y - target_yc) <= median_h * 1.6]
    sub_yc = float(np.median(near_points)) if near_points else target_yc
    tol = max(24.0, median_h * 1.65)

    log.info("  🎯 Định vị dải sub gốc: Y=%.1f (%.1f%% chiều cao), chiều cao dòng=%.1fpx, biên độ=±%.1fpx",
             sub_yc, (sub_yc / H) * 100, median_h, tol)

    # Bước 3: Lọc từng frame, CHỈ giữ lại dòng sub nằm đúng dải đã định vị
    filtered_frames = []
    dropped_count = 0
    for t, rows in raw_frames:
        if not rows:
            filtered_frames.append((t, None))
            continue
        sub_rows = [r for r in rows if abs(r["yc"] - sub_yc) <= tol]
        if not sub_rows:
            dropped_count += len(rows)
            filtered_frames.append((t, None))
            continue

        # Nếu có 2 dòng sub gần nhau (phụ đề 2 dòng), ghép lại
        sub_rows.sort(key=lambda r: r["yc"])
        combined_text = " ".join(r["text"] for r in sub_rows).strip(_PUNCT)
        bx0 = min(r["bbox"][0] for r in sub_rows)
        by0 = min(r["bbox"][1] for r in sub_rows)
        bx1 = max(r["bbox"][2] for r in sub_rows)
        by1 = max(r["bbox"][3] for r in sub_rows)

        filtered_frames.append((t, {
            "text": combined_text,
            "bbox": [bx0, by0, bx1, by1],
            "items": [it for r in sub_rows for it in r["items"]]
        }))

    if dropped_count > 0:
        log.info("  Đã tự động loại bỏ %d cụm chữ rác/slide/tiêu đề nằm lệch dòng sub gốc", dropped_count)

    dt = 1.0 / oc["fps"]
    return _merge(filtered_frames, dt, oc)

def _merge(frames, dt, oc):
    """Gộp các frame liên tiếp có chữ giống nhau thành các phân đoạn câu hoàn chỉnh."""
    segs, cur = [], None
    max_skip_dt = dt * 1.5   # cho phép bỏ qua 1 frame nếu bị chớp/nhỡ OCR
    for t, r in frames:
        if r and cur:
            sim = difflib.SequenceMatcher(None, cur["texts"][-1], r["text"]).ratio()
            if sim >= oc["merge_similarity"] or (cur.get("last_t") and t - cur["last_t"] <= max_skip_dt and sim >= 0.5):
                cur["end"] = t + dt
                cur["texts"].append(r["text"])
                cur["boxes"].append(r["bbox"])
                cur["last_t"] = t
                continue
        if cur:
            segs.append(cur)
            cur = None
        if r:
            cur = {"start": t, "end": t + dt, "texts": [r["text"]], "boxes": [r["bbox"]], "last_t": t}
    if cur:
        segs.append(cur)

    out = []
    for s in segs:
        if s["end"] - s["start"] < oc["min_duration"]:
            continue
        # Ưu tiên câu có tần suất cao nhất; nếu hòa thì chọn câu dài và hoàn chỉnh nhất (tránh frame bị cắt nhịp)
        unique_texts = list(set(s["texts"]))
        text = max(unique_texts, key=lambda x: (s["texts"].count(x), len(x.strip())))

        # Tính khung chữ (bbox) dựa trên các frame nhận diện đúng câu hoàn chỉnh
        matching_boxes = [box for txt, box in zip(s["texts"], s["boxes"]) if txt == text]
        if not matching_boxes:
            matching_boxes = s["boxes"]
        b = np.array(matching_boxes)
        x0 = int(np.percentile(b[:, 0], 5)) if len(matching_boxes) >= 5 else int(b[:, 0].min())
        y0 = int(np.percentile(b[:, 1], 5)) if len(matching_boxes) >= 5 else int(b[:, 1].min())
        x1 = int(np.percentile(b[:, 2], 95)) if len(matching_boxes) >= 5 else int(b[:, 2].max())
        y1 = int(np.percentile(b[:, 3], 95)) if len(matching_boxes) >= 5 else int(b[:, 3].max())

        out.append({"start": round(s["start"], 3), "end": round(s["end"], 3), "src": text,
                    "bbox": [x0, y0, x1, y1]})

    # Nối liền khoảng trống giữa các câu gần nhau (Tránh để lộ sub tiếng Trung cũ ở khoảng nghỉ giữa 2 câu)
    bridge_gap = oc.get("bridge_gap", 0.8)   # mặc định nối các câu cách nhau <= 0.8s
    for k in range(len(out) - 1):
        gap = out[k + 1]["start"] - out[k]["end"]
        if 0 <= gap <= bridge_gap:
            out[k]["end"] = out[k + 1]["start"]
        elif gap < 0:
            out[k]["end"] = out[k + 1]["start"]

    # Thêm tail an toàn 0.15s cho câu cuối hoặc câu trước khoảng lặng dài
    for k in range(len(out)):
        nxt_start = out[k + 1]["start"] if k + 1 < len(out) else out[k]["end"] + 1.0
        if nxt_start - out[k]["end"] > 0.05:
            out[k]["end"] = round(min(nxt_start, out[k]["end"] + 0.15), 3)

    return out
