"""Detector de rosto compartilhado (YuNet) — UMA regra de seleção para todos.

Por que existe: cada helper tinha o seu "maior rosto do quadro", e "maior" é
a regra errada com limiar baixo — um falso positivo do tamanho da cortina
ganha do rosto de verdade (visto no scopes.py com um segmento de 720p:
caixa (132, 0, 576, 807) sobre o fundo). A regra aqui:

  1. YuNet a 0,25 de confiança (rosto grande e inclinado sai com score baixo
     neste modelo, treinado em rosto pequeno) sobre o quadro reduzido a
     ~960 px de largura;
  2. descarta caixa fora do quadro, menor que 6% ou maior que 75% da largura,
     ou com proporção fora de 0,6–1,6 (rosto é ~1:1,3);
  3. entre as que sobram, a de MAIOR SCORE; empate → a mais central.

Devolve (x, y, w, h) nas coordenadas da imagem recebida, ou None.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

MODEL = Path(__file__).resolve().parent.parent / "assets" / "visual" / "face_detection_yunet_2023mar.onnx"
_det = None
_size = None


def detect_face(img: np.ndarray, min_frac: float = 0.06, max_frac: float = 0.75):
    global _det, _size
    if _det is None:
        if not MODEL.exists() or not hasattr(cv2, "FaceDetectorYN"):
            return None
        _det = cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), 0.25, 0.3, 5000)
    h, w = img.shape[:2]
    if _size != (w, h):
        _det.setInputSize((w, h))
        _size = (w, h)
    _, faces = _det.detect(np.ascontiguousarray(img))
    if faces is None or len(faces) == 0:
        return None
    cands = []
    for f in faces:
        x, y, fw, fh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
        score = float(f[14]) if len(f) > 14 else 1.0
        if fw < min_frac * w or fw > max_frac * w or fh < min_frac * h:
            continue
        if not (0.6 <= fw / max(fh, 1) <= 1.6):
            continue
        if x < -0.05 * w or y < -0.05 * h or x + fw > 1.05 * w or y + fh > 1.05 * h:
            continue
        dist = abs((x + fw / 2) / w - 0.5) + abs((y + fh / 2) / h - 0.5)
        cands.append((score, -dist, x, y, fw, fh))
    if not cands:
        return None
    _, _, x, y, fw, fh = max(cands)
    x0, y0 = max(0, int(x)), max(0, int(y))
    return x0, y0, int(min(fw, w - x0)), int(min(fh, h - y0))


def skin_rois(box: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    """Duas bochechas: ao lado do nariz, abaixo dos olhos, acima da barba.
    (x0, y0, x1, y1) cada. É onde a pele é pele mesmo num rosto com barba."""
    x, y, w, h = box
    return [(x + int(0.15 * w), y + int(0.40 * h), x + int(0.35 * w), y + int(0.60 * h)),
            (x + int(0.65 * w), y + int(0.40 * h), x + int(0.85 * w), y + int(0.60 * h))]
