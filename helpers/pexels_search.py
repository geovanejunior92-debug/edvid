"""Search Pexels and download images OR VIDEO CLIPS into a Remotion project's
public/ folder.

PHASE 2 helper. Needs PEXELS_API_KEY (env or .env at the edvid repo root).
Get a free key at https://www.pexels.com/api/.

Prints each downloaded file's local path and photographer credit (keep the
credits for attribution).

`--type video` (2026-08-16) hits Pexels' separate VIDEO endpoint and saves
.mp4 clips usable directly as `kind: "video"` split inserts or cutaways. This
is the right source for REAL PEOPLE doing real things — a person eating bread,
someone exhausted at a desk, a blood draw. AI generation cannot supply those
honestly (it invents people who do not exist and it renders anatomy wrong),
and a still cannot supply the motion that makes a talking-head cut feel alive.
Reach for video here FIRST and treat generation as the fallback for concepts
no camera can film, which is what the track reference already says.

Clips are longer than a typical insert window — trim them to the window with
ffmpeg rather than relying on `loopFrames`, same rule as generated clips.

Usage:
    python helpers/pexels_search.py "hollywood film set" \
        --out-dir <edit>/remotion/public/pexels --count 3 --orientation portrait
    python helpers/pexels_search.py "tired woman at desk" --type video \
        --out-dir <edit>/remotion/public/pexels --count 2 --orientation portrait
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

SEARCH_URL = "https://api.pexels.com/v1/search"
VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"


def load_api_key() -> str:
    for candidate in [Path(__file__).resolve().parent.parent / ".env", Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "PEXELS_API_KEY":
                    return v.strip().strip('"').strip("'")
    v = os.environ.get("PEXELS_API_KEY", "")
    if not v:
        sys.exit("PEXELS_API_KEY not found in .env or environment "
                 "(get one at https://www.pexels.com/api/)")
    return v


def search(query: str, api_key: str, count: int, orientation: str | None) -> list[dict]:
    params: dict[str, str | int] = {"query": query, "per_page": max(1, min(count, 80))}
    if orientation:
        params["orientation"] = orientation  # landscape | portrait | square
    resp = requests.get(SEARCH_URL, headers={"Authorization": api_key},
                        params=params, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Pexels returned {resp.status_code}: {resp.text[:300]}")
    return resp.json().get("photos", [])


def search_videos(query: str, api_key: str, count: int, orientation: str | None) -> list[dict]:
    params: dict[str, str | int] = {"query": query, "per_page": max(1, min(count, 80))}
    if orientation:
        params["orientation"] = orientation
    resp = requests.get(VIDEO_SEARCH_URL, headers={"Authorization": api_key},
                        params=params, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Pexels returned {resp.status_code}: {resp.text[:300]}")
    return resp.json().get("videos", [])


def pick_video_file(v: dict, max_height: int) -> dict | None:
    """Highest-quality .mp4 rendition at or under max_height.

    Pexels returns several renditions per clip, unordered and sometimes with
    height 0 on odd entries — sorting by height and filtering to real mp4s is
    what keeps a 4K 200MB file from landing in public/ for a 750px-tall band.
    Falls back to the SMALLEST available when everything exceeds max_height,
    rather than returning nothing.
    """
    files = [f for f in v.get("video_files", [])
             if (f.get("file_type") == "video/mp4" or str(f.get("link", "")).find(".mp4") != -1)
             and f.get("link")]
    if not files:
        return None
    files.sort(key=lambda f: (f.get("height") or 0))
    under = [f for f in files if 0 < (f.get("height") or 0) <= max_height]
    return under[-1] if under else files[0]


def download(url: str, dest: Path) -> None:
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)


def slugify(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")[:40]


def main() -> None:
    ap = argparse.ArgumentParser(description="Download Pexels images into a Remotion public/ folder")
    ap.add_argument("query", help="Search query")
    ap.add_argument("--out-dir", type=Path, required=True, help="Destination folder (e.g. remotion/public/pexels)")
    ap.add_argument("--count", type=int, default=3, help="How many images to download (default 3)")
    ap.add_argument("--orientation", choices=["landscape", "portrait", "square"], default=None)
    ap.add_argument("--size", choices=["original", "large2x", "large", "medium"], default="large2x",
                    help="Pexels rendition to download (default large2x)")
    ap.add_argument("--type", choices=["image", "video"], default="image",
                    help="image (default) or video — video hits Pexels' separate clip endpoint")
    ap.add_argument("--max-height", type=int, default=1920,
                    help="video only: largest rendition height to accept (default 1920)")
    args = ap.parse_args()

    api_key = load_api_key()

    if args.type == "video":
        vids = search_videos(args.query, api_key, args.count, args.orientation)
        if not vids:
            sys.exit(f"no video results for: {args.query}")
        args.out_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(args.query)
        saved = 0
        for i, v in enumerate(vids[: args.count]):
            f = pick_video_file(v, args.max_height)
            if not f:
                continue
            dest = args.out_dir / f"{slug}-{i+1}.mp4"
            try:
                download(f["link"], dest)
            except Exception as e:
                print(f"  x failed {v.get('id')}: {e}")
                continue
            saved += 1
            who = (v.get("user") or {}).get("name", "?")
            print(f"  + {dest}  ({f.get('width')}x{f.get('height')}, {v.get('duration')}s, "
                  f"video: {who}, {v.get('url','')})")
        print(f"downloaded {saved}/{args.count} → {args.out_dir}")
        if saved:
            print("attribution: clips from Pexels — keep the credits above.")
            print("NOTE: trim each clip to its insert window with ffmpeg; these are longer than a window.")
        return

    photos = search(args.query, api_key, args.count, args.orientation)
    if not photos:
        sys.exit(f"no results for: {args.query}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(args.query)
    saved = 0
    for i, p in enumerate(photos[: args.count]):
        src = p.get("src", {})
        url = src.get(args.size) or src.get("large") or src.get("original")
        if not url:
            continue
        ext = ".jpg"
        dest = args.out_dir / f"{slug}-{i+1}{ext}"
        try:
            download(url, dest)
        except Exception as e:
            print(f"  x failed {p.get('id')}: {e}")
            continue
        saved += 1
        credit = p.get("photographer", "?")
        print(f"  + {dest}  (photo: {credit}, {p.get('url','')})")

    print(f"downloaded {saved}/{args.count} → {args.out_dir}")
    if saved:
        print("attribution: images from Pexels — keep the photographer credits above.")


if __name__ == "__main__":
    main()
