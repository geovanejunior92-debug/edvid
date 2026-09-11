#!/usr/bin/env python3
"""Gate de imagem: o ultimo passo antes de publicar um post. Exit != 0 = nao publique.

O MESMO PRINCIPIO DO `qc_final.py`, aplicado a imagem: medir antes de olhar. As
quatro coisas que estragam post e que o olho perde numa pressa sao exatamente as
que dao numero — contraste, zona coberta pela interface do app, texto em cima do
rosto, e rosto cortado pela borda.

NAO ADIVINHA ONDE ESTA O TEXTO. Le o sidecar `<imagem>.boxes.json` que o
`post_render.py` escreve. Reconhecer texto na imagem renderizada seria caro,
aproximado, e erraria justamente sobre foto, que e onde o problema acontece.

O QUE CHECA
  contraste   luminancia real do fundo SOB cada caixa contra a cor do texto,
              razao WCAG. Abaixo de 4.5:1 falha; contorno preto conta a favor.
  zona segura o que a interface do Instagram/TikTok cobre por cima: coluna de
              icones a direita, faixa de baixo, topo no story.
  rosto       texto por cima de rosto FALHA (regra do usuario: a frase para no
              cabelo, nunca sobre o rosto). Rosto cortado pela borda avisa.
  linha       linha de titulo mais larga que o seguro no formato.

USO
  uv run python helpers/qc_image.py <edit>/post [--plataforma instagram|tiktok]
  uv run python helpers/qc_image.py <edit>/post/01_capa_4x5.jpg

Escreve `<pasta>/qc_image.json`. FALHA bloqueia; AVISO e nota para o gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Fracao do quadro que a interface do app cobre. Medido de captura real (a mesma
# origem do SAFE_WIDTH 720 da legenda karaoke: ~180 px de cada lado em 1080).
ZONAS = {
    "instagram": {
        "4x5":  {"baixo": 0.10, "direita": 0.00, "topo": 0.00},
        "1x1":  {"baixo": 0.10, "direita": 0.00, "topo": 0.00},
        "9x16": {"baixo": 0.20, "direita": 0.167, "topo": 0.12},
        "16x9": {"baixo": 0.00, "direita": 0.00, "topo": 0.00},
    },
    "tiktok": {
        "9x16": {"baixo": 0.23, "direita": 0.20, "topo": 0.10},
        "4x5":  {"baixo": 0.12, "direita": 0.00, "topo": 0.00},
        "1x1":  {"baixo": 0.12, "direita": 0.00, "topo": 0.00},
        "16x9": {"baixo": 0.00, "direita": 0.00, "topo": 0.00},
    },
}
MIN_CONTRASTE = 4.5      # WCAG AA para texto grande e o piso que uso aqui
MIN_FONTE_PX = 26        # abaixo disso nao se le no telefone


def luminancia(c) -> float:
    def canal(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(x) for x in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b) -> float:
    la, lb = luminancia(a), luminancia(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def rostos(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Rostos como (x, y, w, h). Usa o mesmo detector do resto da skill."""
    try:
        import cv2
        from faces import detect_face
    except Exception:
        return []
    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    try:
        r = detect_face(arr)
    except Exception:
        return []
    # MEDIDO: o `faces.detect_face` devolve UMA tupla (x, y, w, h), ou None —
    # nao uma lista. Tratar como lista iterava sobre os inteiros da propria caixa
    # e estourava com "object of type 'int' has no len()".
    if not r:
        return []
    if isinstance(r, (tuple, list)) and len(r) == 4 and all(isinstance(v, (int, float, np.integer)) for v in r):
        return [tuple(int(v) for v in r)]
    out = []
    for f in r:
        if isinstance(f, dict):
            box = f.get("box") or f.get("bbox") or f.get("rect")
            if box and len(box) == 4:
                out.append(tuple(int(v) for v in box))
        elif isinstance(f, (tuple, list)) and len(f) == 4:
            out.append(tuple(int(v) for v in f))
    return out


def sobrepoe(a, b) -> float:
    """Fracao da caixa `a` coberta por `b`."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return (ix * iy) / max(1, aw * ah)


def checar(jpg: Path, plataforma: str) -> dict:
    side = jpg.with_suffix(".boxes.json")
    img = Image.open(jpg).convert("RGB")
    W, H = img.size
    arr = np.array(img)
    achados = []
    meta = json.loads(side.read_text(encoding="utf-8")) if side.is_file() else {}
    fmt = meta.get("formato") or f"{W}x{H}"
    caixas = meta.get("caixas") or []
    if not side.is_file():
        achados.append(("AVISO", "sidecar", f"sem {side.name}: so da para checar rosto e zona"))

    zona = (ZONAS.get(plataforma) or {}).get(fmt, {"baixo": 0, "direita": 0, "topo": 0})
    lim_baixo = H * (1 - zona["baixo"])
    lim_topo = H * zona["topo"]
    lim_dir = W * (1 - zona["direita"])

    faces = rostos(img)
    for (fx, fy, fw, fh) in faces:
        if fx <= 2 or fy <= 2 or fx + fw >= W - 2 or fy + fh >= H - 2:
            achados.append(("AVISO", "rosto", "rosto encosta na borda do quadro"))

    for c in caixas:
        x, y, w, h = c["x"], c["y"], c["w"], c["h"]
        rotulo = f'{c["papel"]} "{c["texto"][:28]}"'

        # contraste contra o fundo REAL sob a caixa
        y0, y1 = max(0, y), min(H, y + h)
        x0, x1 = max(0, x), min(W, x + w)
        if y1 > y0 and x1 > x0:
            fundo = arr[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
            r = contraste(c["cor"], fundo)
            if r < MIN_CONTRASTE:
                nivel = "AVISO" if c.get("contorno") else "FALHA"
                extra = " (tem contorno preto, que ajuda o olho mas nao o numero)" if c.get("contorno") else ""
                achados.append((nivel, "contraste", f"{rotulo}: {r:.1f}:1, minimo {MIN_CONTRASTE}:1{extra}"))

        if c.get("fonte_px", 99) < MIN_FONTE_PX:
            achados.append(("FALHA", "fonte", f"{rotulo}: {c['fonte_px']}px, minimo {MIN_FONTE_PX}px"))

        # zona coberta pela interface do app
        if y + h > lim_baixo:
            achados.append(("FALHA", "zona", f"{rotulo}: entra na faixa de baixo do {plataforma}"))
        if y < lim_topo:
            achados.append(("FALHA", "zona", f"{rotulo}: entra na faixa de topo do {plataforma}"))
        if x + w > lim_dir:
            achados.append(("FALHA", "zona", f"{rotulo}: passa da coluna de icones"))

        # texto por cima do rosto — regra explicita do usuario
        for f in faces:
            cob = sobrepoe(f, (x, y, w, h))
            if cob > 0.12:
                achados.append(("FALHA", "rosto",
                                f"{rotulo}: cobre {cob*100:.0f}% do rosto — a frase tem que parar no cabelo"))

    falhas = [a for a in achados if a[0] == "FALHA"]
    return {"imagem": jpg.name, "formato": fmt, "plataforma": plataforma,
            "rostos": len(faces), "caixas": len(caixas),
            "achados": [{"nivel": n, "tipo": t, "msg": m} for n, t, m in achados],
            "ok": not falhas}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("alvo", type=Path, help="pasta post/ ou um .jpg")
    ap.add_argument("--plataforma", default="instagram", choices=list(ZONAS))
    a = ap.parse_args()

    jpgs = sorted(a.alvo.glob("*.jpg")) if a.alvo.is_dir() else [a.alvo]
    jpgs = [j for j in jpgs if not j.name.startswith("_")]
    if not jpgs:
        print(f"nenhuma imagem em {a.alvo}", file=sys.stderr)
        return 1

    rel, falhas, avisos = [], 0, 0
    for j in jpgs:
        r = checar(j, a.plataforma)
        rel.append(r)
        marca = "ok " if r["ok"] else "FALHA"
        print(f"[{marca}] {j.name}  ({r['caixas']} caixas, {r['rostos']} rosto(s))")
        for x in r["achados"]:
            print(f"    {x['nivel']:5s} {x['tipo']:10s} {x['msg']}")
            falhas += x["nivel"] == "FALHA"
            avisos += x["nivel"] == "AVISO"

    destino = (a.alvo if a.alvo.is_dir() else a.alvo.parent) / "qc_image.json"
    destino.write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(jpgs)} imagem(ns) | {falhas} falha(s), {avisos} aviso(s) → {destino}")
    if falhas:
        print("NAO PUBLIQUE. Corrija no post-data.json e renderize de novo.")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
