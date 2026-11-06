"""Locução gerada no VoiceStudio local: gera o áudio e, se pedido, mixa num vídeo.

Só roda quando ele pede locução. Nada no render.py chama isto, então o áudio de
um vídeo comum não muda. O vídeo passa intacto (-c:v copy) e a fonte nunca é
sobrescrita.

    python helpers/voiceover.py gen --edit-dir <edit> --text "..." [--name locucao]
        [--file roteiro.txt] [--voice pf_dora] [--speed 1.0]
    python helpers/voiceover.py mix --video cut.mp4 --voiceover locucao.wav
        --at 12.3 -o cut_locucao.mp4 [--duck-db 12] [--replace-audio]

`mix` iguala o volume da locução ao da voz do vídeo e abaixa o som original só
enquanto ela fala. Sem som na fonte, a locução vai a -14 LUFS.

Fala com o VoiceStudio pelo vs.py da skill voicestudio, em processo separado, o
que mantém a AGPL dele fora do edvid. Exit codes: 0 ok, 1 erro de uso ou de mídia,
2 VoiceStudio ausente.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

VS = Path.home() / ".agents/skills/voicestudio/scripts/vs.py"
SILENCE_LUFS = -60.0
DEFAULT_LUFS = -14.0
MAX_GAIN_DB = 24.0
RAMP_S = 0.15
AUDIO_BITRATE = "320k"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def has_audio(path: Path) -> bool:
    out = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
               "stream=index", "-of", "csv=p=0", str(path)])
    return bool(out.stdout.strip())


def duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)])
    try:
        return float(out.stdout.strip())
    except ValueError:
        sys.exit(f"Não consegui ler a duração de {path}.")


def loudness(path: Path) -> float | None:
    """LUFS integrado. None quando não há som de verdade."""
    if not has_audio(path):
        return None
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
               "-af", "ebur128=framelog=quiet", "-f", "null", "-"])
    found = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", out.stderr)
    if not found:
        return None
    value = float(found[-1])
    return None if value < SILENCE_LUFS else value


def match_gain(voiceover_lufs: float, source_lufs: float | None) -> float:
    target = DEFAULT_LUFS if source_lufs is None else source_lufs
    return round(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, target - voiceover_lufs)), 2)


def duck_expr(at: float, end: float, duck_db: float) -> str:
    """Volume do som original: cai só durante a locução, com rampa nas pontas."""
    floor = 10 ** (-abs(duck_db) / 20)
    window = f"clip(min((t-{at - RAMP_S:.3f})/{RAMP_S},({end + RAMP_S:.3f}-t)/{RAMP_S}),0,1)"
    return f"1-{1 - floor:.4f}*{window}"


def build_filter(at: float, length: float, gain_db: float, duck_db: float,
                 keep_source: bool) -> str:
    delay = round(at * 1000)
    voice = f"[1:a:0]aresample=48000,aformat=channel_layouts=stereo,volume={gain_db}dB,adelay={delay}:all=1[vo]"
    if not keep_source:
        return f"{voice};[vo]alimiter=limit=0.89:level=false[out]"
    expr = duck_expr(at, at + length, duck_db)
    return (f"{voice};[0:a:0]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume='{expr}':eval=frame[bed];"
            "[bed][vo]amix=inputs=2:duration=first:normalize=0,"
            "alimiter=limit=0.89:level=false[out]")


def gen(args: argparse.Namespace) -> int:
    if not VS.exists():
        print(f"Skill voicestudio não encontrada em {VS}.", file=sys.stderr)
        return 2
    if bool(args.text) == bool(args.file):
        print("Passe --text OU --file.", file=sys.stderr)
        return 1
    out = args.edit_dir / "voiceover" / f"{args.name}.wav"
    if out.exists() and not args.force:
        print(f"{out} já existe; use --force ou outro --name.", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(VS), "say"]
    cmd += ["--file", str(args.file)] if args.file else [args.text]
    cmd += ["-o", str(out), "--voice", args.voice, "--speed", str(args.speed)]
    if args.stop_after:
        cmd.append("--stop-after")
    return subprocess.run(cmd).returncode


def mix(args: argparse.Namespace) -> int:
    for path in (args.video, args.voiceover):
        if not path.exists():
            print(f"Arquivo não encontrado: {path}", file=sys.stderr)
            return 1
    if args.out.resolve() == args.video.resolve():
        print("A saída não pode ser o próprio vídeo.", file=sys.stderr)
        return 1
    if args.at < 0:
        print("--at não pode ser negativo.", file=sys.stderr)
        return 1
    length = duration(args.voiceover)
    total = duration(args.video)
    if args.at + length > total:
        print(f"A locução ({length:.2f} s a partir de {args.at:.2f} s) passa do fim "
              f"do vídeo ({total:.2f} s).", file=sys.stderr)
        return 1
    source = None if args.replace_audio else loudness(args.video)
    vo = loudness(args.voiceover)
    if vo is None:
        print("A locução está sem som.", file=sys.stderr)
        return 1
    gain = match_gain(vo, source)
    keep = has_audio(args.video) and not args.replace_audio
    graph = build_filter(args.at, length, gain, args.duck_db, keep)
    done = run(["ffmpeg", "-y", "-v", "error", "-i", str(args.video), "-i", str(args.voiceover),
                "-filter_complex", graph, "-map", "0:v:0", "-map", "[out]", "-c:v", "copy",
                "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-t", f"{total:.3f}", "-movflags", "+faststart",
                str(args.out)])
    if done.returncode != 0:
        print(done.stderr[-800:], file=sys.stderr)
        return 1
    print(f"{args.out} | locução em {args.at:.2f}-{args.at + length:.2f} s | ganho {gain:+.2f} dB | "
          f"fonte {'sem som' if source is None else f'{source:.1f} LUFS'} | "
          f"saída {loudness(args.out):.1f} LUFS | vídeo copiado sem recodificar")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--edit-dir", type=Path, required=True)
    g.add_argument("--text")
    g.add_argument("--file", type=Path)
    g.add_argument("--name", default="locucao")
    g.add_argument("--voice", default="pf_dora")
    g.add_argument("--speed", type=float, default=1.0)
    g.add_argument("--force", action="store_true")
    g.add_argument("--stop-after", action="store_true")
    m = sub.add_parser("mix")
    m.add_argument("--video", type=Path, required=True)
    m.add_argument("--voiceover", type=Path, required=True)
    m.add_argument("--at", type=float, default=0.0)
    m.add_argument("-o", "--out", type=Path, required=True)
    m.add_argument("--duck-db", type=float, default=12.0)
    m.add_argument("--replace-audio", action="store_true")
    args = ap.parse_args()
    return gen(args) if args.cmd == "gen" else mix(args)


if __name__ == "__main__":
    sys.exit(main())
