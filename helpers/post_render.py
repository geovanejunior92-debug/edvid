#!/usr/bin/env python3
"""Renderiza um post de imagem a partir de `post-data.json`. O `render.py` da imagem.

POR QUE PIL E NAO REMOTION. O `cover.py` ja compoe capa com Pillow + OpenCV e
entrega em 9:16 e 4:5. Para quadro ESTATICO o Remotion so acrescenta Node, um
processo de render e segundos de espera por imagem — paga-se o preco de um motor
de video para produzir um PNG. Toda a composicao aqui reaproveita o que o
`cover.py` provou: fonte da marca, contorno preto, degrade de escurecimento no
topo, corte 1080x1920 -> 1080x1350.

O POST E DADO, NAO CODIGO. Igual a Fase 2: o visual inteiro vive em
`post-data.json`. Slide novo se escreve no JSON, nao aqui.

FORMATOS
  4x5    1080x1350  feed do Instagram (o que mais ocupa tela)
  1x1    1080x1080  quadrado
  9x16   1080x1920  story / Reels capa
  16x9   1280x720   thumbnail de YouTube

TIPOS DE SLIDE
  capa    titulo grande sobre quadro de video ou imagem
  texto   titulo + corpo sobre cor solida da marca
  imagem  imagem cheia com faixa de legenda embaixo
  cta     fecho, cor da marca, chamada

USO
  uv run python helpers/post_render.py <edit>/post-data.json [--formatos 4x5 1x1]
  uv run python helpers/post_render.py <edit>/post-data.json --slide 3

Sai em `<edit>/post/<n>_<tipo>_<formato>.jpg`. Depois disso, SEMPRE `qc_image.py`
— este helper desenha, ele nao julga se ficou legivel.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
TITULO = FONTS / "Poppins-ExtraBold.ttf"
DESTAQUE = FONTS / "PlayfairDisplay-Italic.ttf"
CORPO = FONTS / "Poppins-Light.ttf"

# Identidade do Dr. Geovane: azul-petroleo e dourado, os mesmos da tela de
# encerramento dos videos. Post e Reel do mesmo assunto tem que parecer irmaos.
MARCA = {"fundo": "#071d33", "texto": "#ffffff", "destaque": "#d4b25f"}

FORMATOS = {"4x5": (1080, 1350), "1x1": (1080, 1080),
            "9x16": (1080, 1920), "16x9": (1280, 720)}

# Margem lateral por formato. 84 px em 1080 e a do cover.py, ja validada contra
# a coluna de icones do Instagram.
MARGEM = {"4x5": 84, "1x1": 84, "9x16": 84, "16x9": 72}


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def quadro_do_video(video: Path, t: float, alvo: tuple[int, int]) -> Image.Image:
    """Um quadro do video em `t`, coberto no formato alvo (crop central)."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
           "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise SystemExit(f"nao consegui extrair o quadro em {t}s de {video}")
    import io
    return cobrir(Image.open(io.BytesIO(p.stdout)).convert("RGB"), alvo)


def cobrir(img: Image.Image, alvo: tuple[int, int]) -> Image.Image:
    """Preenche o alvo mantendo proporcao, cortando o excedente pelo centro.

    Corta pelo centro na horizontal e pelo TOPO na vertical: em enquadramento de
    pessoa, o rosto vive na parte de cima e cortar por baixo perde menos.
    """
    W, H = alvo
    s = max(W / img.width, H / img.height)
    img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    left = (img.width - W) // 2
    top = 0 if img.height - H > 0 and H / W > 1 else (img.height - H) // 2
    return img.crop((left, top, left + W, top + H))


def escurecer_topo(img: Image.Image, forca: int = 150, altura: float = 0.42) -> Image.Image:
    """Degrade preto no topo para o titulo ler sobre foto. Do cover.py."""
    W, H = img.size
    col = np.array([int(forca * max(0.0, 1 - y / (H * altura)) ** 1.4) for y in range(H)],
                   dtype=np.uint8)
    grad = Image.fromarray(np.repeat(col[:, None], W, axis=1), mode="L")
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, grad)


def quebrar(draw, texto: str, fonte, max_w: int, max_linhas: int) -> list[str]:
    palavras, linhas, atual = texto.split(), [], ""
    for p in palavras:
        teste = f"{atual} {p}".strip()
        if draw.textlength(teste, font=fonte) <= max_w or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas[:max_linhas] if max_linhas else linhas


def ajustar(draw, texto: str, caminho: Path, max_w: int, max_linhas: int,
            inicio: int, minimo: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Diminui a fonte ate o texto caber nas linhas pedidas. Do cover.py."""
    size = inicio
    while size > minimo:
        f = ImageFont.truetype(str(caminho), size)
        linhas = quebrar(draw, texto, f, max_w, 0)
        if len(linhas) <= max_linhas:
            return f, linhas
        size -= 4
    f = ImageFont.truetype(str(caminho), minimo)
    return f, quebrar(draw, texto, f, max_w, max_linhas)


CAIXAS: list[dict] = []   # o que foi desenhado, para o qc_image.py julgar


def escrever(draw, linhas, fonte, x0, y, cor, alt_linha, destaque=None,
             fonte_destaque=None, cor_destaque=None, contorno=0, largura=None,
             papel=None):
    """Desenha e REGISTRA. O qc_image.py nao adivinha onde o texto caiu: le daqui.

    Sem isso o gate teria que reconhecer texto na imagem renderizada para medir
    contraste e sobreposicao com rosto — caro, aproximado, e errado quando o
    fundo e uma foto. A fonte da verdade e quem desenhou."""
    for linha in linhas:
        pedacos = []
        for w in linha.split():
            acc = destaque and w.strip(".,!?:;").lower() == destaque.lower()
            pedacos.append((w, fonte_destaque if acc and fonte_destaque else fonte,
                            cor_destaque if acc and cor_destaque else cor))
        total = sum(draw.textlength(p[0] + " ", font=p[1]) for p in pedacos)
        x = x0 if largura is None else x0 + (largura - total) / 2
        for w, f, c in pedacos:
            if contorno:
                draw.text((x, y), w, font=f, fill=c, stroke_width=contorno, stroke_fill=(0, 0, 0))
            else:
                draw.text((x, y), w, font=f, fill=c)
            x += draw.textlength(w + " ", font=f)
        if largura is None:
            x0_reg = x0
        else:
            x0_reg = x0 + (largura - total) / 2
        CAIXAS.append({"papel": papel or "texto", "texto": linha,
                       "x": int(x0_reg), "y": int(y),
                       "w": int(total), "h": int(fonte.size * 1.2),
                       "cor": list(cor), "contorno": bool(contorno),
                       "fonte_px": int(fonte.size)})
        y += alt_linha
    return y


def fundo_do_slide(slide: dict, alvo: tuple[int, int], base: Path, marca: dict) -> Image.Image:
    f = slide.get("fundo") or {}
    if "video" in f:
        v = base / f["video"] if not Path(f["video"]).is_absolute() else Path(f["video"])
        return escurecer_topo(quadro_do_video(v, float(f.get("at", 0)), alvo))
    if "arquivo" in f:
        p = base / f["arquivo"] if not Path(f["arquivo"]).is_absolute() else Path(f["arquivo"])
        img = cobrir(Image.open(p).convert("RGB"), alvo)
        return escurecer_topo(img) if slide.get("tipo") != "imagem" else img
    return Image.new("RGB", alvo, rgb(f.get("cor", marca["fundo"])))


def render_slide(slide: dict, fmt: str, base: Path, marca: dict) -> Image.Image:
    CAIXAS.clear()
    alvo = FORMATOS[fmt]
    W, H = alvo
    m = MARGEM[fmt]
    img = fundo_do_slide(slide, alvo, base, marca)
    draw = ImageDraw.Draw(img)
    tipo = slide.get("tipo", "texto")
    sobre_foto = bool((slide.get("fundo") or {}).get("video") or (slide.get("fundo") or {}).get("arquivo"))
    cor_txt = rgb(marca["texto"])
    cor_acc = rgb(marca["destaque"])
    escala = W / 1080

    if tipo == "imagem":
        # faixa de legenda embaixo, imagem limpa em cima
        legenda = slide.get("corpo") or slide.get("titulo") or ""
        if legenda:
            alt = int(H * 0.22)
            faixa = Image.new("RGB", (W, alt), rgb(marca["fundo"]))
            img.paste(faixa, (0, H - alt))
            draw = ImageDraw.Draw(img)
            f, linhas = ajustar(draw, legenda, CORPO, W - 2 * m, 3, int(44 * escala), int(26 * escala))
            escrever(draw, linhas, f, m, H - alt + int(alt * 0.22), cor_txt,
                     int(f.size * 1.35), largura=W - 2 * m, papel="legenda")
        return img

    titulo = slide.get("titulo", "")
    corpo = slide.get("corpo", "")
    destaque = slide.get("destaque")

    # Capa: titulo grande no ALTO. A frase para no cabelo, nunca sobre o rosto —
    # calibragem do usuario (offsetY 0.07), e vale para imagem igual vale no video.
    y = int(H * (0.07 if tipo == "capa" else 0.14))
    inicio = int((112 if tipo == "capa" else 92) * escala)
    f_tit, linhas = ajustar(draw, titulo, TITULO, W - 2 * m, 3, inicio, int(56 * escala))
    f_acc = ImageFont.truetype(str(DESTAQUE), int(f_tit.size * 1.05))
    y = escrever(draw, linhas, f_tit, m, y, cor_txt, int(f_tit.size * 1.12),
                 destaque=destaque, fonte_destaque=f_acc, cor_destaque=cor_acc,
                 contorno=int(10 * escala) if sobre_foto else 0,
                 largura=W - 2 * m, papel="titulo")

    if corpo:
        y += int(f_tit.size * 0.55)
        f_cor, lc = ajustar(draw, corpo, CORPO, W - 2 * m, 8, int(46 * escala), int(28 * escala))
        escrever(draw, lc, f_cor, m, y, cor_txt, int(f_cor.size * 1.45),
                 contorno=int(6 * escala) if sobre_foto else 0, largura=W - 2 * m, papel="corpo")

    if tipo == "cta":
        # regua dourada como assinatura do fecho
        yb = int(H * 0.86)
        draw.rectangle([m, yb, m + int(180 * escala), yb + int(8 * escala)], fill=cor_acc)
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dados", type=Path, help="post-data.json")
    ap.add_argument("--formatos", nargs="*", default=None, choices=list(FORMATOS))
    ap.add_argument("--slide", type=int, default=None, help="renderiza so este (1-based)")
    ap.add_argument("--out-dir", type=Path, default=None)
    a = ap.parse_args()

    if not a.dados.is_file():
        print(f"nao achei {a.dados}", file=sys.stderr)
        return 1
    d = json.loads(a.dados.read_text(encoding="utf-8"))
    base = a.dados.parent
    marca = {**MARCA, **(d.get("marca") or {})}
    formatos = a.formatos or d.get("formatos") or ["4x5"]
    slides = d.get("slides") or []
    if not slides:
        print("post-data.json sem slides", file=sys.stderr)
        return 1
    out = a.out_dir or (base / "post")
    out.mkdir(parents=True, exist_ok=True)

    feitos = []
    for i, s in enumerate(slides, 1):
        if a.slide and i != a.slide:
            continue
        for fmt in formatos:
            img = render_slide(s, fmt, base, marca)
            p = out / f"{i:02d}_{s.get('tipo','texto')}_{fmt}.jpg"
            img.save(p, quality=92, subsampling=0)
            (p.with_suffix(".boxes.json")).write_text(
                json.dumps({"imagem": p.name, "formato": fmt, "tipo": s.get("tipo", "texto"),
                            "marca": marca, "fundo": s.get("fundo") or {},
                            "caixas": list(CAIXAS)}, ensure_ascii=False),
                encoding="utf-8")
            feitos.append(p)
    for p in feitos:
        print(p)
    print(f"{len(feitos)} imagem(ns) em {out}")
    print("Agora rode: qc_image.py — este helper desenha, nao julga.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
