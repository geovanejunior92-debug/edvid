#!/usr/bin/env python3
"""Alinha o roteiro à transcrição e propõe a tomada de cada linha.

O corte por pausas acústicas responde "onde dá para cortar". Não responde
"qual das três vezes que ele falou essa frase é a boa". Este helper responde a
segunda pergunta, que é a editorial.

O que ele faz, e só isso:

- casa cada LINHA do roteiro com trechos da transcrição, tolerando o que a
  transcrição erra (acento, pontuação, uma palavra trocada);
- quando a linha foi gravada mais de uma vez, devolve TODAS as tomadas,
  ordenadas, em vez de escolher em silêncio;
- avisa a linha que não foi encontrada — a que ele esqueceu de gravar;
- avisa a fala que existe na transcrição e não está no roteiro — improviso,
  que pode ser ouro ou pode ser conversa fora.

O que ele NÃO faz, de propósito: escolher por você. A saída é proposta. A
regra do usuário para o Studio é explícita — revisão humana antes de o corte
técnico virar decisão editorial. Por isso `status` distingue `ok` de
`multiple`, e por isso a melhor candidata vem marcada mas as outras vêm junto.

Também não decide borda de corte: os tempos devolvidos são os da palavra
inicial e final do trecho. Quem manda em borda continua sendo o
`speech_regions.py`, como a Hard Rule 4 e 5 exigem.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

# Vícios que não contam para o casamento e pesam no desempate entre tomadas.
# Não é a lista do fillers.py: aqui só serve para ordenar candidatas.
FILLERS = {"e", "ne", "tipo", "assim", "entao", "hum", "ah", "eh", "uh", "ta"}
MIN_SCORE = 0.62
MIN_TOKENS = 2


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", " ", strip_accents(str(text).lower())).strip()


def tokenize(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t]


def script_lines(script: str) -> list[str]:
    """Uma linha por fala. Quebra em linha em branco e em fim de frase, porque
    roteiro vem dos dois jeitos e o usuário não deve ter que formatar."""
    out: list[str] = []
    for bloco in re.split(r"\n\s*\n|\n", str(script or "")):
        bloco = bloco.strip()
        if not bloco:
            continue
        for frase in re.split(r"(?<=[.!?])\s+", bloco):
            frase = frase.strip()
            if frase:
                out.append(frase)
    return out


def _score(a: list[str], b: list[str]) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _candidates(line_tokens: list[str], stream: list[dict], min_score: float) -> list[dict]:
    """Janela deslizante com peneira barata antes da medida cara.

    A peneira é interseção de conjuntos; só o que passa dela vai para o
    SequenceMatcher. Sem isso, um roteiro de 30 linhas contra uma transcrição
    de uma hora ficaria caro sem precisar.
    """
    n = len(line_tokens)
    alvo = set(line_tokens) - FILLERS
    if not alvo:
        alvo = set(line_tokens)
    largura = max(n, 3)
    brutos: list[tuple[float, int, int]] = []
    for i in range(len(stream)):
        # tenta encolher/esticar um pouco: a transcrição gagueja e o roteiro não
        melhor, melhor_fim = 0.0, 0
        for tamanho in dict.fromkeys((largura, largura + 2, max(2, largura - 2))):
            palavras = stream[i:i + tamanho]
            if len(palavras) < 2 or len({w["source"] for w in palavras}) != 1:
                continue
            trecho = [w["norm"] for w in palavras]
            if len(alvo & set(trecho)) / len(alvo) < 0.4:
                continue
            s = _score(line_tokens, trecho)
            if s > melhor:
                melhor, melhor_fim = s, len(palavras)
        if melhor >= min_score:
            brutos.append((melhor, i, i + melhor_fim))
    brutos.sort(key=lambda x: -x[0])
    escolhidos: list[dict] = []
    for s, ini, fim in brutos:
        if any(not (fim <= c["_i"] or ini >= c["_f"]) for c in escolhidos):
            continue  # já existe candidata melhor cobrindo esse trecho
        palavras = stream[ini:fim]
        if not palavras:
            continue
        escolhidos.append({
            "_i": ini, "_f": fim,
            "source": palavras[0].get("source"),
            "start": round(float(palavras[0]["start"]), 3),
            "end": round(float(palavras[-1]["end"]), 3),
            "score": round(s, 3),
            "text": " ".join(w["text"] for w in palavras),
            "fillers": sum(1 for w in palavras if w["norm"] in FILLERS),
        })
    # melhor pontuação primeiro; empate desempata por menos vício, depois mais cedo
    escolhidos.sort(key=lambda c: (-c["score"], c["fillers"], c["start"]))
    return escolhidos


def build_stream(sources: dict[str, list[dict]]) -> list[dict]:
    stream: list[dict] = []
    for source, words in sources.items():
        for w in words:
            text = str(w.get("text") or w.get("word") or "")
            norm = normalize(text)
            if not norm:
                continue
            stream.append({"source": source, "text": text, "norm": norm,
                           "start": float(w["start"]), "end": float(w["end"])})
    return stream


def align(script: str, sources: dict[str, list[dict]], min_score: float = MIN_SCORE) -> dict:
    stream = build_stream(sources)
    if not stream:
        raise ValueError("a transcrição está vazia")
    linhas = script_lines(script)
    if not linhas:
        raise ValueError("o roteiro está vazio")
    resultado, usados = [], []
    for i, linha in enumerate(linhas):
        tokens = tokenize(linha)
        if len(tokens) < MIN_TOKENS:
            resultado.append({"line": i, "text": linha, "status": "curta",
                              "why": "curta demais para alinhar com segurança", "candidates": []})
            continue
        cands = _candidates(tokens, stream, min_score)
        if not cands:
            resultado.append({"line": i, "text": linha, "status": "missing",
                              "why": "não achei essa fala na transcrição", "candidates": []})
            continue
        status = "multiple" if len(cands) > 1 else "ok"
        why = (f"gravada {len(cands)} vezes — escolha a tomada" if status == "multiple"
               else "uma tomada só")
        for c in cands:
            usados.append((c["_i"], c["_f"]))
        resultado.append({"line": i, "text": linha, "status": status, "why": why,
                          "candidates": [{k: v for k, v in c.items() if not k.startswith("_")}
                                         for c in cands]})
    # fala que está na transcrição e em nenhuma linha do roteiro
    cobertos = set()
    for ini, fim in usados:
        cobertos.update(range(ini, fim))
    extras, atual = [], []

    def flush_extra() -> None:
        nonlocal atual
        if len(atual) >= 6:
            extras.append({"source": stream[atual[0]]["source"],
                           "start": round(stream[atual[0]]["start"], 3),
                           "end": round(stream[atual[-1]]["end"], 3),
                           "text": " ".join(stream[j]["text"] for j in atual)})
        atual = []

    for i, w in enumerate(stream):
        if i in cobertos:
            flush_extra()
        else:
            if atual and stream[atual[-1]]["source"] != w["source"]:
                flush_extra()
            atual.append(i)
    flush_extra()
    resumo = {
        "lines": len(linhas),
        "ok": sum(1 for r in resultado if r["status"] == "ok"),
        "multiple": sum(1 for r in resultado if r["status"] == "multiple"),
        "missing": sum(1 for r in resultado if r["status"] == "missing"),
        "short": sum(1 for r in resultado if r["status"] == "curta"),
        "offScript": len(extras),
    }
    return {"version": 1, "summary": resumo, "lines": resultado, "offScript": extras,
            "note": "proposta: nenhuma tomada foi escolhida sozinha; bordas ainda "
                    "precisam de speech_regions.py"}


def draft_edl(alignment: dict, sources: dict[str, str]) -> dict:
    """EDL RASCUNHO com a melhor candidata de cada linha, na ordem do roteiro.

    Rascunho mesmo: as bordas são as palavras, sem a folga da regra 5 e sem
    validação acústica. Serve para ver a forma do vídeo, não para renderizar.
    """
    ranges = []
    for item in alignment["lines"]:
        if not item["candidates"]:
            continue
        best = item["candidates"][0]
        ranges.append({"source": best["source"], "start": best["start"], "end": best["end"],
                       "beat": f"L{item['line']}", "quote": best["text"],
                       "reason": f"roteiro linha {item['line']} (score {best['score']})"})
    return {"version": 1, "sources": sources, "grade": "", "ranges": ranges,
            "total_duration_s": round(sum(r["end"] - r["start"] for r in ranges), 3),
            "_draft": "bordas por palavra; valide com speech_regions.py antes de renderizar"}


def _load_words(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    words = data.get("words") if isinstance(data, dict) else data
    if not isinstance(words, list):
        raise ValueError(f"{path.name}: não encontrei lista de palavras")
    return [w for w in words if isinstance(w, dict) and "start" in w and "end" in w]


def main() -> None:
    ap = argparse.ArgumentParser(description="Alinha roteiro e transcrição, propõe tomadas")
    ap.add_argument("--script", type=Path, required=True)
    ap.add_argument("--transcript", type=Path, nargs="+", required=True,
                    help="um ou mais transcripts; o nome do arquivo vira o id da fonte")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    ap.add_argument("--json", type=Path, help="grava o alinhamento completo")
    args = ap.parse_args()

    sources = {p.stem: _load_words(p) for p in args.transcript}
    try:
        result = align(args.script.read_text(encoding="utf-8"), sources, args.min_score)
    except ValueError as e:
        print(f"✗ {e}")
        raise SystemExit(2)
    s = result["summary"]
    print(f"{s['lines']} linhas · {s['ok']} com tomada única · {s['multiple']} regravadas · "
          f"{s['missing']} NÃO encontradas · {s['short']} curtas · {s['offScript']} trechos fora do roteiro")
    for item in result["lines"]:
        if item["status"] in {"ok"}:
            continue
        marca = {"missing": "✗", "multiple": "»", "curta": "·"}[item["status"]]
        print(f"  {marca} linha {item['line']}: «{item['text'][:58]}» — {item['why']}")
        for c in item["candidates"]:
            print(f"      {c['source']} {c['start']:.2f}–{c['end']:.2f}s  score {c['score']}  "
                  f"vícios {c['fillers']}")
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\nalinhamento completo em {args.json}")
    raise SystemExit(1 if s["missing"] else 0)


if __name__ == "__main__":
    main()
