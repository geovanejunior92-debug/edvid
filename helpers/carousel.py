#!/usr/bin/env python3
"""De um corte aprovado para um esboco de carrossel. Propoe; quem decide e voce.

O MESMO ESPIRITO DO `clipper.py`: pontua e LISTA, nunca escolhe sozinho. A
escolha de qual argumento vira slide e editorial, e o helper que finge decidir
isso entrega carrossel generico.

DE ONDE VEM O CONTEUDO. Do transcript do proprio corte (`transcripts/cut.json`),
nao da fonte bruta: o que sobreviveu ao corte ja passou pelo seu julgamento uma
vez. Cada frase recebe nota por densidade, numero, pergunta, contraste e "voce" —
as mesmas heuristicas que o `retention.py` usa para gancho, porque gancho de
Reel e gancho de carrossel sao o mesmo problema.

O QUADRO DE FUNDO NAO E CHUTADO. Para cada slide escolhido, o instante sugerido
e o da propria frase no corte, entao a foto do slide mostra voce falando aquilo.

SAIDA: um `post-data.json` pronto para o `post_render.py`, com a marcacao
`"_nota"` em cada slide dizendo por que ele foi proposto. Leia, corte o que nao
presta, reescreva o texto, e so entao renderize.

USO
  uv run python helpers/carousel.py <edit>/transcripts/cut.json --video cut.mp4 [--slides 6]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PARADA = {"que", "de", "e", "o", "a", "um", "uma", "para", "com", "em", "no", "na",
          "os", "as", "do", "da", "dos", "das", "por", "se", "mas", "ou", "ai",
          "aqui", "entao", "ne", "tá", "ta", "voce", "você", "eu", "isso", "aí"}


def frases(j: dict) -> list[dict]:
    """Frases do corte, quebrando na PONTUACAO — nao no silencio.

    MEDIDO 2026-09-10, e e o ponto que quase me fez entregar lixo: num corte
    aprovado os silencios JA FORAM REMOVIDOS — e para isso que serve a Fase 1.
    Num `cut.mp4` de 53 s havia UMA unica pausa >= 0,5 s. Quebrar por silencio,
    como faz o `pack_transcripts.py` na fonte BRUTA, devolvia 2 frases para o
    video inteiro e o carrossel saia com dois slides gigantes.

    Depois do corte, a fronteira que sobrou e a da lingua: ponto, interrogacao,
    exclamacao. O silencio entra so como desempate, com limiar baixo (0,28 s),
    para o caso de fala sem pontuacao no transcript.
    """
    palavras = [w for w in j.get("words", []) if w.get("type") == "word"]
    lacuna = {}
    for i, w in enumerate(j.get("words", [])):
        if w.get("type") == "spacing":
            lacuna[w.get("start")] = w.get("end", 0) - w.get("start", 0)

    out, atual = [], []
    for i, w in enumerate(palavras):
        atual.append(w)
        termina = bool(re.search(r"[.!?…]\"?$", w.get("text", "").strip()))
        pausa = lacuna.get(w.get("end"), 0) >= 0.28
        if (termina or pausa) and len(atual) >= 3:
            out.append(atual)
            atual = []
    if atual:
        out.append(atual)
    return [{"texto": " ".join(x["text"] for x in g),
             "inicio": g[0]["start"], "fim": g[-1]["end"]} for g in out if g]


def nota(f: dict) -> tuple[float, list[str]]:
    t = f["texto"]
    baixo = t.lower()
    pal = [p for p in re.findall(r"[\wÀ-ÿ]+", baixo) if p not in PARADA]
    n, por = 0.0, []
    dur = max(0.1, f["fim"] - f["inicio"])
    dens = len(pal) / dur
    if dens > 1.8:
        n += 2; por.append("densa")
    if re.search(r"\d", t):
        n += 2; por.append("numero")
    if "?" in t:
        n += 2; por.append("pergunta")
    if re.search(r"\bvoc[êe]\b|\bseu\b|\bsua\b", baixo):
        n += 1.5; por.append("fala com o leitor")
    if re.search(r"\bmas\b|\bporém\b|\bna verdade\b|\berrad[oa]\b|\bnão é\b", baixo):
        n += 2; por.append("contraste")
    if re.search(r"\bnunca\b|\bsempre\b|\bninguém\b|\bmaioria\b", baixo):
        n += 1.5; por.append("afirmacao forte")
    if 6 <= len(pal) <= 22:
        n += 1; por.append("tamanho de slide")
    else:
        por.append("longa demais para slide" if len(pal) > 22 else "curta demais")
    return n, por


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--video", default="cut.mp4", help="nome do video na pasta do post")
    ap.add_argument("--slides", type=int, default=6, help="miolo, sem contar capa e CTA")
    ap.add_argument("--formatos", nargs="*", default=["4x5"])
    ap.add_argument("-o", "--out", type=Path, default=None)
    a = ap.parse_args()

    if not a.transcript.is_file():
        print(f"nao achei {a.transcript}", file=sys.stderr)
        return 1
    j = json.loads(a.transcript.read_text(encoding="utf-8"))
    fs = frases(j)
    if not fs:
        print("transcript sem frases utilizaveis", file=sys.stderr)
        return 1
    for f in fs:
        f["nota"], f["por"] = nota(f)

    ordenadas = sorted(fs, key=lambda x: -x["nota"])
    gancho = ordenadas[0]
    miolo = sorted([f for f in ordenadas[1:a.slides + 1]], key=lambda x: x["inicio"])

    print(f"{len(fs)} frases no corte. Propostas (nota / instante / motivo):\n")
    print(f"  CAPA   {gancho['nota']:.1f}  {gancho['inicio']:6.1f}s  {gancho['texto'][:60]}")
    print(f"         └─ {', '.join(gancho['por'])}")
    for f in miolo:
        print(f"  slide  {f['nota']:.1f}  {f['inicio']:6.1f}s  {f['texto'][:60]}")
        print(f"         └─ {', '.join(f['por'])}")

    slides = [{"tipo": "capa", "titulo": gancho["texto"], "_nota": ", ".join(gancho["por"]),
               "fundo": {"video": a.video, "at": round(gancho["inicio"] + 0.4, 2)}}]
    for f in miolo:
        slides.append({"tipo": "texto", "titulo": f["texto"], "_nota": ", ".join(f["por"])})
    slides.append({"tipo": "cta", "titulo": "ESCREVA O SEU FECHO AQUI",
                   "corpo": "", "_nota": "placeholder — o CTA e seu, nao meu"})

    dados = {"projeto": a.transcript.parent.parent.name,
             "formatos": a.formatos, "slides": slides}
    out = a.out or (a.transcript.parent.parent / "post-data.json")
    out.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nesboco em {out}")
    print("LEIA ANTES DE RENDERIZAR: o texto e fala transcrita, nao copy. Reescreva")
    print("cada slide na sua voz, apague o que nao presta, e escreva o CTA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
