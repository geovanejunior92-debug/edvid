"""Gate dos inserts de vídeo: eles TOCAM e cabem na faixa sem serem ampliados?

Dois defeitos reais, os dois silenciosos, os dois pegos só pelo usuário
(2026-08-16) depois de um render inteiro:

1. **Insert congelado.** No template, o clipe da faixa só toca do próprio frame 0
   se estiver dentro de uma `<Sequence>`. Sem ela, uma janela que começa aos 55s
   pede o segundo 55 de um clipe de 5s, passa do fim e o quadro CONGELA no último
   frame. Nada falha, nada avisa, e só a primeira janela (perto do zero) parece
   certa. Aqui isso vira número: diferença média entre frames do arquivo.

2. **Insert ampliado.** Um clipe 16:9 jogado com `objectFit: cover` numa faixa de
   1080x850 é cortado e ampliado ~2x — "proporções maiores do que o normal,
   fugindo da visualização". Aqui isso vira número: quanto de área do clipe
   sobrevive ao enquadramento da faixa.

Uso:
    uv run python helpers/check_inserts.py <edit-data.json> [--band-h 750] [--min-motion 0.6] [--min-keep 0.55]

Sai diferente de zero se algum insert reprovar. Rodar SEMPRE antes do render da
Fase 2 — é passo obrigatório, não conferência opcional.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,duration,nb_frames,r_frame_rate", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        s = json.loads(out.stdout)["streams"][0]
    except Exception:
        return {}
    return s


def motion_score(path: Path, dur: float) -> float:
    """Diferença média entre frames consecutivos (0 = imagem parada)."""
    n = max(1, min(int(dur * 30), 240))
    # `file=-` é obrigatório: sem ele o metadata=print não escreve em lugar
    # nenhum nesta build, o parse acha zero linha e a métrica devolve 0.00 para
    # TODO clipe — um verificador que reprova tudo é tão inútil quanto um que
    # aprova tudo (pego na primeira execução real, 2026-08-16).
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", str(n),
         "-vf", "scale=160:-2,tblend=all_mode=difference,signalstats,"
                "metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    vals = [float(l.split("=")[-1]) for l in out.stdout.splitlines() if "YAVG" in l]
    # o primeiro frame do tblend não tem par: descartar
    vals = vals[1:] or vals
    return sum(vals) / len(vals) if vals else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Verifica movimento e proporção dos inserts de vídeo")
    ap.add_argument("edit_data", type=Path)
    ap.add_argument("--band-h", type=float, default=750.0, help="altura da faixa da tela dividida")
    ap.add_argument("--min-motion", type=float, default=0.6,
                    help="diferença média mínima entre frames (abaixo disso é imagem parada)")
    ap.add_argument("--min-keep", type=float, default=0.55,
                    help="fração mínima da área do clipe que sobrevive ao enquadramento")
    args = ap.parse_args()

    data = json.loads(args.edit_data.read_text())
    root = args.edit_data.parent
    items = [("splitInserts", i) for i in data.get("splitInserts", [])]
    items += [("behindVideos", i) for i in data.get("behindVideos", [])]
    items += [("inserts", i) for i in data.get("inserts", []) if i.get("kind") == "video"]
    if not items:
        print("nenhum insert de vídeo em edit-data.json")
        return

    fails = 0
    for kind, it in items:
        src = root / it["src"]
        win = float(it.get("end", 0)) - float(it.get("start", 0))
        if not src.exists():
            print(f"FALTA   {it['src']}")
            fails += 1
            continue
        st = probe(src)
        w, h = int(st.get("width", 0)), int(st.get("height", 0))
        dur = float(st.get("duration") or 0)
        problems = []
        eh_imagem = it.get("kind") == "image" or src.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")

        # 1) o arquivo cobre a janela inteira? senão congela no último frame
        if not eh_imagem and dur + 0.05 < win:
            problems.append(f"curto demais ({dur:.2f}s < janela {win:.2f}s) — congela no fim")

        # 2) tem movimento? (imagem é parada por natureza — o Ken-Burns do
        #    template dá o movimento dela, então não se cobra o mesmo)
        mot = 0.0 if eh_imagem else motion_score(src, min(dur, win) or 1.0)
        if not eh_imagem and mot < args.min_motion:
            problems.append(f"parado (movimento {mot:.2f} < {args.min_motion})")

        # 3) quanto sobra do clipe dentro da faixa, com cover?
        band_h = float(it.get("bandH", args.band_h)) if kind == "splitInserts" else 1920.0
        band_w = 1080.0
        keep = 1.0
        if w and h:
            scale = max(band_w / w, band_h / h)          # cover
            keep = (band_w / (w * scale)) * (band_h / (h * scale))
        fit = it.get("fit", "cover")
        if fit == "cover" and keep < args.min_keep:
            problems.append(f"amplia demais (sobra {keep*100:.0f}% do clipe) — usar fit:contain")

        tag = "FALHA " if problems else "ok    "
        if problems:
            fails += 1
        print(f"{tag} {it['src']:<28} {w}x{h} {dur:5.2f}s  {'imagem' if eh_imagem else f'mov {mot:4.1f}'}  sobra {keep*100:3.0f}%"
              + ("  | " + "; ".join(problems) if problems else ""))

    print(f"\n{len(items) - fails}/{len(items)} inserts ok")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
