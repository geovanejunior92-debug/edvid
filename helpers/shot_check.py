"""O lado da IMAGEM do pré-scan da Fase 1: o que um editor vê sem pensar.

O corte é guiado pela fala (speech_regions, voice_levels). Este helper olha o
que aquele lado não vê, por range do edl.json, DIRETO na fonte, antes do render:

  bordas     em cada início e fim de range: olho fechado (piscada) ou movimento
             brusco (gesto) exatamente no quadro do corte. Um corte que cai numa
             piscada "pisca" para o espectador; um que cai no meio de um gesto
             dá um solavanco. Para cada um, sugere o deslocamento em frames
             dentro da folga que a Hard Rule 5 já permite (30–200 ms).
  takes      exposição (luma média e luma no rosto), balanço de branco (razão
             R/G e B/G na pele) e saturação de cada take contra a mediana dos
             takes. Dois takes da mesma pessoa, na mesma sala, com 10% de
             diferença de luma são um "pulo" visível na junção — e o item que
             o casamento de cor (match_takes.py) corrige.
  quadro     posição e tamanho do rosto por take (pulo de enquadramento entre
             takes), headroom (rosto colado no topo ou afundado) e desvio
             lateral da linha do olhar.

Piscada usa mediapipe FaceMesh (EAR — eye aspect ratio) quando instalado
(`uv sync --extra visual`); sem ele, cai no Haar de olhos do OpenCV, que só
sabe "achou olho / não achou" — mais grosso, mas não cego.

Usage:
    uv run python helpers/shot_check.py <edit>/edl.json
    uv run python helpers/shot_check.py edl.json --json
    uv run python helpers/shot_check.py edl.json --no-edges   # só takes/quadro

Escreve <edit>/verify/shot_check.json. Exit 1 = há CHECK. Como o verify_cut,
é texto primeiro: abra imagem só do que ele apontar (timeline_view no frame).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from faces import detect_face, skin_rois  # noqa: E402

EDGE_FRAMES = 6          # quadros de cada lado da borda que a sugestão pode usar
EAR_CLOSED_RATIO = 0.62  # EAR abaixo de 62% da mediana do trecho = olho fechado
MOTION_SPIKE = 2.2       # movimento na borda ÷ mediana do take
LUMA_DIFF = 0.08         # 8% de luma entre takes já pula
WB_DIFF = 0.05           # 5% na razão R/G ou B/G da pele
FACE_SHIFT = 0.12        # 12% da largura do quadro
FACE_SIZE_DIFF = 0.20    # 20% de tamanho de rosto
HEADROOM_MIN, HEADROOM_MAX = 0.03, 0.45  # só extremos: o quadro de entrega pode ser outro

# FaceMesh: índices dos 6 pontos por olho usados no EAR
LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]


# ---------------------------------------------------------------- vídeo

class Source:
    """Quadros da fonte via ffmpeg, já reduzidos. Seek aleatório do OpenCV num
    4K custa ~0,3 s por quadro; um `-ss` do ffmpeg antes do `-i` + N quadros
    em sequência custa isso por BORDA, não por quadro."""

    def __init__(self, path: Path, width: int = 960):
        self.path = path
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height,r_frame_rate,nb_frames:format=duration",
             "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
        data = json.loads(probe)
        s = data["streams"][0]
        num, _, den = s["r_frame_rate"].partition("/")
        self.fps = float(num) / float(den or 1)
        self.w, self.h = int(s["width"]), int(s["height"])
        self.duration = float(data["format"].get("duration") or 0)
        self.width = width
        self.height = int(round(self.h * width / self.w / 2)) * 2

    def _decode(self, t0: float, count: int) -> list[np.ndarray]:
        t0 = max(0.0, t0)
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t0:.4f}", "-i", str(self.path),
             "-frames:v", str(count), "-vf", f"scale={self.width}:{self.height}",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            capture_output=True, check=True).stdout
        n = len(raw) // (self.width * self.height * 3)
        if n == 0:
            return []
        arr = np.frombuffer(raw[: n * self.width * self.height * 3], dtype=np.uint8)
        return list(arr.reshape(n, self.height, self.width, 3))

    def frame_at(self, t: float) -> np.ndarray | None:
        fr = self._decode(t, 1)
        return fr[0] if fr else None

    def frames_around(self, t: float, span: int) -> list[tuple[int, np.ndarray]]:
        center = int(round(t * self.fps))
        first = max(0, center - span)
        frames = self._decode(first / self.fps, 2 * span + 1)
        return [(first + k, img) for k, img in enumerate(frames)]


# ---------------------------------------------------------------- rosto

class FaceTools:
    """Rosto (Haar) + pontos do rosto (FAN, 68 pontos) para o olho.

    Por que FAN e não mediapipe: o mediapipe 1.0 aborta o processo no macOS
    (falha fatal no helper Metal, mesmo pedindo CPU) e arrasta um segundo cv2
    para o venv. FAN roda em torch, que o whisperx já traz; pesa 91 MB baixados
    uma vez. Passamos a caixa do Haar para ele pular o detector próprio (S3FD),
    que é o que custa — de ~0,8 s para ~0,1 s por quadro.
    """

    def __init__(self):
        self.face = cv2.CascadeClassifier(
            os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
        self.eyes = cv2.CascadeClassifier(
            os.path.join(cv2.data.haarcascades, "haarcascade_eye.xml"))
        self.fan = None
        self.backend = "haar"
        try:
            import torch
            import face_alignment
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            self.fan = face_alignment.FaceAlignment(
                face_alignment.LandmarksType.TWO_D, device=device, flip_input=False,
                face_detector="sfd")
            self.backend = f"fan-{device}"
        except ImportError:
            pass

    def face_box(self, img: np.ndarray) -> tuple[int, int, int, int] | None:
        """Maior-score do YuNet com a regra compartilhada (faces.py); Haar e
        S3FD do FAN como reserva, nessa ordem."""
        box = detect_face(img)
        if box is not None:
            return box
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = self.face.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4,
                                           minSize=(40, 40))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            return int(x), int(y), int(w), int(h)
        if self.fan is None:
            return None
        try:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            dets = self.fan.face_detector.detect_from_image(rgb.copy())
        except Exception:
            return None
        if dets is None or len(dets) == 0:
            return None
        d = max(dets, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        x0, y0, x1, y1 = [int(v) for v in d[:4]]
        h, w = img.shape[:2]
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return x0, y0, x1 - x0, y1 - y0

    @staticmethod
    def _ear(pts: np.ndarray) -> float:
        a = np.linalg.norm(pts[1] - pts[5])
        b = np.linalg.norm(pts[2] - pts[4])
        c = np.linalg.norm(pts[0] - pts[3])
        return float((a + b) / (2.0 * c)) if c > 0 else 0.0

    def ear(self, img: np.ndarray, box: tuple[int, int, int, int] | None) -> float | None:
        """Eye aspect ratio médio dos dois olhos; None se não deu para medir.

        O FAN acha o rosto sozinho (S3FD) e é com a caixa DELE que os pontos
        saem estáveis — a caixa do YuNet (maior, pega testa e cabelo) dava
        pontos aleatórios num rosto inclinado. Então: S3FD primeiro; a caixa
        externa só entra encolhida para a convenção do S3FD, quando ele não
        acha nada. EAR fora de [0,03; 0,6] é ponto perdido, não olho.

        O valor absoluto depende da pessoa e da escala (~0,15 aqui, não os
        0,3 da literatura), então "fechado" é RELATIVO à mediana do trecho.
        """
        if self.fan is None:
            return None
        # O S3FD do FAN perde o rosto quando ele ocupa quase metade de um quadro
        # de 960 px (e justamente nos quadros de olho fechado); a 640 px acha.
        # EAR é razão de distâncias, não muda com a escala — então o FAN sempre
        # vê a versão de 640, seja qual for o tamanho do quadro analisado.
        h0, w0 = img.shape[:2]
        if w0 > 640:
            s = 640 / w0
            img = cv2.resize(img, (640, int(round(h0 * s))))
            if box is not None:
                box = tuple(int(round(v * s)) for v in box)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        try:
            lms = self.fan.get_landmarks_from_image(rgb.copy())
        except Exception:
            lms = None
        if not lms and box is not None:
            x, y, w, h = box
            tight = [float(x + 0.14 * w), float(y + 0.26 * h),
                     float(x + 0.90 * w), float(y + 0.86 * h)]
            try:
                lms = self.fan.get_landmarks_from_image(rgb.copy(), detected_faces=[tight])
            except Exception:
                lms = None
        if not lms:
            return None
        l = lms[0]
        value = (self._ear(l[36:42]) + self._ear(l[42:48])) / 2.0
        return value if 0.03 <= value <= 0.6 else None

    def eyes_found_haar(self, img: np.ndarray, box: tuple[int, int, int, int] | None) -> bool | None:
        if box is None:
            return None
        x, y, w, h = box
        roi = cv2.cvtColor(img[y: y + int(h * 0.6), x: x + w], cv2.COLOR_BGR2GRAY)
        eyes = self.eyes.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=4,
                                          minSize=(int(w * 0.12), int(w * 0.12)))
        return len(eyes) >= 1


# ---------------------------------------------------------------- medidas

def motion_energy(a: np.ndarray, b: np.ndarray) -> float:
    ga = cv2.cvtColor(cv2.resize(a, (160, int(a.shape[0] * 160 / a.shape[1]))), cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(cv2.resize(b, (160, int(b.shape[0] * 160 / b.shape[1]))), cv2.COLOR_BGR2GRAY)
    return float(np.mean(np.abs(ga.astype(np.int16) - gb.astype(np.int16))))


def take_stats(img: np.ndarray, box: tuple[int, int, int, int] | None) -> dict:
    ycc = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    out = {"luma": float(ycc[:, :, 0].mean() / 255), "sat": float(hsv[:, :, 1].mean() / 255)}
    if box is not None:
        sel = np.zeros(img.shape[:2], dtype=bool)
        for x0, y0, x1, y1 in skin_rois(box):  # bochechas: pele mesmo com barba
            sel[y0:y1, x0:x1] = True
        skin = img[sel].astype(np.float64)
        if skin.size:
            b, g, r = skin[:, 0].mean(), skin[:, 1].mean(), skin[:, 2].mean()
            out.update({"face_luma": float(ycc[:, :, 0][sel].mean() / 255),
                        "rg": float(r / g) if g > 0 else 1.0,
                        "bg": float(b / g) if g > 0 else 1.0})
    return out


# ---------------------------------------------------------------- análise

def analyze_edges(src: Source, tools: FaceTools, t: float, kind: str,
                  take_motion_median: float) -> dict:
    """Piscada e movimento na borda; sugere deslocamento em frames."""
    frames = src.frames_around(t, EDGE_FRAMES)
    if len(frames) < 3:
        return {"t": t, "kind": kind, "flags": []}
    idx = [i for i, _ in frames]
    center = int(round(t * src.fps))
    ci = idx.index(min(idx, key=lambda i: abs(i - center)))

    # olhos por frame — EAR do FAN quando há; Haar (achou olho?) se não
    open_map: dict[int, bool | None] = {}
    ear_map: dict[int, float | None] = {}
    if tools.fan is not None:
        # uma caixa por borda: em ±6 quadros o rosto não sai do lugar, e é o
        # detector (não os pontos) que custa tempo
        box = tools.face_box(frames[ci][1])
        for i, img in frames:
            ear_map[i] = tools.ear(img, box)
        vals = [v for v in ear_map.values() if v is not None]
        if len(vals) >= 3:
            ref = float(np.median(vals))
            for i, v in ear_map.items():
                open_map[i] = None if v is None else (v >= EAR_CLOSED_RATIO * ref)
        else:
            open_map = {i: None for i, _ in frames}
    else:
        box = tools.face_box(frames[ci][1])
        for i, img in frames:
            open_map[i] = tools.eyes_found_haar(img, box)
            ear_map[i] = None

    # movimento entre frames consecutivos
    mot = {}
    for (i0, a), (i1, b) in zip(frames, frames[1:]):
        mot[i1] = motion_energy(a, b)

    flags = []
    cf = idx[ci]
    closed_here = any(open_map.get(cf + d) is False for d in (-1, 0, 1))
    if closed_here:
        # frame aberto mais próximo, na direção que a folga da regra 5 permite
        # (fim: pode ir para trás; início: pode ir para frente ou para trás)
        best = None
        for d in sorted(range(-EDGE_FRAMES, EDGE_FRAMES + 1), key=abs):
            if d == 0:
                continue
            j = cf + d
            if open_map.get(j) and all(open_map.get(j + e) is not False for e in (-1, 1)):
                best = d
                break
        flags.append({"check": "piscada", "shift_frames": best,
                      "ear": None if ear_map.get(cf) is None else round(ear_map[cf], 3)})

    if take_motion_median > 0 and mot.get(cf) is not None:
        ratio = mot[cf] / take_motion_median
        if ratio >= MOTION_SPIKE:
            calm = min(((abs(j - cf), j) for j, m in mot.items()
                        if m / take_motion_median < 1.3 and j != cf), default=None)
            flags.append({"check": "movimento", "ratio": round(ratio, 1),
                          "shift_frames": None if calm is None else calm[1] - cf})

    return {"t": round(t, 3), "kind": kind, "flags": flags,
            "eyes_backend": tools.backend}


def analyze_take(src: Source, tools: FaceTools, start: float, end: float,
                 samples: int = 8) -> dict:
    ts = np.linspace(start + 0.2, max(start + 0.2, end - 0.2), samples)
    stats, boxes, motions = [], [], []
    prev = None
    for t in ts:
        img = src.frame_at(float(t))
        if img is None:
            continue
        box = tools.face_box(img)
        stats.append(take_stats(img, box))
        if box is not None:
            x, y, w, h = box
            H, W = img.shape[:2]
            boxes.append({"cx": (x + w / 2) / W, "cy": (y + h / 2) / H,
                          "size": w / W, "top": y / H})
        if prev is not None:
            motions.append(motion_energy(prev, img))
        prev = img
    med = lambda key: float(np.median([s[key] for s in stats if key in s])) if any(key in s for s in stats) else None
    out = {"luma": med("luma"), "face_luma": med("face_luma"), "sat": med("sat"),
           "rg": med("rg"), "bg": med("bg"),
           "motion_median": float(np.median(motions)) if motions else 0.0,
           "face_found": len(boxes) / max(1, len(stats))}
    if boxes:
        out["face"] = {k: float(np.median([b[k] for b in boxes])) for k in ("cx", "cy", "size", "top")}
    return out


def compare_takes(takes: list[dict]) -> list[dict]:
    """Cada take contra a mediana dos takes. Devolve flags."""
    flags = []
    def med(key, sub=None):
        vals = [(t[sub][key] if sub else t.get(key)) for t in takes
                if (t.get(sub) if sub else t.get(key)) is not None]
        return float(np.median(vals)) if vals else None

    m_luma, m_fl, m_rg, m_bg = med("luma"), med("face_luma"), med("rg"), med("bg")
    m_cx, m_size, m_top = med("cx", "face"), med("size", "face"), med("top", "face")
    for i, t in enumerate(takes):
        beat = t.get("beat") or f"take {i + 1}"
        ref = t.get("face_luma") if (t.get("face_luma") is not None and m_fl is not None) else t.get("luma")
        base = m_fl if (t.get("face_luma") is not None and m_fl is not None) else m_luma
        if ref is not None and base and abs(ref - base) / base >= LUMA_DIFF:
            flags.append({"take": i, "beat": beat, "check": "exposição",
                          "delta_pct": round((ref - base) / base * 100, 1)})
        if t.get("rg") is not None and m_rg:
            d_rg, d_bg = (t["rg"] - m_rg) / m_rg, (t["bg"] - m_bg) / m_bg
            if abs(d_rg) >= WB_DIFF or abs(d_bg) >= WB_DIFF:
                tone = "mais quente" if d_rg > 0 or d_bg < 0 else "mais fria"
                flags.append({"take": i, "beat": beat, "check": "branco",
                              "rg_pct": round(d_rg * 100, 1), "bg_pct": round(d_bg * 100, 1),
                              "tone": tone})
        f = t.get("face")
        if f and m_cx is not None:
            if abs(f["cx"] - m_cx) >= FACE_SHIFT:
                flags.append({"take": i, "beat": beat, "check": "enquadramento",
                              "shift_pct": round((f["cx"] - m_cx) * 100, 1)})
            if m_size and abs(f["size"] - m_size) / m_size >= FACE_SIZE_DIFF:
                flags.append({"take": i, "beat": beat, "check": "tamanho do rosto",
                              "delta_pct": round((f["size"] - m_size) / m_size * 100, 1)})
            if f["top"] < HEADROOM_MIN:
                flags.append({"take": i, "beat": beat, "check": "headroom",
                              "note": "rosto colado no topo", "top_pct": round(f["top"] * 100, 1)})
            elif f["top"] > HEADROOM_MAX:
                flags.append({"take": i, "beat": beat, "check": "headroom",
                              "note": "rosto afundado (muito céu)", "top_pct": round(f["top"] * 100, 1)})
        if t.get("face_found", 0) < 0.5:
            flags.append({"take": i, "beat": beat, "check": "rosto",
                          "note": f"rosto achado em só {t['face_found']*100:.0f}% das amostras"})
    return flags


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edl", type=Path)
    ap.add_argument("--no-edges", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    edl = json.loads(edl_path.read_text())
    edit_dir = edl_path.parent
    tools = FaceTools()

    sources: dict[str, Source] = {}
    for key, raw in edl["sources"].items():
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (edit_dir / p).resolve()
        sources[key] = Source(p)

    takes, edges = [], []
    for i, r in enumerate(edl["ranges"]):
        src = sources[r["source"]]
        t = analyze_take(src, tools, float(r["start"]), float(r["end"]))
        t["beat"] = r.get("beat")
        t["range"] = [r["start"], r["end"]]
        takes.append(t)
        if not args.no_edges:
            for kind, when in (("início", float(r["start"])), ("fim", float(r["end"]))):
                e = analyze_edges(src, tools, when, kind, t["motion_median"])
                e["take"] = i
                e["beat"] = r.get("beat")
                e["fps"] = src.fps
                edges.append(e)

    take_flags = compare_takes(takes)
    edge_flags = [e for e in edges if e["flags"]]

    result = {"eyes_backend": tools.backend, "takes": takes, "take_flags": take_flags,
              "edges": edges}
    (edit_dir / "verify").mkdir(exist_ok=True)
    (edit_dir / "verify" / "shot_check.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    n_flags = len(take_flags) + sum(len(e["flags"]) for e in edge_flags)
    if args.json:
        print(json.dumps({"flags": n_flags, "take_flags": take_flags,
                          "edge_flags": edge_flags}, ensure_ascii=False, indent=2))
        return 1 if n_flags else 0

    print(f"shot_check: {len(takes)} take(s), olhos via {tools.backend}")
    for i, t in enumerate(takes):
        f = t.get("face") or {}
        fl = t.get("face_luma")
        print(f"  [{i:02d}] {t.get('beat') or '':<10} luma {t['luma']:.2f}"
              + (f"  rosto {fl:.2f}" if fl is not None else "")
              + (f"  R/G {t['rg']:.2f} B/G {t['bg']:.2f}" if t.get("rg") else "")
              + (f"  cx {f['cx']:.2f} tam {f['size']:.2f} topo {f['top']:.2f}" if f else "  (sem rosto)"))
    if take_flags:
        print("CHECK takes:")
        for fl in take_flags:
            extra = {k: v for k, v in fl.items() if k not in ("take", "beat", "check")}
            print(f"  - [{fl['take']:02d}] {fl['beat']}: {fl['check']} {extra}")
    if edge_flags:
        print("CHECK bordas:")
        for e in edge_flags:
            for fl in e["flags"]:
                shift = fl.get("shift_frames")
                sug = (f"→ mover {shift:+d}f ({shift / e['fps'] * 1000:+.0f} ms)"
                       if shift is not None else "→ sem frame limpo na folga; olhe no timeline_view")
                extra = f" (EAR {fl['ear']})" if fl.get("ear") is not None else ""
                extra += f" (×{fl['ratio']} da mediana)" if fl.get("ratio") else ""
                print(f"  - [{e['take']:02d}] {e['beat']} {e['kind']} @{e['t']}s: "
                      f"{fl['check']}{extra} {sug}")
    if not n_flags:
        print("OK: nenhuma borda em piscada/gesto, takes casados, quadro estável")
    return 1 if n_flags else 0


if __name__ == "__main__":
    sys.exit(main())
