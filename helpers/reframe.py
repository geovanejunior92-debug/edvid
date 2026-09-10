"""Reenquadramento automático: um corte, todos os formatos, seguindo o rosto.

O "Auto Reframe" do Premiere: a partir do cut.mp4 (ou do final.mp4) gera as
versões 1:1, 16:9 ou 9:16 com a janela de corte seguindo a pessoa — não um
crop central cego, que decapita em vertical e deixa a pessoa no canto em
paisagem.

  1. rosto a cada N quadros (YuNet, faces.py) num proxy de 480 px → trajetória
     do centro do rosto; buracos preenchidos, caminho suavizado (gaussiana de
     `--smooth` segundos — a janela tem que ser preguiçosa, não nervosa).
  2. janela de corte na proporção alvo, do maior tamanho que cabe: de 9:16
     para 16:9 a janela usa a largura toda e só sobe/desce; de 16:9 para 9:16
     usa a altura toda e só anda de lado. O rosto fica a 42% do topo da
     janela (headroom de retrato), clampado nas bordas.
  3. quadros decodificados, cortados e mandados para o ffmpeg já na
     resolução padrão da entrega (1080×1080, 1920×1080, 1080×1920). Áudio
     copiado sem reencodar.

Usage:
    uv run python helpers/reframe.py <edit>/final.mp4 --to 1:1
    uv run python helpers/reframe.py <edit>/final.mp4 --to 1:1 --to 16:9 --out-dir <edit>/formats
    uv run python helpers/reframe.py final.mp4 --to 9:16 --smooth 1.5 --headroom 0.40

Saída: <out-dir>/<stem>_1x1.mp4 etc. Rode DEPOIS da Fase 2: legenda e
gráficos já estão queimados e viajam junto — mas só o que está dentro da
janela. Legenda centralizada e capa no topo sobrevivem ao 1:1; um lower-third
no canto pode sair. Confira com `contact_sheet.py`.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from faces import detect_face  # noqa: E402

TARGETS = {"1:1": (1080, 1080), "16:9": (1920, 1080), "9:16": (1080, 1920), "4:5": (1080, 1350)}
PROXY_W = 480


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s = d["streams"][0]
    num, _, den = s["r_frame_rate"].partition("/")
    return {"w": int(s["width"]), "h": int(s["height"]),
            "fps": float(num) / float(den or 1), "duration": float(d["format"].get("duration") or 0)}


def frames(path: Path, w: int, h: int):
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, bufsize=w * h * 3 * 4)
    size = w * h * 3
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    proc.stdout.close()
    proc.wait()


def track(path: Path, info: dict, every: int) -> np.ndarray:
    """Centro do rosto normalizado (cx, cy em 0..1) por quadro, preenchido."""
    pw = PROXY_W
    ph = int(round(info["h"] * pw / info["w"] / 2)) * 2
    raw: list[tuple[float, float] | None] = []
    for i, img in enumerate(frames(path, pw, ph)):
        if i % every:
            raw.append(None)
            continue
        box = detect_face(img)
        if box is None:
            raw.append(None)
        else:
            x, y, w, h = box
            raw.append(((x + w / 2) / pw, (y + h * 0.45) / ph))
    n = len(raw)
    pts = np.full((n, 2), np.nan)
    for i, p in enumerate(raw):
        if p is not None:
            pts[i] = p
    if np.isnan(pts[:, 0]).all():
        pts[:] = (0.5, 0.42)  # sem rosto: centro com headroom de retrato
        return pts
    for c in range(2):
        col = pts[:, c]
        idx = np.flatnonzero(~np.isnan(col))
        pts[:, c] = np.interp(np.arange(n), idx, col[idx])
    return pts


def smooth(pts: np.ndarray, sigma_frames: float) -> np.ndarray:
    if sigma_frames <= 0:
        return pts
    r = int(3 * sigma_frames)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_frames) ** 2)
    k /= k.sum()
    out = np.empty_like(pts)
    for c in range(pts.shape[1]):
        out[:, c] = np.convolve(np.pad(pts[:, c], r, mode="edge"), k, mode="valid")
    return out


def crop_windows(pts: np.ndarray, W: int, H: int, tw: int, th: int, headroom: float) -> np.ndarray:
    """(x, y, w, h) da janela por quadro, em pixels da fonte."""
    target = tw / th
    source = W / H
    if target >= source:
        cw, ch = W, int(round(W / target))
    else:
        cw, ch = int(round(H * target)), H
    cw, ch = min(cw, W), min(ch, H)
    xs = pts[:, 0] * W - cw / 2
    ys = pts[:, 1] * H - ch * headroom
    xs = np.clip(xs, 0, W - cw)
    ys = np.clip(ys, 0, H - ch)
    win = np.zeros((len(pts), 4), dtype=np.int32)
    win[:, 0], win[:, 1], win[:, 2], win[:, 3] = np.round(xs), np.round(ys), cw, ch
    return win


def render(path: Path, out: Path, info: dict, win: np.ndarray, tw: int, th: int) -> None:
    W, H = info["w"], info["h"]
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{tw}x{th}", "-r", f"{info['fps']:.6f}", "-i", "-",
         "-i", str(path), "-map", "0:v:0", "-map", "1:a:0?",
         "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-c:a", "copy", "-movflags", "+faststart", "-shortest", str(out)],
        stdin=subprocess.PIPE)
    for i, img in enumerate(frames(path, W, H)):
        x, y, cw, ch = win[min(i, len(win) - 1)]
        crop = img[y: y + ch, x: x + cw]
        enc.stdin.write(cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA).tobytes())
    enc.stdin.close()
    enc.wait()
    if enc.returncode != 0:
        raise SystemExit("ffmpeg falhou no encode do reenquadramento")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("--to", action="append", choices=sorted(TARGETS), required=True)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--smooth", type=float, default=1.2, help="segundos da suavização do caminho")
    ap.add_argument("--headroom", type=float, default=0.42,
                    help="posição do rosto dentro da janela, do topo (0.42 = retrato)")
    ap.add_argument("--every", type=int, default=4, help="detectar rosto a cada N quadros")
    args = ap.parse_args()

    video = args.video.resolve()
    info = probe(video)
    out_dir = (args.out_dir or video.parent / "formats").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{video.name}: {info['w']}x{info['h']} {info['fps']:.2f}fps {info['duration']:.1f}s")
    pts = track(video, info, args.every)
    found = int((~np.isnan(pts[:, 0])).sum())
    pts = smooth(pts, args.smooth * info["fps"])
    print(f"  rosto: caminho de {len(pts)} quadros (detecção a cada {args.every}), "
          f"suavização {args.smooth:.1f}s")

    for tgt in dict.fromkeys(args.to):
        tw, th = TARGETS[tgt]
        if abs(tw / th - info["w"] / info["h"]) < 0.01:
            print(f"  {tgt}: já é a proporção da fonte, pulando")
            continue
        win = crop_windows(pts, info["w"], info["h"], tw, th, args.headroom)
        travel = float(np.abs(np.diff(win[:, :2], axis=0)).sum(axis=1).mean())
        out = out_dir / f"{video.stem}_{tgt.replace(':', 'x')}.mp4"
        render(video, out, info, win, tw, th)
        print(f"  {tgt}: janela {win[0, 2]}x{win[0, 3]} → {tw}x{th}, "
              f"movimento médio {travel:.2f} px/quadro → {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
