"""Formato 3: vídeo de reação em tela dividida.

Monta entrada (fala) -> conteúdo em cima com a pessoa ouvindo embaixo -> saída em
tela cheia, com dissolução larga no centro e clarão "saida" com whoosh baixo na
troca para a tela cheia. Se o conteúdo for maior que o trecho em que a pessoa
ouve, esse trecho entra em laço, sem repetir a fala.

A biblioteca é um JSON com as entradas e saídas já medidas (fala, roupa, topo do
cabelo). O caminho padrão é ~/Videos/reacoes/biblioteca.json.

Uso:
    reacao.py --conteudo video.mp4 --entrada 1 --saida 1 --cartao "Texto" -o out.mp4
    reacao.py --conteudo montagem.mp4 --crop 720:738:0:0 --ini 3.2 --fim 60.4 ...
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 2160, 3840           # saída em 4K vertical, a resolução das entradas e saídas
FPS = 30
FADE_INI, FADE_FIM = 1748, 2132   # dissolução larga: 874 a 1066 em 1080x1920
TOPO_CABECA = 2000          # o topo do cabelo fica dentro da dissolução
XFADE = 0.2                 # fusão só no painel de baixo, na volta do laço
VELOCIDADE = 1.07
FONTE = Path(__file__).resolve().parent.parent / "assets/fonts/Poppins-ExtraBold.ttf"
WHOOSH = Path(__file__).resolve().parent.parent / "assets/shortform/public/sfx/whoosh.mp3"


def duracao(p: str) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]))


def tem_audio(p: str) -> bool:
    return bool(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", p]).strip())


def lufs(p: str, ini: float, dur: float) -> float:
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-ss", str(ini), "-t", str(dur), "-i", p,
         "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    linhas = [l for l in r.splitlines() if l.strip().startswith("I:")]
    return float(linhas[-1].split()[1]) if linhas else -18.0


def quadros(p: str, ini: float, fim: float, fps: int = 10) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(ini), "-to", str(fim), "-i", p,
         "-vf", f"fps={fps},scale=64:114", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, 114, 64).astype(np.float32)


def segmentos_ouvindo(arq: str, ini: float, fim: float, precisa: float):
    """Devolve [(de, ate), ...] e a diferença na emenda, cobrindo `precisa` segundos."""
    if fim - ini >= precisa:
        return [(ini, ini + precisa)], None
    g = quadros(arq, ini, fim)
    fps = 10
    n = len(g)
    # volta para o início do trecho e sai perto do fim, no par de quadros mais parecido
    melhores = []
    for j in range(max(0, n - 8 * fps), n):
        for i in range(0, min(n, 14 * fps)):
            if j - i >= 12 * fps:
                melhores.append((float(np.abs(g[i] - g[j]).mean()), i / fps, j / fps))
    dif, a, b = min(melhores)
    a, b = ini + a, ini + b
    segs, total = [(ini, b)], b - ini
    while total < precisa:
        falta = precisa - total + XFADE
        ate = min(b, a + falta)
        segs.append((a, ate))
        total += (ate - a) - XFADE
    return segs, round(dif, 2)


def mascara(destino: str) -> None:
    y = np.arange(FADE_FIM, dtype=np.float32)
    t = np.clip((y - FADE_INI) / (FADE_FIM - FADE_INI), 0, 1)
    a = 1 - t * t * (3 - 2 * t)           # curva suave, sem borda aparente
    Image.fromarray(np.tile((a * 255).astype(np.uint8)[:, None], (1, W))).convert("L").save(destino)


def cartao(texto: str, destino: str, cy: int = 1340) -> None:
    fonte = ImageFont.truetype(str(FONTE), 104)
    d0 = ImageDraw.Draw(Image.new("L", (1, 1)))
    linhas, atual = [], ""
    for p in f"“{texto.upper()}”".split():
        t = f"{atual} {p}".strip()
        if d0.textlength(t, font=fonte) > 1800 and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = t
    linhas.append(atual)
    alt = 158
    im = Image.new("RGBA", (W, FADE_FIM), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    y = cy - alt * len(linhas) // 2
    for l in linhas:
        w = d.textlength(l, font=fonte)
        x = (W - w) / 2
        d.rectangle((x - 36, y, x + w + 36, y + alt - 6), fill=(255, 255, 255, 255))
        d.text((W / 2, y + (alt - 6) / 2), l, font=fonte, fill=(0, 0, 0, 255), anchor="mm")
        y += alt
    im.save(destino)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conteudo", required=True)
    ap.add_argument("--entrada", type=int, required=True)
    ap.add_argument("--saida", type=int, required=True)
    ap.add_argument("--cartao", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--crop", help="w:h:x:y da pessoa original, quando o conteúdo vem dentro de outra montagem")
    ap.add_argument("--ini", type=float, default=0.0)
    ap.add_argument("--fim", type=float)
    ap.add_argument("--foco-y", type=float, default=0.0, help="0 = encosta no topo, 1 = na base, ao recortar o conteúdo")
    ap.add_argument("--biblioteca", default="~/Videos/reacoes/biblioteca.json")
    a = ap.parse_args()

    lib = json.load(open(os.path.expanduser(a.biblioteca)))["clipes"]
    ent, sai = lib[f"entrada {a.entrada}"], lib[f"saida {a.saida}"]
    if ent["roupa"] != sai["roupa"]:
        raise SystemExit(f"Roupas diferentes: entrada {a.entrada} é {ent['roupa']}, saída {a.saida} é {sai['roupa']}.")

    c_fim = a.fim if a.fim else duracao(a.conteudo)
    L = c_fim - a.ini
    t0 = max(0.0, ent["fala"][0] - 0.12)
    d_a = ent["fala"][1] + 0.25 - t0          # fim da entrada: a voz dela acabou
    ouv_ini = t0 + d_a
    segs, dif = segmentos_ouvindo(ent["arquivo"], ouv_ini, ent["duracao"] - 0.5, L)
    s0 = max(0.0, sai["fala"][0] - 0.12)
    d_c = sai["usar_ate"] - s0
    x = d_a + L                                # onde a saída entra

    alvo = min(-10.0, max(-14.0, lufs(a.conteudo, a.ini, L)))
    if not tem_audio(a.conteudo):
        raise SystemExit("Conteúdo sem áudio.")
    g_c = alvo - lufs(a.conteudo, a.ini, L)
    g_e = alvo - lufs(ent["arquivo"], t0, d_a)
    g_s = alvo - lufs(sai["arquivo"], s0, sai["fala"][1] + 0.1 - s0)

    tmp = tempfile.mkdtemp(prefix="reacao-")
    masc, card = f"{tmp}/mascara.png", f"{tmp}/cartao.png"
    mascara(masc)
    cartao(a.cartao, card)

    # entradas do ffmpeg: a primeira leva a fala e o primeiro trecho ouvindo
    inp = ["-ss", f"{t0:.3f}", "-t", f"{segs[0][1] - t0:.3f}", "-i", ent["arquivo"]]
    for de, ate in segs[1:]:
        inp += ["-ss", f"{de:.3f}", "-t", f"{ate - de:.3f}", "-i", ent["arquivo"]]
    n = len(segs)
    i_c = n
    inp += ["-ss", f"{a.ini:.3f}", "-t", f"{L:.3f}", "-i", a.conteudo]
    i_p = n + 1                                # prévia muda durante a fala da entrada
    previa = a.ini + min(L * 0.25, max(0.0, L - d_a - 0.1))
    inp += ["-ss", f"{previa:.3f}", "-t", f"{d_a:.3f}", "-i", a.conteudo]
    i_s = n + 2
    inp += ["-ss", f"{s0:.3f}", "-t", f"{d_c:.3f}", "-i", sai["arquivo"]]
    i_m, i_k, i_w = n + 3, n + 4, n + 5
    inp += ["-loop", "1", "-framerate", str(FPS), "-i", masc,
            "-loop", "1", "-framerate", str(FPS), "-i", card, "-i", str(WHOOSH)]

    f = []
    # painel de baixo: fala + ouvindo, com fusão curta só na volta do laço
    for i in range(n):
        f.append(f"[{i}:v]fps={FPS},setsar=1,format=yuv420p[b{i}]")
    ult, ofs = "b0", segs[0][1] - t0
    for i in range(1, n):
        f.append(f"[{ult}][b{i}]xfade=transition=fade:duration={XFADE}:offset={ofs - XFADE:.3f}[j{i}]")
        ult, ofs = f"j{i}", ofs - XFADE + (segs[i][1] - segs[i][0])
    desl = TOPO_CABECA - ent["topo_cabelo"]
    f.append(f"[{ult}]trim=duration={d_a + L:.3f},setpts=PTS-STARTPTS,crop={W}:{H - desl}:0:0,"
             f"pad={W}:{H}:0:{desl}:black[fundo]")
    # conteúdo: recorte opcional e preenchimento da metade de cima
    crop = f"crop={a.crop.replace(':', ':', 3)}," if a.crop else ""
    cob = (f"{crop}scale={W}:{FADE_FIM}:force_original_aspect_ratio=increase:flags=lanczos,"
           f"crop={W}:{FADE_FIM}:0:(in_h-{FADE_FIM})*{a.foco_y},setsar=1,fps={FPS},format=yuv420p")
    f.append(f"[{i_p}:v]{cob}[pv]")
    f.append(f"[{i_k}:v]format=rgba,trim=duration={d_a:.3f}[kk]")
    f.append(f"[pv][kk]overlay=0:0:shortest=1,format=yuv420p[pvk]")
    f.append(f"[{i_c}:v]{cob}[cv]")
    f.append("[pvk][cv]concat=n=2:v=1:a=0,setpts=PTS-STARTPTS[topo]")
    f.append(f"[{i_m}:v]format=gray,trim=duration={d_a + L:.3f}[mk]")
    f.append("[topo]format=yuva420p[ta];[ta][mk]alphamerge[tm]")
    f.append("[fundo][tm]overlay=0:0:shortest=1,format=yuv420p[ab]")
    # saída em tela cheia e clarão "saida": 2 quadros subindo, 3 descendo, pico de 0,62
    f.append(f"[{i_s}:v]fps={FPS},setsar=1,format=yuv420p,trim=duration={d_c:.3f},setpts=PTS-STARTPTS[sv]")
    f.append("[ab][sv]concat=n=2:v=1:a=0[todo]")
    sobe, desce = 2 / FPS, 3 / FPS
    f.append(f"color=white:s={W}x{H}:r={FPS}:d={sobe + desce:.4f},format=yuva420p,"
             f"fade=t=in:st=0:d={sobe:.4f}:alpha=1,fade=t=out:st={sobe:.4f}:d={desce:.4f}:alpha=1,"
             f"colorchannelmixer=aa=0.62,setpts=PTS+{x - sobe:.4f}/TB[fl]")
    f.append(f"[todo][fl]overlay=0:0:eof_action=pass,format=yuv420p,setpts=PTS/{VELOCIDADE}[v]")
    # áudio: voz na entrada, conteúdo no meio, voz na saída, whoosh baixo no clarão
    f.append(f"[0:a]atrim=duration={d_a:.3f},asetpts=PTS-STARTPTS,volume={g_e:.2f}dB,afade=t=out:st={d_a - 0.05:.3f}:d=0.05,aresample=48000,aformat=channel_layouts=stereo[a1]")
    f.append(f"[{i_c}:a]volume={g_c:.2f}dB,afade=t=in:d=0.03,afade=t=out:st={L - 0.05:.3f}:d=0.05,aresample=48000,aformat=channel_layouts=stereo[a2]")
    f.append(f"[{i_s}:a]volume={g_s:.2f}dB,afade=t=out:st={d_c - 0.12:.3f}:d=0.12,aresample=48000,aformat=channel_layouts=stereo[a3]")
    f.append("[a1][a2][a3]concat=n=3:v=0:a=1[voz]")
    f.append(f"[{i_w}:a]volume=0.5,adelay={int((x - 1 / FPS) * 1000)}:all=1,aresample=48000,aformat=channel_layouts=stereo[wh]")
    f.append(f"[voz][wh]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=false,atempo={VELOCIDADE}[a]")

    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", *inp, "-filter_complex", ";".join(f),
           "-map", "[v]", "-map", "[a]", "-c:v", "hevc_videotoolbox", "-q:v", "68", "-tag:v", "hvc1",
           "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", a.out]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)
    print(json.dumps({
        "saida": a.out, "duracao_conteudo": round(L, 2), "laco": segs, "dif_emenda": dif,
        "clarao_em": round(x / VELOCIDADE, 2), "fim_entrada_em": round(d_a / VELOCIDADE, 2),
        "lufs_alvo": alvo, "ganhos_db": {"entrada": round(g_e, 1), "conteudo": round(g_c, 1), "saida": round(g_s, 1)},
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
