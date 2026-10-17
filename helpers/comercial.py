#!/usr/bin/env python3
"""Comercial animado (estilo Apple) tocando dentro de um estúdio de edição — da ficha ao MP4.

O motor é o do "Estúdio de edição" (skill gratuita de Amanda Diniz), guardado em
`assets/comercial/estudio.html`. Ele desenha qualquer instante do comercial a
partir de um bloco JSON, o PROJETO. A skill original pedia ao agente para editar
esse bloco à mão, conferir de olho e mandar a pessoa FILMAR a tela. Este helper
troca as três coisas:

    check  <ficha.json>                    a conferência que o original fazia "de cabeça"
                                           (cenas contínuas, ≤6 palavras, cronômetro
                                           zerando junto do som `destrava`, arquivos que
                                           existem). Exit ≠ 0 = não monte.
    build  <ficha.json> --out <pasta>      check + copia o motor, injeta a ficha, leva
                                           imagens e fontes para a pasta. Nunca edita o motor.
    still  <pasta> [--at 1 5 9]            quadros do comercial em PNG + uma folha, sem
                                           renderizar o vídeo (o phase2_still.py daqui).
    render <pasta> [--fps 60] [--escala 2] MP4 direto do motor, quadro a quadro, com o som
                                           gerado no próprio navegador. Sem filmar a tela.

`still` e `render` rodam o Chrome sem janela contra um servidor local deste
helper: a página desenha cada quadro e manda por POST; o servidor alimenta o
ffmpeg. Só biblioteca padrão — o venv do edvid não tem Playwright e não precisa.

Formato: o motor é 1920×1080 (16:9). Não existe versão vertical; para Reels, o
uso previsto é filmar a interface (atalhos na referência) ou usar o MP4 16:9
dentro de outro vídeo.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

SKILL = Path(__file__).resolve().parents[1]
MOTOR = SKILL / 'assets' / 'comercial' / 'estudio.html'
FONTES_EDVID = SKILL / 'assets' / 'fonts'
CHROME = os.environ.get('EDVID_CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
INICIO, FIM = '/*PROJETO*/', '/*FIM-PROJETO*/'

CENAS = {'rolagem', 'fundo', 'numero', 'anel', 'particulas', 'foto', 'lista', 'contador',
         'medidor', 'notificacoes', 'linhas', 'assinatura'}
SONS = {'rolagem', 'baque', 'whoosh', 'entra', 'revelacao', 'notificacoes', 'impacto',
        'destrava', 'assinatura', 'ding'}
CORES = ('fundo', 'texto', 'destaque', 'acento', 'suave', 'claro')
CORES_TEXTO = {'claro', 'escuro', 'grad', 'suave'}
MAX_PALAVRAS = 6
EPS = 0.011


# ---------------------------------------------------------------- conferência
def _palavras(linhas: list[str]) -> int:
    return sum(len(l.split()) for l in linhas)


def conferir(ficha: dict, base: Path | None = None) -> tuple[list[str], list[str]]:
    """(erros, avisos). Erro = o comercial sai quebrado; aviso = escolha editorial fora do padrão."""
    erros: list[str] = []
    avisos: list[str] = []
    e, a = erros.append, avisos.append

    for campo in ('marca', 'duracao', 'cenas', 'textos'):
        if campo not in ficha:
            e(f'falta o campo "{campo}"')
    if erros:
        return erros, avisos
    dur = ficha['duracao']
    if not isinstance(dur, (int, float)) or dur <= 0:
        return [f'duracao inválida: {dur!r}'], avisos
    if not 20 <= dur <= 35:
        a(f'duracao {dur}s fora de 20–35 s, a faixa que funciona no feed')

    cores = ficha.get('cores') or {}
    for k in CORES:
        v = cores.get(k)
        if v is None:
            a(f'cor "{k}" ausente: o motor usa a paleta âmbar do exemplo')
        elif not re.fullmatch(r'#[0-9a-fA-F]{6}', str(v)):
            e(f'cor "{k}" = {v!r}: escreva #rrggbb')
    if str(cores.get('fundo', '')).lower() == '#000000':
        a('fundo #000000 puro: use um quase preto puxado para a cor da marca')

    # cenas contínuas, sem buraco nem sobreposição
    cenas = sorted(ficha['cenas'], key=lambda c: c.get('ini', 0))
    if cenas != ficha['cenas']:
        e('cenas fora de ordem de tempo')
    ids = [c.get('id') for c in cenas]
    if len(set(ids)) != len(ids):
        e('id de cena repetido')
    if not cenas:
        e('nenhuma cena')
    else:
        if abs(cenas[0].get('ini', -1)) > EPS:
            e(f'a primeira cena começa em {cenas[0].get("ini")}, não em 0')
        if abs(cenas[-1].get('fim', -1) - dur) > EPS:
            e(f'a última cena termina em {cenas[-1].get("fim")}, não na duracao {dur}')
        for c1, c2 in zip(cenas, cenas[1:]):
            if abs(c1['fim'] - c2['ini']) > EPS:
                tipo = 'buraco' if c2['ini'] > c1['fim'] else 'sobreposição'
                e(f'{tipo} entre {c1.get("id")} (fim {c1["fim"]}) e {c2.get("id")} (início {c2["ini"]})')
        if cenas[-1].get('tipo') != 'assinatura':
            a('a última cena não é "assinatura"')
    imagens = ficha.get('imagens') or {}
    for c in cenas:
        cid = c.get('id', '?')
        if c.get('fim', 0) <= c.get('ini', 0):
            e(f'{cid}: fim antes do início')
        if c.get('tipo') not in CENAS:
            e(f'{cid}: tipo "{c.get("tipo")}" não existe no catálogo')
        if not c.get('nota'):
            a(f'{cid}: sem "nota" — é ela que aparece no painel do Claude')
        p = c.get('params') or {}
        if c.get('tipo') in ('foto', 'assinatura') and p.get('imagem') and p['imagem'] not in imagens:
            e(f'{cid}: imagem "{p["imagem"]}" não está em "imagens"')
        if c.get('tipo') == 'foto' and not p.get('imagem'):
            e(f'{cid}: cena "foto" sem params.imagem (sem foto, use "particulas")')
        for it in p.get('itens') or []:
            texto = ' '.join(it) if isinstance(it, list) else str(it)
            if c.get('tipo') == 'lista' and len(texto.split()) > 4:
                a(f'{cid}: item "{texto}" com mais de 4 palavras')
        if len(p.get('itens') or []) > 4:
            a(f'{cid}: mais de 4 itens')

    # textos dentro de uma cena, curtos
    for i, t in enumerate(ficha['textos']):
        nome = f'texto {i + 1} ("{" ".join(t.get("linhas", []))}")'
        if not t.get('linhas') or len(t['linhas']) > 2:
            e(f'{nome}: 1 ou 2 linhas')
            continue
        n = _palavras(t['linhas'])
        if n > MAX_PALAVRAS:
            e(f'{nome}: {n} palavras (máximo {MAX_PALAVRAS})')
        ini, fim = t.get('ini', -1), t.get('fim', -1)
        if fim <= ini:
            e(f'{nome}: fim antes do início')
        dono = [c for c in cenas if c['ini'] - EPS <= ini and fim <= c['fim'] + EPS]
        if not dono:
            e(f'{nome}: atravessa uma troca de cena ({ini}–{fim})')
        tam = t.get('tam', 140)
        if len(t['linhas']) == 2 and tam > 140:
            a(f'{nome}: duas linhas com tam {tam} (até 140)')
        if n == 1 and tam < 120:
            a(f'{nome}: uma palavra só com tam {tam}; costuma pedir 200–260')
        if t.get('cor') and t['cor'] not in CORES_TEXTO:
            e(f'{nome}: cor "{t["cor"]}" não existe (claro, escuro, grad, suave)')
        d = t.get('destaque')
        if d:
            if not (isinstance(d, list) and len(d) == 2 and isinstance(d[0], int) and 0 <= d[0] < len(t['linhas'])):
                e(f'{nome}: destaque deve ser [número da linha, "final da linha"]')
            elif not t['linhas'][d[0]].endswith(d[1]):
                e(f'{nome}: destaque "{d[1]}" não é o final da linha {d[0]}')

    sons = ficha.get('sons') or []
    for s in sons:
        if s.get('tipo') not in SONS:
            e(f'som "{s.get("tipo")}" não existe no catálogo')
        if not 0 <= s.get('t', -1) < dur:
            e(f'som "{s.get("tipo")}" em {s.get("t")}s, fora do comercial')

    cr = ficha.get('cronometro')
    if cr:
        seg, ap, co, ze, so = (cr.get(k) for k in ('segundos', 'aparece', 'comeca', 'zera', 'some'))
        if None in (seg, ap, co, ze, so):
            e('cronometro precisa de segundos, aparece, comeca, zera e some')
        else:
            if abs(co + seg - ze) > EPS:
                e(f'cronometro: zera ({ze}) ≠ comeca + segundos ({co + seg:g})')
            if not ap <= co <= ze <= so <= dur:
                e('cronometro: a ordem é aparece ≤ comeca ≤ zera ≤ some ≤ duracao')
            if abs(so - ze - 1.6) > 0.3:
                a(f'cronometro: some {so - ze:.1f}s depois de zerar (o padrão é 1,6 s)')
            if not any(s.get('tipo') == 'destrava' and abs(s.get('t', -9) - ze) <= 0.05 for s in sons):
                e(f'cronometro zera em {ze}s sem som "destrava" nesse instante')
    elif any(s.get('tipo') == 'destrava' for s in sons):
        a('som "destrava" sem cronômetro')

    tr = ficha.get('trilha') or {}
    if tr.get('pausa'):
        p0, p1 = tr['pausa']
        if not 0 <= p0 < p1 <= dur:
            e(f'trilha.pausa {tr["pausa"]} fora do comercial')
    if tr.get('tom') not in (None, 'maior', 'menor'):
        e('trilha.tom é "maior" ou "menor"')

    if base is not None:
        for k, arq in imagens.items():
            if not (base / arq).expanduser().exists() and not Path(arq).expanduser().exists():
                e(f'imagem "{k}": arquivo {arq} não existe')
    return erros, avisos


# ---------------------------------------------------------------- montagem
def _resolve(arq: str, base: Path, extra: Path | None = None) -> Path | None:
    for cand in (Path(arq).expanduser(), base / arq, *( [extra / arq] if extra else [] )):
        if cand.is_file():
            return cand.resolve()
    return None


def montar(ficha_path: Path, out: Path) -> Path:
    ficha = json.loads(ficha_path.read_text())
    base = ficha_path.parent
    out.mkdir(parents=True, exist_ok=True)
    imagens = {}
    for k, arq in (ficha.get('imagens') or {}).items():
        src = _resolve(arq, base)
        if not src:
            raise SystemExit(f'imagem "{k}" não encontrada: {arq}')
        nome = f'{k}{src.suffix.lower()}'
        if src != (out / nome).resolve():
            shutil.copy2(src, out / nome)
        imagens[k] = nome
    ficha['imagens'] = imagens
    fontes = ficha.get('fontes') or {}
    if fontes.get('arquivos'):
        (out / 'fontes').mkdir(exist_ok=True)
        novos = {}
        for fam, arq in fontes['arquivos'].items():
            src = _resolve(arq, base, FONTES_EDVID)
            if not src:
                raise SystemExit(f'fonte "{fam}" não encontrada: {arq} (procurei também em assets/fonts)')
            shutil.copy2(src, out / 'fontes' / src.name)
            novos[fam] = f'fontes/{src.name}'
        fontes['arquivos'] = novos
    html = MOTOR.read_text()
    i, j = html.index(INICIO) + len(INICIO), html.index(FIM)
    html = html[:i] + json.dumps(ficha, ensure_ascii=False, indent=2) + html[j:]
    alvo = out / 'estudio.html'
    alvo.write_text(html)
    (out / 'ficha.json').write_text(json.dumps(ficha, ensure_ascii=False, indent=2) + '\n')
    return alvo


def ler_ficha_html(pasta: Path) -> dict:
    html = (pasta / 'estudio.html').read_text()
    return json.loads(html[html.index(INICIO) + len(INICIO):html.index(FIM)])


# ---------------------------------------------------------------- Chrome sem janela
def _loudnorm_2p(wav: Path, alvo: float = -14.0) -> str:
    """Duas passagens: na de uma passagem, som esparso (só efeitos) parava em −16 LUFS."""
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(wav), '-af',
                        f'loudnorm=I={alvo}:TP=-1:LRA=11:print_format=json', '-f', 'null', '-'],
                       capture_output=True, text=True)
    try:
        m = json.loads(r.stderr[r.stderr.rindex('{'):r.stderr.rindex('}') + 1])
        return (f'loudnorm=I={alvo}:TP=-1:LRA=11:measured_I={m["input_i"]}:measured_TP={m["input_tp"]}:'
                f'measured_LRA={m["input_lra"]}:measured_thresh={m["input_thresh"]}:offset={m["target_offset"]}:linear=true')
    except (ValueError, KeyError):
        return f'loudnorm=I={alvo}:TP=-1:LRA=11'


class _Sessao:
    def __init__(self, pasta: Path, saida: Path, still_dir: Path | None, crf: int, codec: str):
        self.pasta, self.saida, self.still_dir, self.crf, self.codec = pasta, saida, still_dir, crf, codec
        self.ff = None
        self.info: dict = {}
        self.wav: Path | None = None
        self.quadros = 0
        self.erro: str | None = None
        self.pronto = threading.Event()
        self.tmp = Path(tempfile.mkdtemp(prefix='comercial_'))

    def inicio(self, info):
        self.info = info
        if info.get('still'):
            return
        self.ff = subprocess.Popen(
            ['ffmpeg', '-v', 'error', '-y', '-f', 'image2pipe', '-framerate', str(info['fps']), '-i', '-',
             '-c:v', self.codec, '-crf', str(self.crf), '-preset', 'slow', '-pix_fmt', 'yuv420p',
             '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv',
             *(['-tag:v', 'hvc1'] if self.codec == 'libx265' else []),
             str(self.tmp / 'video.mp4')], stdin=subprocess.PIPE)

    def quadro(self, i, t, corpo):
        self.quadros += 1
        if self.info.get('still'):
            self.still_dir.mkdir(parents=True, exist_ok=True)
            (self.still_dir / f'q{i:02d}_{t:06.2f}s.png').write_bytes(corpo)
        else:
            self.ff.stdin.write(corpo)
        if self.quadros % 60 == 0 or self.quadros == self.info.get('quadros'):
            print(f'  {self.quadros}/{self.info.get("quadros")} quadros', flush=True)

    def audio(self, corpo):
        self.wav = self.tmp / 'som.wav'
        self.wav.write_bytes(corpo)

    def fim(self):
        try:
            if self.ff:
                self.ff.stdin.close()
                if self.ff.wait():
                    raise RuntimeError('ffmpeg falhou ao codificar os quadros')
                cmd = ['ffmpeg', '-v', 'error', '-y', '-i', str(self.tmp / 'video.mp4')]
                if self.wav:
                    cmd += ['-i', str(self.wav), '-af', _loudnorm_2p(self.wav), '-c:a', 'aac', '-b:a', '256k',
                            '-ar', '48000']
                cmd += ['-t', f'{self.info["duracao"]:.3f}']  # nunca -shortest: amputa quadros (anti-padrão do SKILL.md)
                cmd += ['-c:v', 'copy', '-movflags', '+faststart', str(self.saida)]
                subprocess.run(cmd, check=True)
        except Exception as ex:  # noqa: BLE001 — o erro vai para quem chamou
            self.erro = str(ex)
        finally:
            self.pronto.set()


def _servidor(sessao: _Sessao):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(sessao.pasta), **k)

        def log_message(self, *a):
            pass

        def do_POST(self):
            corpo = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            rota, _, qs = self.path.partition('?')
            q = dict(x.split('=', 1) for x in qs.split('&') if '=' in x)
            try:
                if rota == '/inicio':
                    sessao.inicio(json.loads(corpo))
                elif rota == '/quadro':
                    sessao.quadro(int(q['i']), float(q.get('t', 0)), corpo)
                elif rota == '/audio':
                    sessao.audio(corpo)
                elif rota == '/fim':
                    threading.Thread(target=sessao.fim, daemon=True).start()
                elif rota == '/erro':
                    sessao.erro = 'página: ' + corpo.decode(errors='replace')
                    sessao.pronto.set()
                self.send_response(200)
            except Exception as ex:  # noqa: BLE001
                sessao.erro = str(ex)
                sessao.pronto.set()
                self.send_response(500)
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _rodar(pasta: Path, hash_: str, sessao: _Sessao, timeout: float) -> None:
    if not Path(CHROME).exists():
        raise SystemExit(f'Chrome não encontrado em {CHROME} (defina EDVID_CHROME)')
    srv = _servidor(sessao)
    perfil = tempfile.mkdtemp(prefix='comercial_chrome_')
    url = f'http://127.0.0.1:{srv.server_address[1]}/estudio.html#{hash_}'
    chrome = subprocess.Popen([CHROME, '--headless=new', f'--user-data-dir={perfil}', '--no-first-run',
                               '--mute-audio', '--hide-scrollbars', '--window-size=1920,1080',
                               '--autoplay-policy=no-user-gesture-required', url],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not sessao.pronto.wait(timeout):
            raise SystemExit(f'tempo esgotado ({timeout:.0f}s) com {sessao.quadros} quadros recebidos')
    finally:
        chrome.terminate()
        try:
            chrome.wait(10)
        except subprocess.TimeoutExpired:
            chrome.kill()
        srv.shutdown()
        shutil.rmtree(perfil, ignore_errors=True)
        shutil.rmtree(sessao.tmp, ignore_errors=True)
    if sessao.erro:
        raise SystemExit('falhou: ' + sessao.erro)


def tempos_padrao(ficha: dict) -> list[float]:
    """Meio de cada cena: onde o texto já entrou e ainda não saiu."""
    return [round(c['ini'] + (c['fim'] - c['ini']) * 0.6, 2) for c in ficha['cenas']]


def folha(pngs: list[Path], saida: Path, colunas: int = 4) -> None:
    """Uma imagem com todos os quadros e o instante de cada um (o ffmpeg local não tem drawtext)."""
    from PIL import Image, ImageDraw
    if not pngs:
        return
    w, h = 480, 270
    linhas = -(-len(pngs) // colunas)
    out = Image.new('RGB', (colunas * w, linhas * h), 'black')
    d = ImageDraw.Draw(out)
    for i, p in enumerate(pngs):
        x, y = (i % colunas) * w, (i // colunas) * h
        out.paste(Image.open(p).convert('RGB').resize((w, h)), (x, y))
        rot = p.stem.split('_', 1)[1]
        d.rectangle([x + 6, y + 6, x + 12 + 7 * len(rot), y + 24], fill=(0, 0, 0))
        d.text((x + 9, y + 9), rot, fill=(255, 255, 255))
    out.save(saida)


# ---------------------------------------------------------------- CLI
def _imprime(erros, avisos) -> int:
    for x in erros:
        print('ERRO  ', x)
    for x in avisos:
        print('AVISO ', x)
    print(f'{len(erros)} erro(s), {len(avisos)} aviso(s)')
    return 1 if erros else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check');  c.add_argument('ficha', type=Path)
    b = sub.add_parser('build');  b.add_argument('ficha', type=Path); b.add_argument('--out', type=Path, required=True)
    b.add_argument('--abrir', action='store_true', help='abre no Chrome depois de montar')
    s = sub.add_parser('still');  s.add_argument('pasta', type=Path); s.add_argument('--at', type=float, nargs='*')
    r = sub.add_parser('render'); r.add_argument('pasta', type=Path)
    r.add_argument('-o', '--out', type=Path); r.add_argument('--fps', type=float, default=30)
    r.add_argument('--escala', type=float, default=1, help='2 = 3840×2160')
    r.add_argument('--hevc', action='store_true'); r.add_argument('--crf', type=int, default=16)
    r.add_argument('--jpg', action='store_true', help='quadros em JPEG 95%% (mais rápido, perde um pouco)')
    for x in (s, r):
        x.add_argument('--timeout', type=float, default=1800)
    a = ap.parse_args(argv)

    if a.cmd == 'check':
        ficha = json.loads(a.ficha.read_text())
        return _imprime(*conferir(ficha, a.ficha.parent))
    if a.cmd == 'build':
        ficha = json.loads(a.ficha.read_text())
        if _imprime(*conferir(ficha, a.ficha.parent)):
            return 1
        alvo = montar(a.ficha, a.out)
        print(f'montado: {alvo}')
        if a.abrir:
            subprocess.run(['open', '-a', 'Google Chrome', str(alvo)])
        return 0
    pasta = a.pasta.resolve()
    ficha = ler_ficha_html(pasta)
    if a.cmd == 'still':
        tempos = a.at or tempos_padrao(ficha)
        destino = pasta / 'verify'
        shutil.rmtree(destino, ignore_errors=True)
        sessao = _Sessao(pasta, pasta / 'x.mp4', destino, 16, 'libx264')
        t0 = time.time()
        _rodar(pasta, 'tempos=' + ','.join(f'{t:g}' for t in tempos), sessao, a.timeout)
        pngs = sorted(destino.glob('q*.png'))
        folha(pngs, destino / 'sheet.png')
        print(f'{len(pngs)} quadros em {time.time() - t0:.0f}s → {destino}/sheet.png')
        return 0
    saida = (a.out or pasta / 'comercial.mp4').resolve()
    sessao = _Sessao(pasta, saida, None, a.crf, 'libx265' if a.hevc else 'libx264')
    t0 = time.time()
    fmt = '&formato=jpg' if a.jpg else ''
    _rodar(pasta, f'exportar&fps={a.fps:g}&escala={a.escala:g}{fmt}', sessao, a.timeout)
    print(f'{saida} ({sessao.quadros} quadros, {time.time() - t0:.0f}s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
