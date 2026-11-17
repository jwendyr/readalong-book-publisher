#!/usr/bin/env python3
"""Strip outer paper-cut edges and convert white backgrounds to transparent RGBA PNGs."""

import argparse
from pathlib import Path
from PIL import Image


def clean_image(src: Path, dst: Path, edge_px: int = 44, alpha_cutoff: int = 50, max_width: int = 960):
    im = Image.open(src).convert("L")
    w, h = im.size
    if w > max_width:
        im = im.resize((max_width, int(h * max_width / w)), Image.Resampling.LANCZOS)
        w, h = im.size

    rgba = Image.new("RGBA", (w, h), (17, 24, 39, 0))
    alpha_lut = [255 if v < 40 else (0 if v >= 225 else int((225 - v) * 255 / 185)) for v in range(256)]
    alpha = im.point(alpha_lut).point(lambda v: 0 if v < alpha_cutoff else min(255, int((v - alpha_cutoff) * 255 / (255 - alpha_cutoff))))

    if edge_px > 0:
        px = alpha.load()
        for y in range(h):
            for x in range(w):
                if x < edge_px or x >= w - edge_px or y < edge_px or y >= h - edge_px:
                    px[x, y] = 0

    rgba.putalpha(alpha)
    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    rgba.save(dst, optimize=True)


def main():
    ap = argparse.ArgumentParser(description="Clean etching illustrations to transparent PNGs")
    ap.add_argument("--images-dir", required=True, help="Directory containing ch*.png/jpg (excluding cover)")
    ap.add_argument("--edge-px", type=int, default=44, help="Outer pixel border to erase (default: 44)")
    args = ap.parse_args()

    img_dir = Path(args.images_dir)
    for src in sorted(img_dir.glob("ch*.*")):
        if src.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        dst = img_dir / f"{src.stem}.png"
        clean_image(src, dst, edge_px=args.edge_px)
        if src != dst:
            src.unlink()
        print(f"Cleaned {dst.name}: {dst.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
