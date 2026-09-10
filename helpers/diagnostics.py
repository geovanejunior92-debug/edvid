"""Reúne o que os gates mediram num JSON só, para o preview mostrar.

O check_audio, o shot_check, o scopes/match_takes e o qc_final falam cada um
no seu stdout. O preview não lê stdout; lê arquivos. Este helper junta os
resultados que existirem em <edit>/diagnostics.json, já com os instantes
convertidos para a linha do tempo do CORTE (o shot_check fala em tempo da
fonte; a agulha do preview anda no cut.mp4), e o preview desenha o painel
"Diagnóstico": A/B do áudio para ouvir, bordas apontadas clicáveis, tabela
dos takes, veredito do QC.

Roda de graça (só lê); chame depois de cada gate, antes de abrir o preview:

    uv run python helpers/diagnostics.py <edit>

Fontes lidas, quando existem:
  audio_clean/<stem>.json            (audio_clean)   antes/depois por fonte
  audio_clean/<stem>.ab.wav          (check_audio)   A/B servido em /media/
  verify/shot_check.json             (shot_check)    bordas e takes
  verify/qc_final.json               (qc_final)      falhas e avisos
  edl.json                           ranges, grade_pre, jcut_timeline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def out_time(edl: dict, source: str, t: float) -> float | None:
    """Tempo da fonte → tempo no cut.mp4 (usa jcut_timeline quando há)."""
    jt = edl.get("jcut_timeline")
    if jt:
        for entry, r in zip(jt, edl["ranges"]):
            if r["source"] == source and float(r["start"]) - 0.3 <= t <= float(r["end"]) + 0.3:
                return round(entry["video_start_in_output"] + (t - float(r["start"])), 3)
        return None
    off = 0.0
    for r in edl["ranges"]:
        s, e = float(r["start"]), float(r["end"])
        if r["source"] == source and s - 0.3 <= t <= e + 0.3:
            return round(off + (t - s), 3)
        off += (e - s) / float(r.get("speed", 1) or 1) + float(r.get("freeze_end", 0) or 0)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edit_dir", type=Path)
    args = ap.parse_args()
    edit = args.edit_dir.resolve()
    edl_path = edit / "edl.json"
    edl = json.loads(edl_path.read_text()) if edl_path.exists() else {"ranges": [], "sources": {}}
    diag: dict = {"audio": [], "edges": [], "takes": [], "qc": None, "matched": []}

    # áudio
    for key, raw in (edl.get("sources") or {}).items():
        stem = Path(raw).stem
        rep = edit / "audio_clean" / f"{stem}.json"
        if rep.exists():
            try:
                d = json.loads(rep.read_text())
            except json.JSONDecodeError:
                continue
            ab = edit / "audio_clean" / f"{stem}.ab.wav"
            diag["audio"].append({"source": key, "stem": stem,
                                  "before": d.get("before"), "after": d.get("after"),
                                  "denoise": d.get("denoise"), "breaths": len(d.get("breaths") or []),
                                  "leveled": len(d.get("leveler") or []),
                                  "ab": f"audio_clean/{ab.name}" if ab.exists() else None})

    # shot_check
    sc = edit / "verify" / "shot_check.json"
    if sc.exists():
        try:
            d = json.loads(sc.read_text())
        except json.JSONDecodeError:
            d = {}
        for e in d.get("edges") or []:
            for f in e.get("flags") or []:
                diag["edges"].append({"take": e.get("take"), "beat": e.get("beat"), "kind": e.get("kind"),
                                      "t_source": e.get("t"), "check": f.get("check"),
                                      "shift_frames": f.get("shift_frames"), "fps": e.get("fps"),
                                      "t_out": out_time(edl, edl["ranges"][e["take"]]["source"], float(e["t"]))
                                      if e.get("take") is not None and e["take"] < len(edl["ranges"]) else None})
        for i, t in enumerate(d.get("takes") or []):
            face = t.get("face") or {}
            diag["takes"].append({"take": i, "beat": t.get("beat"), "luma": t.get("luma"),
                                  "face_luma": t.get("face_luma"), "rg": t.get("rg"), "bg": t.get("bg"),
                                  "size": face.get("size"), "cx": face.get("cx"),
                                  "flags": [f for f in (d.get("take_flags") or []) if f.get("take") == i]})

    # match_takes → grade_pre por range
    for i, r in enumerate(edl.get("ranges") or []):
        if r.get("grade_pre"):
            diag["matched"].append({"take": i, "beat": r.get("beat"), "grade_pre": r["grade_pre"]})

    # qc
    qc = edit / "verify" / "qc_final.json"
    if qc.exists():
        try:
            d = json.loads(qc.read_text())
            diag["qc"] = {"fails": d.get("fails") or [], "warns": d.get("warns") or [],
                          "loudness": d.get("loudness"), "duration": d.get("duration"),
                          "safe_zones": (d.get("safe_zones") or {}).get("in_unsafe_pct")}
        except json.JSONDecodeError:
            pass

    (edit / "diagnostics.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2) + "\n")
    print(f"diagnostics.json: {len(diag['audio'])} fonte(s) de áudio, {len(diag['edges'])} borda(s) apontada(s), "
          f"{len(diag['takes'])} take(s), {len(diag['matched'])} casado(s), qc {'sim' if diag['qc'] else 'não'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
