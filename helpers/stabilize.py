"""Estabilização de câmera, UMA vez por fonte e cacheada — como o audio_clean.

O ffmpeg deste Mac não tem vidstab; o `deshake` que ele tem é de passagem única
e treme junto. Este helper faz o que o vidstab e o Warp Stabilizer fazem, em
duas passagens e com controle total:

  1. análise    fluxo óptico (Lucas-Kanade em cantos) quadro a quadro num
                proxy de 480 px → transformação afim parcial (dx, dy, rotação)
                por RANSAC → trajetória acumulada da câmera.
  2. correção   a trajetória é suavizada (gaussiana, `--smooth` segundos) ou
                travada (`--mode lock`: como se estivesse num tripé) e cada
                quadro recebe a diferença, em resolução de entrega, com um
                zoom fixo que esconde as bordas — o zoom é calculado da maior
                correção necessária e limitado a `--max-zoom`; o que passar
                disso é clampado (melhor um solavanco residual que zoom 20%).

`lock` é o modo certo para fala de frente para a câmera segurada na mão: a
pessoa fica plantada e só o fundo "respira" nas bordas. `smooth` é para câmera
que se move de propósito (caminhada, pan) e só quer perder a tremida.

Saída em resolução de ENTREGA (1080 de altura para retrato, 1920 de largura
para paisagem), H.264 CRF 14 — o render extrai os segmentos daí em vez da
fonte, com o mesmo grade e os mesmos fades. Cacheado por tamanho+mtime+params.

Usage:
    uv run python helpers/stabilize.py <source> --edit-dir <edit>
    uv run python helpers/stabilize.py <source> --edit-dir <edit> --mode smooth --smooth 1.5
    uv run python helpers/stabilize.py <source> --edit-dir <edit> --report   # só mede a tremida

Saídas em <edit>/stab/:
    <stem>.mp4    fonte estabilizada
    <stem>.json   trajetória, zoom aplicado, tremida antes/depois (px RMS)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

PROXY_W = 480


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate,nb_frames:format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s = d["streams"][0]
    num, _, den = s["r_frame_rate"].partition("/")
    return {"w": int(s["width"]), "h": int(s["height"]),
            "fps": float(num) / float(den or 1),
            "duration": float(d["format"].get("duration") or 0)}


def delivery_size(w: int, h: int) -> tuple[int, int]:
    if h > w:
        return int(round(w * 1920 / h / 2)) * 2, 1920
    return 1920, int(round(h * 1920 / w / 2)) * 2


def frames(path: Path, w: int, h: int):
    """Gera quadros BGR (h, w, 3) via ffmpeg, na ordem."""
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, bufsize=w * h * 3 * 4)
    size = w * h * 3
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    proc.stdout.close()
    proc.wait()


# ---------------------------------------------------------------- passo 1

def analyze(path: Path, info: dict) -> np.ndarray:
    """Movimento quadro a quadro (dx, dy, da) no proxy, em pixels do proxy."""
    pw = PROXY_W
    ph = int(round(info["h"] * pw / info["w"] / 2)) * 2
    prev_gray = None
    motions = [(0.0, 0.0, 0.0)]
    # Só a moldura do quadro conta como "câmera". Num talking head a pessoa
    # ocupa o centro e se mexe; sem a máscara o RANSAC elege o torso dela como
    # o movimento dominante e "estabiliza" a câmera contra a pessoa — medido:
    # 1,16 px/quadro numa fonte em tripé. A moldura é onde o fundo está.
    border = np.zeros((ph, pw), np.uint8)
    bx, by = int(pw * 0.22), int(ph * 0.22)
    border[:by, :] = 255
    border[-by:, :] = 255
    border[:, :bx] = 255
    border[:, -bx:] = 255
    for img in frames(path, pw, ph):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if prev_gray is None:
            prev_gray = gray
            continue
        pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=300, qualityLevel=0.01,
                                      minDistance=12, blockSize=5, mask=border)
        if pts is None or len(pts) < 12:  # fundo liso: usa o quadro inteiro
            pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=300, qualityLevel=0.01,
                                          minDistance=12, blockSize=5)
        dx = dy = da = 0.0
        if pts is not None and len(pts) >= 12:
            nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None,
                                                  winSize=(21, 21), maxLevel=3)
            good = st.reshape(-1) == 1
            p0, p1 = pts[good].reshape(-1, 2), nxt[good].reshape(-1, 2)
            if len(p0) >= 12:
                # Origem no CENTRO do quadro: a rotação medida passa a ser "em
                # torno do centro", que é como apply() a desfaz. Com a origem no
                # canto, a translação da afim carrega (I−R)·centro — ~2 px por
                # quadro a 0,25°, o bastante para a correção errar quase metade.
                center = np.array([[pw / 2, ph / 2]], dtype=np.float32)
                m, inliers = cv2.estimateAffinePartial2D(p0 - center, p1 - center,
                                                         method=cv2.RANSAC,
                                                         ransacReprojThreshold=2.0)
                if m is not None:
                    dx, dy = float(m[0, 2]), float(m[1, 2])
                    da = float(math.atan2(m[1, 0], m[0, 0]))
        motions.append((dx, dy, da))
        prev_gray = gray
    return np.array(motions, dtype=np.float64)


def smooth_path(traj: np.ndarray, sigma_frames: float) -> np.ndarray:
    if sigma_frames <= 0:
        return traj
    r = int(3 * sigma_frames)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_frames) ** 2)
    k /= k.sum()
    out = np.empty_like(traj)
    for c in range(traj.shape[1]):
        padded = np.pad(traj[:, c], r, mode="edge")
        out[:, c] = np.convolve(padded, k, mode="valid")
    return out


# ---------------------------------------------------------------- passo 2

def apply(path: Path, out: Path, info: dict, corr: np.ndarray, zoom: float,
          proxy_scale: float) -> None:
    ow, oh = delivery_size(info["w"], info["h"])
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{ow}x{oh}", "-r", f"{info['fps']:.6f}", "-i", "-",
         "-i", str(path), "-map", "0:v:0", "-map", "1:a:0?",
         "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-c:a", "copy", "-movflags", "+faststart", "-shortest", str(out)],
        stdin=subprocess.PIPE)
    cx, cy = ow / 2, oh / 2
    for i, img in enumerate(frames(path, ow, oh)):
        dx, dy, da = corr[min(i, len(corr) - 1)]
        # correção medida no proxy → escala de entrega
        dx *= proxy_scale
        dy *= proxy_scale
        # sinal: estimateAffinePartial2D mede a = atan2(m10, m00); getRotationMatrix2D
        # usa a convenção oposta, então a correção entra negada
        m = cv2.getRotationMatrix2D((cx, cy), -math.degrees(da), zoom)
        m[0, 2] += dx
        m[1, 2] += dy
        warped = cv2.warpAffine(img, m, (ow, oh), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_REPLICATE)
        enc.stdin.write(warped.tobytes())
    enc.stdin.close()
    enc.wait()
    if enc.returncode != 0:
        raise SystemExit("ffmpeg falhou no encode da fonte estabilizada")


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", type=Path)
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--mode", choices=["lock", "smooth"], default="lock")
    ap.add_argument("--smooth", type=float, default=1.0,
                    help="segundos da janela de suavização (modo smooth)")
    ap.add_argument("--max-zoom", type=float, default=1.08,
                    help="zoom máximo para esconder bordas (1.08 = 8%%)")
    ap.add_argument("--report", action="store_true", help="só mede, não escreve")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    source = args.source.expanduser().resolve()
    edit_dir = args.edit_dir.expanduser().resolve()
    out_dir = edit_dir / "stab"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = out_dir / f"{source.stem}.mp4"
    out_json = out_dir / f"{source.stem}.json"

    info = probe(source)
    params = {"mode": args.mode, "smooth": args.smooth, "max_zoom": args.max_zoom, "v": 1}
    st = source.stat()
    key = hashlib.sha1(json.dumps({"size": st.st_size, "mtime": int(st.st_mtime),
                                   **params}, sort_keys=True).encode()).hexdigest()[:12]
    if not args.force and not args.report and out_json.exists() and out_mp4.exists():
        try:
            if json.loads(out_json.read_text()).get("cache_key") == key:
                print(f"cache: {out_mp4.name} já estabilizado com estes parâmetros")
                return 0
        except json.JSONDecodeError:
            pass

    print(f"{source.name}: {info['w']}x{info['h']} {info['fps']:.2f}fps {info['duration']:.1f}s")
    motions = analyze(source, info)
    traj = np.cumsum(motions, axis=0)
    proxy_scale = delivery_size(info["w"], info["h"])[0] / PROXY_W

    if args.mode == "lock":
        target = np.repeat(np.median(traj, axis=0, keepdims=True), len(traj), axis=0)
        # lock total em translação e rotação: a pessoa fica plantada
    else:
        target = smooth_path(traj, args.smooth * info["fps"])
    corr = target - traj  # o que somar a cada quadro para cair na trajetória alvo

    # zoom necessário: maior deslocamento em px de entrega vs metade da borda
    ow, oh = delivery_size(info["w"], info["h"])
    need_x = float(np.abs(corr[:, 0]).max() * proxy_scale)
    need_y = float(np.abs(corr[:, 1]).max() * proxy_scale)
    need_rot = float(np.abs(corr[:, 2]).max())
    zoom_needed = max(1 + 2 * need_x / ow, 1 + 2 * need_y / oh,
                      1 + math.sin(need_rot) * max(ow, oh) / min(ow, oh))
    zoom = min(zoom_needed, args.max_zoom)
    if zoom_needed > args.max_zoom:
        # clampa a correção ao que o zoom cobre; sobra um solavanco residual
        lim_x = (zoom - 1) * ow / 2 / proxy_scale
        lim_y = (zoom - 1) * oh / 2 / proxy_scale
        corr[:, 0] = np.clip(corr[:, 0], -lim_x, lim_x)
        corr[:, 1] = np.clip(corr[:, 1], -lim_y, lim_y)
        clamp_note = f" (precisava {zoom_needed:.3f}; correção clampada)"
    else:
        clamp_note = ""

    shake_before = float(np.sqrt(np.mean(np.sum(motions[:, :2] ** 2, axis=1))) * proxy_scale)
    residual = motions + np.diff(np.vstack([corr[:1], corr]), axis=0)
    shake_after = float(np.sqrt(np.mean(np.sum(residual[:, :2] ** 2, axis=1))) * proxy_scale)
    print(f"  tremida: {shake_before:.2f} px/quadro RMS → {shake_after:.2f} "
          f"(modo {args.mode}, zoom {zoom:.3f}{clamp_note})")
    if shake_before < 0.35:
        print("  fonte já estável (< 0,35 px/quadro): estabilizar não muda nada")

    report = {"source": str(source), "cache_key": key, "params": params,
              "shake_px_before": round(shake_before, 3), "shake_px_after": round(shake_after, 3),
              "zoom": round(zoom, 4), "zoom_needed": round(zoom_needed, 4),
              "delivery": [ow, oh], "frames": int(len(motions))}
    if args.report:
        print(json.dumps(report, indent=2))
        return 0

    apply(source, out_mp4, info, corr, zoom, proxy_scale)
    out_json.write_text(json.dumps(report, indent=2) + "\n")
    print(f"  → {out_mp4} ({out_mp4.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
