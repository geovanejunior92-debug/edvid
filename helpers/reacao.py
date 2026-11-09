"""Formato 3: vídeo de reação em tela dividida. Ver references/formato-3-reacao.md.

Recebe um job JSON com o conteúdo (muitas vezes já dentro de outra montagem) e monta:
entrada -> conteúdo em cima com a pessoa ouvindo embaixo -> saída em tela cheia.

A capa original é extraída da abertura pelo que fica parado entre os quadros e volta
na mesma posição do quadro. A legenda gravada no original cairia na dissolução, por
isso o conteúdo é recortado acima dela e ganha legenda nova, acima da dissolução.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 2160, 3840
FPS = 30
FADE_INI, FADE_FIM = 1748, 2132   # dissolução larga: 874 a 1066 em 1080x1920
TOPO_CABECA = 2000
XFADE = 0.2
VELOCIDADE = 1.07
RAIZ = Path(__file__).resolve().parent.parent
FONTE = RAIZ / "assets/fonts/Poppins-ExtraBold.ttf"
WHOOSH = RAIZ / "assets/shortform/public/sfx/whoosh.mp3"
LEG_Y, LEG_H = 1180, 560          # faixa da legenda nova, acima da dissolução
FONTE_ID = RAIZ / "assets/fonts/Poppins-Light.ttf"
ID_NOME, ID_REG = "Dr. Geovane Júnior", "CRM - PE 28037"
ID_Y = 3190                       # acima da área que o Instagram cobre com a legenda do post


def duracao(p: str) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]))


def lufs(p: str, ini: float, dur: float) -> float:
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-ss", str(ini), "-t", str(dur), "-i", p,
                        "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    l = [x for x in r.splitlines() if x.strip().startswith("I:")]
    return float(l[-1].split()[1]) if l else -18.0


def quadros(p: str, ini: float, fim: float, fps: int, w: int, h: int, fmt: str = "gray") -> np.ndarray:
    c = 1 if fmt == "gray" else 3
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(ini), "-to", str(fim), "-i", p,
                          "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", fmt, "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8)
    return a.reshape(-1, h, w) if c == 1 else a.reshape(-1, h, w, 3)


def segmentos_ouvindo(arq: str, ini: float, fim: float, precisa: float):
    if fim - ini >= precisa:
        return [(ini, ini + precisa)], None
    g = quadros(arq, ini, fim, 10, 64, 114).astype(np.float32)
    n, melhores = len(g), []
    for j in range(max(0, n - 80), n):
        for i in range(0, min(n, 140)):
            if j - i >= 120:
                melhores.append((float(np.abs(g[i] - g[j]).mean()), i / 10, j / 10))
    dif, a, b = min(melhores)
    a, b = ini + a, ini + b
    segs, total = [(ini, b)], b - ini
    while total < precisa:
        ate = min(b, a + precisa - total + XFADE)
        segs.append((a, ate))
        total += (ate - a) - XFADE
    return segs, round(dif, 2)


def trechos_mantidos(ini: float, fim: float, cortes) -> list[tuple[float, float]]:
    fica, pos = [], ini
    for a, b in sorted(tuple(c) for c in cortes):
        if a >= b:
            raise SystemExit(f"Corte inválido: {a}-{b}")
        if a > pos:
            fica.append((pos, min(a, fim)))
        pos = max(pos, b)
    if pos < fim:
        fica.append((pos, fim))
    fica = [(a, b) for a, b in fica if b - a > 0.05]
    if not fica:
        raise SystemExit("Os cortes removeram o conteúdo inteiro.")
    return fica


def conteudo_limpo(arq: str, fica, destino: str) -> None:
    f, rot = [], ""
    for i, (a, b) in enumerate(fica):
        f.append(f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}]")
        f.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.02,"
                 f"afade=t=out:st={max(0.0, b - a - 0.02):.3f}:d=0.02[a{i}]")
        rot += f"[v{i}][a{i}]"
    f.append(f"{rot}concat=n={len(fica)}:v=1:a=1[v][a]")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", arq, "-filter_complex", ";".join(f),
                    "-map", "[v]", "-map", "[a]", "-c:v", "hevc_videotoolbox", "-q:v", "82",
                    "-c:a", "aac", "-b:a", "256k", destino], check=True)


def mascara(destino: str, ini: int = FADE_INI, fim: int = FADE_FIM) -> None:
    y = np.arange(FADE_FIM, dtype=np.float32)
    t = np.clip((y - ini) / (fim - ini), 0, 1)
    a = 1 - t * t * (3 - 2 * t)
    Image.fromarray(np.tile((a * 255).astype(np.uint8)[:, None], (1, W))).convert("L").save(destino)


def mascara_area(fr: np.ndarray, area: dict):
    """Isola texto parado na área indicada, em pixels de 720x1280.

    {"box": [y0, y1, x0, x1], "amarelo": false}: blocos brancos e ícone verde.
    {"rect": [y0, y1, x0, x1]}: copia a área inteira, para cartão de fundo sólido.
    """
    med = np.median(fr, axis=0).astype(np.uint8)
    m = np.zeros(med.shape[:2], np.uint8)
    if "rect" in area:
        y0, y1, x0, x1 = area["rect"]
        m[y0:y1, x0:x1] = 1
        return med, m
    y0, y1, x0, x1 = area["box"]
    std = fr.astype(np.float32).std(axis=0).max(axis=2)
    cinza = cv2.cvtColor(med, cv2.COLOR_RGB2GRAY)
    h, sat, val = [c for c in np.moveaxis(cv2.cvtColor(med, cv2.COLOR_RGB2HSV), 2, 0)]
    janela = np.zeros(m.shape, bool)
    janela[y0:y1, x0:x1] = True
    br = ((std < 10) & (cinza > 205) & janela).astype(np.uint8)
    br = cv2.morphologyEx(br, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    br = cv2.morphologyEx(br, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (41, 15)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(br, connectivity=8)
    if n > 1:
        maior = st[1:, cv2.CC_STAT_AREA].max()
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] >= maior * 0.15:
                m[lab == i] = 1
    cor = (h >= 55) & (h <= 90) & (sat > 110) & (val > 130)
    if area.get("amarelo"):
        cor |= (h >= 18) & (h <= 34) & (sat > 170) & (val > 200)
    if area.get("vermelho"):
        cor |= ((h < 8) | (h > 172)) & (sat > 150) & (val > 150)
    cor = ((std < 8) & cor & janela).astype(np.uint8)
    cor = cv2.morphologyEx(cor, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(cor, connectivity=8)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 250:
            m[lab == i] = 1
    return med, m


def salvar_camada(med: np.ndarray, m: np.ndarray, destino: str) -> None:
    a = cv2.GaussianBlur(m.astype(np.float32), (0, 0), 0.7)
    Image.fromarray(np.dstack([med, (a * 255).astype(np.uint8)]), "RGBA").resize((W, H), Image.LANCZOS).save(destino)


def extrair_capa(arq: str, intro_fim: float, destino: str, capa: dict):
    """Salva a capa e devolve a base dela em 4K."""
    fr = quadros(arq, 0.35, max(0.6, intro_fim - 0.05), 15, 720, 1280, "rgb24")
    med, m = mascara_area(fr, capa)
    salvar_camada(med, m, destino)
    base = int(np.where(m.any(axis=1))[0].max() * 3)
    return base


def segundo_cartao(arq: str, ini: float, area: dict, destino: str) -> float:
    """Cartão que o conteúdo mostra logo depois da abertura. Devolve quanto tempo ele fica."""
    primeiro = quadros(arq, ini, ini + 1.5, 10, 720, 1280, "rgb24")
    med, m = mascara_area(primeiro, area)
    salvar_camada(med, m, destino)
    cinza = cv2.cvtColor(med, cv2.COLOR_RGB2GRAY)
    sel = m.astype(bool) & ((cinza > 190) | (cinza < 50))
    dep = quadros(arq, ini, ini + 20, 10, 720, 1280, "rgb24")
    dif = np.abs(dep.astype(np.float32)[:, sel] - med[sel].astype(np.float32)).mean(axis=(1, 2))
    fora = dif > 35
    for i in range(len(fora) - 2):
        if fora[i:i + 3].all():
            return i / 10
    return len(fora) / 10


def grupos_de_legenda(palavras, troca, max_pal=5, max_car=30):
    """[(ini, fim, texto)], quebrando em pausa, pontuação ou tamanho."""
    corr = []
    i = 0
    tok = [(a, b, w.strip()) for a, b, w in palavras]
    while i < len(tok):
        ach = False
        for de, para in troca:
            d = de.split()
            if [t[2].strip(",.?!").lower() for t in tok[i:i + len(d)]] == [x.lower() for x in d]:
                fim_pont = re.search(r"[,.?!]+$", tok[i + len(d) - 1][2])
                corr.append((tok[i][0], tok[i + len(d) - 1][1], para + (fim_pont.group() if fim_pont else "")))
                i += len(d)
                ach = True
                break
        if not ach:
            corr.append(tok[i])
            i += 1
    corr = [c for c in corr if re.sub(r"[,.?!]", "", c[2]).strip()]
    out, atual = [], []
    for a, b, w in corr:
        if atual and (a - atual[-1][1] > 0.45 or len(atual) >= max_pal
                      or len(" ".join(x[2] for x in atual)) + len(w) > max_car):
            out.append(atual)
            atual = []
        atual.append((a, b, w))
        if re.search(r"[.?!]$", w):
            out.append(atual)
            atual = []
    if atual:
        out.append(atual)
    return [(g[0][0], g[-1][1], " ".join(x[2] for x in g).strip()) for g in out]


def legenda_png(texto: str, destino: str) -> None:
    fonte = ImageFont.truetype(str(FONTE), 100)
    im = Image.new("RGBA", (W, LEG_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    linhas, atual = [], ""
    for p in texto.split():
        t = f"{atual} {p}".strip()
        if d.textlength(t, font=fonte) > 1800 and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = t
    linhas.append(atual)
    y = LEG_H - 40 - 128 * len(linhas)
    for l in linhas:
        d.text((W / 2, y + 62), l, font=fonte, fill="white", anchor="mm", stroke_width=9, stroke_fill=(0, 0, 0))
        y += 128
    im.save(destino)


def camada_legenda(grupos, total: float, tmp: str) -> str:
    vazio = f"{tmp}/vazio.png"
    Image.new("RGBA", (W, LEG_H), (0, 0, 0, 0)).save(vazio)
    linhas, pos = [], 0.0
    for i, (a, b, t) in enumerate(grupos):
        a, b = max(a, pos), min(b + 0.08, total)
        if b <= a:
            continue
        if a > pos:
            linhas += [f"file '{vazio}'", f"duration {a - pos:.3f}"]
        png = f"{tmp}/l{i:04d}.png"
        legenda_png(t, png)
        linhas += [f"file '{png}'", f"duration {b - a:.3f}"]
        pos = b
    if pos < total:
        linhas += [f"file '{vazio}'", f"duration {total - pos:.3f}"]
    linhas.append(f"file '{vazio}'")
    lista = f"{tmp}/legendas.txt"
    Path(lista).write_text("\n".join(linhas))
    return lista


def identificacao(destino: str) -> None:
    """Nome e registro, discretos, só nos trechos em que o médico fala."""
    im = Image.new("RGBA", (W, 240), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y, txt, tam in ((70, ID_NOME, 66), (156, ID_REG, 50)):
        f = ImageFont.truetype(str(FONTE_ID), tam)
        d.text((W / 2, y), txt, font=f, fill=(255, 255, 255, 235), anchor="mm",
               stroke_width=3, stroke_fill=(0, 0, 0, 110))
    im.save(destino)


def montar(job: dict, biblioteca: str, saida: str) -> dict:
    lib = json.load(open(os.path.expanduser(biblioteca)))["clipes"]
    ent, sai = lib[f"entrada {job['entrada']}"], lib[f"saida {job['saida']}"]
    if ent["roupa"] != sai["roupa"]:
        raise SystemExit(f"Roupas diferentes: entrada {job['entrada']} e saída {job['saida']}.")
    tmp = tempfile.mkdtemp(prefix="reacao-")
    arq, ini, fim = job["conteudo"], job["ini"], job["fim"]
    fica = trechos_mantidos(ini, fim, job.get("cortes", []))
    limpo = f"{tmp}/conteudo.mov"
    conteudo_limpo(arq, fica, limpo)
    L = duracao(limpo)

    pal, base = [], 0.0
    for a, b in fica:
        pal += [(x - a + base, y - a + base, w) for x, y, w in job["palavras"] if a - 0.05 <= x and x < b]
        base += b - a
    grupos = [] if job.get("sem_legenda") else grupos_de_legenda(pal, job.get("troca", []))
    grupos_todos = grupos

    t0 = max(0.0, ent["fala"][0] - 0.12)
    d_a = ent["fala"][1] + 0.25 - t0
    segs, dif = segmentos_ouvindo(ent["arquivo"], t0 + d_a, ent["duracao"] - 0.5, L)
    s0 = max(0.0, sai["fala"][0] - 0.12)
    d_c = sai["usar_ate"] - s0
    x = d_a + L

    alvo = min(-10.0, max(-14.0, lufs(limpo, 0, L)))
    g_c = alvo - lufs(limpo, 0, L)
    g_e = alvo - lufs(ent["arquivo"], t0, d_a)
    g_s = alvo - lufs(sai["arquivo"], s0, sai["fala"][1] + 0.1 - s0)

    masc, capa = f"{tmp}/mascara.png", f"{tmp}/capa.png"
    # moldura: conteúdo em que a pessoa anda pela largura toda não pode levar zoom.
    # Mostra a largura inteira e termina a dissolução antes de vazar o outro reator.
    mold = job.get("moldura") or {}
    mascara(masc, mold.get("fade_ini", FADE_INI), mold.get("fade_fim", FADE_FIM))
    leg_y = mold.get("leg_y", LEG_Y)
    base_capa = extrair_capa(arq, job["intro_fim"], capa, job["capa"])
    # cartão gravado no começo do conteúdo: escala 1 e nada de legenda nova enquanto ele estiver lá
    cartao2 = None
    T = job.get("cartao_ate", 0.0)
    if job.get("cartao2"):
        cartao2 = f"{tmp}/cartao2.png"
        T = segundo_cartao(arq, ini, job["cartao2"], cartao2) + 0.03
    T = min(max(2 / FPS, T), L - 1)
    capa_ate = d_a + T if job.get("capa_continua") else d_a
    faixa = None
    if job.get("faixa"):
        amostra = quadros(arq, ini, fim, 1, 720, 1280, "rgb24")
        fm, fk = mascara_area(amostra, job["faixa"])
        faixa = f"{tmp}/faixa.png"
        salvar_camada(fm, fk, faixa)
    grupos = [(max(a - T, 0.0), b - T, t) for a, b, t in grupos_todos if b - T > 0.2]
    lista = camada_legenda(grupos, L - T, tmp)
    ident = f"{tmp}/id.png"
    identificacao(ident)

    inp = ["-ss", f"{t0:.3f}", "-t", f"{segs[0][1] - t0:.3f}", "-i", ent["arquivo"]]
    for de, ate in segs[1:]:
        inp += ["-ss", f"{de:.3f}", "-t", f"{ate - de:.3f}", "-i", ent["arquivo"]]
    n = len(segs)
    i_c, i_p, i_s, i_m, i_k, i_w, i_l, i_id = n, n + 1, n + 2, n + 3, n + 4, n + 5, n + 6, n + 7
    D = d_a + T
    inp += ["-i", limpo, "-t", f"{job['intro_fim']:.3f}", "-i", arq,
            "-ss", f"{s0:.3f}", "-t", f"{d_c:.3f}", "-i", sai["arquivo"],
            "-loop", "1", "-framerate", str(FPS), "-i", masc,
            "-loop", "1", "-framerate", str(FPS), "-i", capa,
            "-i", str(WHOOSH), "-f", "concat", "-safe", "0", "-i", lista,
            "-loop", "1", "-framerate", str(FPS), "-i", ident]
    if faixa:
        inp += ["-loop", "1", "-framerate", str(FPS), "-i", faixa]
    if cartao2:
        inp += ["-loop", "1", "-framerate", str(FPS), "-i", cartao2]

    f = []
    for i in range(n):
        f.append(f"[{i}:v]fps={FPS},setsar=1,format=yuv420p[b{i}]")
    ult, ofs = "b0", segs[0][1] - t0
    for i in range(1, n):
        f.append(f"[{ult}][b{i}]xfade=transition=fade:duration={XFADE}:offset={ofs - XFADE:.3f}[j{i}]")
        ult, ofs = f"j{i}", ofs - XFADE + (segs[i][1] - segs[i][0])
    d_int = mold.get("topo_cabeca", TOPO_CABECA) - ent["topo_cabelo"]
    # na abertura, a pessoa desce o que for preciso para a capa não cobrir os olhos
    d_ab = max(d_int, base_capa - 260 - ent["topo_cabelo"])
    f.append(f"[{ult}]split=2[ba][bm]")
    f.append(f"[ba]trim=0:{D:.3f},setpts=PTS-STARTPTS,crop={W}:{H - d_ab}:0:0,pad={W}:{H}:0:{d_ab}:black[f1]")
    f.append(f"[bm]trim={D:.3f}:{d_a + L:.3f},setpts=PTS-STARTPTS,crop={W}:{H - d_int}:0:0,pad={W}:{H}:0:{d_int}:black[f2]")
    # abertura em escala 1: a capa original continua alinhada com a imagem de baixo dela
    f.append(f"[{i_p}:v]crop=720:711:0:0,scale={W}:{FADE_FIM}:flags=lanczos,setsar=1,"
             f"setpts=PTS*{d_a / job['intro_fim']:.5f},fps={FPS},trim=duration={d_a:.3f},setpts=PTS-STARTPTS,format=yuv420p[t1i]")
    f.append(f"[{i_c}:v]split=2[cc1][cc2]")
    f.append(f"[cc1]trim=0:{T:.3f},setpts=PTS-STARTPTS,crop=720:711:0:0,scale={W}:{FADE_FIM}:flags=lanczos,setsar=1,fps={FPS},format=yuv420p[t1c]")
    f.append("[t1i][t1c]concat=n=2:v=1:a=0,format=yuva420p[t1a]")
    f.append(f"[{i_m}:v]format=gray,split=2[mm1][mm2]")
    f.append(f"[mm1]trim=duration={D:.3f},setpts=PTS-STARTPTS[m1]")
    f.append("[t1a][m1]alphamerge[t1]")
    f.append(f"[f1][t1]overlay=0:0:shortest=1[c1]")
    f.append(f"[{i_k}:v]format=rgba,trim=duration={capa_ate:.3f},setpts=PTS-STARTPTS[kk]")
    f.append(f"[{i_id}:v]format=rgba,split=2[id1a][id2a]")
    f.append(f"[id1a]trim=duration={d_a:.3f},setpts=PTS-STARTPTS,fade=t=in:d=0.15:alpha=1,fade=t=out:st={d_a - 0.15:.3f}:d=0.15:alpha=1[id1]")
    f.append(f"[c1][kk]overlay=0:0:eof_action=pass[c1k0]")
    if cartao2:
        i_c2 = i_id + (2 if faixa else 1)
        f.append(f"[{i_c2}:v]format=rgba,trim=duration={max(0.1, T - 0.3):.3f},setpts=PTS-STARTPTS+{d_a:.3f}/TB[c2k]")
        f.append("[c1k0][c2k]overlay=0:0:eof_action=pass[c1k]")
    else:
        f.append("[c1k0]null[c1k]")
    f.append(f"[c1k][id1]overlay=0:{ID_Y}:eof_action=pass,format=yuv420p[p1]")
    # meio: recorte acima da legenda antiga e do que vaza do outro reator
    # sem zoom (pedido de 2026-11-09): largura inteira, só desce o recorte com moldura.y
    recorte = f"crop=720:711:0:{mold.get('y', 0)}"
    f.append(f"[cc2]trim={T:.3f}:{L:.3f},setpts=PTS-STARTPTS,{recorte},"
             f"scale={W}:{FADE_FIM}:flags=lanczos,setsar=1,fps={FPS},format=yuva420p[t2a]")
    f.append(f"[mm2]trim=duration={L - T:.3f},setpts=PTS-STARTPTS[m2]")
    f.append("[t2a][m2]alphamerge[t2]")
    f.append("[f2][t2]overlay=0:0:shortest=1[c2]")
    f.append(f"[{i_l}:v]fps={FPS},format=rgba,trim=duration={L - T:.3f},setpts=PTS-STARTPTS[ll]")
    if faixa:
        f.append(f"[c2][ll]overlay=0:{leg_y}:shortest=1[c2l]")
        f.append(f"[{i_id + 1}:v]format=rgba,trim=duration={L - T:.3f},setpts=PTS-STARTPTS[fx]")
        f.append("[c2l][fx]overlay=0:0:shortest=1,format=yuv420p[p2]")
    else:
        f.append(f"[c2][ll]overlay=0:{leg_y}:shortest=1,format=yuv420p[p2]")
    f.append(f"[id2a]trim=duration={d_c:.3f},setpts=PTS-STARTPTS,fade=t=in:st=0.1:d=0.15:alpha=1,fade=t=out:st={d_c - 0.15:.3f}:d=0.15:alpha=1[id2]")
    f.append(f"[{i_s}:v]fps={FPS},setsar=1,trim=duration={d_c:.3f},setpts=PTS-STARTPTS[sv0]")
    f.append(f"[sv0][id2]overlay=0:{ID_Y}:shortest=1,format=yuv420p[sv]")
    f.append("[p1][p2][sv]concat=n=3:v=1:a=0[todo]")
    sobe, desce = 2 / FPS, 3 / FPS
    f.append(f"color=white:s={W}x{H}:r={FPS}:d={sobe + desce:.4f},format=yuva420p,"
             f"fade=t=in:st=0:d={sobe:.4f}:alpha=1,fade=t=out:st={sobe:.4f}:d={desce:.4f}:alpha=1,"
             f"colorchannelmixer=aa=0.62,setpts=PTS+{x - sobe:.4f}/TB[fl]")
    f.append(f"[todo][fl]overlay=0:0:eof_action=pass,format=yuv420p,setpts=PTS/{VELOCIDADE}[v]")
    st = "aresample=48000,aformat=channel_layouts=stereo"
    f.append(f"[0:a]atrim=duration={d_a:.3f},asetpts=PTS-STARTPTS,volume={g_e:.2f}dB,afade=t=out:st={d_a - 0.05:.3f}:d=0.05,{st}[a1]")
    f.append(f"[{i_c}:a]volume={g_c:.2f}dB,afade=t=in:d=0.03,afade=t=out:st={L - 0.05:.3f}:d=0.05,{st}[a2]")
    f.append(f"[{i_s}:a]volume={g_s:.2f}dB,afade=t=out:st={d_c - 0.12:.3f}:d=0.12,{st}[a3]")
    f.append("[a1][a2][a3]concat=n=3:v=0:a=1[voz]")
    f.append(f"[{i_w}:a]volume=0.5,adelay={int((x - 1 / FPS) * 1000)}:all=1,{st}[wh]")
    f.append(f"[voz][wh]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=false,atempo={VELOCIDADE}[a]")

    Path(saida).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *inp, "-filter_complex", ";".join(f),
                    "-map", "[v]", "-map", "[a]", "-c:v", "hevc_videotoolbox", "-q:v", "68", "-tag:v", "hvc1",
                    "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", saida], check=True)
    return {"saida": saida, "conteudo_s": round(L, 2), "total_s": round(duracao(saida), 2), "laco": segs, "dif_emenda": dif,
            "fim_abertura": round(d_a / VELOCIDADE, 2), "clarao": round(x / VELOCIDADE, 2), "base_capa": base_capa, "capa_ate": round(D / VELOCIDADE, 2),
            "legendas": len(grupos), "ganhos_db": [round(g_e, 1), round(g_c, 1), round(g_s, 1)]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--biblioteca", default="~/Videos/reacoes/biblioteca.json")
    a = ap.parse_args()
    print(json.dumps(montar(json.load(open(a.job)), a.biblioteca, a.out), ensure_ascii=False, indent=1))
