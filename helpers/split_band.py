#!/usr/bin/env python3
"""bandH da tela dividida a partir do clipe — o padrão do Formato 1, generalizado.

O template desenha a arte com `bandH + SEAM_BLEND` de altura e dissolve os
últimos SEAM_BLEND pixels. Então a costura cai exatamente na BORDA DE BAIXO do
próprio clipe — sem sombra, sem cortar a arte — quando:

    bandH = altura natural do clipe (na largura do quadro) − SEAM_BLEND

É a regra que o preset do Formato 1 registra como caso particular: clipe 16:9 a
1080 de largura mede 608, logo bandH 508. O mesmo cálculo num clipe 1080×860 dá
bandH 760, que foi a calibragem de um vídeo em enquadramento fechado. Um número
não contradiz o outro: é a mesma regra com clipes de altura diferente.

O que este helper NÃO dá é o `focusY`. Ele depende de onde a cabeça está na
FONTE, não no clipe, e continua medido num still — a própria nota do preset
avisa que mexer em bandH obriga a recalcular focusY, e é por isso que a saída
aqui repete o aviso quando o valor sai do padrão.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

SEAM_BLEND = 100   # espelha CustomGraphics.tsx — mudar lá obriga mudar aqui
FRAME_W = 1080
FRAME_H = 1920
FORMATO_1_BANDH = 508


def band_height(clip_w: int, clip_h: int, frame_w: int = FRAME_W,
                seam_blend: int = SEAM_BLEND) -> int:
    """bandH para a costura cair na borda inferior do clipe."""
    if clip_w <= 0 or clip_h <= 0:
        raise ValueError('Dimensões do clipe inválidas')
    natural = round(clip_h * frame_w / clip_w)
    band = natural - seam_blend
    if band <= 0:
        raise ValueError(
            f'Clipe baixo demais: a {frame_w}px de largura ele mede {natural}px, '
            f'menos que os {seam_blend}px da dissolução. Use um clipe mais alto '
            f'ou recorte-o para a proporção da faixa.')
    return band


def probe(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height', '-of', 'json', str(path)],
        capture_output=True, text=True, check=True).stdout
    stream = json.loads(out)['streams'][0]
    return int(stream['width']), int(stream['height'])


def main() -> None:
    ap = argparse.ArgumentParser(description='bandH da tela dividida, a partir do clipe')
    ap.add_argument('clips', nargs='+', type=Path)
    ap.add_argument('--frame-width', type=int, default=FRAME_W)
    args = ap.parse_args()

    failed = False
    for clip in args.clips:
        try:
            w, h = probe(clip)
            band = band_height(w, h, args.frame_width)
        except (OSError, ValueError, KeyError, IndexError, subprocess.CalledProcessError) as e:
            print(f'✗ {clip.name}: {e}')
            failed = True
            continue
        natural = round(h * args.frame_width / w)
        note = '' if band == FORMATO_1_BANDH else '  ← fora do padrão: recalibre o focusY num still'
        print(f'· {clip.name}: {w}x{h} → {args.frame_width}x{natural} → bandH {band}{note}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
