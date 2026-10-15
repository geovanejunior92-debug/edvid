"""Resumo de um vídeo de referência em UM JSON: cortes, ritmo, movimento, áudio, fala.

Quando usar: o usuário manda um Reel/TikTok/Short/YouTube (ou um arquivo) e pede
"faz um parecido". As peças já existiam soltas — este helper junta tudo num
`reference_brief.json` e em folhas de contato, para o agente comparar a
referência com o corte dele em número, não de memória.

O que o código mede (tudo local, sem chave de API):
  - cortes: PySceneDetect (ContentDetector) se estiver instalado; senão o filtro
    `select=gt(scene,T)` do ffmpeg. Cortes a menos de --min-shot do anterior
    são fundidos (flash de 2 quadros não é plano).
  - ritmo: cortes por minuto, duração média/mín./máx. dos planos, palavras por
    minuto e uma classe — média > 10 s contemplativo, > 5 s educativo,
    > 2 s dinâmico, abaixo disso rajada.
  - movimento por plano: fluxo óptico Farneback em 360p (lado menor), a 6 qps,
    só entre quadros do mesmo plano. Magnitude em % do lado menor por segundo:
    < 2 parado, < 8 leve, acima disso movimento.
  - energia do áudio: ebur128 do ffmpeg (integrado, LRA, pico, curva por
    segundo, média por plano, gancho contra o resto).
  - fala: transcribe.py (WhisperX, com cache) + gancho/ritmo/fechamento do
    retention.py.

O que o código NÃO mede fica em `para_o_agente`, vazio: técnica do gancho,
estilo de legenda, transições, paleta, tipografia, observações. O agente
preenche olhando as folhas (`sheets/`) e roda `--validate` de novo.

Uso:
    uv run python helpers/reference_brief.py <url ou arquivo>
    uv run python helpers/reference_brief.py <url> --out-dir ~/Videos/referencias/x
    uv run python helpers/reference_brief.py ref.mp4 --no-transcribe
    uv run python helpers/reference_brief.py --validate <dir>/reference_brief.json

Saída: <out-dir>/reference_brief.json, <out-dir>/sheets/shots_*.png (um quadro
por plano, rotulado com duração e movimento) e <out-dir>/sheets/sheet_*.png
(levantamento por cena do watch_video.py). Padrão de --out-dir:
~/Videos/referencias/<nome do vídeo>/.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
sys.path.insert(0, str(HELPERS))

SCHEMA_VERSION = 1
SCENE_THRESHOLD = 0.22        # jump cut de talking head marca 0,25–0,30; ruído de gesto fica ≤ 0,19
MIN_SHOT_S = 0.25
FLOW_FPS = 6.0
FLOW_SHORT_SIDE = 360
MOTION_STILL = 2.0            # % do lado menor por segundo
MOTION_LIGHT = 8.0
SHOTS_PER_SHEET = 24
DEFAULT_ROOT = Path.home() / "Videos" / "referencias"
URL_RE = re.compile(r"^https?://", re.I)

AGENT_FIELDS = ("tecnica_do_gancho", "estilo_de_legenda", "transicoes", "paleta",
                "tipografia", "observacoes")


# ---------------------------------------------------------------- utilidades

def probe(video: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,avg_frame_rate",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True)
    data = json.loads(r.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return {"duration": round(float(data["format"]["duration"]), 3),
            "width": int(v.get("width") or 0), "height": int(v.get("height") or 0),
            "fps": round(fps, 3), "has_audio": has_audio}


def fetch(url: str, dest: Path) -> tuple[Path, dict]:
    """Baixa pelo ingest_url.py (yt-dlp) e devolve o arquivo + metadados."""
    r = subprocess.run([sys.executable, str(HELPERS / "ingest_url.py"), url,
                        "--dest", str(dest), "--max-height", "1080"],
                       stdout=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.exit(f"download falhou (ingest_url.py saiu {r.returncode})")
    start = r.stdout.find("{")
    info = json.loads(r.stdout[start:])
    return Path(info["path"]), info


# ---------------------------------------------------------------- cortes

def merge_cuts(cuts: list[float], duration: float, min_shot: float = MIN_SHOT_S) -> list[float]:
    """Ordena, descarta cortes colados ao início/fim e funde os que ficam a
    menos de min_shot do anterior."""
    out: list[float] = []
    for t in sorted(cuts):
        if t < min_shot or t > duration - min_shot:
            continue
        if out and t - out[-1] < min_shot:
            continue
        out.append(round(t, 3))
    return out


def detect_cuts_ffmpeg(video: Path, threshold: float = SCENE_THRESHOLD) -> list[float]:
    vf = f"scale=-2:{FLOW_SHORT_SIDE},select='gt(scene\\,{threshold})',showinfo"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an",
                        "-vf", vf, "-f", "null", "-"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg scene falhou: {r.stderr.strip()[-400:]}")
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]


def detect_cuts(video: Path, threshold: float = SCENE_THRESHOLD) -> tuple[list[float], str]:
    try:
        from scenedetect import ContentDetector, detect  # type: ignore
    except ImportError:
        return detect_cuts_ffmpeg(video, threshold), f"ffmpeg scene>{threshold}"
    scenes = detect(str(video), ContentDetector())
    return [s[0].get_seconds() for s in scenes[1:]], "pyscenedetect ContentDetector"


def shots_from_cuts(cuts: list[float], duration: float) -> list[dict]:
    edges = [0.0] + cuts + [duration]
    return [{"index": i, "start": round(a, 3), "end": round(b, 3), "duration": round(b - a, 3)}
            for i, (a, b) in enumerate(zip(edges, edges[1:])) if b - a > 0]


# ---------------------------------------------------------------- ritmo

def pacing_class(mean_shot_s: float) -> str:
    if mean_shot_s > 10:
        return "contemplativo"
    if mean_shot_s > 5:
        return "educativo"
    if mean_shot_s > 2:
        return "dinamico"
    return "rajada"


def pacing_profile(shots: list[dict], duration: float, n_words: int | None) -> dict:
    durs = [s["duration"] for s in shots] or [duration]
    mean = sum(durs) / len(durs)
    minutes = duration / 60 if duration else 0
    return {
        "cortes": max(0, len(shots) - 1),
        "planos": len(shots),
        "cortes_por_minuto": round((len(shots) - 1) / minutes, 1) if minutes else 0.0,
        "plano_medio_s": round(mean, 2),
        "plano_min_s": round(min(durs), 2),
        "plano_max_s": round(max(durs), 2),
        "palavras_por_minuto": round(n_words / minutes, 1) if (n_words and minutes) else None,
        "classe": pacing_class(mean),
    }


# ---------------------------------------------------------------- movimento

def motion_class(pct_per_s: float | None) -> str | None:
    if pct_per_s is None:
        return None
    if pct_per_s < MOTION_STILL:
        return "parado"
    if pct_per_s < MOTION_LIGHT:
        return "leve"
    return "movimento"


def _gray_frames(video: Path, width: int, height: int):
    """Quadros em cinza a FLOW_FPS, lado menor = FLOW_SHORT_SIDE, via pipe."""
    import numpy as np
    if width >= height:
        h = FLOW_SHORT_SIDE
        w = int(round(width * h / height / 2)) * 2
    else:
        w = FLOW_SHORT_SIDE
        h = int(round(height * w / width / 2)) * 2
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-an",
         "-vf", f"fps={FLOW_FPS},scale={w}:{h}", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE)
    size = w * h
    i = 0
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield i / FLOW_FPS, np.frombuffer(buf, np.uint8).reshape(h, w)
        i += 1
    proc.stdout.close()
    proc.wait()


def shot_motion(video: Path, shots: list[dict], width: int, height: int) -> None:
    """Preenche movimento_pct_s / movimento / camera_pct_s em cada plano."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        for s in shots:
            s.update(movimento_pct_s=None, movimento=None, camera_pct_s=None)
        return
    acc = {s["index"]: [] for s in shots}
    cam = {s["index"]: [] for s in shots}

    def shot_of(t: float) -> int | None:
        for s in shots:
            if s["start"] <= t < s["end"]:
                return s["index"]
        return None

    prev_t, prev, prev_shot = None, None, None
    for t, frame in _gray_frames(video, width, height):
        cur_shot = shot_of(t)
        if prev is not None and cur_shot is not None and cur_shot == prev_shot:
            flow = cv2.calcOpticalFlowFarneback(prev, frame, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mag = np.linalg.norm(flow, axis=2)
            scale = 100.0 * FLOW_FPS / FLOW_SHORT_SIDE   # px/passo → % lado menor/s
            acc[cur_shot].append(float(mag.mean()) * scale)
            # vetor mediano ≈ movimento de câmera (a maior parte do quadro anda junto)
            med = np.median(flow.reshape(-1, 2), axis=0)
            cam[cur_shot].append(float(np.hypot(*med)) * scale)
        prev_t, prev, prev_shot = t, frame, cur_shot
    for s in shots:
        vals = acc[s["index"]]
        pct = round(sum(vals) / len(vals), 2) if vals else None
        cvals = cam[s["index"]]
        s["movimento_pct_s"] = pct
        s["movimento"] = motion_class(pct)
        s["camera_pct_s"] = round(sum(cvals) / len(cvals), 2) if cvals else None


# ---------------------------------------------------------------- áudio

def parse_ebur128(stderr: str) -> dict:
    series = [(float(t), float(m)) for t, m in
              re.findall(r"t:\s*([0-9.]+)\s+TARGET:\S+\s+LUFS\s+M:\s*(-?[0-9.]+|-inf)", stderr)
              if m != "-inf"]
    if not series:   # versões do ffmpeg sem TARGET na linha
        series = [(float(t), float(m)) for t, m in
                  re.findall(r"t:\s*([0-9.]+).*?M:\s*(-?[0-9.]+)", stderr)]
    summary = stderr[stderr.rfind("Summary:"):] if "Summary:" in stderr else ""
    def grab(label: str) -> float | None:
        m = re.search(label + r":\s*(-?[0-9.]+)", summary)
        return float(m.group(1)) if m else None
    return {"series": series, "integrated_lufs": grab("I"), "lra_lu": grab("LRA"),
            "peak_dbfs": grab("Peak")}


def audio_energy(video: Path, shots: list[dict], has_audio: bool) -> dict:
    if not has_audio:
        for s in shots:
            s["loudness_lufs"] = None
        return {"tem_audio": False}
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vn",
                        "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    p = parse_ebur128(r.stderr)
    series = [(t, m) for t, m in p["series"] if m > -70]   # -70 = silêncio digital

    def mean_between(a: float, b: float) -> float | None:
        vals = [m for t, m in series if a <= t < b]
        return round(sum(vals) / len(vals), 1) if vals else None

    for s in shots:
        s["loudness_lufs"] = mean_between(s["start"], s["end"])
    end = series[-1][0] if series else 0
    per_second = [mean_between(i, i + 1) for i in range(int(end) + 1)]
    hook, rest = mean_between(0, 3), mean_between(3, end + 1)
    return {"tem_audio": True, "integrado_lufs": p["integrated_lufs"], "lra_lu": p["lra_lu"],
            "pico_dbfs": p["peak_dbfs"], "gancho_lufs": hook, "resto_lufs": rest,
            "gancho_menos_resto_lu": round(hook - rest, 1) if (hook is not None and rest is not None) else None,
            "curva_por_segundo_lufs": per_second}


# ---------------------------------------------------------------- fala

def speech(video: Path, work: Path, language: str | None) -> dict | None:
    import retention
    from transcribe import transcribe_one
    path = transcribe_one(video, work, language=language, verbose=False)
    words = retention.load_words(path)
    if not words:
        return {"transcript": str(path), "palavras": 0}
    total = probe(video)["duration"]
    spoken = sum(w["end"] - w["start"] for w in words)
    pc = retention.pacing(words, total)
    return {"transcript": str(path), "palavras": len(words),
            "texto": " ".join(w["word"] for w in words),
            "ar_morto_pct": round(100 * (1 - spoken / total), 0),
            "gancho": retention.hook_score(words),
            "ritmo_fala": {"mediana_palavras_s": pc.get("median_wps"),
                           "pausa_mais_longa": pc.get("longest_pause"),
                           "arrastos": pc.get("drags", [])},
            "fechamento": retention.ending(words, total)}


# ---------------------------------------------------------------- folhas

def shot_sheets(video: Path, shots: list[dict], sheets_dir: Path) -> list[str]:
    out = []
    for page in range(0, len(shots), SHOTS_PER_SHEET):
        chunk = shots[page:page + SHOTS_PER_SHEET]
        times = [round((s["start"] + s["end"]) / 2, 3) for s in chunk]
        labels = [f"#{s['index'] + 1} {s['start']:.1f}s ({s['duration']:.1f}s) {s.get('movimento') or ''}".strip()
                  for s in chunk]
        dest = sheets_dir / f"shots_{page // SHOTS_PER_SHEET + 1:02d}.png"
        subprocess.run([sys.executable, str(HELPERS / "contact_sheet.py"), str(video),
                        "--times", *map(str, times), "--labels", ",".join(l.replace(",", " ") for l in labels),
                        "-o", str(dest), "--cols", "6"],
                       check=True, stdout=subprocess.DEVNULL)
        out.append(str(dest))
    return out


def scene_sheets(video: Path, sheets_dir: Path) -> list[str]:
    subprocess.run([sys.executable, str(HELPERS / "watch_video.py"), str(video),
                    "--max-frames", "24", "-o", str(sheets_dir)],
                   check=True, stdout=subprocess.DEVNULL)
    return sorted(str(p) for p in sheets_dir.glob("sheet_*.png"))


# ---------------------------------------------------------------- validação

def validate_brief(brief: dict) -> list[str]:
    """Lista de problemas; vazia = válido."""
    errs = []
    if brief.get("schema") != SCHEMA_VERSION:
        errs.append(f"schema != {SCHEMA_VERSION}")
    for key in ("fonte", "video", "cortes", "planos", "ritmo", "audio", "folhas", "para_o_agente"):
        if key not in brief:
            errs.append(f"falta '{key}'")
    if errs:
        return errs
    dur = brief["video"].get("duration") or 0
    shots = brief["planos"]
    if not shots:
        errs.append("nenhum plano")
    else:
        if abs(shots[0]["start"]) > 1e-6 or abs(shots[-1]["end"] - dur) > 0.05:
            errs.append("planos não cobrem o vídeo do início ao fim")
        for a, b in zip(shots, shots[1:]):
            if abs(a["end"] - b["start"]) > 1e-6:
                errs.append(f"buraco entre planos {a['index']} e {b['index']}")
                break
        if abs(sum(s["duration"] for s in shots) - dur) > 0.05:
            errs.append("soma dos planos ≠ duração")
        bad = [s["index"] for s in shots if s.get("movimento") not in (None, "parado", "leve", "movimento")]
        if bad:
            errs.append(f"movimento inválido nos planos {bad}")
    if len(brief["cortes"]) != len(shots) - 1:
        errs.append("nº de cortes ≠ planos − 1")
    if brief["ritmo"].get("classe") not in ("contemplativo", "educativo", "dinamico", "rajada"):
        errs.append("classe de ritmo inválida")
    missing = [f for f in AGENT_FIELDS if f not in brief["para_o_agente"]]
    if missing:
        errs.append(f"para_o_agente sem {missing}")
    for p in brief["folhas"].get("planos", []) + brief["folhas"].get("cenas", []):
        if not Path(p).exists():
            errs.append(f"folha ausente: {p}")
    return errs


# ---------------------------------------------------------------- main

def build(source: str, out_dir: Path | None, transcribe: bool, language: str | None,
          threshold: float) -> Path:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        sys.exit("ffmpeg/ffprobe não estão no PATH")
    meta: dict = {}
    if URL_RE.match(source):
        dl_dir = (out_dir or DEFAULT_ROOT / "_downloads").resolve()
        video, meta = fetch(source, dl_dir)
        out_dir = out_dir or DEFAULT_ROOT / video.stem
    else:
        video = Path(source).expanduser().resolve()
        if not video.exists():
            sys.exit(f"arquivo não encontrado: {video}")
        out_dir = out_dir or DEFAULT_ROOT / video.stem
    out_dir = out_dir.expanduser().resolve()
    sheets_dir = out_dir / "sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)
    for old in sheets_dir.glob("shots_*.png"):
        old.unlink()

    info = probe(video)
    raw, engine = detect_cuts(video, threshold)
    cuts = merge_cuts(raw, info["duration"])
    shots = shots_from_cuts(cuts, info["duration"])
    print(f"  {len(shots)} planos ({engine}); medindo movimento…", file=sys.stderr)
    shot_motion(video, shots, info["width"], info["height"])
    audio = audio_energy(video, shots, info["has_audio"])

    fala = None
    if transcribe and info["has_audio"]:
        print("  transcrevendo (WhisperX, com cache)…", file=sys.stderr)
        fala = speech(video, out_dir, language)

    counts = {k: sum(1 for s in shots if s.get("movimento") == k) for k in ("parado", "leve", "movimento")}
    brief = {
        "schema": SCHEMA_VERSION,
        "fonte": {"entrada": source, "arquivo": str(video),
                  **{k: meta.get(k) for k in ("title", "uploader", "source_url", "upload_date") if meta.get(k)}},
        "video": {**info, "orientacao": "vertical" if info["height"] > info["width"] else "horizontal"},
        "detector_de_cortes": engine,
        "cortes": cuts,
        "planos": shots,
        "ritmo": pacing_profile(shots, info["duration"], fala["palavras"] if fala else None),
        "movimento_resumo": counts,
        "audio": audio,
        "fala": fala,
        "folhas": {"planos": shot_sheets(video, shots, sheets_dir),
                   "cenas": scene_sheets(video, sheets_dir)},
        "para_o_agente": {k: None for k in AGENT_FIELDS},
    }
    errs = validate_brief(brief)
    if errs:
        sys.exit("brief inválido: " + "; ".join(errs))
    dest = out_dir / "reference_brief.json"
    dest.write_text(json.dumps(brief, ensure_ascii=False, indent=2))
    return dest


def summary(brief: dict) -> str:
    r, a, f = brief["ritmo"], brief["audio"], brief.get("fala") or {}
    lines = [f"{Path(brief['fonte']['arquivo']).name} — {brief['video']['duration']:.1f}s "
             f"{brief['video']['width']}×{brief['video']['height']}",
             f"  RITMO {r['classe']}: {r['planos']} planos, {r['cortes_por_minuto']} cortes/min, "
             f"plano médio {r['plano_medio_s']}s (mín {r['plano_min_s']}, máx {r['plano_max_s']})"
             + (f", {r['palavras_por_minuto']} palavras/min" if r.get("palavras_por_minuto") else ""),
             f"  MOVIMENTO {brief['movimento_resumo']}"]
    if a.get("tem_audio"):
        lines.append(f"  ÁUDIO {a['integrado_lufs']} LUFS, LRA {a['lra_lu']} LU, "
                     f"gancho − resto {a['gancho_menos_resto_lu']} LU")
    if f.get("gancho"):
        lines.append(f"  GANCHO {f['gancho']['score']}/10 «{f['gancho']['text'][:90]}»")
    lines.append("  folhas: " + ", ".join(brief["folhas"]["planos"] + brief["folhas"]["cenas"]))
    lines.append("  falta o agente preencher para_o_agente: " + ", ".join(AGENT_FIELDS))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", nargs="?", help="link (Reel, TikTok, Short, YouTube) ou arquivo local")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help=f"padrão: {DEFAULT_ROOT}/<nome do vídeo>/")
    ap.add_argument("--no-transcribe", action="store_true", help="pula WhisperX (só imagem e áudio)")
    ap.add_argument("--language", default=None, help="código ISO da fala (ex. pt); omitir = detectar")
    ap.add_argument("--threshold", type=float, default=SCENE_THRESHOLD,
                    help=f"limiar do ffmpeg scene (padrão {SCENE_THRESHOLD})")
    ap.add_argument("--validate", type=Path, default=None, metavar="JSON",
                    help="só valida um reference_brief.json existente")
    args = ap.parse_args()

    if args.validate:
        errs = validate_brief(json.loads(args.validate.read_text()))
        print("OK" if not errs else "\n".join(errs))
        return 1 if errs else 0
    if not args.source:
        ap.error("informe um link ou arquivo (ou --validate)")
    dest = build(args.source, args.out_dir, not args.no_transcribe, args.language, args.threshold)
    print(summary(json.loads(dest.read_text())))
    print(str(dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
