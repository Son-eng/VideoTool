"""Tạo video mock giống video Douyin: giọng Trung + nhạc nền + hardsub Trung ở dưới."""
import os, subprocess
from videodub.utils import ffmpeg_bin
from videodub.render import _ff_path
OUT = "mock"; os.makedirs(OUT, exist_ok=True)
FONT = _ff_path(os.path.abspath("fonts/BeVietnamPro-Bold.ttf"))
LINES = [  # (start, end, text)
    (0.5, 3.5, "这款按摩仪真的太好用了"),
    (4.0, 7.0, "每天只需要十分钟"),
    (7.5, 10.5, "肩膀和脖子都放松了"),
    (11.0, 14.0, "现在下单还有优惠哦"),
]
DUR = 15
def run(c):
    c[0] = ffmpeg_bin(c[0]) if c[0] in ("ffmpeg", "ffprobe") else c[0]
    subprocess.run(c, check=True, capture_output=True)

# giọng Trung từng câu
parts = []
for i, (s, e, t) in enumerate(LINES):
    w = f"{OUT}/zh_{i}.wav"
    try:
        run(["espeak-ng", "-v", "cmn", "-s", "150", "-w", w, t])
    except (FileNotFoundError, Exception):
        dur = e - s
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=f=440:d={dur:.2f}", "-ar", "44100", w])
    parts.append((s, w))
inputs, filt = [], []
for i, (s, w) in enumerate(parts):
    inputs += ["-i", w]; filt.append(f"[{i}]adelay={int(s*1000)}|{int(s*1000)},aresample=44100[a{i}]")
n = len(parts)
inputs += ["-f", "lavfi", "-i", f"sine=f=220:d={DUR},volume=0.15", "-f", "lavfi", "-i", f"sine=f=330:d={DUR},volume=0.1"]
filt.append(f"[{n}][{n+1}]amix=2,aresample=44100[bg]")
filt.append("".join(f"[a{i}]" for i in range(n)) + f"[bg]amix={n+1}:normalize=0,atrim=0:{DUR}[out]")
run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt), "-map", "[out]", f"{OUT}/audio.wav"])

# video nền + hardsub
draw = ",".join(
    f"drawtext=fontfile='{FONT}':text='{t}':fontsize=46:fontcolor=white:borderw=3:bordercolor=black:"
    f"x=(w-text_w)/2:y=h-200:enable='between(t,{s},{e})'" for s, e, t in LINES)
vf_file = f"{OUT}/vf.txt"
with open(vf_file, "w", encoding="utf-8") as f:
    f.write(draw)
run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=s=720x1280:d={DUR}:r=30", "-i", f"{OUT}/audio.wav",
     "-filter_script:v", vf_file, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
     f"{OUT}/douyin_mock.mp4"])
print("ok", f"{OUT}/douyin_mock.mp4")
