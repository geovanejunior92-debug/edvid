"""Casamento de takes: todos os takes com a MESMA exposição, branco e saturação.

Dois takes da mesma pessoa, na mesma sala, gravados com 20 minutos de
diferença, raramente saem iguais: a luz da janela mudou, o auto-branco do
celular decidiu outra coisa, o rosto ficou 10% mais escuro. Na junção isso é
um "pulo" que o espectador sente e não sabe nomear. O DaVinci resolve com
"shot match"; aqui é este helper, em número, escrevendo no próprio EDL.

Mede cada take com o scopes.py (luma da pele quando há rosto, senão luma
geral; razão R/G e B/G do gray-world; croma) e calcula, por take, o filtro
`grade_pre` que o leva à referência — a mediana dos takes por padrão, ou o
take que você escolher com `--ref N`:

  exposição   `exposure=exposure=±EV` (log2 da razão de luma), teto ±0,7 EV
  branco      `colorchannelmixer=rr=…:bb=…` com os ganhos que igualam R/G e B/G
  saturação   `eq=saturation=…` para igualar o croma, teto 0,8–1,25

Só escreve correção acima do limiar (3% de luma, 2% de branco, 6% de croma):
abaixo disso o olho não vê e o filtro só custa render. O `grade_pre` roda
ANTES do look (`grade`), então o look vê takes iguais — é a ordem certa:
primeiro casar, depois estilizar.

Usage:
    uv run python helpers/match_takes.py <edit>/edl.json            # mostra
    uv run python helpers/match_takes.py <edit>/edl.json --apply    # escreve grade_pre
    uv run python helpers/match_takes.py edl.json --ref 1 --apply   # take 1 é o alvo
    uv run python helpers/match_takes.py edl.json --clear           # remove todos

Depois: render normal. Confira com `scopes.py --edl` de novo — os takes
convergem — e no gate, na junção.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scopes import analyze_take  # noqa: E402

LUMA_TOL = 0.03     # 3% de luma relativa
WB_TOL = 0.02       # 2% na razão R/G ou B/G
CHROMA_TOL = 0.06   # 6% de croma
EV_CAP = 0.7
SAT_CAP = (0.8, 1.25)


def take_key(rep: dict) -> dict:
    """As três medidas que o casamento usa, com fallback sem rosto."""
    luma = rep.get("skin", {}).get("luma_p50") or rep.get("luma", {}).get("p50")
    w = rep.get("white") or {}
    return {"luma": luma, "rg": w.get("r_over_g"), "bg": w.get("b_over_g"),
            "chroma": rep.get("chroma_mean"), "has_face": "skin" in rep}


def build_filter(cur: dict, ref: dict) -> tuple[str, dict]:
    parts, delta = [], {}
    if cur["luma"] and ref["luma"] and cur["luma"] > 0:
        ratio = ref["luma"] / cur["luma"]
        if abs(ratio - 1) >= LUMA_TOL:
            ev = float(np.clip(math.log2(ratio), -EV_CAP, EV_CAP))
            parts.append(f"exposure=exposure={ev:+.3f}")
            delta["ev"] = round(ev, 3)
    if cur["rg"] and ref["rg"] and cur["bg"] and ref["bg"]:
        rr = ref["rg"] / cur["rg"]
        bb = ref["bg"] / cur["bg"]
        if abs(rr - 1) >= WB_TOL or abs(bb - 1) >= WB_TOL:
            rr = float(np.clip(rr, 0.85, 1.18))
            bb = float(np.clip(bb, 0.85, 1.18))
            parts.append(f"colorchannelmixer=rr={rr:.4f}:bb={bb:.4f}")
            delta["rr"], delta["bb"] = round(rr, 4), round(bb, 4)
    if cur["chroma"] and ref["chroma"] and cur["chroma"] > 0:
        s = ref["chroma"] / cur["chroma"]
        if abs(s - 1) >= CHROMA_TOL:
            s = float(np.clip(s, *SAT_CAP))
            parts.append(f"eq=saturation={s:.3f}")
            delta["sat"] = round(s, 3)
    return ",".join(parts), delta


def measure_through(src: Path, t: float, filt: str) -> float | None:
    """Luma da pele do quadro `t` DEPOIS de passar pelo filtro — pelo ffmpeg
    de verdade, não pela conta. O `exposure` do ffmpeg é 2^EV certinho, mas
    outros filtros não são, e o que vale é o que sai do render."""
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        png = Path(tmp.name)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src),
                    "-vf", f"scale=-2:1080,format=yuv420p,{filt or 'null'}",
                    "-frames:v", "1", "-pix_fmt", "yuv420p", str(png)], check=True)
    from scopes import frame_at, measure
    img = frame_at(png, 0.0)
    png.unlink(missing_ok=True)
    if img is None:
        return None
    rep = measure(img, True)
    return rep.get("skin", {}).get("luma_p50") or rep.get("luma", {}).get("p50")


def refine(edl: dict, base: Path, results: list[dict], ref: dict) -> None:
    """Fecha o laço: aplica o grade_pre num quadro do take, mede, corrige o EV
    pelo resíduo (uma vez). Só mexe na exposição; branco e croma ficam."""
    for res, r in zip(results, edl["ranges"]):
        if not res["grade_pre"] or not ref.get("luma"):
            continue
        src = Path(edl["sources"][r["source"]]).expanduser()
        if not src.is_absolute():
            src = (base / src).resolve()
        mid = (float(r["start"]) + float(r["end"])) / 2
        before = measure_through(src, mid, "")
        after = measure_through(src, mid, res["grade_pre"])
        if not before or not after:
            continue
        # alvo relativo: o mesmo quadro precisa subir/descer a razão ref/take
        want = before * ref["luma"] / res["measured"]["luma"] if res["measured"]["luma"] else after
        resid = math.log2(want / after) if after > 0 else 0.0
        res["verify"] = {"before": round(before, 1), "after": round(after, 1),
                         "want": round(want, 1), "resid_ev": round(resid, 3)}
        if abs(resid) >= 0.03 and "ev" in res["delta"]:
            ev = float(np.clip(res["delta"]["ev"] + resid, -EV_CAP, EV_CAP))
            res["delta"]["ev"] = round(ev, 3)
            parts = [x for x in res["grade_pre"].split(",") if not x.startswith("exposure=")]
            res["grade_pre"] = ",".join([f"exposure=exposure={ev:+.3f}"] + parts)
            res["verify"]["after2"] = round(measure_through(src, mid, res["grade_pre"]) or 0, 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edl", type=Path)
    ap.add_argument("--ref", type=int, default=None, help="índice do take-alvo (padrão: mediana)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-verify", action="store_true",
                    help="não fecha o laço pelo ffmpeg (mais rápido, menos exato)")
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    edl = json.loads(edl_path.read_text())
    base = edl_path.parent

    if args.clear:
        n = sum(1 for r in edl["ranges"] if r.pop("grade_pre", None))
        edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2))
        print(f"{n} grade_pre removido(s)")
        return 0

    keys = []
    for r in edl["ranges"]:
        src = Path(edl["sources"][r["source"]]).expanduser()
        if not src.is_absolute():
            src = (base / src).resolve()
        keys.append(take_key(analyze_take(src, float(r["start"]), float(r["end"]), True)))

    if args.ref is not None:
        ref = keys[args.ref]
        ref_name = f"take {args.ref}"
    else:
        def med(k):
            v = [x[k] for x in keys if x[k] is not None]
            return float(np.median(v)) if v else None
        ref = {k: med(k) for k in ("luma", "rg", "bg", "chroma")}
        ref_name = "mediana dos takes"

    results = []
    for i, (r, cur) in enumerate(zip(edl["ranges"], keys)):
        filt, delta = build_filter(cur, ref)
        results.append({"take": i, "beat": r.get("beat"), "grade_pre": filt, "delta": delta,
                        "measured": cur})
    if not args.no_verify:
        refine(edl, base, results, ref)
    for res, r in zip(results, edl["ranges"]):
        if args.apply:
            if res["grade_pre"]:
                r["grade_pre"] = res["grade_pre"]
            else:
                r.pop("grade_pre", None)

    if args.apply:
        edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2))

    if args.json:
        print(json.dumps({"ref": ref_name, "takes": results}, ensure_ascii=False, indent=2))
        return 0
    print(f"alvo: {ref_name}  (luma {ref['luma']:.0f}, R/G {ref['rg']:.3f}, B/G {ref['bg']:.3f}, croma {ref['chroma']:.1f})"
          if ref.get("luma") else f"alvo: {ref_name}")
    for res in results:
        m = res["measured"]
        meas = (f"luma {m['luma']:.0f}" if m["luma"] else "luma ?") + \
               (f"  R/G {m['rg']:.3f} B/G {m['bg']:.3f}" if m["rg"] else "") + \
               (f"  croma {m['chroma']:.1f}" if m["chroma"] else "") + \
               ("" if m["has_face"] else "  (sem rosto: luma geral)")
        action = f"→ {res['grade_pre']}" if res["grade_pre"] else "→ dentro da tolerância"
        v = res.get("verify")
        if v:
            action += (f"\n        verificado no ffmpeg: {v['before']:.0f} → {v['after']:.0f}"
                       f" (alvo {v['want']:.0f}"
                       + (f", refinado → {v['after2']:.0f}" if "after2" in v else "") + ")")
        print(f"  [{res['take']:02d}] {res['beat'] or '':<10} {meas}\n        {action}")
    if args.apply:
        n = sum(1 for r in results if r["grade_pre"])
        print(f"grade_pre escrito em {n} take(s) → {edl_path.name}")
    else:
        print("(--apply escreve no EDL)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
