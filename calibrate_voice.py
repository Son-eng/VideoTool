"""Nghe thử Supertonic ở nhiều tốc độ / chất lượng để chọn thông số hợp tai.

Chạy:  .venv\\Scripts\\python calibrate_voice.py            (mặc định giọng F1, M1)
       .venv\\Scripts\\python calibrate_voice.py M2 F3      (chọn giọng khác)
Kết quả: output\\calib\\<giọng>_so_sanh.wav — các mức tốc độ nối tiếp nhau, cách nhau 1 tiếng "bíp".
"""
import os, sys
import numpy as np
import soundfile as sf

SENTENCES = [
    "Hạ Thành có một kho hồ sơ cũ, không nối mạng chủ.",
    "Ngươi cũng biết lão Tôn ư? Ai mà không biết chứ!",
    "Xin xuất trình định danh và thanh toán ba điểm công đức.",
]
SPEEDS = [1.2, 1.4, 1.6, 1.8]
STEPS = [8, 12]

def trim(w, sr):
    thr = np.abs(w).max() * 0.01
    idx = np.where(np.abs(w) > thr)[0]
    return w[max(0, idx[0] - int(0.04 * sr)): idx[-1] + int(0.04 * sr)] if len(idx) else w

def main():
    from supertonic import TTS
    voices = sys.argv[1:] or ["F1", "M1"]
    out = os.path.join("output", "calib"); os.makedirs(out, exist_ok=True)
    tts = TTS(auto_download=True); sr = tts.sample_rate
    beep = 0.2 * np.sin(2 * np.pi * 880 * np.arange(int(0.15 * sr)) / sr).astype(np.float32)
    gap = np.zeros(int(0.5 * sr), np.float32)
    syl = sum(len(s.split()) for s in SENTENCES)
    print(f"{'giọng':6}{'tốc độ':>8}{'steps':>7}{'âm tiết/giây':>14}   (lồng tiếng tự nhiên ~4–5)")
    for v in voices:
        style = tts.get_voice_style(voice_name=v); parts = []
        for steps in STEPS:
            for sp in (SPEEDS if steps == STEPS[0] else [1.5]):
                clips = []
                for s in SENTENCES:
                    w, _ = tts.synthesize(s, voice_style=style, lang="vi", speed=sp, total_steps=steps)
                    clips.append(trim(np.asarray(w, np.float32).ravel(), sr))
                dur = sum(len(c) for c in clips) / sr
                print(f"{v:6}{sp:>8}{steps:>7}{syl / dur:>14.1f}")
                parts += [beep, gap] + sum(([c, gap] for c in clips), [])
        path = os.path.join(out, f"{v}_so_sanh.wav")
        sf.write(path, np.concatenate(parts), sr)
        print(f"  → {path}  (thứ tự: " + ", ".join(f"x{s}" for s in SPEEDS) + ", rồi x1.5 steps 12)")

if __name__ == "__main__":
    main()
