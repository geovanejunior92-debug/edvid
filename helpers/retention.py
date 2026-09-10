"""Inteligência de retenção: gancho, ritmo, ar morto, fechamento — em número.

Nenhum editor de vídeo faz isto, porque nenhum lê o que está sendo dito. O
edvid lê. Este helper transforma o transcript do CORTE (ou dos takes do EDL)
nas quatro coisas que decidem se um Reel segura:

  gancho     os primeiros 3 s: quantas palavras, se há número, pergunta,
             "você", contraste ("não/nunca/pare/erro"), e quanto de ar morto
             antes da primeira palavra. Score 0–10 com o porquê.
  ritmo      palavras por segundo em janelas de 5 s contra a mediana do
             próprio vídeo: janela abaixo de 60% é arrasto; % de silêncio
             por janela; a pausa mais longa. Onde o vídeo "afunda".
  ar morto   silêncio acumulado sem fala em relação ao total.
  fechamento o último 1,5 s tem fala? Há chamada para ação ("comenta",
             "segue", "salva", "compartilha", "manda", "marca")? Termina em
             frase completa ou no meio?

Com `--candidates <source.json>` também procura, no transcript da FONTE,
frases candidatas a gancho (número, pergunta, contraste, "você") nos primeiros
`--window` segundos de material — variantes de abertura para o agente julgar
e propor. Ele lista e pontua; quem escolhe é quem tem gosto.

Usage:
    uv run python helpers/retention.py <edit>/transcripts/cut.json
    uv run python helpers/retention.py cut.json --candidates <edit>/transcripts/<fonte>.json
    uv run python helpers/retention.py cut.json --json

Aprendizado com o que performou: quando o Metricool devolver retenção por
Reel, este relatório é o que se cruza com ela. Sem esse dado, é heurística
calibrada em manual de retenção, não no seu público — diga isso ao usar.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

HOOK_S = 3.0
WINDOW_S = 5.0
CTA = re.compile(r"\b(coment[ae]|segue|seguir|salva|salve|compartilh|manda|mande|marca|marque|"
                 r"link|bio|clica|clique|inscreva|responde|me conta|me diz)", re.I)
CONTRAST = re.compile(r"\b(n[aã]o|nunca|pare|para de|erro|errado|mentira|mito|ningu[eé]m|cuidado|"
                      r"perigo|jamais|esquece|verdade)\b", re.I)
YOU = re.compile(r"\b(voc[eê]|seu|sua|te|tu)\b", re.I)
NUMBER = re.compile(r"\b(\d+|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|"
                    r"metade|dobro|por cento|%)\b", re.I)


def load_words(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    out = []
    for w in data.get("words") or []:
        if w.get("type", "word") != "word":
            continue
        try:
            out.append({"word": (w.get("text") or w.get("word") or "").strip(),
                        "start": float(w["start"]), "end": float(w["end"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def phrases(words: list[dict], gap: float = 0.5, split_punct: bool = False) -> list[dict]:
    """Frases por pausa ≥ gap; com split_punct também fecha em . ! ? — para
    candidatas a gancho, senão um take fluente vira uma 'frase' de 30 s."""
    out, cur = [], []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] >= gap:
            out.append(cur); cur = []
        cur.append(w)
        if split_punct and re.search(r"[.!?…]$", w["word"]):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return [{"start": p[0]["start"], "end": p[-1]["end"], "text": " ".join(w["word"] for w in p),
             "n": len(p)} for p in out]


def hook_score(words: list[dict]) -> dict:
    first = [w for w in words if w["start"] < HOOK_S]
    text = " ".join(w["word"] for w in first)
    lead = words[0]["start"] if words else HOOK_S
    reasons, score = [], 0.0
    if first:
        n = len(first)
        if n >= 7:
            score += 3; reasons.append(f"{n} palavras nos 3 s (denso)")
        elif n >= 4:
            score += 1.5; reasons.append(f"{n} palavras nos 3 s")
        else:
            reasons.append(f"só {n} palavra(s) nos 3 s")
    if lead > 0.6:
        score -= 2; reasons.append(f"{lead:.1f} s de ar morto antes da primeira palavra")
    elif lead <= 0.25:
        score += 1; reasons.append("fala já no primeiro quarto de segundo")
    if NUMBER.search(text):
        score += 1.5; reasons.append("tem número")
    if "?" in text or re.search(r"\b(como|por que|porque|qual|quando|será)\b", text, re.I):
        score += 1.5; reasons.append("pergunta ou 'como/por que'")
    if YOU.search(text):
        score += 1; reasons.append("fala com 'você'")
    if CONTRAST.search(text):
        score += 1.5; reasons.append("contraste/negação")
    ph = phrases(words)
    if ph and ph[0]["end"] <= HOOK_S + 0.3:
        score += 0.5; reasons.append("primeira frase fecha dentro do gancho")
    return {"score": round(max(0.0, min(10.0, score)), 1), "text": text, "lead_s": round(lead, 2),
            "reasons": reasons}


def pacing(words: list[dict], total: float) -> dict:
    if not words:
        return {}
    edges = np.arange(0, total + WINDOW_S, WINDOW_S)
    wins = []
    for a in edges[:-1]:
        b = min(a + WINDOW_S, total)
        if b - a < 1.5:
            continue
        ws = [w for w in words if a <= w["start"] < b]
        spoken = sum(min(w["end"], b) - max(w["start"], a) for w in words if w["end"] > a and w["start"] < b)
        wins.append({"start": round(float(a), 1), "end": round(float(b), 1), "wps": round(len(ws) / (b - a), 2),
                     "silence_pct": round(100 * (1 - spoken / (b - a)), 0)})
    med = float(np.median([w["wps"] for w in wins])) if wins else 0
    drags = [w for w in wins if med and w["wps"] < 0.6 * med]
    quiet = [w for w in wins if w["silence_pct"] >= 35]
    gaps = [(words[i + 1]["start"] - words[i]["end"], words[i]["end"]) for i in range(len(words) - 1)]
    longest = max(gaps, default=(0, 0))
    return {"median_wps": round(med, 2), "windows": wins, "drags": drags, "quiet": quiet,
            "longest_pause": {"s": round(longest[0], 2), "at": round(longest[1], 2)}}


def ending(words: list[dict], total: float) -> dict:
    last = words[-1] if words else None
    tail_speech = bool(last and total - last["end"] <= 1.5)
    text_last = " ".join(w["word"] for w in words if w["start"] >= total - 8)
    cta = CTA.search(text_last)
    ph = phrases(words)
    complete = bool(ph and re.search(r"[.!?…]$", ph[-1]["text"].strip()))
    return {"speech_to_end": tail_speech, "tail_silence_s": round(total - last["end"], 2) if last else None,
            "cta": cta.group(0) if cta else None, "last_phrase": ph[-1]["text"][-80:] if ph else "",
            "complete": complete}


def candidates(source_words: list[dict], window: float) -> list[dict]:
    out = []
    for p in phrases(source_words, split_punct=True):
        if p["start"] > window or p["n"] < 4 or p["end"] - p["start"] > 8:
            continue
        s, why = 0.0, []
        if NUMBER.search(p["text"]): s += 1.5; why.append("número")
        if "?" in p["text"] or re.search(r"\b(como|por que|porque|qual|quando)\b", p["text"], re.I):
            s += 1.5; why.append("pergunta")
        if YOU.search(p["text"]): s += 1; why.append("você")
        if CONTRAST.search(p["text"]): s += 1.5; why.append("contraste")
        dur = p["end"] - p["start"]
        if 1.5 <= dur <= 4.5: s += 1; why.append("cabe em 3 s")
        if s >= 2:
            out.append({"start": round(p["start"], 2), "end": round(p["end"], 2), "score": s,
                        "why": why, "text": p["text"][:110]})
    return sorted(out, key=lambda c: -c["score"])[:6]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("transcript", type=Path, help="transcript do corte (transcripts/cut.json)")
    ap.add_argument("--duration", type=float, default=None, help="duração do corte (padrão: última palavra + 0,5)")
    ap.add_argument("--candidates", type=Path, default=None, help="transcript da FONTE para variantes de gancho")
    ap.add_argument("--window", type=float, default=90.0, help="segundos iniciais da fonte a vasculhar")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ledger", type=Path, default=None,
                    help="JSONL global (ex. ~/Videos/retencao.jsonl): grava as heurísticas deste vídeo")
    ap.add_argument("--project", default=None, help="nome do projeto na ledger")
    ap.add_argument("--metrics", default=None,
                    help="'viewRate=47.6,avgWatch=12.4,views=1145,saved=3,shares=11' vindos do Metricool, para amarrar ao projeto")
    args = ap.parse_args()

    words = load_words(args.transcript)
    if not words:
        raise SystemExit("transcript sem palavras")
    total = args.duration or (words[-1]["end"] + 0.5)
    spoken = sum(w["end"] - w["start"] for w in words)
    rep = {"duration": round(total, 2), "words": len(words),
           "dead_air_pct": round(100 * (1 - spoken / total), 0),
           "hook": hook_score(words), "pacing": pacing(words, total), "ending": ending(words, total)}
    if args.candidates:
        rep["hook_candidates"] = candidates(load_words(args.candidates), args.window)

    if args.ledger:
        entry = {"project": args.project or args.transcript.resolve().parent.parent.parent.name,
                 "date": __import__("datetime").date.today().isoformat(),
                 "duration": rep["duration"], "hook_score": rep["hook"]["score"],
                 "hook_text": rep["hook"]["text"][:120], "lead_s": rep["hook"]["lead_s"],
                 "dead_air_pct": rep["dead_air_pct"], "median_wps": rep["pacing"].get("median_wps"),
                 "drags": len(rep["pacing"].get("drags", [])), "cta": rep["ending"]["cta"]}
        if args.metrics:
            for kv in args.metrics.split(","):
                k, _, v = kv.partition("=")
                try:
                    entry[k.strip()] = float(v)
                except ValueError:
                    entry[k.strip()] = v.strip()
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        with args.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"ledger: {entry['project']} → {args.ledger}")

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    h, pc, en = rep["hook"], rep["pacing"], rep["ending"]
    print(f"retenção: {total:.1f}s, {len(words)} palavras, ar morto {rep['dead_air_pct']:.0f}%")
    print(f"  GANCHO {h['score']}/10  «{h['text'][:90]}»")
    for r in h["reasons"]:
        print(f"    · {r}")
    print(f"  RITMO  mediana {pc['median_wps']:.2f} palavras/s; pausa mais longa {pc['longest_pause']['s']:.1f}s em {pc['longest_pause']['at']:.1f}s")
    for d in pc["drags"]:
        print(f"    · arrasto {d['start']:.0f}–{d['end']:.0f}s: {d['wps']:.2f} p/s ({d['silence_pct']:.0f}% silêncio)")
    for q in pc["quiet"]:
        if q not in pc["drags"]:
            print(f"    · silêncio {q['start']:.0f}–{q['end']:.0f}s: {q['silence_pct']:.0f}%")
    print(f"  FECHO  fala até o fim: {'sim' if en['speech_to_end'] else f'não ({en['tail_silence_s']}s de cauda)'}; "
          f"CTA: {en['cta'] or 'nenhum'}; frase final {'completa' if en['complete'] else 'sem pontuação final'}")
    print(f"         «…{en['last_phrase']}»")
    if rep.get("hook_candidates"):
        print("  VARIANTES de gancho na fonte (para você julgar):")
        for c in rep["hook_candidates"]:
            print(f"    {c['score']:.1f}  {c['start']:6.2f}–{c['end']:6.2f}  [{', '.join(c['why'])}]  «{c['text']}»")
    print("  (heurística de manual de retenção, não do seu público — cruze com a retenção real quando houver)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
