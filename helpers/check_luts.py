"""Gate: are the LUTs and their picker thumbnails actually healthy?

Run this BEFORE opening the Fase-1 approval gate (right after lut_thumbs.py).
It answers the three questions that have each broken the picker in practice,
and exits non-zero on any of them so it can't be passed over silently:

  1. Do the .cube files exist and parse, and does ffmpeg's lut3d ACTUALLY
     apply each one to this project's own video? ("os filtros nao reconhecem
     o video" is this check.) A .cube that is present but malformed fails
     here, not later in a render.
  2. Does every catalog id have a thumbnail on disk that is a real, decodable
     JPEG of non-trivial size? A 0-byte or truncated file looks like success
     to `ls` and like a broken card in the browser.
  3. Does the preview server actually SERVE them? The thumbnails live under a
     dot-directory (.preview_cache/), are fetched from a different URL space
     than the .cube files, and the grid only builds once — so "the file
     exists" and "the picker can show it" are genuinely different claims.
     Skipped when --port is not given or the server isn't up.

Usage:
    python helpers/check_luts.py <video> --edit-dir <edit> [--port 4820]
    python helpers/check_luts.py <video> --edit-dir <edit> --quick   # skip ffmpeg pass

Exit codes: 0 = everything healthy, 1 = at least one problem (details on
stdout, one line per failure).
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LUTS_DIR = SKILL_DIR / "assets" / "preview" / "luts"
APP_JS = SKILL_DIR / "assets" / "preview" / "app.js"
MIN_THUMB_BYTES = 1024


def lut_id(path: Path) -> str:
    """Mirrors lut_id() in lut_thumbs.py and the ids in app.js's LUT_CATALOG."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", path.stem)


def catalog_ids() -> list[str] | None:
    """Ids the BROWSER will ask for, read from app.js — the picker renders from
    that list, not from the .cube directory, so a drift between the two shows
    up as permanently blank cards. None when app.js can't be parsed."""
    try:
        src = APP_JS.read_text(errors="ignore")
    except OSError:
        return None
    m = re.search(r"const LUT_CATALOG\s*=\s*\[(.*?)\n\];", src, re.S)
    if not m:
        return None
    return re.findall(r"id:\s*'([^']+)'", m.group(1))


def jpeg_dimensions(p: Path) -> tuple[int, int] | None:
    """Decode just the SOF header. A file that `ls` shows as non-empty but has
    no valid frame header is exactly the case a size check alone lets pass."""
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > len(data):
            return None
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 9 > len(data):
                return None
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return (w, h)
        i += 2 + seg_len
    return None


def cube_ok(p: Path) -> str | None:
    """Structural parse. Returns an error string, or None when the file is fine."""
    try:
        size = None
        rows = 0
        with p.open("r", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                m = re.match(r"LUT_3D_SIZE\s+(\d+)", s)
                if m:
                    size = int(m.group(1))
                    continue
                if re.match(r"^[-+0-9.eE]+\s+[-+0-9.eE]+\s+[-+0-9.eE]+\s*$", s):
                    rows += 1
    except OSError as e:
        return f"ilegivel ({e})"
    if size is None:
        return "sem LUT_3D_SIZE"
    if rows != size ** 3:
        return f"LUT_3D_SIZE={size} pede {size ** 3} linhas, achei {rows}"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Health gate for LUT filters + picker thumbnails")
    ap.add_argument("video", type=Path, help="the project's cut.mp4 (or any real frame source)")
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--luts-dir", type=Path, default=DEFAULT_LUTS_DIR)
    ap.add_argument("--port", type=int, default=None, help="preview server port; enables the serving check")
    ap.add_argument("--quick", action="store_true", help="skip the ffmpeg lut3d pass")
    args = ap.parse_args()

    problems: list[str] = []
    thumbs_dir = args.edit_dir / ".preview_cache" / "luts"
    cubes = sorted(args.luts_dir.glob("*.cube"))

    print(f"LUTs em   {args.luts_dir}")
    print(f"miniaturas em {thumbs_dir}")
    print()

    # ---- 1. .cube files present and structurally valid -------------------
    if not cubes:
        problems.append(f"nenhum .cube em {args.luts_dir}")
    bad_cubes = 0
    for c in cubes:
        err = cube_ok(c)
        if err:
            problems.append(f".cube invalido: {c.name} — {err}")
            bad_cubes += 1
    print(f"[1] .cube estruturais: {len(cubes) - bad_cubes}/{len(cubes)} ok")

    # ---- 2. catalog (what the browser asks for) vs disk -------------------
    ids_from_cubes = {lut_id(c) for c in cubes}
    cat = catalog_ids()
    if cat is None:
        problems.append("nao consegui ler LUT_CATALOG de app.js — o picker pode pedir ids que nao existem")
        expected = sorted(ids_from_cubes | {"none"})
        print("[2] catalogo: NAO LIDO (usando os .cube como referencia)")
    else:
        expected = cat
        missing_cube = [i for i in cat if i != "none" and i not in ids_from_cubes]
        orphan = sorted(ids_from_cubes - set(cat))
        for i in missing_cube:
            problems.append(f"catalogo pede '{i}' mas nao ha .cube correspondente")
        for i in orphan:
            problems.append(f".cube '{i}' existe mas nao esta no LUT_CATALOG — nunca aparece no picker")
        print(f"[2] catalogo x disco: {len(cat)} entradas, {len(missing_cube)} sem .cube, {len(orphan)} orfaos")

    # ---- 3. ffmpeg really applies each LUT to THIS video ------------------
    if args.quick:
        print("[3] lut3d no ffmpeg: pulado (--quick)")
    elif not args.video.exists():
        problems.append(f"video nao encontrado: {args.video} — nao da pra testar lut3d")
    else:
        failed = []
        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "f.jpg"
            r = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(args.video),
                 "-frames:v", "1", str(frame)],
                capture_output=True, text=True,
            )
            if r.returncode != 0 or not frame.exists():
                problems.append(f"ffmpeg nao conseguiu extrair um frame de {args.video.name}: {r.stderr.strip()[:200]}")
            else:
                for c in cubes:
                    out = Path(tmp) / "o.jpg"
                    r = subprocess.run(
                        ["ffmpeg", "-y", "-v", "error", "-i", str(frame),
                         "-vf", f"lut3d={c.as_posix()},scale=80:-1", "-q:v", "6", str(out)],
                        capture_output=True, text=True,
                    )
                    if r.returncode != 0 or not out.exists() or out.stat().st_size < 200:
                        failed.append(c.name)
                        problems.append(f"lut3d falhou em {c.name}: {r.stderr.strip()[:160] or 'saida vazia'}")
        print(f"[3] lut3d no ffmpeg: {len(cubes) - len(failed)}/{len(cubes)} aplicaram no video real")

    # ---- 4. thumbnails on disk, decodable ---------------------------------
    if not thumbs_dir.is_dir():
        problems.append(f"pasta de miniaturas nao existe: {thumbs_dir} — rode helpers/lut_thumbs.py")
        print("[4] miniaturas: pasta ausente")
    else:
        bad = 0
        for i in expected:
            p = thumbs_dir / f"{i}.jpg"
            if not p.exists():
                problems.append(f"miniatura faltando: {i}.jpg")
                bad += 1
            elif p.stat().st_size < MIN_THUMB_BYTES:
                problems.append(f"miniatura minuscula ({p.stat().st_size}B), provavelmente truncada: {i}.jpg")
                bad += 1
            elif jpeg_dimensions(p) is None:
                problems.append(f"miniatura nao decodifica como JPEG: {i}.jpg")
                bad += 1
        print(f"[4] miniaturas em disco: {len(expected) - bad}/{len(expected)} validas")

    # ---- 5. the server actually serves them -------------------------------
    if args.port is None:
        print("[5] servidas pelo preview: pulado (sem --port)")
    else:
        base = f"http://127.0.0.1:{args.port}"
        try:
            urllib.request.urlopen(f"{base}/api/state", timeout=3).read()
        except (urllib.error.URLError, OSError) as e:
            print(f"[5] servidas pelo preview: pulado (servidor nao respondeu em {base}: {e})")
        else:
            bad = 0
            for i in expected:
                url = f"{base}/media/.preview_cache/luts/{i}.jpg"
                # GET, not HEAD: preview_server.py implements do_GET only and
                # answers HEAD with 501. GET is also the stronger claim — it
                # proves the bytes actually come out, not just that a route
                # exists.
                try:
                    with urllib.request.urlopen(url, timeout=5) as resp:
                        body = resp.read()
                        if resp.status != 200:
                            problems.append(f"servidor devolveu {resp.status} em {i}.jpg")
                            bad += 1
                        elif len(body) < MIN_THUMB_BYTES:
                            problems.append(f"servidor devolveu so {len(body)}B em {i}.jpg (truncado)")
                            bad += 1
                except urllib.error.HTTPError as e:
                    problems.append(f"servidor devolveu {e.code} em {i}.jpg (o picker mostra card vazio)")
                    bad += 1
                except (urllib.error.URLError, OSError) as e:
                    problems.append(f"erro de rede em {i}.jpg: {e}")
                    bad += 1
            print(f"[5] servidas pelo preview: {len(expected) - bad}/{len(expected)} respondem 200")

    print()
    if problems:
        print(f"FALHOU — {len(problems)} problema(s):")
        for p in problems:
            print(f"  · {p}")
        sys.exit(1)
    print("OK — LUTs aplicam no video real e todas as miniaturas existem, decodificam e sao servidas.")
    sys.exit(0)


if __name__ == "__main__":
    main()
