"""Ver a Fase 2 num QUADRO, sem renderizar o vídeo inteiro.

Todo defeito que já atravessou um render completo desta skill aparece numa
imagem parada: costura da tela dividida virando faixa reta, legenda empurrada
para fora pela faixa, frase da capa em cima do rosto, insert ampliado, bloco de
legenda vazio. Até agora o único jeito de olhar era renderizar o vídeo e
assistir — e o `review_final.py` existe justamente para o fim, não para iterar.

Medido em projeto real (55.73s, 1080x1920, 24fps): **o primeiro still custa ~8s
e os seguintes ~6s**, porque o bundle fica em cache. Oito quadros-chave saem em
menos de um minuto, contra o render completo dos 1337 frames.

Sem `--at`, os instantes vêm do próprio `edit-data.json` — cada um é um lugar
onde algo já deu errado antes: o meio da capa, a saída da capa, o começo de cada
janela de tela dividida/insert, a primeira legenda e o encerramento.

Uso:
    uv run python helpers/phase2_still.py <edit-dir>
    uv run python helpers/phase2_still.py <edit-dir> --at 4.2 11.6 --max 12

Sai em `<edit>/verify/phase2_still/`: um PNG por instante e a folha `sheet.png`.
Exit ≠ 0 quando algum quadro não renderizou — aí o render completo também não vai.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:  # a composição é a mesma que o Studio renderiza; não duplicar a constante
    from studio_phase2 import COMPOSITION
except Exception:  # noqa: BLE001 — helper tem que rodar sozinho
    COMPOSITION = "Reels"

# Quanto entrar numa janela antes de tirar o quadro: depois do flash de entrada,
# com a arte já no lugar.
ENTRADA_S = 0.5


def momentos(data: dict, captions: Path) -> tuple[list[tuple[float, str]], list[int]]:
    """Os instantes que valem um quadro, com o que conferir em cada um."""
    itens: list[tuple[float, str, int]] = []  # (t, rótulo, prioridade)
    dur = float(data.get("durationSec") or 0)

    capa = data.get("hookStacked") if isinstance(data.get("hookStacked"), dict) else None
    if not (capa and capa.get("enabled")):
        capa = data.get("hook") if isinstance(data.get("hook"), dict) else None
    if capa and capa.get("enabled"):
        fim = float(capa.get("endSec") or 0)
        if fim > 0:
            itens.append((fim * 0.55, "capa — altura e largura da frase", 0))
            itens.append((max(0.0, fim - 0.15), "capa saindo", 2))

    for campo, etiqueta in (("splitInserts", "tela dividida"), ("inserts", "insert"),
                            ("behindVideos", "atrás"), ("behind", "atrás")):
        for i, it in enumerate(data.get(campo) or []):
            if not isinstance(it, dict):
                continue
            try:
                start, end = float(it["start"]), float(it["end"])
            except (KeyError, TypeError, ValueError):
                continue
            t = min(start + ENTRADA_S, (start + end) / 2)
            alvo = "costura e proporção" if campo == "splitInserts" else "enquadramento"
            itens.append((t, f"{etiqueta} {i + 1} — {alvo}", 1 if i == 0 else 3))

    if (data.get("captions") or {}).get("enabled") and captions.is_file():
        try:
            cues = json.loads(captions.read_text())
            primeiro = next((c for c in cues if isinstance(c, dict)
                             and (c.get("text") or c.get("words"))), None)
            if primeiro is not None:
                ms = primeiro.get("startMs", primeiro.get("start", 0))
                itens.append((float(ms) / 1000.0 + 0.25, "primeira legenda — cabe na zona segura?", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    outro = data.get("outro") or {}
    if isinstance(outro, dict) and outro.get("enabled"):
        try:
            itens.append((float(outro["startSec"]) + 0.8, "encerramento", 0))
        except (KeyError, TypeError, ValueError):
            pass

    vistos: list[tuple[float, str, int]] = []
    for t, rot, pri in sorted(itens):
        if t < 0 or (dur and t > dur):
            continue
        if vistos and abs(t - vistos[-1][0]) < 0.15:  # dois rótulos no mesmo quadro
            continue
        vistos.append((t, rot, pri))
    return [(t, rot) for t, rot, _ in vistos], [pri for _, _, pri in vistos]


def orcamento(lista: list[tuple[float, str]], prioridades: list[int], maximo: int):
    """Corta pelos menos importantes, mantendo a ordem do tempo."""
    if len(lista) <= maximo:
        return lista
    ordem = sorted(range(len(lista)), key=lambda i: (prioridades[i], lista[i][0]))
    mantidos = sorted(ordem[:maximo])
    return [lista[i] for i in mantidos]


def still(remotion: Path, frame: int, saida: Path) -> tuple[bool, str]:
    run = subprocess.run(
        ["npx", "--no-install", "remotion", "still", COMPOSITION, str(saida),
         "--frame", str(frame), "--log", "error"],
        cwd=remotion, capture_output=True, text=True,
    )
    if run.returncode != 0 or not saida.is_file():
        erro = (run.stderr or run.stdout or "").strip().splitlines()
        return False, (erro[-1] if erro else f"código {run.returncode}")
    return True, ""


def folha(pngs: list[tuple[Path, str]], destino: Path, cols: int = 4) -> Image.Image:
    tiles = [(Image.open(p).convert("RGB"), rot) for p, rot in pngs]
    n = len(tiles)
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols
    tile_w = max(260, min(520, 1800 // cols))
    aspect = tiles[0][0].height / tiles[0][0].width
    tile_h = int(tile_w * aspect)
    label_h, gap = 42, 8
    sheet = Image.new("RGB", (cols * tile_w + (cols - 1) * gap,
                              rows * (tile_h + label_h) + (rows - 1) * gap), (12, 12, 14))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    except OSError:
        font = ImageFont.load_default()
    for i, (img, rot) in enumerate(tiles):
        cx = (i % cols) * (tile_w + gap)
        cy = (i // cols) * (tile_h + label_h + gap)
        # Truncar por LARGURA, não por número de caracteres: com 4 colunas o
        # rótulo de um corta o do vizinho e a folha fica ilegível.
        texto = rot
        while texto and draw.textlength(texto, font=font) > tile_w - 20:
            texto = texto[:-1]
        if texto != rot:
            texto = texto[:-1] + "\u2026"
        draw.text((cx + 10, cy + 8), texto, fill=(255, 255, 255), font=font)
        sheet.paste(img.resize((tile_w, tile_h)), (cx, cy + label_h))
    destino.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destino)
    return sheet


def main() -> None:
    ap = argparse.ArgumentParser(description="Quadros-chave da Fase 2 sem render completo")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--at", type=float, nargs="+", help="instantes em segundos (sobrepõe os automáticos)")
    ap.add_argument("--max", type=int, default=8, help="teto de quadros (padrão 8)")
    ap.add_argument("--cols", type=int, default=3)
    args = ap.parse_args()

    edit = args.edit_dir.expanduser().resolve()
    remotion = edit / "remotion"
    edit_data = remotion / "public" / "edit-data.json"
    if not edit_data.is_file():
        sys.exit(f"edit-data.json não encontrado: {edit_data}")
    if not (remotion / "node_modules").is_dir():
        sys.exit("as dependências do Remotion não estão neste projeto — rode o scaffold da Fase 2 "
                 "(studio_phase2.py) ou ligue o node_modules compartilhado do template")
    data = json.loads(edit_data.read_text())
    fps = float(data.get("fps") or 30)
    dur = float(data.get("durationSec") or 0)
    ultimo = max(0, int(round(dur * fps)) - 1)

    if args.at:
        lista = [(t, f"{t:.2f}s") for t in args.at]
    else:
        lista, prioridades = momentos(data, remotion / "public" / "captions.json")
        lista = orcamento(lista, prioridades, args.max)
    if not lista:
        sys.exit("nada para conferir: o edit-data.json não tem capa, insert, legenda nem encerramento")

    destino = edit / "verify" / "phase2_still"
    destino.mkdir(parents=True, exist_ok=True)
    print(f"{len(lista)} quadro(s) de {edit.parent.name} — {fps:g}fps, {dur:.2f}s\n")

    feitos: list[tuple[Path, str]] = []
    falhas = 0
    t0 = time.time()
    for i, (t, rot) in enumerate(lista):
        frame = min(max(0, int(round(t * fps))), ultimo)
        png = destino / f"{i:02d}_{frame:06d}.png"
        marca = time.time()
        ok, erro = still(remotion, frame, png)
        gasto = time.time() - marca
        if ok:
            feitos.append((png, f"{t:.2f}s — {rot}"))
            print(f"ok     {t:7.2f}s  frame {frame:<6} {rot}  ({gasto:.1f}s)")
        else:
            falhas += 1
            print(f"FALHA  {t:7.2f}s  frame {frame:<6} {rot}  — {erro}")

    if feitos:
        sheet = folha(feitos, destino / "sheet.png", cols=args.cols)
        print(f"\n{destino / 'sheet.png'} — {len(feitos)} quadros ({sheet.width}x{sheet.height})")
    print(f"{len(feitos)}/{len(lista)} em {time.time() - t0:.1f}s")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
