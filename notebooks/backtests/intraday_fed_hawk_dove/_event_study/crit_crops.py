"""Crop regions of each figure so the critic can inspect overlap / legibility at 100%."""
import sys
from pathlib import Path
from PIL import Image

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
OUT = HERE / "_crops"
OUT.mkdir(exist_ok=True)

jobs = [
    # (file, name, left, top, right, bottom) as FRACTIONS of the image
    ("fig1_event_fan.png",      "f1_legend",   0.03, 0.13, 0.45, 0.42),
    ("fig1_event_fan.png",      "f1_yaxis",    0.02, 0.13, 0.20, 0.60),
    ("fig1b_event_fan_all.png", "f1b_legend",  0.03, 0.13, 0.45, 0.42),
    ("fig2_strip_response.png", "f2A_legend",  0.02, 0.55, 0.35, 0.95),
    ("fig2_strip_response.png", "f2B_anno",    0.60, 0.08, 1.00, 0.35),
    ("fig2_strip_response.png", "f2A_clears",  0.03, 0.15, 0.30, 0.40),
    ("fig3_speaker_scatter.png","f3_labels",   0.30, 0.12, 0.62, 0.45),
    ("fig3_speaker_scatter.png","f3_right",    0.60, 0.10, 1.00, 0.50),
    ("fig4_window_decay.png",   "f4A_ticks",   0.02, 0.30, 0.60, 0.52),
    ("fig4_window_decay.png",   "f4A_legend",  0.03, 0.10, 0.50, 0.28),
]

for fn, name, l, t, r, b in jobs:
    im = Image.open(HERE / fn)
    W, H = im.size
    box = (int(l * W), int(t * H), int(r * W), int(b * H))
    c = im.crop(box)
    # upscale small crops so fine type is readable
    if c.size[0] < 1100:
        s = 1100 / c.size[0]
        c = c.resize((int(c.size[0] * s), int(c.size[1] * s)), Image.LANCZOS)
    p = OUT / f"{name}.png"
    c.save(p)
    print(name, im.size, "->", box, c.size, p)
