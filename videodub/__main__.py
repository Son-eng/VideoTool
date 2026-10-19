"""CLI:
  python -m videodub run  video.mp4 -o output [-c config.yaml] [--segments x.segments.json]
  python -m videodub batch input_folder -o output [-c config.yaml]
"""
import argparse, copy, glob, json, logging, os, sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
from .config import load_config
from .pipeline import process

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi")

def main():
    ap = argparse.ArgumentParser(prog="videodub")
    ap.add_argument("cmd", choices=["run", "batch"])
    ap.add_argument("input")
    ap.add_argument("-o", "--out", default="output")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-m", "--mode", choices=["vietsub", "dubbing", "both"], default="both",
                    help="chế độ: vietsub (chỉ vietsub, không lồng tiếng), dubbing (chỉ lồng tiếng), both (cả hai)")
    ap.add_argument("--segments", help="file segments.json đã sửa tay → bỏ qua OCR/dịch, chạy lại lồng tiếng + xuất")
    ap.add_argument("--retranslate", action="store_true", help="giữ kết quả OCR, chỉ dịch lại (vd sau khi đổi sang Gemini)")
    ap.add_argument("--fresh", action="store_true", help="bỏ cache, OCR + dịch lại từ đầu")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = load_config(a.config)
    if a.cmd == "run":
        print(json.dumps(process(a.input, a.out, cfg, a.segments, a.fresh, a.retranslate, mode=a.mode), ensure_ascii=False, indent=1))
        return
    files = sorted(f for f in glob.glob(os.path.join(a.input, "*")) if f.lower().endswith(VIDEO_EXT))
    done, failed = [], []
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        suffix = "_vi" if a.mode == "both" else ("_vietsub" if a.mode == "vietsub" else "_dub")
        if not (a.fresh or a.retranslate) and os.path.exists(os.path.join(a.out, f"{name}{suffix}.mp4")):
            continue  # đã làm rồi → bỏ qua (chạy lại batch an toàn)
        try:
            done.append(process(f, a.out, copy.deepcopy(cfg), fresh=a.fresh, retranslate=a.retranslate, mode=a.mode))
        except Exception as e:
            logging.exception("Lỗi %s", f); failed.append({"file": f, "error": str(e)})
    print(json.dumps({"done": len(done), "failed": failed}, ensure_ascii=False, indent=1))
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
