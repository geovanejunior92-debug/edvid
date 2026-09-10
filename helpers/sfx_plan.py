"""Monta o plano de efeitos sonoros de um vídeo e escreve em `sfxCues`.

Entra no fluxo DEPOIS do corte e ANTES da aba Estilo: a entrega pós-corte já sai
com corte, zoom, transições, flash **e som** (pedido do usuário, 2026-08-17).

O catálogo é a SOMA de dois pacotes — o antigo (whoosh, pop, clicks, tictac) e o
novo (typing, shutter, ui, riser, hit), este derivado da medição de uma
referência que ele mandou. Nada foi substituído; o leque só aumentou. As regras
de uso e os níveis estão em `references/sfx-catalogo.md`.

Este helper PROPÕE — ele acha os pontos óbvios a partir do EDL, das janelas de
tela dividida e do transcript. A escolha final é de quem edita: revise a lista,
troque o que não servir ao conteúdo, e só então renderize.

Uso:
    uv run python helpers/sfx_plan.py <edit-dir> [--dry-run] [--intensidade 1.0]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# nome → (arquivo, volume base, duração p/ a Sequence)
CATALOGO = {
    # pacote antigo — continuam valendo
    "whoosh":       ("whoosh.mp3",       0.45, 1.0),
    "pop":          ("pop.mp3",          0.35, 0.6),
    "click":        ("click.mp3",        0.35, 0.4),
    "cut-click":    ("cut-click.mp3",    0.85, 0.5),
    "tictac":       ("tictac.mp3",       0.30, 3.0),
    # pacote novo (2026-08-17)
    "typing":       ("typing.mp3",       0.55, 1.2),
    "key":          ("key.mp3",          0.40, 0.3),
    "shutter":      ("shutter.mp3",      0.50, 0.5),
    "ui-blip":      ("ui-blip.mp3",      0.28, 0.3),
    "ui-tap":       ("ui-tap.mp3",       0.24, 0.3),
    # "riser"/"riser-long" fora do catalogo desde 2026-08-20 (ver secao 3)
    "hit":          ("hit.mp3",          0.70, 2.0),
    "hit-soft":     ("hit-soft.mp3",     0.45, 1.1),
    "whoosh-long":  ("whoosh-long.mp3",  0.45, 1.1),
}

# Frases que pedem um acento sonoro. O gatilho é o SENTIDO, não a palavra solta:
# por isso a lista é de expressões, e o helper marca a posição da PRIMEIRA
# palavra da expressão.
GATILHOS_RISER = [
    r"\bmas\b", r"\bporém\b", r"\bo (?:mais )?(?:perigoso|importante|grave)\b",
    r"\be (?:o )?(?:terceiro|quarto|quinto)\b", r"\bpresta atenção\b",
    r"\bo que ninguém (?:te )?(?:conta|fala)\b", r"\bo problema\b",
]
GATILHOS_HIT = [
    r"\bé o chamado\b", r"\bnunca foi investigado\b", r"\bnão é (?:só|apenas)\b",
    r"\bo ideal\b", r"\ba verdade\b", r"\bé isso\b", r"\bresultado\b",
]
GATILHOS_UI = [r"\bolha\b", r"\bveja\b", r"\bassim\b", r"\bexemplo\b"]


def palavras(transcript: Path) -> list[tuple[float, float, str]]:
    d = json.loads(transcript.read_text())
    ws = d.get("words") or []
    out = []
    for w in ws:
        if w.get("type") not in (None, "word"):
            continue
        if "start" in w:
            out.append((float(w["start"]), float(w.get("end", w["start"])),
                        str(w.get("text") or w.get("word") or "").strip()))
    return out


def acha(frases: list[str], pal: list[tuple[float, float, str]]) -> list[float]:
    texto = " ".join(p[2] for p in pal).lower()
    # mapa de posição de caractere → índice da palavra
    pos, mapa = 0, []
    for i, p in enumerate(pal):
        mapa.append((pos, i))
        pos += len(p[2]) + 1
    achados = []
    for rx in frases:
        for m in re.finditer(rx, texto):
            idx = max((i for c, i in mapa if c <= m.start()), default=0)
            achados.append(pal[idx][0])
    return sorted(set(achados))


def main() -> None:
    ap = argparse.ArgumentParser(description="Propõe os efeitos sonoros da edição")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="só imprime, não grava")
    ap.add_argument("--intensidade", type=float, default=1.0,
                    help="multiplica todos os volumes (0.7 = discreto, 1.3 = marcado)")
    args = ap.parse_args()

    E = args.edit_dir
    data_p = E / "remotion/public/edit-data.json"
    d = json.loads(data_p.read_text())
    fim = float(d.get("durationSec") or 0)

    tr = E / "transcripts/cut.json"
    pal = palavras(tr) if tr.exists() else []

    cues: list[dict] = []

    def add(t: float, nome: str, motivo: str, mult: float = 1.0):
        if nome not in CATALOGO:
            return
        arq, vol, dur = CATALOGO[nome]
        if t < 0 or (fim and t > fim - 0.1):
            return
        # não empilhar dois efeitos no mesmo instante
        for c in cues:
            if abs(c["at"] - t) < 0.18:
                return
        # SÓ o nome do arquivo: o componente Sfx do template já prefixa `sfx/`.
        # Escrever "sfx/x.mp3" aqui vira "sfx/sfx/x.mp3" e o render morre com 404
        # no meio (pego em 2026-08-17, depois de 114 frames).
        cues.append({"at": round(t, 3), "src": arq,
                     "volume": round(min(0.95, vol * mult * args.intensidade), 3),
                     "dur": dur, "label": motivo})

    # 1. As transições JÁ tocam um som (o clique do flash). Aqui não se empilha
    #    um segundo efeito em cima — troca-se o que já existe, que é o pedido
    #    dele: complementar onde falta, não dobrar onde já tem.
    #    Entrada de janela = corte rápido → shutter. Saída = whoosh.
    trocadas = 0
    for tr_ in d.get("transitions") or []:
        alvo = "shutter.mp3" if tr_.get("variant", "corte") == "corte" else "whoosh.mp3"
        if tr_.get("sfx") != alvo:
            tr_["sfx"] = alvo
            tr_["volume"] = 0.75 if alvo == "shutter.mp3" else 0.5
            trocadas += 1

    janelas = d.get("splitInserts") or []

    # 2. WHOOSH-REV BANIDO (2026-09-03, pedido do usuário): ele ouviu o efeito na
    # saída da capa e mandou tirar e não usar mais — em nenhum vídeo. O motivo
    # bate com a regra dele de que todo efeito precisa cair num flash ou num
    # corte: a capa apenas some, não há evento visual para o som acompanhar.
    # Não reintroduzir, nem aqui nem em outro gatilho. Mesmo status do riser.

    # 3. Tensão e revelação, a partir da fala
    # RISER REMOVIDO (2026-08-20, pedido do usuário): ele ouviu o riser aos 13s
    # de um vídeo e mandou tirar e nao usar mais. Nenhuma variante (riser,
    # riser-long, riser-deep) entra automaticamente. Nao reintroduzir.
    for t in acha(GATILHOS_HIT, pal):
        add(t, "hit-soft", "acento na revelação")
    for t in acha(GATILHOS_UI, pal):
        add(t, "ui-blip", "acento de interface", 0.9)

    # 4. O HIT grande é UM por vídeo: a frase mais forte, perto do fecho.
    #    Sem candidato claro, fica no último terço, no começo de uma frase.
    alvos = [t for t in acha(GATILHOS_HIT, pal) if fim * 0.6 <= t <= fim * 0.95]
    if alvos:
        t = alvos[-1]
        cues[:] = [c for c in cues if abs(c["at"] - t) > 0.3]
        add(t, "hit", "HIT principal — a virada do vídeo", 1.0)

    # 5. Encerramento da marca
    outro = d.get("outro") or {}
    if outro.get("enabled"):
        add(float(outro["startSec"]) - 0.1, "whoosh-long", "entra a tela final", 0.8)

    cues.sort(key=lambda c: c["at"])

    print(f"{trocadas} transições ganharam som próprio (shutter na entrada, whoosh na saída)")
    print(f"{len(cues)} efeitos NOVOS, em pontos que ainda não tinham som\n")
    print(f"{'tempo':>7}  {'efeito':<16} {'vol':>5}  motivo")
    for c in cues:
        print(f"{c['at']:7.2f}  {Path(c['src']).stem:<16} {c['volume']:5.2f}  {c['label']}")

    faltando = [c["src"] for c in cues
                if not (E / "remotion/public/sfx" / c["src"]).exists()]
    if faltando:
        print("\nARQUIVOS AUSENTES em public/sfx (rode generate_sfx_extra.py no projeto):")
        for f in sorted(set(faltando)):
            print(f"  {f}")

    if args.dry_run:
        print("\n--dry-run: nada foi gravado")
        return
    d["sfxCues"] = cues
    data_p.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    print(f"\ngravado em {data_p} (sfxCues)")


if __name__ == "__main__":
    main()
