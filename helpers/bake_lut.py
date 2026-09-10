"""Bake a POINTWISE ffmpeg filter chain (eq, colorbalance, colortemperature,
curves, colorchannelmixer, etc. — anything with no spatial/temporal
dependency) into a real 3D .cube LUT.

Works by rendering every (r,g,b) grid point as a flat identity image, running
it through the filter chain with ffmpeg, and reading the graded pixels back —
so the result is EXACT for pointwise filters, not an approximation. Do NOT
feed this a filter with spatial or temporal dependency (unsharp, noise,
smartblur, deband, etc.) — those look at neighboring pixels/frames, so a
per-swatch identity image doesn't mean what it means on real footage; the
bake will "succeed" but the resulting LUT will be wrong.

Usage:
    python helpers/bake_lut.py "eq=contrast=1.04:saturation=0.96,colorbalance=rs=0.02" \
        -o assets/preview/luts/premium.cube --title "Premium" --size 33
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


def build_identity_png(path: Path, n: int) -> None:
    img = Image.new("RGB", (n, n * n))
    px = img.load()
    for b in range(n):
        for g in range(n):
            for r in range(n):
                v = (
                    round(r * 255 / (n - 1)),
                    round(g * 255 / (n - 1)),
                    round(b * 255 / (n - 1)),
                )
                px[r, g + b * n] = v
    img.save(path)


def apply_filter(src: Path, dst: Path, filters: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-vf", filters,
        "-frames:v", "1",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def write_cube(path: Path, graded: Path, n: int, title: str) -> None:
    img = Image.open(graded).convert("RGB")
    px = img.load()
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {n}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    for b in range(n):
        for g in range(n):
            for r in range(n):
                pr, pg, pb = px[r, g + b * n]
                lines.append(f"{pr/255:.6f} {pg/255:.6f} {pb/255:.6f}")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Bake a pointwise ffmpeg filter chain into a .cube LUT")
    ap.add_argument("filters", help="ffmpeg -vf filter chain (pointwise filters only)")
    ap.add_argument("-o", "--out", required=True, type=Path)
    ap.add_argument("--title", default="Baked")
    ap.add_argument("--size", type=int, default=33)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as td:
        identity = Path(td) / "identity.png"
        graded = Path(td) / "graded.png"
        build_identity_png(identity, args.size)
        apply_filter(identity, graded, args.filters)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_cube(args.out, graded, args.size, args.title)
    print(f"wrote {args.out} (LUT_3D_SIZE {args.size})")


if __name__ == "__main__":
    sys.exit(main())
