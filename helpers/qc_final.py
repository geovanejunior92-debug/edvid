"""QC de entrega: o que uma emissora checa antes de ir ao ar, sem ninguém assistir.

Gate final, DEPOIS do render da Fase 2/3 e ANTES de mandar o vídeo. Cada
checagem é um número com limiar; qualquer uma fora = exit 1 e a lista do que
falhou. Complementa o `review_final.py` (que assiste) — este não assiste, mede.

  loudness     I (LUFS), LRA e true peak do arquivo entregue, contra o alvo
               (-14/-1 padrão; -16/-3 com --premium; ou --target-i/--target-tp).
  preto        quadros pretos (blackdetect ≥ 0,1 s). Um corte nunca produz
               preto; se produziu, é insert que não carregou ou fade sobrando.
  congelado    quadros repetidos ≥ 0,5 s (freezedetect) — insert de imagem
               parada é legítimo, então só AVISA; falha se for ≥ 2 s.
  níveis       Y abaixo de 16 ou acima de 235 (tv range) em % dos quadros:
               "ilegal" para broadcast, e no Instagram vira esmagado/estourado.
  legenda      cada cue do captions.json contra a fala do áudio final
               (silencedetect): cue sem fala embaixo, cue adiantada > 300 ms,
               cue que fica > 700 ms depois de a fala acabar.
  zona segura  compara final.mp4 com cut.mp4 (mesma linha do tempo): onde a
               Fase 2 DESENHOU (diferença > limiar) e quanto disso cai onde a
               interface do app fica por cima — coluna de ícones à direita,
               faixa inferior de legenda/usuário, topo. Mapas por plataforma:
               --platform reels (padrão) | tiktok | shorts.
  duração      final × cut: divergência > 0,25 s = alguma camada mudou a
               linha do tempo.

Usage:
    uv run python helpers/qc_final.py <edit>/final.mp4
    uv run python helpers/qc_final.py <edit>/final.mp4 --premium --platform tiktok
    uv run python helpers/qc_final.py final.mp4 --cut cut.mp4 --captions remotion/public/captions.json

Escreve <edit>/verify/qc_final.json. Exit 0 = pode enviar.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

# Zonas cobertas pela interface, em frações do quadro (x0, y0, x1, y1).
# Medidas nos apps em 2026: coluna de ações à direita, faixa inferior com
# usuário/legenda/áudio, topo com status/câmera. Conservadoras de propósito.
UNSAFE = {
    "reels": {"topo": (0.0, 0.0, 1.0, 0.08), "rodapé": (0.0, 0.76, 1.0, 1.0),
              "coluna direita": (0.84, 0.42, 1.0, 0.86)},
    "tiktok": {"topo": (0.0, 0.0, 1.0, 0.10), "rodapé": (0.0, 0.74, 1.0, 1.0),
               "coluna direita": (0.82, 0.40, 1.0, 0.88)},
    "shorts": {"topo": (0.0, 0.0, 1.0, 0.09), "rodapé": (0.0, 0.78, 1.0, 1.0),
               "coluna direita": (0.85, 0.45, 1.0, 0.86)},
}
DRAW_THRESHOLD = 28      # diferença média por pixel que conta como "desenhou"
UNSAFE_MAX_PCT = 15.0    # % dos pixels desenhados que podem cair em zona coberta


def sh(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stderr


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return float(out.strip() or 0)


def loudness(path: Path) -> dict:
    err = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
              "-f", "null", "-"])
    summary = err[err.rfind("Summary:"):]
    def grab(key):
        m = re.search(key + r":\s*(-?[\d.]+)", summary)
        return float(m.group(1)) if m else None
    return {"I": grab("I"), "LRA": grab("LRA"), "TP": grab("Peak")}


def detect_ranges(path: Path, filt: str, start_key: str, end_key: str | None, dur_key: str | None) -> list[tuple[float, float]]:
    err = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf", filt, "-an", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(start_key + r":\s*([\d.]+)", err)]
    if end_key:
        ends = [float(x) for x in re.findall(end_key + r":\s*([\d.]+)", err)]
    else:
        durs = [float(x) for x in re.findall(dur_key + r":\s*([\d.]+)", err)]
        ends = [s + d for s, d in zip(starts, durs)]
    return list(zip(starts, ends))


def illegal_levels(path: Path, every: float = 0.5) -> dict:
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-vf", f"fps=1/{every},signalstats,metadata=print:key=lavfi.signalstats.YMIN:file=-,"
                f"metadata=print:key=lavfi.signalstats.YMAX:file=-",
         "-an", "-f", "null", "-"], capture_output=True, text=True).stdout
    ymin = [int(v) for v in re.findall(r"YMIN=(\d+)", err)]
    ymax = [int(v) for v in re.findall(r"YMAX=(\d+)", err)]
    n = max(1, len(ymin))
    return {"frames": len(ymin),
            "crushed_pct": round(100 * sum(v < 8 for v in ymin) / n, 1),
            "clipped_pct": round(100 * sum(v > 245 for v in ymax) / n, 1)}


def speech_regions(path: Path, noise: str = "-33dB", min_sil: float = 0.25) -> list[tuple[float, float]]:
    err = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
              "-af", f"silencedetect=noise={noise}:d={min_sil}", "-vn", "-f", "null", "-"])
    ss = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", err)]
    se = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", err)]
    total = duration(path)
    regions, cursor = [], 0.0
    for s, e in zip(ss, se):
        if s > cursor:
            regions.append((cursor, s))
        cursor = e
    if cursor < total:
        regions.append((cursor, total))
    return regions


def check_captions(captions: Path, regions: list[tuple[float, float]]) -> dict:
    data = json.loads(captions.read_text())
    cues = data if isinstance(data, list) else (data.get("cues") or data.get("captions") or data.get("words") or [])
    early, late, silent = [], [], []
    for c in cues:
        if not str(c.get("text", "")).strip():
            continue  # cue vazia não é legenda
        s = float(c.get("startMs", c.get("start", 0)) or 0) / (1000 if "startMs" in c else 1)
        e = float(c.get("endMs", c.get("end", 0)) or 0) / (1000 if "endMs" in c else 1)
        text = str(c.get("text", ""))[:30]
        overlap = [(a, b) for a, b in regions if b > s and a < e]
        if not overlap:
            silent.append({"t": round(s, 2), "text": text})
            continue
        a, b = overlap[0][0], overlap[-1][1]
        if a - s > 0.3:
            early.append({"t": round(s, 2), "by_ms": int((a - s) * 1000), "text": text})
        if e - b > 0.7:
            late.append({"t": round(s, 2), "by_ms": int((e - b) * 1000), "text": text})
    return {"cues": sum(1 for c in cues if str(c.get("text", "")).strip()),
            "silent": silent, "early": early, "late": late}


def safe_zones(final: Path, cut: Path, platform: str, every: float = 0.5) -> dict:
    """Onde a Fase 2 desenhou (final − cut) e quanto cai em zona coberta."""
    def size(path):
        info = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "json", str(path)], capture_output=True, text=True).stdout)
        s = info["streams"][0]
        return int(s["width"]), int(s["height"])
    def frames(path, w, h):
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps=1/{every},scale={w}:{h}",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        n = len(raw) // (w * h)
        return np.frombuffer(raw[: n * w * h], np.uint8).reshape(n, h, w).astype(np.int16)
    (fw, fh), (cw, ch) = size(final), size(cut)
    if abs(fw / fh - cw / ch) > 0.02:
        return {"error": f"proporções diferentes (final {fw}x{fh}, cut {cw}x{ch}): sem comparação"}
    w = 270
    h = int(round(fh * w / fw / 2)) * 2
    fa = frames(final, w, h)
    fb = frames(cut, w, h)
    n = min(len(fa), len(fb))
    if n == 0:
        return {"error": "sem quadros"}
    diff = np.abs(fa[:n] - fb[:n])
    drawn = diff > DRAW_THRESHOLD
    total = int(drawn.sum())
    zones = {}
    for name, (x0, y0, x1, y1) in UNSAFE[platform].items():
        m = np.zeros((h, w), bool)
        m[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)] = True
        zones[name] = round(100 * int((drawn & m).sum()) / max(1, total), 1)
    return {"drawn_px_pct": round(100 * total / (n * w * h), 2), "in_unsafe_pct": zones,
            "samples": n}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("final", type=Path)
    ap.add_argument("--cut", type=Path, default=None)
    ap.add_argument("--captions", type=Path, default=None)
    ap.add_argument("--platform", choices=sorted(UNSAFE), default="reels")
    ap.add_argument("--premium", action="store_true", help="alvo -16 LUFS / -3 dBTP")
    ap.add_argument("--target-i", type=float, default=None)
    ap.add_argument("--target-tp", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    final = args.final.resolve()
    edit_dir = final.parent
    cut = args.cut or (edit_dir / "cut.mp4")
    captions = args.captions or (edit_dir / "remotion" / "public" / "captions.json")
    ti = args.target_i if args.target_i is not None else (-16.0 if args.premium else -14.0)
    ttp = args.target_tp if args.target_tp is not None else (-3.0 if args.premium else -1.0)

    fails, warns, report = [], [], {"file": str(final), "platform": args.platform}

    # A Fase 2 sabe o que ela acrescentou: o encerramento (tela escura, sem
    # fala, sem legenda) é conteúdo, não defeito. Lê o edit-data.json para
    # não acusar a tela azul de "preto" nem a duração dela de "divergência".
    edit_data = {}
    for cand in (edit_dir / "remotion" / "public" / "edit-data.json",):
        if cand.exists():
            try:
                edit_data = json.loads(cand.read_text())
            except json.JSONDecodeError:
                pass
    outro = edit_data.get("outro") or {}
    outro_start = float(outro.get("startSec") or 0) if outro.get("enabled", True) and outro.get("startSec") else None
    expected = float(edit_data.get("durationSec") or 0) or None

    dur = duration(final)
    report["duration"] = round(dur, 3)
    if expected:
        if abs(dur - expected) > 0.25:
            fails.append(f"duração {dur:.2f}s ≠ edit-data {expected:.2f}s ({dur - expected:+.2f}s)")
    elif cut.exists():
        dcut = duration(cut)
        report["cut_duration"] = round(dcut, 3)
        if abs(dur - dcut) > 0.25:
            fails.append(f"duração {dur:.2f}s ≠ cut {dcut:.2f}s ({dur - dcut:+.2f}s)")

    lo = loudness(final)
    report["loudness"] = lo
    if lo["I"] is not None:
        if abs(lo["I"] - ti) > 1.0:
            fails.append(f"loudness {lo['I']:.1f} LUFS (alvo {ti:.0f} ±1)")
        if lo["TP"] is not None and lo["TP"] > ttp + 0.35:  # AAC estoura ~0,3 dB acima do loudnorm
            fails.append(f"true peak {lo['TP']:.1f} dBTP (teto {ttp:.0f})")
        if lo["LRA"] is not None and lo["LRA"] > 14:
            warns.append(f"LRA {lo['LRA']:.1f} LU: dinâmica larga para celular")

    blacks = detect_ranges(final, "blackdetect=d=0.1:pic_th=0.98", "black_start", "black_end", None)
    if outro_start is not None:
        blacks = [(a, b) for a, b in blacks if b <= outro_start + 0.1]
    report["black"] = [[round(a, 2), round(b, 2)] for a, b in blacks]
    if blacks:
        fails.append(f"{len(blacks)} trecho(s) preto: " + ", ".join(f"{a:.1f}–{b:.1f}s" for a, b in blacks[:3]))

    freezes = detect_ranges(final, "freezedetect=n=-60dB:d=0.5", "freeze_start", None, "freeze_duration")
    report["frozen"] = [[round(a, 2), round(b, 2)] for a, b in freezes]
    long_f = [(a, b) for a, b in freezes if b - a >= 2.0]
    if long_f:
        fails.append(f"quadro congelado ≥2s: " + ", ".join(f"{a:.1f}–{b:.1f}s" for a, b in long_f[:3]))
    elif freezes:
        warns.append(f"{len(freezes)} trecho(s) congelado(s) 0,5–2s (insert parado?): "
                     + ", ".join(f"{a:.1f}s" for a, _ in freezes[:4]))

    lv = illegal_levels(final)
    report["levels"] = lv
    if lv["crushed_pct"] > 20:
        fails.append(f"níveis: Y<8 em {lv['crushed_pct']:.0f}% dos quadros (preto esmagado)")
    if lv["clipped_pct"] > 5:
        fails.append(f"níveis: Y>245 em {lv['clipped_pct']:.0f}% dos quadros (branco estourado)")

    if captions.exists():
        regions = speech_regions(final)
        cc = check_captions(captions, regions)
        report["captions"] = cc
        if cc["silent"]:
            fails.append(f"{len(cc['silent'])} legenda(s) sem fala embaixo, ex. {cc['silent'][0]}")
        if cc["early"]:
            warns.append(f"{len(cc['early'])} legenda(s) adiantada(s) >300ms, ex. {cc['early'][0]}")
        if cc["late"]:
            warns.append(f"{len(cc['late'])} legenda(s) atrasada(s) >700ms, ex. {cc['late'][0]}")
    else:
        report["captions"] = None

    if cut.exists():
        sz = safe_zones(final, cut, args.platform)
        report["safe_zones"] = sz
        if sz.get("error"):
            warns.append(f"zona segura: {sz['error']}")
        for zone, pct in (sz.get("in_unsafe_pct") or {}).items():
            if pct > UNSAFE_MAX_PCT:
                fails.append(f"zona coberta ({args.platform}, {zone}): {pct:.0f}% do que a Fase 2 desenhou")
    else:
        report["safe_zones"] = None
        warns.append("sem cut.mp4 ao lado: zona segura e duração não checadas")

    report["fails"], report["warns"] = fails, warns
    (edit_dir / "verify").mkdir(exist_ok=True)
    (edit_dir / "verify" / "qc_final.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if fails else 0
    print(f"qc_final: {final.name}  {dur:.2f}s  {args.platform}")
    if lo["I"] is not None:
        print(f"  loudness  I {lo['I']:.1f} LUFS  LRA {lo['LRA']:.1f}  TP {lo['TP']:.1f} dBTP  (alvo {ti:.0f}/{ttp:.0f})")
    print(f"  preto {len(blacks)}  congelado {len(freezes)}  níveis: esmagado {lv['crushed_pct']:.0f}% estourado {lv['clipped_pct']:.0f}%")
    if report.get("captions"):
        cc = report["captions"]
        print(f"  legenda   {cc['cues']} cues: {len(cc['silent'])} em silêncio, {len(cc['early'])} adiantadas, {len(cc['late'])} atrasadas")
    if report.get("safe_zones") and "in_unsafe_pct" in report["safe_zones"]:
        sz = report["safe_zones"]
        z = ", ".join(f"{k} {v:.0f}%" for k, v in sz["in_unsafe_pct"].items())
        print(f"  zona segura  desenhado {sz['drawn_px_pct']:.1f}% do quadro; em zona coberta: {z}")
    for w in warns:
        print(f"  AVISO: {w}")
    if fails:
        print("FALHA:")
        for f in fails:
            print(f"  - {f}")
    else:
        print("OK: pode enviar")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
