"""Clipper de longform: de uma gravação longa, os N trechos que dão Reel.

Lê o transcript da fonte (word-level), monta frases (pausa ≥ 0,5 s ou
pontuação final) e testa toda janela que começa numa frase e termina numa
frase, com duração entre --min e --max. Cada janela recebe nota:

  gancho     os 3 primeiros segundos, pela mesma régua do retention.py
  densidade  palavras/s da janela contra a mediana da fonte
  conteúdo   número, pergunta, contraste, "você"
  fecho      termina em pontuação final (+), tem CTA (+), ar morto (−)

As melhores janelas que não se sobrepõem viram esboços de EDL, um por pasta
(<out>/clip_1/edl.json …), prontos para a Fase 1 normal refinar as bordas
com speech_regions. Isto NÃO substitui a escolha editorial: lista e pontua;
você lê os trechos e decide.

Usage:
    uv run python helpers/clipper.py <edit>/transcripts/<fonte>.json --source <fonte.mp4> --out <edit>/clips
    uv run python helpers/clipper.py fonte.json --source fonte.mp4 --min 40 --max 75 --top 3
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retention import CTA, CONTRAST, NUMBER, YOU, hook_score, load_words  # noqa: E402


def phrases(words: list[dict]) -> list[dict]:
    out, cur = [], []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] >= 0.5:
            out.append(cur); cur = []
        cur.append(w)
        if re.search(r"[.!?…]$", w["word"]):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return [{"start": p[0]["start"], "end": p[-1]["end"], "words": p,
             "text": " ".join(w["word"] for w in p),
             "final": bool(re.search(r"[.!?…]$", p[-1]["word"]))} for p in out]


def score_window(ws: list[dict], start: float, end: float, median_wps: float) -> tuple[float, list[str]]:
    shifted = [{**w, "start": w["start"] - start, "end": w["end"] - start} for w in ws]
    hook = hook_score(shifted)
    why = [f"gancho {hook['score']}"]
    s = hook["score"] * 0.6
    dur = end - start
    wps = len(ws) / dur if dur else 0
    if median_wps:
        ratio = wps / median_wps
        if ratio >= 1.05:
            s += 1.0; why.append("denso")
        elif ratio < 0.8:
            s -= 1.0; why.append("lento")
    text = " ".join(w["word"] for w in ws)
    if NUMBER.search(text): s += 0.8; why.append("número")
    if "?" in text: s += 0.6; why.append("pergunta")
    if CONTRAST.search(text): s += 0.6; why.append("contraste")
    if YOU.search(text): s += 0.4; why.append("você")
    if CTA.search(" ".join(w["word"] for w in ws[-25:])): s += 0.8; why.append("CTA no fim")
    spoken = sum(w["end"] - w["start"] for w in ws)
    dead = 1 - spoken / dur if dur else 0
    if dead > 0.35: s -= 1.0; why.append(f"ar morto {dead*100:.0f}%")
    return round(s, 2), why


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--source", type=Path, required=True, help="arquivo de vídeo da fonte (para o EDL)")
    ap.add_argument("--out", type=Path, default=None, help="pasta dos esboços (padrão: <edit>/clips)")
    ap.add_argument("--min", type=float, default=40.0)
    ap.add_argument("--max", type=float, default=75.0)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    words = load_words(args.transcript)
    if not words:
        raise SystemExit("transcript sem palavras")
    ph = phrases(words)
    total = words[-1]["end"]
    median_wps = float(np.median([len(p["words"]) / max(0.3, p["end"] - p["start"]) for p in ph])) if ph else 0

    cands = []
    for i, p in enumerate(ph):
        for j in range(i, len(ph)):
            q = ph[j]
            dur = q["end"] - p["start"]
            if dur < args.min:
                continue
            if dur > args.max:
                break
            ws = [w for w in words if w["start"] >= p["start"] and w["end"] <= q["end"]]
            s, why = score_window(ws, p["start"], q["end"], median_wps)
            if q["final"]:
                s += 0.7; why.append("fecha em pontuação")
            cands.append({"start": round(p["start"], 2), "end": round(q["end"], 2), "score": round(s, 2),
                          "why": why, "text": " ".join(w["word"] for w in ws)})
    cands.sort(key=lambda c: -c["score"])
    chosen = []
    for c in cands:
        if all(c["end"] <= o["start"] + 0.3 * (o["end"] - o["start"]) or c["start"] >= o["end"] - 0.3 * (o["end"] - o["start"])
               for o in chosen):
            chosen.append(c)
        if len(chosen) >= args.top:
            break

    edit_dir = args.transcript.resolve().parent.parent
    out_dir = (args.out or edit_dir / "clips").resolve()
    src = args.source.resolve()
    key = src.stem
    summary = [f"# Clipper — {src.name} ({total:.0f}s de fonte, {len(cands)} janelas testadas)\n"]
    for n, c in enumerate(chosen, 1):
        d = out_dir / f"clip_{n}"
        d.mkdir(parents=True, exist_ok=True)
        edl = {"version": 1, "sources": {key: str(src)}, "grade": "auto", "audio_clean": True,
               "ranges": [{"source": key, "start": c["start"], "end": c["end"], "beat": f"CLIP {n}",
                           "quote": c["text"][:140], "reason": "clipper: " + ", ".join(c["why"])}],
               "total_duration_s": round(c["end"] - c["start"], 3)}
        (d / "edl.json").write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n")
        summary.append(f"## clip_{n} — {c['start']:.1f}–{c['end']:.1f}s ({c['end']-c['start']:.0f}s) nota {c['score']}\n"
                       f"_{', '.join(c['why'])}_\n\n> {c['text']}\n")
    (out_dir / "clips.md").write_text("\n".join(summary))

    if args.json:
        print(json.dumps(chosen, ensure_ascii=False, indent=2))
        return 0
    print(f"clipper: {len(cands)} janelas de {args.min:.0f}–{args.max:.0f}s testadas; {len(chosen)} escolhidas → {out_dir}")
    for n, c in enumerate(chosen, 1):
        print(f"  clip_{n}: {c['start']:7.1f}–{c['end']:7.1f}s  nota {c['score']:.1f}  [{', '.join(c['why'])}]")
        print(f"          «{c['text'][:120]}…»")
    print("  esboços de EDL prontos para a Fase 1 (bordas ainda por speech_regions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
