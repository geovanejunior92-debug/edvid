#!/usr/bin/env python3
"""A costura passa atrás do ALTO da cabeça? — o gate da tela dividida dele.

Regra dele, repetida em 16/08 e de novo em 11/09: *"a divisão fica atrás da
parte superior da minha cabeça como se eu estivesse na frente"*. Ter `matte` na
janela não basta. Se o `focusY` não subir a pessoa o bastante, o cabelo para
ABAIXO da faixa, o recorte não aparece em lugar nenhum e o quadro fica idêntico
a uma faixa reta — **falha silenciosa**: o render conclui, o `check_inserts.py`
aprova, e só olhando é que se vê que o efeito não aconteceu. O padrão do
template (`focusY` 400 no layout `top`) cai justamente nesse caso.

O que este helper faz é a conta que ninguém deveria fazer de cabeça: onde o
topo da cabeça CAI na tela, dado o par zoom/focusY, e onde isso fica em relação
à costura. Ele não julga estética — julga se o efeito existe e se a costura
cruza o terço superior em vez de atravessar o rosto.

A transformação é a que o próprio template documenta: um ponto `y_src` da fonte
renderiza em `(y_src − focusY) * zoom + bandH`. O termo `+ bandH` é fácil de
esquecer e inverte a conclusão — sem ele, o `focusY` 400 parece cruzar a cabeça
quando na verdade deixa o cabelo ~70px ABAIXO da faixa. No início da janela
`zoomPulse` é 1 e o push-in é 0, então é exatamente esse par; com pulso e
push-in a cabeça sobe um pouco mais ao longo da janela, e este teste mede o
momento mais apertado, que é o começo.

Só `layout: "top"` por enquanto: é o layout da fórmula documentada e o do padrão
dele. Para `bottom` a geometria do recorte é outra e eu não a medi.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

SEAM_BLEND = 100          # espelha CustomGraphics.tsx
FRAME_H = 1920
# Ancorados na calibragem real do canal (focusY 560 / 640 / 720 num mesmo
# still): 560 deu fração 0.16 e foi descrito como "encosta"; 640 deu 0.28,
# "entra"; 720 deu 0.40 e foi o que "lê como a referência". Daí a janela.
UPPER_MIN = 0.20          # abaixo disto a costura raspa o topo, mal cruza
UPPER_MAX = 0.50          # acima disto ela desce no rosto
REFERENCE = 0.40          # o que ele aprovou


def seam_position(head_top: float, head_bottom: float, focus_y: float,
                  zoom: float, band_h: float, layout: str = 'top') -> dict:
    """Onde a costura cai na cabeça, em fração da altura dela (0 = topo)."""
    if head_bottom <= head_top:
        raise ValueError('Caixa da cabeça inválida')
    if zoom <= 0:
        raise ValueError('Zoom inválido')
    if layout != 'top':
        raise ValueError("Só layout 'top' — a geometria do 'bottom' não foi medida")
    # + band_h: o termo do template. Sem ele a conclusão se inverte.
    top_r = (head_top - focus_y) * zoom + band_h
    bottom_r = (head_bottom - focus_y) * zoom + band_h
    seam = band_h
    frac = (seam - top_r) / (bottom_r - top_r)
    if frac < 0:
        verdict, why = 'FAIXA RETA', 'a cabeça fica toda abaixo da costura — o recorte não aparece'
    elif frac < UPPER_MIN:
        verdict, why = 'RASPANDO', 'a costura mal encosta no topo da cabeça'
    elif frac <= UPPER_MAX:
        verdict, why = 'OK', f'a costura cruza o alto da cabeça (referência aprovada: {REFERENCE})'
    else:
        verdict, why = 'BAIXA DEMAIS', 'a costura atravessa o rosto, não o alto da cabeça'
    return {'verdict': verdict, 'why': why, 'fraction': round(frac, 3),
            'headTopRendered': round(top_r, 1), 'seamY': round(seam, 1)}


def head_box(video: Path, at: float) -> tuple[float, float]:
    """(topo, base) da cabeça na FONTE, do quadro em `at`."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cv2  # noqa: E402  (só quando o CLI roda)
    import faces  # noqa: E402
    with tempfile.TemporaryDirectory() as tmp:
        still = Path(tmp) / 'f.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(at), '-i', str(video),
                        '-frames:v', '1', str(still), '-y'], check=True, capture_output=True)
        img = cv2.imread(str(still))
    if img is None:
        raise ValueError('Não consegui ler o quadro')
    box = faces.detect_face(img)
    if not box:
        raise ValueError('Nenhum rosto encontrado nesse instante — escolha outro')
    _, y, _, h = box
    return float(y), float(y + h)


def main() -> None:
    ap = argparse.ArgumentParser(description='A costura cruza o alto da cabeça?')
    ap.add_argument('video', type=Path)
    ap.add_argument('--at', type=float, required=True, help='instante do início da janela')
    ap.add_argument('--band-h', type=float, required=True)
    ap.add_argument('--focus-y', type=float, required=True)
    ap.add_argument('--zoom', type=float, required=True)
    ap.add_argument('--layout', choices=['top', 'bottom'], default='top')
    args = ap.parse_args()

    try:
        top, bottom = head_box(args.video, args.at)
        r = seam_position(top, bottom, args.focus_y, args.zoom, args.band_h, args.layout)
    except (OSError, ValueError, ImportError, subprocess.CalledProcessError) as e:
        print(f'✗ {e}')
        sys.exit(2)

    print(f"{r['verdict']}: {r['why']}")
    print(f"  cabeça na fonte {top:.0f}–{bottom:.0f} · topo renderiza em {r['headTopRendered']:.0f} · "
          f"costura em {r['seamY']:.0f} · fração {r['fraction']}")
    if r['verdict'] != 'OK':
        step = 'suba' if r['fraction'] < UPPER_MIN else 'desça'
        print(f"  → {step} o focusY e rode de novo (focusY MAIOR sobe a pessoa)")
    sys.exit(0 if r['verdict'] == 'OK' else 1)


if __name__ == '__main__':
    main()
