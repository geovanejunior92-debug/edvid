#!/usr/bin/env python3
"""Tempo, divisão e junção de legenda — e as invariantes que o render não checa.

`caption_fix.py` conserta o TEXTO sem tocar no tempo. Este arquivo é o outro
lado: mexe no tempo, divide uma palavra que a transcrição grudou, junta duas
que ela partiu, e desloca tudo depois de um corte novo.

O que ele guarda são as invariantes que ninguém mais guarda. O Remotion desenha
o que receber: bloco vazio vira um piscar sem texto, sobreposição vira duas
legendas na tela, tempo invertido some sem erro, e legenda que passa do fim da
fala aparece por cima do encerramento. Nada disso levanta exceção em lugar
nenhum do fluxo — aparece no vídeo entregue.

Formato: a lista de palavras do `captions.json` do Remotion — `text`,
`startMs`, `endMs`, `timestampMs`. Os tempos são em MILISSEGUNDOS, e essa é a
principal fonte de erro de quem mexe nisso à mão.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

MIN_MS = 40          # abaixo disso a palavra pisca e não se lê


class CaptionError(ValueError):
    pass


def _norm(cue: dict) -> dict:
    out = dict(cue)
    out["text"] = str(cue.get("text", "")).strip()
    out["startMs"] = int(round(float(cue["startMs"])))
    out["endMs"] = int(round(float(cue["endMs"])))
    out["timestampMs"] = int(round(float(cue.get("timestampMs",
                                                 (out["startMs"] + out["endMs"]) / 2))))
    return out


def inspect(cues: list[dict], *, duration_ms: int | None = None,
            outro_start_ms: int | None = None) -> dict:
    """Separa ERRO de AVISO. A diferença veio do dado real, não da teoria.

    Rodando nas legendas já entregues do canal, o que apareceu foram palavras
    de 20ms — artigos como "a" e "e", que o WhisperX cronometra curtos porque
    são curtos mesmo. A 30fps isso é menos de um quadro, então o realce do
    karaokê pula a palavra: chato, não quebrado, e os vídeos foram entregues
    assim. Tratar isso no mesmo nível de um bloco vazio tornaria o gate
    inutilizável — reprovaria todo vídeo do canal por um defeito cosmético.
    """
    erros: list[str] = []
    avisos: list[str] = []
    anterior = None
    for i, raw in enumerate(cues):
        try:
            c = _norm(raw)
        except (KeyError, TypeError, ValueError):
            erros.append(f"cue {i}: sem startMs/endMs legível")
            continue
        if not c["text"]:
            erros.append(f"cue {i}: bloco vazio")
        if c["endMs"] <= c["startMs"]:
            erros.append(f"cue {i} «{c['text']}»: fim ({c['endMs']}) não passa do início ({c['startMs']})")
        elif c["endMs"] - c["startMs"] < MIN_MS:
            avisos.append(f"cue {i} «{c['text']}»: dura {c['endMs'] - c['startMs']}ms — o realce do karaokê pula")
        if not (c["startMs"] <= c["timestampMs"] <= c["endMs"]):
            erros.append(f"cue {i} «{c['text']}»: timestampMs fora do próprio intervalo")
        if anterior and c["startMs"] < anterior["endMs"]:
            erros.append(f"cue {i} «{c['text']}»: começa antes de «{anterior['text']}» terminar")
        if duration_ms is not None and c["endMs"] > duration_ms:
            erros.append(f"cue {i} «{c['text']}»: passa do fim do vídeo ({duration_ms}ms)")
        # Qualquer SOBREPOSIÇÃO com o encerramento conta, não só começar depois
        # dele: um bloco que começa antes e termina depois é desenhado por cima
        # da tela azul durante a diferença, que é exatamente o defeito.
        if outro_start_ms is not None and c["endMs"] > outro_start_ms:
            erros.append(f"cue {i} «{c['text']}»: cai em cima do encerramento")
        anterior = c
    if not cues:
        erros.append("a lista de legendas está vazia")
    return {"errors": erros, "warnings": avisos}


def validate(cues: list[dict], **limites) -> list[str]:
    """Só os ERROS — é o que impede renderizar."""
    return inspect(cues, **limites)["errors"]


def _apply_and_check(cues: list[dict], duration_ms=None, outro_start_ms=None) -> list[dict]:
    problemas = validate(cues, duration_ms=duration_ms, outro_start_ms=outro_start_ms)
    if problemas:
        raise CaptionError("a edição deixaria a legenda inválida: " + "; ".join(problemas[:4]))
    return [_norm(c) for c in cues]


def retime(cues: list[dict], index: int, start_ms: int | None = None,
           end_ms: int | None = None, **limites) -> list[dict]:
    """Move o início e/ou o fim de UM bloco, sem empurrar os vizinhos."""
    out = [dict(c) for c in cues]
    if not 0 <= index < len(out):
        raise CaptionError("índice de legenda fora da lista")
    alvo = out[index]
    if start_ms is not None:
        alvo["startMs"] = int(start_ms)
    if end_ms is not None:
        alvo["endMs"] = int(end_ms)
    alvo["timestampMs"] = int((alvo["startMs"] + alvo["endMs"]) / 2)
    return _apply_and_check(out, **limites)


def split(cues: list[dict], index: int, text_a: str, text_b: str, at_ms: int | None = None,
          **limites) -> list[dict]:
    """Divide um bloco em dois. A transcrição às vezes gruda duas palavras."""
    out = [dict(c) for c in cues]
    if not 0 <= index < len(out):
        raise CaptionError("índice de legenda fora da lista")
    a, b = str(text_a).strip(), str(text_b).strip()
    if not a or not b:
        raise CaptionError("dividir exige texto nos dois lados")
    alvo = _norm(out[index])
    corte = int(at_ms) if at_ms is not None else (alvo["startMs"] + alvo["endMs"]) // 2
    if not (alvo["startMs"] < corte < alvo["endMs"]):
        raise CaptionError("o ponto de divisão precisa ficar dentro do bloco")
    primeiro = {**alvo, "text": a, "endMs": corte,
                "timestampMs": (alvo["startMs"] + corte) // 2}
    segundo = {**alvo, "text": b, "startMs": corte,
               "timestampMs": (corte + alvo["endMs"]) // 2}
    out[index:index + 1] = [primeiro, segundo]
    return _apply_and_check(out, **limites)


def merge(cues: list[dict], index: int, text: str | None = None, **limites) -> list[dict]:
    """Junta o bloco com o SEGUINTE. Para o que a transcrição partiu no meio."""
    out = [dict(c) for c in cues]
    if not 0 <= index < len(out) - 1:
        raise CaptionError("não há bloco seguinte para juntar")
    a, b = _norm(out[index]), _norm(out[index + 1])
    juntou = {**a, "text": (text.strip() if text else f"{a['text']}{b['text']}"),
              "endMs": b["endMs"], "timestampMs": (a["startMs"] + b["endMs"]) // 2}
    if not juntou["text"]:
        raise CaptionError("juntar não pode resultar em bloco vazio")
    out[index:index + 2] = [juntou]
    return _apply_and_check(out, **limites)


def shift(cues: list[dict], delta_ms: int, from_index: int = 0, **limites) -> list[dict]:
    """Desloca daqui para a frente. É o que ressincroniza depois de um corte novo."""
    out = []
    for i, c in enumerate(cues):
        c = _norm(c)
        if i >= from_index:
            c["startMs"] += int(delta_ms)
            c["endMs"] += int(delta_ms)
            c["timestampMs"] += int(delta_ms)
        if c["startMs"] < 0:
            raise CaptionError("o deslocamento jogaria a legenda para antes do vídeo")
        out.append(c)
    return _apply_and_check(out, **limites)


def drop_after(cues: list[dict], limit_ms: int) -> list[dict]:
    """Remove o que começa depois do limite — o caso do encerramento.

    Corta pelo INÍCIO, não pelo fim: um bloco que começa antes e termina depois
    é aparado, porque a fala existe; um que começa depois é fala que não existe
    mais e vira legenda órfã sobre a tela azul."""
    out = []
    for c in cues:
        c = _norm(c)
        if c["startMs"] >= int(limit_ms):
            continue
        if c["endMs"] > int(limit_ms):
            c["endMs"] = int(limit_ms)
            c["timestampMs"] = min(c["timestampMs"], c["endMs"])
        if c["endMs"] - c["startMs"] >= MIN_MS and c["text"]:
            out.append(c)
    return out


def load(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text())
    cues = data if isinstance(data, list) else (data.get("captions") or data.get("words"))
    if not isinstance(cues, list):
        raise CaptionError(f"{Path(path).name}: não encontrei a lista de legendas")
    return cues


def main() -> None:
    ap = argparse.ArgumentParser(description="Valida e edita tempo/blocos da legenda")
    ap.add_argument("captions", type=Path)
    ap.add_argument("--duration-ms", type=int)
    ap.add_argument("--outro-start-ms", type=int)
    ap.add_argument("--drop-after-ms", type=int, help="remove legenda que começa depois disto")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cues = load(args.captions)
    if args.drop_after_ms is not None:
        antes = len(cues)
        cues = drop_after(cues, args.drop_after_ms)
        print(f"· {antes - len(cues)} bloco(s) removidos depois de {args.drop_after_ms}ms")
    achados = inspect(cues, duration_ms=args.duration_ms, outro_start_ms=args.outro_start_ms)
    erros, avisos = achados["errors"], achados["warnings"]
    if erros:
        print(f"✗ {len(erros)} erro(s) — não renderize:")
        for p in erros[:20]:
            print(f"   {p}")
    else:
        print(f"✓ {len(cues)} blocos, sem sobreposição, sem bloco vazio, dentro dos limites")
    if avisos:
        print(f"· {len(avisos)} aviso(s) cosmético(s), não bloqueiam:")
        for p in avisos[:5]:
            print(f"   {p}")
        if len(avisos) > 5:
            print(f"   … e mais {len(avisos) - 5}")
    if args.apply:
        Path(args.captions).write_text(json.dumps(cues, ensure_ascii=False, indent=2))
        print(f"gravado em {args.captions}")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
