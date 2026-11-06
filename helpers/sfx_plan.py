"""Monta o plano de efeitos sonoros de um vídeo, sem nunca apagar efeito manual.

Os efeitos moram em `<edit>/sfx_cues.json` e só depois são fundidos em `sfxCues`
no `edit-data.json`. Cada cue tem origem: `auto` (deste helper, refeita a cada
execução) ou `manual` (preservada sempre).

- Sem `edit-data.json` o helper também roda: lê a transcrição e a duração do EDL
  e grava o arquivo próprio. Transições e encerramento só existem depois do
  preset, então rode de novo com o `edit-data.json` pronto: é isso que funde.
- Cue novo posto à mão: acrescente em `sfx_cues.json` com `"origin": "manual"`,
  ou em `sfxCues` sem `origin`, que a próxima execução adota como manual. Para
  tirar ou mover um cue manual, edite `sfx_cues.json`: o `sfxCues` é só a fusão.
- Sem o arquivo próprio (projeto antigo), os cues de `sfxCues` são adotados como
  manuais, exceto os que levam um rótulo gerado por versão anterior deste helper.

O catálogo está em `references/sfx-catalogo.md`, com regras e níveis. Riser e
whoosh-rev são banidos: nenhum gatilho aqui os propõe. A transição que leva à
tela azul fica reservada ao encerramento: só o `outro-swell` soa ali.

Este helper PROPÕE. A escolha final é de quem edita: revise a lista e troque o
que não servir ao conteúdo antes de renderizar.

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
    "outro-swell":  ("outro-swell.mp3",  0.60, 1.0),
}

CUES_FILE = "sfx_cues.json"
AUTO, MANUAL = "auto", "manual"
# O swell entra NA transição que leva à tela azul, nunca antes dela.
SWELL_ANTES_S = 0.2
# Uma transição a até esta distância do ponto do swell é a de encerramento.
TRANSICAO_FINAL_S = 0.6
# Rótulos que versões anteriores deste helper gravavam em `sfxCues`, sem origem.
ROTULOS_ANTIGOS = {"acento na revelação", "acento de interface",
                   "HIT principal — a virada do vídeo", "entra a tela final"}

# Frases que pedem um acento sonoro. O gatilho é o SENTIDO, não a palavra solta:
# por isso a lista é de expressões, e o helper marca a posição da PRIMEIRA
# palavra da expressão.
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


def _le_json(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.is_file() else None


def _mesmo_cue(a: dict, b: dict) -> bool:
    return a.get("src") == b.get("src") and abs(float(a["at"]) - float(b["at"])) < 0.01


def cues_manuais(guardados: dict | None, edit_data: dict | None) -> list[dict]:
    """Os cues que a execução não pode tocar. Ver a regra no topo do arquivo."""
    fundidos = list((edit_data or {}).get("sfxCues") or [])
    if guardados is None:
        manuais = [c for c in fundidos
                   if c.get("origin") != AUTO and c.get("label") not in ROTULOS_ANTIGOS]
    else:
        manuais = [c for c in guardados.get("cues") or [] if c.get("origin") == MANUAL]
        for c in fundidos:
            if "origin" not in c and not any(_mesmo_cue(c, m) for m in manuais):
                manuais.append(c)
    return [{**c, "origin": MANUAL} for c in manuais]


def duracao_do_corte(edit: Path, edit_data: dict | None, pal: list) -> float:
    fim = float((edit_data or {}).get("durationSec") or 0)
    if not fim:
        edl = _le_json(edit / "edl.json") or {}
        fim = float(edl.get("total_duration_s") or 0)
    return fim or (pal[-1][1] if pal else 0.0)


def transicao_de_encerramento(edit_data: dict) -> tuple[float | None, dict | None]:
    """(instante do swell, transição reservada). Sem tela final, (None, None)."""
    outro = edit_data.get("outro") or {}
    if not outro.get("enabled") or outro.get("startSec") is None:
        return None, None
    alvo = float(outro["startSec"]) - SWELL_ANTES_S
    perto = [t for t in edit_data.get("transitions") or []
             if abs(float(t.get("at", 0)) - alvo) <= TRANSICAO_FINAL_S]
    if not perto:
        return alvo, None
    final = min(perto, key=lambda t: abs(float(t["at"]) - alvo))
    return float(final["at"]), final


def planejar_transicoes(edit_data: dict, reservada: dict | None) -> int:
    """Dá som às transições: troca o que já soa em vez de empilhar um segundo efeito.

    Entrada de janela = corte rápido → shutter. Saída = whoosh. Som escolhido à
    mão fica como está; os dois valores que este helper propõe são dele.
    """
    trocadas = 0
    for t in edit_data.get("transitions") or []:
        if t is reservada:
            # volume 0 porque o template toca um som padrão quando falta `sfx`.
            t.pop("sfx", None)
            t["volume"] = 0
            continue
        alvo = "shutter.mp3" if t.get("variant", "corte") == "corte" else "whoosh.mp3"
        atual = t.get("sfx")
        if atual and atual not in ("shutter.mp3", "whoosh.mp3"):
            continue
        if atual != alvo:
            t["sfx"] = alvo
            t["volume"] = 0.75 if alvo == "shutter.mp3" else 0.5
            trocadas += 1
    return trocadas


def planejar_cues(pal: list, fim: float, manuais: list[dict], swell_em: float | None,
                  intensidade: float = 1.0) -> list[dict]:
    """Só as automáticas. Ponto já ocupado por cue manual ou pelo swell fica livre."""
    cues: list[dict] = []
    swell = CATALOGO["outro-swell"][0]

    def add(t: float, nome: str, motivo: str, mult: float = 1.0) -> None:
        arq, vol, dur = CATALOGO[nome]
        if t < 0 or (fim and t > fim - 0.1):
            return
        # não empilhar dois efeitos no mesmo instante
        for c in cues + manuais:
            if abs(float(c["at"]) - t) < 0.18:
                return
        # SÓ o nome do arquivo: o componente Sfx do template já prefixa `sfx/`.
        # Escrever "sfx/x.mp3" aqui vira "sfx/sfx/x.mp3" e o render morre com 404
        # no meio (pego em 2026-08-17, depois de 114 frames).
        cues.append({"at": round(t, 3), "src": arq,
                     "volume": round(min(0.95, vol * mult * intensidade), 3),
                     "dur": dur, "label": motivo, "origin": AUTO})

    # Primeiro o encerramento: nenhum acento da fala pode tomar o lugar dele.
    if swell_em is not None and not any(c.get("src") == swell for c in manuais):
        add(swell_em, "outro-swell", "encerramento, na transição para a tela final")

    # WHOOSH-REV BANIDO (2026-09-03) e RISER BANIDO (2026-08-20), pedidos do
    # usuário: nenhuma variante entra aqui, nem com outro nome ou outro gatilho.
    for t in acha(GATILHOS_HIT, pal):
        add(t, "hit-soft", "acento na revelação")
    for t in acha(GATILHOS_UI, pal):
        add(t, "ui-blip", "acento de interface", 0.9)

    # O HIT grande é UM por vídeo: a frase mais forte, perto do fecho.
    alvos = [t for t in acha(GATILHOS_HIT, pal) if fim * 0.6 <= t <= fim * 0.95]
    if alvos:
        t = alvos[-1]
        cues[:] = [c for c in cues if abs(c["at"] - t) > 0.3 or c["src"] == swell]
        add(t, "hit", "HIT principal — a virada do vídeo", 1.0)
    return cues


def main() -> None:
    ap = argparse.ArgumentParser(description="Propõe os efeitos sonoros da edição")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="só imprime, não grava")
    ap.add_argument("--intensidade", type=float, default=1.0,
                    help="multiplica os volumes (0.7 = discreto, 1.3 = marcado)")
    args = ap.parse_args()

    edit = args.edit_dir
    data_p = edit / "remotion/public/edit-data.json"
    cues_p = edit / CUES_FILE
    edit_data = _le_json(data_p)
    tr = edit / "transcripts/cut.json"
    pal = palavras(tr) if tr.exists() else []
    fim = duracao_do_corte(edit, edit_data, pal)

    manuais = cues_manuais(_le_json(cues_p), edit_data)
    swell_em, reservada = transicao_de_encerramento(edit_data) if edit_data else (None, None)
    trocadas = planejar_transicoes(edit_data, reservada) if edit_data else 0
    automaticas = planejar_cues(pal, fim, manuais, swell_em, args.intensidade)
    cues = sorted(manuais + automaticas, key=lambda c: float(c["at"]))

    if edit_data:
        print(f"{trocadas} transições ganharam som próprio (shutter na entrada, whoosh na saída)")
    print(f"{len(automaticas)} efeitos automáticos e {len(manuais)} manuais preservados\n")
    print(f"{'tempo':>7}  {'efeito':<16} {'vol':>5}  {'origem':<7} motivo")
    for c in cues:
        print(f"{float(c['at']):7.2f}  {Path(c['src']).stem:<16} {float(c.get('volume', 0)):5.2f}  "
              f"{c['origin']:<7} {c.get('label', '')}")

    sfx_dir = edit / "remotion/public/sfx"
    faltando = [c["src"] for c in cues if sfx_dir.is_dir() and not (sfx_dir / c["src"]).exists()]
    if faltando:
        print("\nARQUIVOS AUSENTES em public/sfx (rode generate_sfx_extra.py no projeto):")
        for f in sorted(set(faltando)):
            print(f"  {f}")

    if args.dry_run:
        print("\n--dry-run: nada foi gravado")
        return
    cues_p.write_text(json.dumps({"cues": cues}, indent=2, ensure_ascii=False))
    print(f"\ngravado em {cues_p}")
    if edit_data is None:
        print("sem edit-data.json: transições e encerramento ficam para depois do preset; "
              "rode este helper de novo para fundir em sfxCues")
        return
    edit_data["sfxCues"] = cues
    data_p.write_text(json.dumps(edit_data, indent=2, ensure_ascii=False))
    print(f"fundido em {data_p} (sfxCues)")


if __name__ == "__main__":
    main()
