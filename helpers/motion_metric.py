"""Quanto o vídeo se move, medido onde ele se move e em unidade independente de fps.

Usado por `check_inserts.py` e `review_final.py`. A média do quadro inteiro reprovava
um gênero inteiro de imagem: animação médica 3D tem fundo chapado na maior parte do
quadro e um objeto pequeno girando devagar, e o denominador engolia o movimento.

- **Região:** a nota é a diferença média só nos pontos que de fato mudam. Se essa
  região for pequena demais (um logo girando num quadro parado), vale a média do
  quadro inteiro, e o clipe continua reprovando. Um quadro parado dá zero nos dois.
- **fps:** a diferença entre quadros vizinhos cai à metade a 60 fps. Acima de 30 fps
  o vídeo é amostrado a 30, e abaixo disso a nota é convertida para a mesma base,
  de modo que os limiares valem igual para qualquer fps.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

REF_FPS = 30.0
LADO = 160              # o quadro é medido em 160x160: só importa a fração da área
NIVEL_ATIVO = 1.0       # abaixo disto, em níveis de luma, é ruído de compressão
AREA_MINIMA = 0.02      # região menor que isto não conta como conteúdo em movimento


def fps_de(video: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=avg_frame_rate", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True).stdout.strip()
    try:
        num, _, den = out.partition("/")
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return REF_FPS
    return fps if fps > 0 else REF_FPS


def medir(video: Path, t0: float = 0.0, dur: float | None = None, crop: str | None = None,
          max_quadros: int = 240) -> dict:
    """{'nota', 'global', 'area'}: nota na região ativa, média do quadro, fração ativa."""
    taxa = min(fps_de(video), REF_FPS)
    filtro = (f"{crop}," if crop else "") + f"fps={taxa:.6f},scale={LADO}:{LADO},format=gray"
    cmd = ["ffmpeg", "-v", "error"]
    if t0:
        cmd += ["-ss", str(t0)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-i", str(video), "-vf", filtro, "-frames:v", str(max_quadros),
            "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (LADO * LADO)
    if n < 2:
        return {"nota": 0.0, "global": 0.0, "area": 0.0}
    quadros = np.frombuffer(raw[: n * LADO * LADO], np.uint8).reshape(n, LADO, LADO).astype(np.int16)
    # Média temporal por ponto: em quantos níveis cada um muda de um quadro ao outro.
    por_ponto = np.abs(np.diff(quadros, axis=0)).mean(axis=0)
    base = taxa / REF_FPS
    media = float(por_ponto.mean()) * base
    ativo = por_ponto > NIVEL_ATIVO
    area = float(ativo.mean())
    nota = float(por_ponto[ativo].mean()) * base if area >= AREA_MINIMA else media
    return {"nota": nota, "global": media, "area": area}
