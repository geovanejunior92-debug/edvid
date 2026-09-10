"""Recria como .cube os filtros mostrados numa referência, MEDINDO o vídeo.

Os filtros são do CapCut e não existem como arquivo. O que existe é o efeito
deles na imagem — e o vídeo mostra a mesma pessoa, na mesma sala, na mesma luz,
com um filtro por trecho. Então a diferença entre um trecho e outro É o filtro.

Método: casamento de histograma por canal contra um trecho de referência (o
filtro mais neutro do vídeo), somado a um ajuste de saturação medido. Isso
captura curva de tom e viés de cor, que é o que esses filtros fazem. Não captura
efeito espacial — o "Bokeh" desfoca o fundo, e desfoque não cabe num LUT; aqui
sobra a parte de cor dele, e isso precisa ser dito a quem escolhe.
"""
import subprocess, numpy as np
from pathlib import Path

V = "/Users/geovanejunior/Downloads/majusoarees_DcG2503R4fn.mp4"
DEST = Path("/Users/geovanejunior/.claude/skills/edvid/assets/preview/luts")
W, H = 320, 568
N = 33  # tamanho do cubo, igual ao resto do acervo

TRECHOS = [
    ("4K",                  1.2,  3.6),
    ("Qualidade II",        4.8,  8.6),
    ("Bokeh",               9.8, 13.6),
    ("Laranja Azul",       15.0, 19.0),
    ("Baile de Formatura", 20.2, 23.2),
    ("Ensolarado",         24.2, 27.6),
    ("Café Escuro",        28.6, 32.2),
]
BASE = "4K"          # referência: o mais neutro do vídeo


def frames(t0, t1, passo=0.25):
    fs = []
    t = t0
    while t < t1:
        raw = subprocess.run(
            ["ffmpeg", "-v", "quiet", "-ss", f"{t:.2f}", "-i", V, "-frames:v", "1",
             "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True).stdout
        if len(raw) == W * H * 3:
            fs.append(np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3))
        t += passo
    return np.concatenate([f.reshape(-1, 3) for f in fs], axis=0) if fs else None


def cdf(px_ch):
    h = np.bincount(px_ch, minlength=256).astype(np.float64)
    c = np.cumsum(h)
    return c / c[-1]


def curva(origem, destino):
    """Mapa 0..255 que leva a distribuição de `origem` na de `destino`."""
    co, cd = cdf(origem), cdf(destino)
    return np.interp(co, cd, np.arange(256)).astype(np.float64)


print("medindo os trechos…")
dados = {}
for nome, a, b in TRECHOS:
    px = frames(a, b)
    dados[nome] = px
    print(f"  {nome:20} {len(px):>8} pixels  RGB médio "
          f"({px[:,0].mean():.0f},{px[:,1].mean():.0f},{px[:,2].mean():.0f})")

base = dados[BASE]


def sat_de(px):
    mx, mn = px.max(axis=1).astype(np.float64), px.min(axis=1).astype(np.float64)
    return float(np.mean((mx - mn) / (mx + 1e-6)))


sat_base = sat_de(base)
DEST.mkdir(parents=True, exist_ok=True)
feitos = []

for nome, a, b in TRECHOS:
    if nome == BASE:
        # o próprio baseline: curva suave de contraste, para ele não ser um LUT nulo
        x = np.linspace(0, 1, 256)
        s = np.clip((x - 0.5) * 1.10 + 0.5, 0, 1) ** 0.98
        curvas = [s * 255, s * 255, s * 255]
        ganho_sat = 1.06
    else:
        px = dados[nome]
        curvas = [curva(base[:, c], px[:, c]) for c in range(3)]
        ganho_sat = float(np.clip(sat_de(px) / (sat_base + 1e-6), 0.55, 1.65))

    linhas = []
    grid = np.linspace(0, 1, N)
    for ib in range(N):
        for ig in range(N):
            for ir in range(N):
                rgb = np.array([grid[ir], grid[ig], grid[ib]]) * 255
                out = np.array([np.interp(rgb[c], np.arange(256), curvas[c]) for c in range(3)]) / 255
                luma = float(out @ np.array([0.2126, 0.7152, 0.0722]))
                out = np.clip(luma + (out - luma) * ganho_sat, 0, 1)
                linhas.append(f"{out[0]:.6f} {out[1]:.6f} {out[2]:.6f}")

    arq = DEST / f"{nome}.cube"
    arq.write_text(
        f"# Recriado de uma referência do usuário (2026-08-17) medindo o vídeo.\n"
        f"# Filtro original: \"{nome}\" (CapCut). Curva por canal + saturação {ganho_sat:.2f}x.\n"
        f'TITLE "{nome}"\nLUT_3D_SIZE {N}\nDOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n\n'
        + "\n".join(linhas) + "\n")
    feitos.append((nome, ganho_sat, arq.stat().st_size // 1024))
    print(f"  escrito {arq.name}  (saturação {ganho_sat:.2f}x, {arq.stat().st_size//1024} KB)")

print(f"\n{len(feitos)} LUTs novos em {DEST}")
