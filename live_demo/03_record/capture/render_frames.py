#!/usr/bin/env python3
"""Render snap_tmux.sh frames (.ans, ANSI-coloured pane text) to PNGs for make_video.sh.
  python render_frames.py <frames_dir> [--font /path/to/Mono.ttf] [--size 16]
Needs Pillow (pip install pillow). Panes are laid out at their tmux positions; 16 ANSI colours + bold.
"""
import argparse, glob, os, re
from PIL import Image, ImageDraw, ImageFont

PAL = ["#1e1e1e", "#f44747", "#6a9955", "#d7ba7d", "#569cd6", "#c586c0", "#4ec9b0", "#d4d4d4",
       "#808080", "#f14c4c", "#89d185", "#dcdcaa", "#9cdcfe", "#d670d6", "#4fc1ff", "#ffffff"]
BG, FG = "#101010", "#d4d4d4"
SGR = re.compile(r"\x1b\[([0-9;]*)m")


def spans(line):
    """(text, fg, bold) runs from an ANSI line."""
    out, fg, bold, pos = [], FG, False, 0
    for m in SGR.finditer(line):
        if m.start() > pos:
            out.append((line[pos:m.start()], fg, bold))
        for c in (m.group(1) or "0").split(";"):
            c = int(c or 0)
            if c == 0: fg, bold = FG, False
            elif c == 1: bold = True
            elif 30 <= c <= 37: fg = PAL[c - 30]
            elif 90 <= c <= 97: fg = PAL[c - 90 + 8]
            elif c == 39: fg = FG
        pos = m.end()
    out.append((line[pos:], fg, bold))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames"); ap.add_argument("--font", default=None); ap.add_argument("--size", type=int, default=16)
    a = ap.parse_args()
    cands = [a.font, "/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
             "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"]
    font = next((ImageFont.truetype(f, a.size) for f in cands if f and os.path.exists(f)), ImageFont.load_default())
    bold = font
    cw, ch = font.getbbox("M")[2], a.size + 4
    for f in sorted(glob.glob(os.path.join(a.frames, "frame_*.ans"))):
        png = f[:-4] + ".png"
        if os.path.exists(png):
            continue
        panes, cur = [], None
        for ln in open(f, encoding="utf-8", errors="replace").read().split("\n"):
            if ln.startswith("@@PANE "):
                _, pid, w, h, left, top = ln.split()
                cur = {"w": int(w), "h": int(h), "x": int(left), "y": int(top), "lines": []}
                panes.append(cur)
            elif cur is not None:
                cur["lines"].append(ln)
        W = max(p["x"] + p["w"] for p in panes) + 1
        H = max(p["y"] + p["h"] for p in panes) + 1
        im = Image.new("RGB", (W * cw + 20, H * ch + 20), BG)
        d = ImageDraw.Draw(im)
        for p in panes:
            for r, ln in enumerate(p["lines"][: p["h"]]):
                x = 10 + p["x"] * cw
                for text, fg, b in spans(ln):
                    d.text((x, 10 + (p["y"] + r) * ch), text, fill=fg, font=bold if b else font)
                    x += len(text) * cw
            if p["x"] > 0:   # pane border
                d.line([(10 + p["x"] * cw - cw // 2, 10 + p["y"] * ch), (10 + p["x"] * cw - cw // 2, 10 + (p["y"] + p["h"]) * ch)], fill="#444444")
        im.save(png)
    print("rendered", len(glob.glob(os.path.join(a.frames, "frame_*.png"))), "png frames in", a.frames)


if __name__ == "__main__":
    main()
