"""Vícios de fala, repetições e falsas partidas: cortes propostos, você aprova.

O corte por fala escolhe takes e bordas. Dentro de um take bom sobram o "é…"
antes de retomar, o "né" no fim da frase, o "o o" da língua que tropeça e a
frase começada duas vezes. Cada um é meio segundo que o espectador sente e o
editor humano tira sem pensar. Este helper os lista, com tempo e contexto,
como CORTES dentro dos ranges do EDL:

  vício      "é", "eh", "hum", "ah", "né" isolados por pausa (fortes); "tipo",
             "assim", "então", "aí", "sabe" só quando cercados de pausa dos
             dois lados (fracos — muitas vezes são a frase de verdade)
  repetição  a mesma palavra duas vezes seguida ("que que", "a a"): sai a 1ª
  falsa      frase curta (≤ 3 palavras) cuja primeira palavra é a mesma da
  partida    frase seguinte, começada em < 2 s: sai a curta
  órfã       região de fala (speech_regions) sem NENHUMA palavra do transcript
             ≥ 0,3 s — o Whisper esconde falsa partida; listada para você
             transcrever isolada e decidir (observação 14 do log)

Nada é cortado sem `--apply`. Com ele, cada corte vira uma divisão do range
no EDL, nas bordas das palavras vizinhas com 30 ms de folga (regra 4: nunca
dentro de palavra); as bordas novas seguem para o `speech_regions.py` no
fluxo normal. Backup do edl.json ao lado.

Usage:
    uv run python helpers/fillers.py <edit>/edl.json
    uv run python helpers/fillers.py <edit>/edl.json --apply
    uv run python helpers/fillers.py edl.json --no-weak      # só os vícios fortes
    uv run python helpers/fillers.py edl.json --json

Escreve <edit>/fillers.json com a lista (id por item para você aprovar
alguns: `--apply --only 1,3,7`).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STRONG = {"é", "eh", "hum", "hmm", "ah", "ãh", "né", "hã", "uh", "um"}
WEAK = {"tipo", "assim", "então", "aí", "sabe", "enfim", "olha"}
PAD = 0.03          # folga nas bordas do corte
MIN_PIECE = 0.25    # pedaço de range menor que isto some
PAUSE_STRONG = 0.15
PAUSE_WEAK = 0.25


def norm(w: str) -> str:
    w = unicodedata.normalize("NFKC", w.lower()).strip(".,!?;:…\"'()")
    return w


def load_words(edit_dir: Path, stem: str) -> list[dict]:
    p = edit_dir / "transcripts" / f"{stem}.json"
    if not p.exists():
        return []
    out = []
    for w in json.loads(p.read_text()).get("words") or []:
        if w.get("type", "word") != "word":
            continue
        try:
            out.append({"word": (w.get("text") or w.get("word") or "").strip(),
                        "start": float(w["start"]), "end": float(w["end"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def speech_regions(path: Path) -> list[tuple[float, float]]:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                          "-af", "silencedetect=noise=-33dB:d=0.10", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    ss = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", err)]
    se = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", err)]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout or 0)
    regions, cur = [], 0.0
    for s, e in zip(ss, se):
        if s > cur:
            regions.append((cur, s))
        cur = e
    if cur < dur:
        regions.append((cur, dur))
    return [(a, b) for a, b in regions if b - a >= 0.15]


def find_in_range(words: list[dict], r_start: float, r_end: float, use_weak: bool) -> list[dict]:
    ws = [w for w in words if w["start"] >= r_start - 0.01 and w["end"] <= r_end + 0.01]
    items = []
    for i, w in enumerate(ws):
        n = norm(w["word"])
        gap_b = w["start"] - (ws[i - 1]["end"] if i else r_start)
        gap_a = (ws[i + 1]["start"] if i + 1 < len(ws) else r_end) - w["end"]
        dur = w["end"] - w["start"]
        ctx = " ".join(x["word"] for x in ws[max(0, i - 3): i + 4])
        if n in STRONG and dur < 0.6 and (gap_b >= PAUSE_STRONG or gap_a >= PAUSE_STRONG):
            items.append({"kind": "vício", "start": w["start"], "end": w["end"], "text": w["word"],
                          "gap_before": round(gap_b, 2), "gap_after": round(gap_a, 2), "context": ctx})
        elif use_weak and n in WEAK and gap_b >= PAUSE_WEAK and gap_a >= PAUSE_WEAK:
            items.append({"kind": "vício fraco", "start": w["start"], "end": w["end"], "text": w["word"],
                          "gap_before": round(gap_b, 2), "gap_after": round(gap_a, 2), "context": ctx})
        if i + 1 < len(ws) and n and n == norm(ws[i + 1]["word"]) and ws[i + 1]["start"] - w["end"] < 0.6:
            items.append({"kind": "repetição", "start": w["start"], "end": w["end"], "text": f"{w['word']} {ws[i+1]['word']}",
                          "gap_before": round(gap_b, 2), "gap_after": round(ws[i + 1]["start"] - w["end"], 2),
                          "context": ctx})
    # falsas partidas: frases curtas reiniciadas
    phrases, cur = [], []
    for w in ws:
        if cur and w["start"] - cur[-1]["end"] >= 0.35:
            phrases.append(cur); cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    for p, q in zip(phrases, phrases[1:]):
        if len(p) <= 3 and norm(p[0]["word"]) == norm(q[0]["word"]) and q[0]["start"] - p[-1]["end"] < 2.0:
            items.append({"kind": "falsa partida", "start": p[0]["start"], "end": p[-1]["end"],
                          "text": " ".join(x["word"] for x in p),
                          "gap_before": 0.0, "gap_after": round(q[0]["start"] - p[-1]["end"], 2),
                          "context": " ".join(x["word"] for x in p) + " | " + " ".join(x["word"] for x in q[:4])})
    # dedupe por (start,end)
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["start"]):
        key = (round(it["start"], 2), round(it["end"], 2))
        if key not in seen:
            seen.add(key); out.append(it)
    return out


def orphans(regions: list[tuple[float, float]], words: list[dict], r_start: float, r_end: float) -> list[dict]:
    out = []
    for a, b in regions:
        if b <= r_start or a >= r_end or b - a < 0.3:
            continue
        if not any(w["start"] < b and w["end"] > a for w in words):
            out.append({"kind": "órfã", "start": round(a, 2), "end": round(b, 2), "text": "(fala sem palavra no transcript)",
                        "gap_before": 0, "gap_after": 0, "context": "transcreva isolado antes de decidir"})
    return out


def text_cuts_to_source(edl: dict, text_cuts: list[dict]) -> list[dict]:
    """textCuts do preview (tempo RENDERIZADO do cut.mp4) → cortes em tempo da fonte."""
    jt = edl.get("jcut_timeline")
    slots = []
    off = 0.0
    for i, r in enumerate(edl["ranges"]):
        s, e = float(r["start"]), float(r["end"])
        if jt and i < len(jt):
            o = float(jt[i]["video_start_in_output"])
            d = float(jt[i]["video_duration"])
        else:
            o, d = off, (e - s) / float(r.get("speed", 1) or 1)
            off += d + float(r.get("freeze_end", 0) or 0)
        slots.append((o, o + d, s, r["source"]))
    out = []
    for tc in text_cuts:
        a = float(tc.get("renderedStart", tc.get("start", 0)))
        b = float(tc.get("renderedEnd", tc.get("end", 0)))
        for o0, o1, s, src in slots:
            if a >= o0 - 0.05 and a <= o1 + 0.05:
                out.append({"source": src, "start": round(s + (a - o0), 3),
                            "end": round(s + min(b, o1) - o0, 3), "text": str(tc.get("text", ""))[:60],
                            "kind": "texto"})
                break
    return out


def apply_cuts(edl: dict, cuts: list[dict]) -> list[dict]:
    """Divide os ranges em torno dos cortes; devolve os ranges novos."""
    new_ranges = []
    for r in edl["ranges"]:
        pieces = [(float(r["start"]), float(r["end"]))]
        for c in sorted((c for c in cuts if c["source"] == r["source"]), key=lambda c: c["start"]):
            cs, ce = c["start"] - PAD, c["end"] + PAD
            nxt = []
            for a, b in pieces:
                if ce <= a or cs >= b:
                    nxt.append((a, b))
                    continue
                if cs - a >= MIN_PIECE:
                    nxt.append((a, cs))
                if b - ce >= MIN_PIECE:
                    nxt.append((ce, b))
            pieces = nxt
        for k, (a, b) in enumerate(pieces):
            nr = dict(r)
            nr["start"], nr["end"] = round(a, 3), round(b, 3)
            if len(pieces) > 1 and r.get("beat"):
                nr["beat"] = f"{r['beat']}" if k == 0 else f"{r['beat']} ({k + 1})"
            new_ranges.append(nr)
    return new_ranges


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edl", type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default=None, help="ids a aplicar, ex. 1,3,7")
    ap.add_argument("--no-weak", action="store_true")
    ap.add_argument("--no-orphans", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--from-preview", type=Path, default=None,
                    help="preview_edits.json com textCuts[] (edição pelo texto): aplica esses cortes em vez de procurar vícios")
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    edl = json.loads(edl_path.read_text())
    edit_dir = edl_path.parent

    if args.from_preview:
        cuts = text_cuts_to_source(edl, json.loads(args.from_preview.read_text()).get("textCuts") or [])
        if not cuts:
            print("nenhum textCut mapeável")
            return 0
        for c in cuts:
            print(f"  {c['source']} {c['start']:7.2f}–{c['end']:7.2f}  «{c['text']}»")
        if not args.apply:
            print("(--apply corta)")
            return 0
        backup = edl_path.with_name(f"edl.json.bak-textcuts-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(edl_path, backup)
        before = len(edl["ranges"])
        edl["ranges"] = apply_cuts(edl, cuts)
        edl.pop("jcut_timeline", None)
        edl["total_duration_s"] = round(sum(r["end"] - r["start"] for r in edl["ranges"]), 3)
        edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n")
        print(f"aplicado: {len(cuts)} corte(s) do texto, {before} → {len(edl['ranges'])} ranges (backup {backup.name}). "
              f"Agora: speech_regions nas bordas novas → render.")
        return 0

    items = []
    regions_cache: dict[str, list] = {}
    for r in edl["ranges"]:
        src = Path(edl["sources"][r["source"]]).expanduser()
        if not src.is_absolute():
            src = (edit_dir / src).resolve()
        words = load_words(edit_dir, src.stem)
        if not words:
            print(f"  (sem transcript para {src.name}: transcribe.py antes)")
            continue
        found = find_in_range(words, float(r["start"]), float(r["end"]), not args.no_weak)
        if not args.no_orphans:
            if r["source"] not in regions_cache:
                regions_cache[r["source"]] = speech_regions(src)
            found += orphans(regions_cache[r["source"]], words, float(r["start"]), float(r["end"]))
        for it in found:
            it["source"] = r["source"]
            it["beat"] = r.get("beat")
        items += found
    items.sort(key=lambda x: (x["source"], x["start"]))
    for i, it in enumerate(items, 1):
        it["id"] = i
    (edit_dir / "fillers.json").write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        total = sum(it["end"] - it["start"] for it in items if it["kind"] != "órfã")
        print(f"fillers: {len(items)} item(ns), {total:.1f}s de fala descartável")
        for it in items:
            print(f"  [{it['id']:2d}] {it['kind']:<14} {it['start']:7.2f}–{it['end']:7.2f}  «{it['text']}»"
                  f"   pausa {it['gap_before']:.2f}/{it['gap_after']:.2f}s   …{it['context'][:60]}…")
    if not args.apply:
        if items and not args.json:
            print("(--apply corta todos menos as órfãs; --apply --only 1,3 escolhe)")
        return 0

    chosen = items
    if args.only:
        ids = {int(x) for x in args.only.split(",") if x.strip()}
        chosen = [it for it in items if it["id"] in ids]
    chosen = [it for it in chosen if it["kind"] != "órfã"]
    if not chosen:
        print("nada a aplicar")
        return 0
    backup = edl_path.with_name(f"edl.json.bak-fillers-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(edl_path, backup)
    before = len(edl["ranges"])
    edl["ranges"] = apply_cuts(edl, chosen)
    edl.pop("jcut_timeline", None)
    edl["total_duration_s"] = round(sum(r["end"] - r["start"] for r in edl["ranges"]), 3)
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n")
    print(f"aplicado: {len(chosen)} corte(s), {before} → {len(edl['ranges'])} ranges, "
          f"{edl['total_duration_s']:.1f}s (backup {backup.name}). Agora: speech_regions nas bordas novas → render.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
