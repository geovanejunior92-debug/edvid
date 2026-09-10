"""B-roll sugerido pelo transcript, do acervo local, com o ledger reconciliado.

Para cada frase do corte, procura no acervo (`~/Videos/stock-medico`, pastas
nomeadas por tema) os clipes cujo nome de pasta ou de arquivo compartilha
palavras com a frase, e traz até 5 opções ranqueadas. Frases sem cobertura
viram a lista de compras — já cruzada com o PEDIDOS.md, para não pedir de
novo o que já foi pedido (observação 6: pedido feito nunca era reconciliado).

Antes de qualquer pedido novo, reconcilia o ledger: cada item em aberto
`- [ ]` do PEDIDOS.md que tenha material correspondente no acervo é listado
como "chegou" (e marcado `[x]` com --apply-ledger). Quem marca é o agente,
nunca o usuário — regra dele.

Usage:
    uv run python helpers/broll_suggest.py <edit>/edl.json
    uv run python helpers/broll_suggest.py edl.json --acervo ~/Videos/stock-medico --top 5
    uv run python helpers/broll_suggest.py edl.json --apply-ledger

Escreve <edit>/broll_suggest.md (tabela por frase) e imprime o resumo. É
sugestão por palavra, não por sentido: o acerto é bom quando a pasta do
acervo tem o tema no nome, e ruim quando o clipe se chama pelo ID.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png"}
STOP = set("""a o os as um uma uns umas de do da dos das em no na nos nas por para pra com sem sobre
que quem qual quais como quando onde porque por isso isto esse essa este esta aquele aquela ele ela eles elas
eu tu você vocês nós me te se lhe nosso nossa seu sua meu minha
e ou mas nem também já ainda só mais menos muito muita muitos muitas pouco pouca tudo nada algo cada todo toda todos todas
é ser está estão estava foi era são sou tem têm tinha ter há vai vou ir fazer faz fez pode podem
não sim aqui ali lá agora hoje ontem amanhã então assim depois antes sempre nunca bem mal
gente pessoa pessoas coisa coisas ano anos dia dias vez vezes né tipo olha vamos""".split())


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def tokens(s: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-zà-ú0-9]+", fold(s)):
        if len(w) >= 4 and w not in STOP and not w.isdigit():
            out.add(w[:6])  # radical curto: "hormonio" ~ "hormonal"
    return out


def load_words(edit_dir: Path, stem: str) -> list[dict]:
    p = edit_dir / "transcripts" / f"{stem}.json"
    if not p.exists():
        return []
    out = []
    for w in json.loads(p.read_text()).get("words") or []:
        if w.get("type", "word") == "word":
            try:
                out.append({"word": (w.get("text") or w.get("word") or "").strip(),
                            "start": float(w["start"]), "end": float(w["end"])})
            except (KeyError, TypeError, ValueError):
                pass
    return out


def phrases_on_cut(edl: dict, edit_dir: Path) -> list[dict]:
    """Frases (pausa ≥ 0,5 s / pontuação) já na linha do tempo do CORTE."""
    out, offset = [], 0.0
    for r in edl["ranges"]:
        src = Path(edl["sources"][r["source"]]).expanduser()
        words = [w for w in load_words(edit_dir, src.stem)
                 if w["start"] >= float(r["start"]) and w["end"] <= float(r["end"])]
        cur = []
        def flush():
            if cur:
                out.append({"start": round(offset + cur[0]["start"] - float(r["start"]), 2),
                            "end": round(offset + cur[-1]["end"] - float(r["start"]), 2),
                            "text": " ".join(w["word"] for w in cur), "beat": r.get("beat")})
        for w in words:
            if cur and w["start"] - cur[-1]["end"] >= 0.5:
                flush(); cur = []
            cur.append(w)
            if re.search(r"[.!?…]$", w["word"]):
                flush(); cur = []
        flush()
        offset += float(r["end"]) - float(r["start"])
    return out


def index_acervo(root: Path) -> list[dict]:
    items = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXT or "_licencas" in p.parts:
            continue
        rel = p.relative_to(root)
        folder = " ".join(rel.parts[:-1])
        toks = tokens(folder) | tokens(p.stem)
        items.append({"path": str(rel), "folder": folder, "tokens": toks})
    return items


def rank(phrase_tokens: set[str], acervo: list[dict], top: int) -> list[tuple[float, dict]]:
    scored = []
    for it in acervo:
        common = phrase_tokens & it["tokens"]
        if not common:
            continue
        s = len(common) + 0.5 * len(common & tokens(it["folder"]))
        scored.append((s, it))
    scored.sort(key=lambda x: (-x[0], x[1]["path"]))
    # uma opção por pasta primeiro, depois completa
    seen, out = set(), []
    for s, it in scored:
        if it["folder"] in seen:
            continue
        seen.add(it["folder"]); out.append((s, it))
        if len(out) >= top:
            break
    if len(out) < top:
        for s, it in scored:
            if (s, it) not in out and len(out) < top:
                out.append((s, it))
    return out


def reconcile_ledger(ledger: Path, acervo: list[dict], apply: bool) -> list[str]:
    if not ledger.exists():
        return []
    text = ledger.read_text()
    arrived = []
    new_lines = []
    for line in text.splitlines():
        m = re.match(r"^(\s*-\s*)\[ \](\s*)(.*)$", line)
        if m:
            need = tokens(m.group(3).split("→")[0])
            hit = [it for it in acervo if len(need & it["tokens"]) >= max(1, min(2, len(need)))]
            if hit:
                arrived.append(f"{m.group(3).strip()}  ← {hit[0]['path']}")
                if apply:
                    line = f"{m.group(1)}[x]{m.group(2)}{m.group(3)}"
        new_lines.append(line)
    if apply and arrived:
        ledger.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""))
    return arrived


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edl", type=Path)
    ap.add_argument("--acervo", type=Path, default=Path.home() / "Videos" / "stock-medico")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--apply-ledger", action="store_true")
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    edl = json.loads(edl_path.read_text())
    edit_dir = edl_path.parent
    acervo = index_acervo(args.acervo.expanduser())
    ph = phrases_on_cut(edl, edit_dir)
    if not ph:
        raise SystemExit("sem frases: transcreva as fontes antes")

    lines = [f"# B-roll sugerido — {edit_dir.parent.name}", "",
             f"Acervo: {args.acervo} ({len(acervo)} arquivos). Sugestão por palavra; você julga.", "",
             "| t | frase | opções |", "|---|---|---|"]
    uncovered = []
    for p in ph:
        opts = rank(tokens(p["text"]), acervo, args.top)
        cell = "<br>".join(f"{s:.1f} `{it['path']}`" for s, it in opts) if opts else "—"
        lines.append(f"| {p['start']:.1f}–{p['end']:.1f} | {p['text'][:90]} | {cell} |")
        if not opts:
            uncovered.append(p)
    arrived = reconcile_ledger(args.acervo.expanduser() / "PEDIDOS.md", acervo, args.apply_ledger)
    if arrived:
        lines += ["", "## Ledger: pedidos que já chegaram ao acervo"] + [f"- {a}" for a in arrived]
    if uncovered:
        lines += ["", "## Sem cobertura no acervo (candidatas à lista de compras)"]
        lines += [f"- {p['start']:.1f}s «{p['text'][:100]}»" for p in uncovered]
    (edit_dir / "broll_suggest.md").write_text("\n".join(lines) + "\n")

    covered = len(ph) - len(uncovered)
    print(f"broll_suggest: {len(ph)} frases, {covered} com opção no acervo, {len(uncovered)} sem → {edit_dir / 'broll_suggest.md'}")
    for p in ph[:40]:
        opts = rank(tokens(p["text"]), acervo, 2)
        if opts:
            print(f"  {p['start']:6.1f}s «{p['text'][:60]}» → {opts[0][1]['folder'][:40]}")
    if arrived:
        print(f"  ledger: {len(arrived)} pedido(s) em aberto já têm material no acervo" + (" (marcados)" if args.apply_ledger else " (--apply-ledger marca)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
