"""Scopes em número: o waveform e o vectorscope do DaVinci, sem olhar para eles.

Princípio 7 do skill: verificação é numérica antes de ser visual. Este helper
mede o que um colorista lê nos scopes e devolve os números — por vídeo, por
instante, ou por take de um EDL:

  waveform   luma em % (0 = preto, 100 = branco): P1 / P5 / mediana / P95 /
             P99, mais % de pixels esmagados no preto (<1%) e estourados no
             branco (>99%). Um take com P99 = 100 e 3% de pixels estourados
             está clipando: nenhum LUT devolve isso.
  vectorscope saturação média (croma), e a PELE: tom de pele do rosto (YuNet)
             como ângulo no plano Cb/Cr e desvio em graus da "linha de pele"
             (~123° na convenção do vectorscope, onde toda pele humana cai).
             Positivo = puxando pra magenta/vermelho, negativo = pra amarelo/
             verde. O ângulo também alimenta o `skin_protect` do EDL.
  branco     ganhos R/G e B/G que o gray-world (pixels de baixa saturação) pede
             para neutralizar a cena — o "auto white balance" em número.

Usage:
    uv run python helpers/scopes.py <video> [--at 12.5] [--face]
    uv run python helpers/scopes.py --edl <edit>/edl.json          # por take
    uv run python helpers/scopes.py <video> --json

Sem `--at`, amostra 12 instantes espalhados e reporta a mediana de cada medida.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

SKIN_LINE_DEG = 123.0   # ângulo da linha de pele no vectorscope (Cb→Cr, sentido horário a partir de +Cb)


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    return {"w": int(d["streams"][0]["width"]), "h": int(d["streams"][0]["height"]),
            "duration": float(d["format"].get("duration") or 0)}


def frame_at(path: Path, t: float, width: int = 960) -> np.ndarray | None:
    info = probe(path)
    h = int(round(info["h"] * width / info["w"] / 2)) * 2
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.4f}", "-i", str(path),
         "-frames:v", "1", "-vf", f"scale={width}:{h}", "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-"], capture_output=True, check=True).stdout
    if len(raw) < width * h * 3:
        return None
    return np.frombuffer(raw[: width * h * 3], np.uint8).reshape(h, width, 3)


from faces import detect_face as face_box, skin_rois  # noqa: E402


def measure(img: np.ndarray, want_face: bool = True) -> dict:
    ycc = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb).astype(np.float64)
    y = ycc[:, :, 0] / 255 * 100
    cr, cb = ycc[:, :, 1] - 128, ycc[:, :, 2] - 128
    chroma = np.sqrt(cr ** 2 + cb ** 2)
    out = {
        "luma": {"p1": round(float(np.percentile(y, 1)), 1),
                 "p5": round(float(np.percentile(y, 5)), 1),
                 "p50": round(float(np.percentile(y, 50)), 1),
                 "p95": round(float(np.percentile(y, 95)), 1),
                 "p99": round(float(np.percentile(y, 99)), 1),
                 "crushed_pct": round(float((y < 1.0).mean() * 100), 2),
                 "clipped_pct": round(float((y > 99.0).mean() * 100), 2)},
        "chroma_mean": round(float(chroma.mean()), 1),
    }
    # gray-world em pixels de baixa saturação: ganhos que neutralizam
    bgr = img.astype(np.float64)
    low_sat = chroma < 12
    if low_sat.sum() > 500:
        b, g, r = (bgr[:, :, i][low_sat].mean() for i in range(3))
        out["white"] = {"r_over_g": round(r / g, 3) if g else 1.0,
                        "b_over_g": round(b / g, 3) if g else 1.0,
                        "gain_r": round(g / r, 3) if r else 1.0,
                        "gain_b": round(g / b, 3) if b else 1.0}
    if want_face:
        box = face_box(img)
        if box:
            sel = np.zeros(y.shape, dtype=bool)
            for x0, y0, x1, y1 in skin_rois(box):
                sel[y0:y1, x0:x1] = True
            fcr, fcb = cr[sel].mean(), cb[sel].mean()
            angle = (np.degrees(np.arctan2(fcr, fcb)) + 360) % 360
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 0][sel]
            out["skin"] = {"luma_p50": round(float(np.percentile(y[sel], 50)), 1),
                           "angle_deg": round(float(angle), 1),
                           "off_skin_line_deg": round(float(angle - SKIN_LINE_DEG), 1),
                           "chroma": round(float(np.sqrt(fcr ** 2 + fcb ** 2)), 1),
                           "hue_hsv": round(float(np.median(hsv) * 2), 0),
                           "box": [int(v) for v in box]}
    return out


def median_of(reports: list[dict]) -> dict:
    """Mediana campo a campo (numérico) de vários relatórios.

    Um campo entra se está em pelo menos METADE das amostras (o rosto some
    num quadro ou outro e isso não pode apagar a medida de pele do take
    inteiro); a mediana é calculada só sobre as amostras que o têm.
    """
    def walk(items):
        items = [i for i in items if i is not None]
        if not items:
            return None
        if isinstance(items[0], dict):
            dicts = [i for i in items if isinstance(i, dict)]
            keys = []
            for d in dicts:
                for k in d:
                    if k not in keys:
                        keys.append(k)
            out = {}
            for k in keys:
                have = [d[k] for d in dicts if k in d]
                if len(have) * 2 >= len(dicts):
                    out[k] = walk(have)
            return out
        if isinstance(items[0], (int, float)):
            return round(float(np.median(items)), 2)
        return items[0]
    return walk(reports)


def analyze_video(path: Path, at: float | None, face: bool, samples: int = 12) -> dict:
    info = probe(path)
    if at is not None:
        ts = [at]
    else:
        ts = list(np.linspace(0.3, max(0.3, info["duration"] - 0.3), samples))
    reps = []
    for t in ts:
        img = frame_at(path, float(t))
        if img is not None:
            reps.append(measure(img, face))
    rep = median_of(reps) if len(reps) > 1 else (reps[0] if reps else {})
    rep["samples"] = len(reps)
    return rep


def analyze_take(path: Path, start: float, end: float, face: bool, samples: int = 6) -> dict:
    ts = np.linspace(start + 0.2, max(start + 0.2, end - 0.2), samples)
    reps = [measure(img, face) for t in ts if (img := frame_at(path, float(t))) is not None]
    rep = median_of(reps) if len(reps) > 1 else (reps[0] if reps else {})
    rep["samples"] = len(reps)
    return rep


def fmt(rep: dict) -> str:
    l = rep.get("luma", {})
    line = (f"luma P1/P50/P99 {l.get('p1', 0):5.1f}/{l.get('p50', 0):5.1f}/{l.get('p99', 0):5.1f}"
            f"  esmagado {l.get('crushed_pct', 0):.1f}%  estourado {l.get('clipped_pct', 0):.1f}%"
            f"  croma {rep.get('chroma_mean', 0):.1f}")
    if "white" in rep:
        w = rep["white"]
        line += f"  branco R/G {w['r_over_g']:.3f} B/G {w['b_over_g']:.3f}"
    if "skin" in rep:
        s = rep["skin"]
        line += (f"  pele: luma {s['luma_p50']:.0f}, {s['off_skin_line_deg']:+.0f}° da linha,"
                 f" croma {s['chroma']:.0f}")
    return line


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path, nargs="?")
    ap.add_argument("--at", type=float, default=None)
    ap.add_argument("--edl", type=Path, default=None)
    ap.add_argument("--face", action="store_true", default=True)
    ap.add_argument("--no-face", dest="face", action="store_false")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.edl:
        edl = json.loads(args.edl.read_text())
        base = args.edl.resolve().parent
        out = []
        for i, r in enumerate(edl["ranges"]):
            src = Path(edl["sources"][r["source"]]).expanduser()
            if not src.is_absolute():
                src = (base / src).resolve()
            rep = analyze_take(src, float(r["start"]), float(r["end"]), args.face)
            rep["take"], rep["beat"] = i, r.get("beat")
            out.append(rep)
            if not args.json:
                print(f"[{i:02d}] {r.get('beat') or '':<10} {fmt(rep)}")
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if not args.video:
        ap.error("passe um vídeo ou --edl")
    rep = analyze_video(args.video, args.at, args.face)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        where = f"@{args.at}s" if args.at is not None else f"mediana de {rep.get('samples')} amostras"
        print(f"{args.video.name} ({where})")
        print("  " + fmt(rep))
        if "skin" in rep:
            print(f"  skin_protect sugerido no EDL: {{\"hue\": {rep['skin']['hue_hsv']:.0f}, \"strength\": 0.6}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
