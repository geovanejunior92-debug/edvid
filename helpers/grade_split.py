"""Grade separado para pessoa e fundo, com a máscara rastreada do person_matte.

O "power window rastreado" do DaVinci: um look para o sujeito, outro para o
fundo, e a janela segue a pessoa. Aqui a janela é o alpha do Robust Video
Matting que a Fase 2 já gera para o efeito "elemento atrás da pessoa"
(`person_matte.py cut.mp4 -o fg.webm`), então o rastreio vem de graça e a
borda do cabelo é a do RVM, não uma elipse.

Usos típicos:
  --bg "eq=brightness=-0.08:saturation=0.85"   fundo mais escuro e sóbrio, a
                                               pessoa salta (o clássico)
  --fg "eq=contrast=1.05"                      contraste só no rosto
  --bg "gblur=sigma=6"                         profundidade de campo fake

Roda em UMA passagem sobre o cut.mp4 (depois do render da Fase 1, antes da
Fase 2), preservando o áudio. Não mexe no edl.json: é acabamento, e é
reversível — o cut original fica em cut.pre_split.mp4.

Usage:
    uv run python helpers/grade_split.py <edit>/cut.mp4 --matte <edit>/remotion/public/fg.webm --bg "…" [--fg "…"]
    uv run python helpers/grade_split.py cut.mp4 --matte fg.webm --bg "…" --feather 3 --strength 0.8
    uv run python helpers/grade_split.py cut.mp4 --matte fg.webm --bg "…" -o cut_split.mp4   # sem substituir

Sem `--matte`, gera um com o person_matte.py (lento: RVM quadro a quadro).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"falhou: {' '.join(cmd[:3])}…\n{proc.stderr[-1500:]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("--matte", type=Path, default=None, help="fg.webm (VP9 com alpha) do person_matte.py")
    ap.add_argument("--bg", default="", help="filtro ffmpeg para o FUNDO")
    ap.add_argument("--fg", default="", help="filtro ffmpeg para a PESSOA")
    ap.add_argument("--feather", type=float, default=2.0, help="suavização da borda da máscara (px)")
    ap.add_argument("--strength", type=float, default=1.0, help="0–1: quanto da separação entra")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="saída; sem isto substitui o vídeo (original vira .pre_split.mp4)")
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.exists():
        raise SystemExit(f"não existe: {video}")
    if not args.bg and not args.fg:
        raise SystemExit("passe --bg e/ou --fg")

    matte = args.matte
    if matte is None:
        matte = video.with_name("fg_split.webm")
        print(f"sem --matte: gerando {matte.name} com person_matte.py (RVM)…")
        run([sys.executable, str(Path(__file__).resolve().parent / "person_matte.py"),
             str(video), "-o", str(matte)])
    matte = matte.resolve()
    if not matte.exists():
        raise SystemExit(f"matte não existe: {matte}")

    out = args.output.resolve() if args.output else video.with_name(video.stem + ".split_tmp.mp4")
    strength = min(max(args.strength, 0.0), 1.0)
    bg = args.bg or "null"
    fg = args.fg or "null"
    feather = f",gblur=sigma={args.feather:.1f}" if args.feather > 0 else ""

    # [base] → duas cópias graduadas; a máscara vem do alpha do matte
    # (alphaextract → cinza), com pena e força. maskedmerge: 1 = pessoa.
    fc = (f"[0:v]format=gbrp,split[b0][b1];"
          f"[b0]{bg},format=gbrp[bgg];"
          f"[b1]{fg},format=gbrp[fgg];"
          f"[1:v]format=rgba,alphaextract{feather},lutyuv=y='val*{strength:.2f}',"
          f"scale=iw:ih,format=gbrp[m];"
          f"[bgg][fgg][m]maskedmerge,format=yuv420p[vout]")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-c:v", "libvpx-vp9",
           "-i", str(matte), "-filter_complex", fc, "-map", "[vout]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-c:a", "copy", "-movflags", "+faststart", "-shortest", str(out)]
    print(f"grade_split: fundo «{bg}»  pessoa «{fg}»  força {strength:.2f}")
    run(cmd)

    if args.output:
        print(f"→ {out}")
    else:
        backup = video.with_name(video.stem + ".pre_split.mp4")
        if not backup.exists():
            shutil.copy2(video, backup)
        out.replace(video)
        print(f"→ {video.name} substituído (original em {backup.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
