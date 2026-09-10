"""Generate one small preview JPEG per .cube LUT, applied to a REAL frame of
THIS project's own footage — not a generic gradient chart. That's what makes
the picker useful: the user is comparing "how does this look on my video",
not an abstract color-chart rendering that may not transfer.

Usage:
    python helpers/lut_thumbs.py <video> --out-dir <edit>/.preview_cache/luts
    python helpers/lut_thumbs.py <video> --out-dir <dir> --time 12.5 --luts-dir <dir>

Writes <out-dir>/<lut-id>.jpg for every .cube in --luts-dir (default: the
shared assets/preview/luts/ next to this skill), plus <out-dir>/none.jpg (the
ungraded frame, for the "Nenhum" choice) and <out-dir>/meta.json (id → title,
read from the .cube's own TITLE line when present).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LUTS_DIR = SKILL_DIR / "assets" / "preview" / "luts"


def lut_id(path: Path) -> str:
    # Safe for use as a URL path segment and a JS object key.
    return re.sub(r"[^a-zA-Z0-9_-]", "_", path.stem)


def lut_title(path: Path) -> str:
    try:
        with path.open("r", errors="ignore") as f:
            for _ in range(5):
                line = f.readline()
                if not line:
                    break
                m = re.match(r'\s*TITLE\s+"([^"]+)"', line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return path.stem.replace("_", " ").replace("-", " ").strip()


def grab_frame(video: Path, t: float, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", str(out)],
        check=True,
    )


def render_thumb(frame: Path, out: Path, width: int, lut_path: Path | None) -> None:
    vf = f"scale={width}:-1"
    if lut_path is not None:
        # No spaces/colons expected in our storage path, so unquoted is safe;
        # if this ever moves somewhere with spaces, this needs proper escaping.
        vf = f"lut3d={lut_path.as_posix()},{vf}"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(frame), "-vf", vf,
         "-q:v", "4", str(out)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Per-LUT preview thumbnails from real project footage")
    ap.add_argument("video", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--luts-dir", type=Path, default=DEFAULT_LUTS_DIR)
    ap.add_argument("--time", type=float, default=None, help="seconds; default = middle of the video")
    ap.add_argument("--width", type=int, default=220)
    args = ap.parse_args()

    if not args.video.exists():
        print(f"video not found: {args.video}", file=sys.stderr)
        sys.exit(1)
    cube_files = sorted(args.luts_dir.glob("*.cube"))
    if not cube_files:
        print(f"no .cube files in {args.luts_dir}", file=sys.stderr)
        sys.exit(1)

    t = args.time
    if t is None:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(args.video)],
            capture_output=True, text=True, check=True,
        )
        dur = float(probe.stdout.strip() or 0) or 10.0
        t = dur / 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.jpg"
        grab_frame(args.video, t, frame)

        render_thumb(frame, args.out_dir / "none.jpg", args.width, None)
        meta: dict[str, str] = {}
        for cube in cube_files:
            cid = lut_id(cube)
            render_thumb(frame, args.out_dir / f"{cid}.jpg", args.width, cube)
            meta[cid] = lut_title(cube)
            print(f"{cid}: {meta[cid]}")

    (args.out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"{len(cube_files)} thumbnails -> {args.out_dir}")


if __name__ == "__main__":
    main()
