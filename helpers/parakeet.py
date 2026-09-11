#!/usr/bin/env python3
"""Transcricao rapida com Parakeet TDT 0.6B v3 (ONNX via sherpa-onnx).

POR QUE EXISTE. O `transcribe.py` usa WhisperX: faster-whisper para decodificar
mais um wav2vec2 so para alinhar palavra. Dois modelos, ~1,7 GB, e roda perto de
1x tempo real. O Parakeet e um TRANSDUTOR: ele emite o instante de cada token
durante a propria decodificacao, entao o modelo de alinhamento desaparece e a
transcricao fica uma ordem de grandeza mais rapida.

IMPLEMENTACAO PROPRIA (2026-09-10). Usa apenas a API publica do sherpa-onnx
(Apache-2.0) e o modelo publico da NVIDIA. Nao reaproveita codigo do Edvid.app,
que e produto comercial e cujo helper equivalente NAO esta no repositorio MIT.

TRES LIMITES DO MODELO que ditam o formato deste arquivo:

1. O ENCODER TEM TETO DE JANELA. O grafo ONNX exportado carrega tensor de
   posicao de tamanho fixo; passar audio longo demais estoura com erro de
   broadcast. Por isso o audio e picotado, nunca mandado inteiro.

2. PEDACO CURTO FAZ O MODELO TROCAR DE IDIOMA. O v3 e multilingue, detecta o
   idioma sozinho e nao aceita que se force um. Em trecho de poucos segundos ele
   responde em ingles. A defesa e dar CONTEXTO: pedaco alvo de 60 s.

3. A MEMORIA CRESCE COM O TAMANHO DO PEDACO, nao com a duracao do video — a
   atencao e quadratica. Picotar sai mais rapido E mais leve que uma passada
   unica.

A EMENDA CAI NO SILENCIO. Cortar o pedaco onde nao ha fala e o que impede partir
palavra entre dois pedacos. O silencio aqui NAO decide corte de edicao nenhum —
quem faz isso e o `speech_regions.py`; este limiar so escolhe onde e seguro
emendar.

USO
  uv run python helpers/parakeet.py <video> --edit-dir <edit> [--model-dir DIR]
  uv run python helpers/parakeet.py <video> --edit-dir <edit> --bench

Escreve `<edit>/transcripts/<stem>.json` no MESMO formato do `transcribe.py`
(words com word/start/end, segments, text, _transcription_backend), entao todo o
resto da skill — `pack_transcripts.py`, o EDL, as legendas — consome sem saber
qual motor rodou. Se o modelo ou o sherpa-onnx faltarem, sai com codigo 2 e uma
linha dizendo o que fazer; quem chama deve cair no WhisperX.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SR = 16_000
CHUNK_ALVO = 60.0          # contexto suficiente para o idioma se sustentar
CHUNK_TETO = 300.0         # folga contra o teto de janela do encoder
EMENDA_NOISE_DB = -32.0    # limiar SO para escolher onde emendar
EMENDA_MIN_PAUSA = 0.25

# Onde o Edvid.app deixa o modelo ja baixado. Reaproveitar o download e so nao
# baixar 640 MB de novo — o modelo e publico, nao e ativo do app.
CACHE_PADRAO = Path.home() / "Library/Application Support/Edvid/cache/parakeet"
CACHE_ALT = Path.home() / ".cache/parakeet-tdt-0.6b-v3"
ARQUIVOS = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")


def achar_modelo(dado: Path | None) -> Path:
    for cand in [c for c in (dado, CACHE_PADRAO, CACHE_ALT) if c]:
        if all((cand / f).is_file() for f in ARQUIVOS):
            return cand
    raise SystemExit(
        "Modelo Parakeet nao encontrado. Procurei em:\n"
        + "\n".join(f"  {c}" for c in (dado, CACHE_PADRAO, CACHE_ALT) if c)
        + "\nBaixe o parakeet-tdt-0.6b-v3 (ONNX int8) para uma dessas pastas,\n"
          "ou passe --model-dir. Sem ele, use o transcribe.py (WhisperX)."
    )


def ler_audio(media: Path):
    """ffmpeg -> PCM float32 mono 16 kHz, em memoria."""
    import numpy as np
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(media),
           "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise SystemExit(f"ffmpeg falhou: {p.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(p.stdout, dtype="<f4").copy()


def silencios(media: Path) -> list[tuple[float, float]]:
    cmd = ["ffmpeg", "-nostdin", "-v", "info", "-i", str(media),
           "-af", f"silencedetect=noise={EMENDA_NOISE_DB}dB:d={EMENDA_MIN_PAUSA}",
           "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    out, ini, res = p.stderr, None, []
    for m in re.finditer(r"silence_(start|end):\s*(-?[\d.]+)", out):
        if m.group(1) == "start":
            ini = float(m.group(2))
        elif ini is not None:
            res.append((ini, float(m.group(2))))
            ini = None
    return res


def fatias(dur: float, sil: list[tuple[float, float]], alvo: float) -> list[tuple[float, float]]:
    """Pedacos de ~alvo segundos, com a emenda no meio do silencio mais proximo."""
    if dur <= alvo:
        return [(0.0, dur)]
    cortes, t = [0.0], alvo
    while t < dur - 1.0:
        meios = [(a + b) / 2 for a, b in sil if cortes[-1] + 5.0 < (a + b) / 2 < min(t + alvo, dur)]
        escolha = min(meios, key=lambda m: abs(m - t)) if meios else min(t, dur)
        if escolha <= cortes[-1] + 1.0:          # sem silencio usavel: corta seco
            escolha = min(cortes[-1] + CHUNK_TETO, dur)
        cortes.append(escolha)
        t = escolha + alvo
    cortes.append(dur)
    return [(a, b) for a, b in zip(cortes, cortes[1:]) if b - a > 0.05]


def regioes_de_fala(dur: float, sil_local: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Complemento do silencio dentro do pedaco: onde HA fala, em tempo real."""
    out, t = [], 0.0
    for a, b in sorted(sil_local):
        a, b = max(0.0, a), min(dur, b)
        if a > t:
            out.append((t, a))
        t = max(t, b)
    if t < dur:
        out.append((t, dur))
    return [(a, b) for a, b in out if b - a > 0.01]


def para_real(t: float, fala: list[tuple[float, float]]) -> float:
    """Tempo comprimido -> tempo real, por MAPEAMENTO EXATO.

    CORRIGIDO 2026-09-10 apos o Astra apontar, e a medicao confirmar, que a
    versao heuristica somava silencio demais: a ultima palavra caia em 238,0 s
    num video de 227,7 s — 10,3 s de excesso acumulado, e o erro crescia ao
    longo do arquivo.

    A versao certa nao SOMA nada: o relogio do transdutor e a linha do tempo so
    da fala, entao basta percorrer as regioes de fala reais gastando `t` dentro
    delas. Nao pode ultrapassar a duracao do pedaco, porque o resultado e sempre
    um instante DENTRO de uma regiao de fala medida no audio.
    """
    acc = 0.0
    for a, b in fala:
        d = b - a
        if t <= acc + d:
            return a + (t - acc)
        acc += d
    return fala[-1][1] if fala else t


def _descomprimir_antigo(t: float, sil_local: list[tuple[float, float]]) -> float:
    """OBSOLETA — mantida so para documentar o erro. Ver `para_real`.

    Tempo comprimido do transdutor -> tempo real do audio.

    O NUCLEO DO PROBLEMA. O transdutor so emite token quando ha fala: o silencio
    nao gasta nenhum passo, entao a linha do tempo que ele devolve e a do audio
    COM AS PAUSAS REMOVIDAS. Medido em 3,8 min de fala: a maior lacuna entre
    palavras saiu 0,72 s quando havia pausas reais de varios segundos.

    Consequencia pratica, e por isso isto existe: as entradas `spacing` saem
    curtas demais, o `pack_transcripts.py` nao acha silencio de 0,5 s e devolve
    3 frases para 864 palavras. O `takes_packed.md` — a visao de leitura da Fase
    1 — vira um paredao inutil.

    A correcao usa o silencio ACUSTICO que ja foi medido para picotar: percorre
    as pausas em ordem e, para cada uma que ja passou no tempo comprimido,
    devolve a duracao dela. `sil_local` vem em tempo real, relativo ao pedaco.
    """
    off = 0.0
    for a, b in sil_local:
        if t >= a - off:
            off += b - a
        else:
            break
    return t + off


def palavras_de_tokens(tokens: list[str], ts: list[float], off: float) -> list[dict]:
    """Tokens de subpalavra -> palavras.

    MEDIDO neste export (2026-09-10): o inicio de palavra vem marcado com ESPACO
    a esquerda (' Voce', ' precis', 'a', ' cri', 'ar'), nao com o '▁' que outros
    exports do NeMo usam. Os dois casos sao aceitos aqui — checar so o '▁' fazia
    o pedaco inteiro virar UMA palavra, e nada no resultado denunciava isso: o
    texto saia perfeito e so o tempo por palavra estava perdido.
    """
    out: list[dict] = []
    for tok, t in zip(tokens, ts):
        novo = tok.startswith(("▁", " ")) or not out
        limpo = tok.replace("▁", "").strip() if novo else tok.replace("▁", "")
        if novo:
            if not limpo:
                continue
            out.append({"word": limpo, "start": off + t, "end": off + t})
        else:
            out[-1]["word"] += limpo
            out[-1]["end"] = off + t
    for i, w in enumerate(out):                   # fim = inicio do proximo, com teto
        prox = out[i + 1]["start"] if i + 1 < len(out) else None
        cauda = w["end"] + 0.08
        w["end"] = min(cauda, prox) if prox else cauda
        if w["end"] <= w["start"]:
            w["end"] = w["start"] + 0.08
    return [w for w in out if w["word"].strip()]


def frases(palavras: list[dict], sil: list[tuple[float, float]] | None = None,
           pausa: float = 0.5) -> list[dict]:
    """Quebra em frases pelo SILENCIO ACUSTICO, nao pela lacuna do transcript.

    MEDIDO (2026-09-10): o transdutor COMPRIME a pausa. Em 3,8 min de fala com
    pausas reais, a maior lacuna entre palavras foi 0,72 s e so duas passaram de
    0,5 s — porque silencio nao emite token e o tempo do token marca a emissao,
    nao o instante acustico. Quebrar frase por essa lacuna daria 3 frases para
    864 palavras: um paredao de texto em vez da visao por frase.

    O `speech_regions.py` ja e a fonte de verdade das bordas de corte nesta skill
    justamente porque tempo de transcricao deriva. A mesma regra vale aqui: a
    frase fecha na palavra anterior a um silencio de >= `pausa`, medido no audio.
    Sem lista de silencio, cai na lacuna do transcript (pior, mas nao vazio).
    """
    marcos = [a for a, b in (sil or []) if b - a >= pausa]
    # O tempo do transdutor DERIVA dentro do pedaco (a pausa comprimida encurta a
    # linha do tempo interna), entao o marco acustico nao cai na lacuna entre dois
    # tokens: cai no meio de uma sequencia densa. Casar por INTERVALO nao acha
    # nada — medido, dava 1 frase para 864 palavras. Casa por PROXIMIDADE: cada
    # silencio real fecha a frase na palavra de fim mais perto dele.
    quebras: set[int] = set()
    if marcos and palavras:
        for m in marcos:
            i = min(range(len(palavras)), key=lambda k: abs(palavras[k]["end"] - m))
            if i < len(palavras) - 1:
                quebras.add(i)
    segs, atual = [], []
    for i, w in enumerate(palavras):
        atual.append(w)
        if marcos:
            fim = i + 1 >= len(palavras) or i in quebras
        else:
            fim = i + 1 >= len(palavras) or palavras[i + 1]["start"] - w["end"] >= pausa
        if fim and atual:
            segs.append({"start": atual[0]["start"], "end": atual[-1]["end"],
                         "text": " ".join(x["word"] for x in atual), "words": list(atual)})
            atual = []
    return segs


def transcrever(media: Path, modelo: Path, threads: int, alvo: float) -> dict:
    try:
        import sherpa_onnx
    except ImportError:
        raise SystemExit("sherpa-onnx nao instalado. Rode: uv pip install sherpa-onnx")
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(modelo / "encoder.int8.onnx"),
        decoder=str(modelo / "decoder.int8.onnx"),
        joiner=str(modelo / "joiner.int8.onnx"),
        tokens=str(modelo / "tokens.txt"),
        num_threads=threads,
        sample_rate=SR,
        feature_dim=80,
        model_type="nemo_transducer",
    )
    pcm = ler_audio(media)
    dur = len(pcm) / SR
    sil = silencios(media)          # serve a DOIS fins: emenda e quebra de frase
    palavras: list[dict] = []
    for ini, fim in fatias(dur, sil, alvo):
        trecho = pcm[int(ini * SR):int(fim * SR)]
        if len(trecho) < SR // 10:
            continue
        s = rec.create_stream()
        s.accept_waveform(SR, trecho)
        rec.decode_stream(s)
        r = s.result
        # pausas DENTRO deste pedaco, em tempo relativo a ele
        sil_local = [(a - ini, b - ini) for a, b in sil if a >= ini and b <= fim]
        fala_local = regioes_de_fala(fim - ini, sil_local)
        ts_real = [para_real(float(x), fala_local) for x in r.timestamps]
        palavras.extend(palavras_de_tokens(list(r.tokens), ts_real, ini))
    # O SCHEMA e o do transcribe.py, e o conversor dele e importado em vez de
    # reescrito: assim os dois motores nao podem divergir de formato. O resto da
    # skill le `words` com type=word/spacing — e das entradas `spacing` que o
    # pack_transcripts.py tira as frases. Nao existe campo `segments` no schema.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from transcribe import _to_scribe_words
    return {
        "language_code": "pt",
        "language": "pt",
        "text": " ".join(w["word"] for w in palavras),
        "words": _to_scribe_words(palavras),
        "duration": dur,
        # O sufixo /UNALIGNED e a convencao que esta skill JA usa para dizer "tempo de
        # palavra e do decodificador, nao de alinhamento forcado — nao confie nele
        # para legenda karaoke". Medido em 2026-09-10 contra o speech_regions.py:
        # 88,4% dos inicios caem dentro de fala real, com a linha de base do acaso
        # em 80,8% e o WhisperX em 93%. Serve para LER e escolher trecho; nao serve
        # para borda de corte nem para karaoke. Quem precisa de precisao usa o
        # transcribe.py.
        "_transcription_backend": "parakeet-tdt-0.6b-v3/onnx/UNALIGNED",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("media", type=Path)
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--model-dir", type=Path, default=None)
    ap.add_argument("--threads", type=int, default=max(2, (os.cpu_count() or 4) - 2))
    ap.add_argument("--chunk", type=float, default=CHUNK_ALVO)
    ap.add_argument("--force", action="store_true", help="re-transcreve mesmo com cache")
    ap.add_argument("--bench", action="store_true", help="imprime o fator de tempo real")
    a = ap.parse_args()

    if not a.media.is_file():
        print(f"nao achei {a.media}", file=sys.stderr)
        return 1
    destino = a.edit_dir / "transcripts" / f"{a.media.stem}.json"
    if destino.is_file() and not a.force:
        print(f"cache: {destino}")
        return 0
    destino.parent.mkdir(parents=True, exist_ok=True)

    modelo = achar_modelo(a.model_dir)
    t0 = time.time()
    dados = transcrever(a.media, modelo, a.threads, a.chunk)
    gasto = time.time() - t0
    dados["_elapsed_s"] = round(gasto, 1)
    destino.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")

    dur = dados["duration"]
    n_w = sum(1 for w in dados["words"] if w.get("type") == "word")
    n_s = sum(1 for w in dados["words"] if w.get("type") == "spacing")
    print(f"{destino}  |  {n_w} palavras, {n_s} intervalos")
    print(f"{dur/60:.1f} min de audio em {gasto:.1f}s"
          + (f"  =  {dur/gasto:.1f}x tempo real" if a.bench and gasto > 0 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
