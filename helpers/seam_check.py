#!/usr/bin/env python3
"""A costura passa atrás do ALTO da cabeça? Um aviso, não um gate.

**Este helper só avisa: não reprova, não decide e não altera a posição.** Quem
define a costura é a regra do topo do cabelo, medido pela máscara:
`focusY = topo + 0,13 × (queixo − topo)` (`rule_focus`). A fração abaixo parte da
caixa do detector de rosto, que começa na testa e ignora o cabelo, e por isso não
define nada: serve para chamar atenção a uma faixa reta ou a um número estranho.

Regra dele, repetida em 16/08 e de novo em 11/09: *"a divisão fica atrás da
parte superior da minha cabeça como se eu estivesse na frente"*. Ter `matte` na
janela não basta. Se o `focusY` não subir a pessoa o bastante, o cabelo para
ABAIXO da faixa, o recorte não aparece em lugar nenhum e o quadro fica idêntico
a uma faixa reta — **falha silenciosa**: o render conclui, o `check_inserts.py`
aprova, e só olhando é que se vê que o efeito não aconteceu. O padrão do
template (`focusY` 400 no layout `top`) cai justamente nesse caso.

O que este helper faz é a conta que ninguém deveria fazer de cabeça: onde o
topo da cabeça CAI na tela, dado o par zoom/focusY, e onde isso fica em relação
à costura. Ele não julga estética: aponta se o efeito parece não existir.

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
import json
from pathlib import Path
import subprocess
import sys
import tempfile

SEAM_BLEND = 100          # espelha CustomGraphics.tsx
FRAME_H = 1920
LAYOUT_W = 1080           # largura padrão da grade do edit-data (focusY, bandH)
# Ancorados na calibragem real do canal (focusY 560 / 640 / 720 num mesmo
# still): 560 deu fração 0.16 e foi descrito como "encosta"; 640 deu 0.28,
# "entra"; 720 deu 0.40 e foi o que "lê como a referência". Daí a janela.
UPPER_MIN = 0.20          # abaixo disto a costura raspa o topo, mal cruza
UPPER_MAX = 0.50          # acima disto ela desce no rosto
REFERENCE = 0.40          # o que ele aprovou


# O Formato 2 (medido do vídeo de referência, 2026-09-11) não usa matte: a
# dissolução é LARGA (~192px contra 100) e o topo da cabeça cai DENTRO dela.
# É a largura da dissolução que faz a pessoa "estar na frente", porque a arte
# termina de sumir exatamente onde a cabeça começa. Por isso há dois critérios,
# e não um: com dissolução estreita importa onde a linha cruza a cabeça; com
# dissolução larga importa se o topo da cabeça cai dentro da faixa que dissolve.
BLEND_MIN, BLEND_MAX = 0.15, 0.85   # do referência: topo da cabeça em 0,24–0,74

# A regra dele (2026-09-23): a costura cruza o terço superior da cabeça real,
# pegando só parte do cabelo. A costura cai em source-y = focusY, com qualquer
# zoom ou bandH.
RULE_FRACTION = 0.13
ALPHA_LEVEL = 128         # alfa a partir do qual o pixel é pessoa
HAIR_MIN_WIDTH = 0.005    # fração da largura: fio solto não é o topo do cabelo


def seam_position(head_top: float, head_bottom: float, focus_y: float,
                  zoom: float, band_h: float, layout: str = 'top',
                  seam_blend: float = SEAM_BLEND) -> dict:
    """Onde a costura cai na cabeça, em fração da altura dela (0 = topo)."""
    if head_bottom <= head_top:
        raise ValueError('Caixa da cabeça inválida')
    if zoom <= 0:
        raise ValueError('Zoom inválido')
    if layout != 'top':
        raise ValueError("Só layout 'top' — a geometria do 'bottom' não foi medida")
    # + band_h: o termo do template. Sem ele a conclusão se inverte.
    if seam_blend <= 0:
        raise ValueError('Dissolução inválida')
    top_r = (head_top - focus_y) * zoom + band_h
    bottom_r = (head_bottom - focus_y) * zoom + band_h
    seam = band_h
    frac = (seam - top_r) / (bottom_r - top_r)
    # onde o TOPO da cabeça cai dentro da faixa que dissolve (0 = borda sólida,
    # 1 = fim da dissolução). Só é o critério quando a dissolução é larga.
    blend_frac = (top_r - band_h) / seam_blend
    wide = seam_blend > SEAM_BLEND * 1.4
    if wide:
        if blend_frac < BLEND_MIN:
            verdict, why = 'ALTA DEMAIS', 'a cabeça entra antes da dissolução começar a sumir'
        elif blend_frac > BLEND_MAX:
            verdict, why = 'FAIXA RETA', 'a cabeça começa depois da dissolução — a arte não a atravessa'
        else:
            verdict, why = 'OK', 'o topo da cabeça cai dentro da dissolução'
        return {'verdict': verdict, 'why': why, 'fraction': round(frac, 3),
                'blendFraction': round(blend_frac, 3), 'criterion': 'dissolução larga',
                'headTopRendered': round(top_r, 1), 'seamY': round(seam, 1)}
    if frac < 0:
        verdict, why = 'FAIXA RETA', 'a cabeça fica toda abaixo da costura — o recorte não aparece'
    elif frac < UPPER_MIN:
        verdict, why = 'RASPANDO', 'a costura mal encosta no topo da cabeça'
    elif frac <= UPPER_MAX:
        verdict, why = 'OK', f'a costura cruza o alto da cabeça (referência aprovada: {REFERENCE})'
    else:
        verdict, why = 'BAIXA DEMAIS', 'a costura atravessa o rosto, não o alto da cabeça'
    return {'verdict': verdict, 'why': why, 'fraction': round(frac, 3),
            'blendFraction': round(blend_frac, 3), 'criterion': 'costura estreita',
            'headTopRendered': round(top_r, 1), 'seamY': round(seam, 1)}


def layout_width(edit_dir: Path) -> float:
    """`width` do edit-data do projeto; sem ele, a grade padrão."""
    try:
        data = json.loads((Path(edit_dir) / 'remotion/public/edit-data.json').read_text())
        return float(data.get('width') or LAYOUT_W)
    except (OSError, ValueError, TypeError, AttributeError):
        return float(LAYOUT_W)


def head_box(video: Path, at: float, layout_w: float = LAYOUT_W) -> tuple[float, float]:
    """(topo, base) da cabeça na FONTE, do quadro em `at`, na grade do layout.

    focusY e bandH vivem na grade do edit-data; o detector mede pixel do quadro.
    Num corte 4K a medida viria com o dobro do valor e o veredito sairia errado
    sem aviso nenhum, por isso a conversão pela largura.
    """
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
    escala = layout_w / img.shape[1]
    return float(y) * escala, float(y + h) * escala


def hair_top(matte: Path, layout_w: float = LAYOUT_W) -> float:
    """Topo do cabelo pelo alfa do PRIMEIRO quadro da máscara, na grade do layout.

    O quadro 0 de cada matte é o início da janela (`person_matte.py`).
    """
    matte = Path(matte)
    info = json.loads(subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
         '-of', 'json', str(matte)], capture_output=True, text=True, check=True).stdout)['streams'][0]
    w, h = int(info['width']), int(info['height'])
    # O decodificador nativo do VP9 descarta o alfa; precisa do libvpx.
    entrada = ['-c:v', 'libvpx-vp9'] if matte.suffix.lower() == '.webm' else []
    raw = subprocess.run(['ffmpeg', '-v', 'error', *entrada, '-i', str(matte), '-frames:v', '1',
                          '-vf', 'format=rgba,alphaextract,format=gray', '-f', 'rawvideo', '-'],
                         capture_output=True, check=True).stdout
    if len(raw) < w * h:
        raise ValueError(f'Não consegui ler o alfa de {matte.name}')
    minimo = max(1, int(w * HAIR_MIN_WIDTH))
    for y in range(h):
        if sum(v >= ALPHA_LEVEL for v in raw[y * w:(y + 1) * w]) >= minimo:
            return y * layout_w / w
    raise ValueError(f'A máscara {matte.name} não tem pessoa no primeiro quadro')


def focus_from_rule(top: float, chin: float) -> float:
    if chin <= top:
        raise ValueError('Topo do cabelo abaixo do queixo')
    return top + RULE_FRACTION * (chin - top)


def rule_focus(video: Path, at: float, matte: Path, layout_w: float = LAYOUT_W) -> dict:
    """O `focusY` da regra: topo pela máscara, queixo pela base da caixa do rosto."""
    top = hair_top(matte, layout_w)
    _, chin = head_box(video, at, layout_w)
    return {'focusY': round(focus_from_rule(top, chin)), 'hairTop': round(top, 1), 'chin': round(chin, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description='Aviso: a costura parece cruzar o alto da cabeça?')
    ap.add_argument('video', type=Path)
    ap.add_argument('--at', type=float, required=True, help='instante do início da janela')
    ap.add_argument('--band-h', type=float, required=True)
    ap.add_argument('--focus-y', type=float, required=True)
    ap.add_argument('--zoom', type=float, required=True)
    ap.add_argument('--layout', choices=['top', 'bottom'], default='top')
    ap.add_argument('--seam-blend', type=float, default=SEAM_BLEND,
                    help='192 no Formato 2; 100 (padrão) no Formato 1')
    ap.add_argument('--layout-width', type=float, default=LAYOUT_W,
                    help='`width` do edit-data: a medida do quadro é convertida para essa grade')
    ap.add_argument('--matte', type=Path, help='máscara da janela: mostra o focusY da regra do cabelo')
    args = ap.parse_args()

    try:
        top, bottom = head_box(args.video, args.at, args.layout_width)
        r = seam_position(top, bottom, args.focus_y, args.zoom, args.band_h,
                          args.layout, args.seam_blend)
    except (OSError, ValueError, ImportError, subprocess.CalledProcessError) as e:
        print(f'✗ {e}')
        sys.exit(2)

    prefixo = 'ok' if r['verdict'] == 'OK' else f"AVISO {r['verdict']}"
    print(f"{prefixo} ({r['criterion']}): {r['why']}")
    print(f"  cabeça na fonte {top:.0f}–{bottom:.0f} · topo renderiza em {r['headTopRendered']:.0f} · "
          f"costura em {r['seamY']:.0f} · fração {r['fraction']}")
    if args.matte:
        try:
            regra = rule_focus(args.video, args.at, args.matte, args.layout_width)
            print(f"  regra do cabelo: focusY {regra['focusY']} (topo {regra['hairTop']:.0f}, "
                  f"queixo {regra['chin']:.0f}); nesta janela está {args.focus_y:.0f}")
        except (OSError, ValueError, ImportError, subprocess.CalledProcessError) as e:
            print(f'  regra do cabelo: sem medida ({e})')
    else:
        print('  a posição vem da regra do topo do cabelo: passe --matte para calculá-la')
    sys.exit(0)


if __name__ == '__main__':
    main()
