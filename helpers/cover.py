"""Capa do Reel: o melhor quadro do vídeo com a frase do gancho por cima.

O quadro é escolhido, não chutado: amostras a cada 0,25 s dentro da janela,
e cada uma recebe nota por olho aberto (EAR pelo FAN), nitidez (variância do
Laplaciano no rosto), tamanho e centralidade do rosto. O melhor vira a capa
em 1080×1920 e uma versão 4:5 (1080×1350, mantendo o topo) para o feed.

O texto segue a capa do vídeo: Poppins ExtraBold, branco com contorno preto,
quebrado em duas linhas equilibradas, e uma palavra de destaque opcional em
Playfair itálico dourado — a mesma identidade do `hookStacked`.

Usage:
    uv run python helpers/cover.py <edit>/final.mp4 --text "Sua tireoide está sendo atacada" --accent-word tireoide
    uv run python helpers/cover.py cut.mp4 --text "…" --window 0 15 --out <edit>/cover.jpg
    uv run python helpers/cover.py cut.mp4 --text "…" --at 7.4      # quadro escolhido por você

Saídas: <edit>/cover.jpg e <edit>/cover_4x5.jpg (ou --out). Imprime o
instante escolhido e as notas dos 5 melhores, para você discordar se quiser.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from faces import detect_face  # noqa: E402

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
GOLD = (212, 178, 95)


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    return {"w": int(d["streams"][0]["width"]), "h": int(d["streams"][0]["height"]),
            "duration": float(d["format"].get("duration") or 0)}


def frame_at(path: Path, t: float, width: int | None) -> np.ndarray | None:
    vf = f"scale={width}:-2" if width else "null"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                          "-vf", vf, "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True).stdout
    if not raw:
        return None
    arr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    return arr


class Eyes:
    def __init__(self):
        self.fan = None
        try:
            import torch, face_alignment
            dev = "mps" if torch.backends.mps.is_available() else "cpu"
            self.fan = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, device=dev, flip_input=False)
        except Exception:
            pass

    def ear(self, img: np.ndarray) -> float | None:
        if self.fan is None:
            return None
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        try:
            lms = self.fan.get_landmarks_from_image(rgb.copy())
        except Exception:
            return None
        if not lms:
            return None
        l = lms[0]
        def e(p):
            a = np.linalg.norm(p[1] - p[5]); b = np.linalg.norm(p[2] - p[4]); c = np.linalg.norm(p[0] - p[3])
            return (a + b) / (2 * c) if c else 0
        v = (e(l[36:42]) + e(l[42:48])) / 2
        return v if 0.03 <= v <= 0.6 else None


def score_frames(video: Path, t0: float, t1: float, step: float = 0.25) -> list[dict]:
    eyes = Eyes()
    rows = []
    for t in np.arange(t0, t1, step):
        img = frame_at(video, float(t), 640)
        if img is None:
            continue
        box = detect_face(img)
        if box is None:
            continue
        x, y, w, h = box
        face = img[y: y + h, x: x + w]
        sharp = float(cv2.Laplacian(cv2.cvtColor(face, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()) if face.size else 0
        W, H = img.shape[1], img.shape[0]
        center = 1 - min(1, abs((x + w / 2) / W - 0.5) * 2)
        size = w / W
        size_ok = 1.0 if 0.15 <= size <= 0.6 else 0.4
        rows.append({"t": round(float(t), 2), "ear": eyes.ear(img), "sharp": sharp, "center": center,
                     "size": size, "size_ok": size_ok})
    if not rows:
        return []
    ears = [r["ear"] for r in rows if r["ear"] is not None]
    ear_ref = float(np.median(ears)) if ears else None
    sharp_max = max(r["sharp"] for r in rows) or 1
    for r in rows:
        eye = 1.0 if r["ear"] is None else min(1.0, r["ear"] / (ear_ref or 1) / 1.05)
        if r["ear"] is not None and ear_ref and r["ear"] < 0.75 * ear_ref:
            eye = 0.0  # olho fechando: descarta
        r["score"] = round(2.2 * eye + 1.0 * (r["sharp"] / sharp_max) + 0.5 * r["center"] + 0.6 * r["size_ok"], 3)
    return sorted(rows, key=lambda r: -r["score"])


def wrap_two_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    if len(words) <= 2:
        return [text]
    best, best_diff = None, 1e9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        wa, wb = draw.textlength(a, font=font), draw.textlength(b, font=font)
        if wa > max_w or wb > max_w:
            continue
        if abs(wa - wb) < best_diff:
            best, best_diff = [a, b], abs(wa - wb)
    if best:
        return best
    # não coube em duas: três linhas gulosas
    lines, cur = [], []
    for w in words:
        if draw.textlength(" ".join(cur + [w]), font=font) > max_w and cur:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def compose(frame_bgr: np.ndarray, text: str, accent_word: str | None, out: Path, out_45: Path) -> None:
    img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)).convert("RGB")
    W, H = img.size
    if (W, H) != (1080, 1920):
        # cobre 1080x1920 mantendo proporção
        s = max(1080 / W, 1920 / H)
        img = img.resize((int(W * s), int(H * s)), Image.LANCZOS)
        left, top = (img.width - 1080) // 2, 0
        img = img.crop((left, top, left + 1080, top + 1920))
        W, H = 1080, 1920
    # escurece o topo para o texto ler
    grad = Image.new("L", (1, H))
    for y in range(H):
        v = int(150 * max(0, 1 - y / (H * 0.42)) ** 1.4)
        grad.putpixel((0, y), v)
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.composite(dark, img, grad.resize((W, H)))

    draw = ImageDraw.Draw(img)
    size = 112
    font = ImageFont.truetype(str(FONTS / "Poppins-ExtraBold.ttf"), size)
    accent_font = ImageFont.truetype(str(FONTS / "PlayfairDisplay-Italic.ttf"), int(size * 1.05))
    max_w = W - 2 * 84
    lines = wrap_two_lines(draw, text, font, max_w)
    while len(lines) > 2 and size > 72:
        size -= 8
        font = ImageFont.truetype(str(FONTS / "Poppins-ExtraBold.ttf"), size)
        accent_font = ImageFont.truetype(str(FONTS / "PlayfairDisplay-Italic.ttf"), int(size * 1.05))
        lines = wrap_two_lines(draw, text, font, max_w)
    y = int(H * 0.11)
    lh = int(size * 1.12)
    for line in lines:
        # mede a linha em pedaços (palavra de destaque em outra fonte)
        parts = []
        for word in line.split():
            is_acc = accent_word and word.strip(".,!?").lower() == accent_word.lower()
            parts.append((word, accent_font if is_acc else font, GOLD if is_acc else (255, 255, 255)))
        total = sum(draw.textlength(p[0] + " ", font=p[1]) for p in parts)
        x = (W - total) / 2
        for word, f, color in parts:
            draw.text((x, y), word, font=f, fill=color, stroke_width=10, stroke_fill=(0, 0, 0))
            x += draw.textlength(word + " ", font=f)
        y += lh
    img.save(out, quality=92)
    img.crop((0, 0, 1080, 1350)).save(out_45, quality=92)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("--text", required=True)
    ap.add_argument("--accent-word", default=None)
    ap.add_argument("--window", nargs=2, type=float, default=None, metavar=("T0", "T1"))
    ap.add_argument("--at", type=float, default=None, help="usa este instante em vez de escolher")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    video = args.video.resolve()
    info = probe(video)
    out = args.out or video.parent / "cover.jpg"
    out45 = out.with_name(out.stem + "_4x5" + out.suffix)

    if args.at is not None:
        best_t, ranking = args.at, []
    else:
        t0, t1 = args.window or (0.0, min(15.0, info["duration"]))
        ranking = score_frames(video, t0, t1)
        if not ranking:
            raise SystemExit("nenhum quadro com rosto na janela")
        best_t = ranking[0]["t"]
    frame = frame_at(video, best_t, None)
    if frame is None:
        raise SystemExit("não decodifiquei o quadro")
    compose(frame, args.text, args.accent_word, out, out45)
    print(f"capa: quadro em {best_t:.2f}s → {out.name} e {out45.name}")
    for r in ranking[:5]:
        ear = "olho ?" if r["ear"] is None else f"EAR {r['ear']:.3f}"
        print(f"  {r['t']:6.2f}s  nota {r['score']:.2f}  {ear}  nitidez {r['sharp']:.0f}  centro {r['center']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
