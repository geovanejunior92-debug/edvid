"""Cadeia de diálogo profissional, aplicada UMA vez por fonte e cacheada.

O que um editor de diálogo faz antes de qualquer mixagem, na ordem:

  1. Ruído / isolamento de voz — RNNoise (ffmpeg `arnndn`, ~140x tempo real) por
     padrão; Demucs (separação de fonte, vocals) quando o fundo é música, trânsito
     ou outra voz — coisa que um denoiser de ruído estacionário não tira.
  2. Respiração — cada inspiração entre palavras cai -14 dB (não some: respiração
     zerada soa como corte). Só é candidata o que fica ENTRE duas palavras do
     transcript, acima do piso e bem abaixo da fala, com espectro de sopro.
  3. Nivelamento por frase — cada frase é puxada para a mediana da própria voz
     (P75 dos quadros de fala, como o `voice_levels.py`), com teto de +6/-3 dB e
     rampas suaves. Complementa o `gain_db` por take, que é grosso demais para
     uma frase engolida no meio de um take bom.
  4. Tom de sala — 1,5 s do silêncio mais limpo do ORIGINAL vira uma cama
     constante sob a faixa limpa. Sem isso o denoise deixa pausas de silêncio
     digital e todo corte "respira". É a técnica de sempre: limpa, depois põe
     um piso consistente e baixo.

A saída é um WAV que o `render.py --audio-clean` usa no lugar do áudio da
fonte, extraído por range como sempre (Hard Rule 2 intacta). O `.json` ao lado
é o cache: mesma fonte, mesmos parâmetros → não roda de novo.

Usage:
    uv run python helpers/audio_clean.py <source> --edit-dir <edit>
    uv run python helpers/audio_clean.py <source> --edit-dir <edit> --denoise demucs
    uv run python helpers/audio_clean.py <source> --edit-dir <edit> --no-breath --no-level
    uv run python helpers/audio_clean.py <source> --edit-dir <edit> --force

Saídas em <edit>/audio_clean/:
    <stem>.wav            faixa limpa, 48 kHz, mesmos canais da fonte (máx 2)
    <stem>.roomtone.wav   a cama extraída do original
    <stem>.json           relatório + chave de cache

Depois rode `check_audio.py` — ele compara antes/depois em número e monta o
A/B para ouvir. Este script limpa; ele é quem diz se a limpeza prestou.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_levels import estimate_floor as speech_gate  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
RNNOISE_DIR = SKILL_DIR / "assets" / "audio" / "rnnoise"
SR = 48000
FRAME = 1024  # ~21 ms @ 48k — mesma janela do voice_levels.py

# Modelos RNNoise (GregorR/rnnoise-models). `sh` é o de uso geral; os outros
# ficam disponíveis para quando o material pedir.
RNN_MODELS = {"sh": "somnolent-hogwash", "bd": "beguiling-drafter",
              "mp": "marathon-prescription", "lq": "leavened-quisling",
              "cb": "conjoined-burgers"}


# ---------------------------------------------------------------- io

def ffprobe_audio(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=channels,sample_rate,codec_name:format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    streams = data.get("streams") or []
    if not streams:
        raise SystemExit(f"{path.name}: sem trilha de áudio")
    return {"channels": int(streams[0].get("channels") or 1),
            "duration": float(data["format"].get("duration") or 0.0)}


def decode(path: Path, channels: int) -> np.ndarray:
    """float32 (n, channels) a 48 kHz via ffmpeg."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", str(channels),
         "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    return x.reshape(-1, channels)


def encode(x: np.ndarray, path: Path, limiter: bool = True) -> None:
    """(n, channels) float32 → WAV 24-bit 48 kHz, com limiter de segurança."""
    af = "alimiter=level_in=1:level_out=1:limit=0.95:attack=5:release=50" if limiter else "anull"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR),
         "-ac", str(x.shape[1]), "-i", "-", "-af", af,
         "-c:a", "pcm_s24le", str(path)],
        input=np.ascontiguousarray(x, dtype=np.float32).tobytes(), check=True)


# ---------------------------------------------------------------- análise

def mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.shape[1] > 1 else x[:, 0]


def frame_rms_db(m: np.ndarray, frame: int = FRAME) -> tuple[np.ndarray, np.ndarray]:
    """(tempos, dBFS) por janela de `frame` amostras."""
    n = len(m) // frame
    if n == 0:
        return np.zeros(1), np.full(1, -120.0)
    blocks = m[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(blocks.astype(np.float64) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    times = np.arange(n) * frame / SR
    return times, db


def floor_and_gate(levels: np.ndarray) -> tuple[float, float]:
    """(piso de ruído, gate fala/silêncio), aprendidos da gravação.

    O gate é o do `voice_levels.py` (intermeans de Ridler-Calvard, clampado
    12–32 dB abaixo da mediana da fala): separa sala de voz. O piso é OUTRA
    coisa: o nível real da sala, mediana dos quadros abaixo do gate. Confundir
    os dois foi o primeiro erro deste helper — o gate de um arquivo falado cai
    a ~10 dB da voz, e tratá-lo como piso fazia a cama de tom de sala entrar a
    -48 dB numa sala de -64.
    """
    gate = speech_gate(levels)
    below = levels[(levels < gate) & (levels > -119)]
    floor = float(np.median(below)) if below.size else gate - 10.0
    return floor, gate


def speech_p75(levels: np.ndarray, gate_db: float) -> float:
    sp = levels[levels > gate_db]
    return float(np.percentile(sp, 75)) if sp.size else gate_db + 20


def load_words(edit_dir: Path, stem: str) -> list[dict]:
    p = edit_dir / "transcripts" / f"{stem}.json"
    if not p.exists():
        return []
    words = []
    for w in json.loads(p.read_text()).get("words") or []:
        if w.get("type", "word") != "word":
            continue
        try:
            words.append({"word": (w.get("text") or w.get("word") or "").strip(),
                          "start": float(w["start"]), "end": float(w["end"])})
        except (KeyError, TypeError, ValueError):
            continue
    return words


def group_phrases(words: list[dict], gap_s: float = 0.5) -> list[dict]:
    phrases, cur = [], []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] >= gap_s:
            phrases.append(cur)
            cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return [{"start": p[0]["start"], "end": p[-1]["end"],
             "text": " ".join(w["word"] for w in p)} for p in phrases]


def spectral_centroid(seg: np.ndarray) -> float:
    if len(seg) < 256:
        return 0.0
    win = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(win))
    freqs = np.fft.rfftfreq(len(win), 1 / SR)
    total = spec.sum()
    return float((spec * freqs).sum() / total) if total > 0 else 0.0


# ---------------------------------------------------------------- etapas

def stage_denoise(x: np.ndarray, mode: str, rnn_model: str, rnn_mix: float,
                  tmp: Path) -> tuple[np.ndarray, str]:
    """Devolve (áudio, descrição)."""
    if mode == "off":
        return x, "denoise desligado"

    src = tmp / "in.wav"
    encode(x, src, limiter=False)
    cur = src
    notes = []

    if mode in ("demucs", "both"):
        out_dir = tmp / "demucs"
        stem_dir = out_dir / "htdemucs" / "in"
        cmd = [sys.executable, "-m", "demucs.separate", "--two-stems=vocals",
               "-n", "htdemucs", "-o", str(out_dir), str(cur)]
        ok = False
        for device in ("mps", "cpu"):
            proc = subprocess.run(cmd + ["-d", device], capture_output=True, text=True)
            if proc.returncode == 0 and (stem_dir / "vocals.wav").exists():
                notes.append(f"demucs vocals ({device})")
                ok = True
                break
        if not ok:
            raise SystemExit(f"demucs falhou:\n{proc.stderr[-1500:]}")
        cur = stem_dir / "vocals.wav"

    if mode in ("rnnoise", "both"):
        model = RNNOISE_DIR / f"{rnn_model}.rnnn"
        if not model.exists():
            raise SystemExit(f"modelo RNNoise não encontrado: {model}")
        mix = rnn_mix if mode == "rnnoise" else min(rnn_mix, 0.6)
        out = tmp / "rnn.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(cur),
                        "-af", f"arnndn=m={model}:mix={mix:.2f}",
                        "-ar", str(SR), "-c:a", "pcm_f32le", str(out)], check=True)
        notes.append(f"rnnoise {RNN_MODELS.get(rnn_model, rnn_model)} mix {mix:.2f}")
        cur = out

    y = decode(cur, x.shape[1])
    # demucs pode devolver 1–2 amostras a mais/menos: alinha ao original
    if len(y) != len(x):
        if len(y) > len(x):
            y = y[: len(x)]
        else:
            y = np.vstack([y, np.zeros((len(x) - len(y), x.shape[1]), np.float32)])
    return y, " + ".join(notes)


def stage_breath(x: np.ndarray, words: list[dict], floor_db: float,
                 speech_db: float, atten_db: float) -> tuple[np.ndarray, list[dict]]:
    """Atenua respirações entre palavras. Devolve (áudio, lista)."""
    if len(words) < 2:
        return x, []
    m = mono(x)
    hop = FRAME // 4  # 5 ms de resolução para achar bordas
    n = len(m) // hop
    env = np.sqrt(np.convolve(m.astype(np.float64) ** 2,
                              np.ones(FRAME) / FRAME, mode="same"))
    env_db = 20 * np.log10(np.maximum(env, 1e-6))

    gain = np.ones(len(m), dtype=np.float32)
    found = []
    lo = floor_db + 6.0
    hi = speech_db - 10.0
    if hi <= lo:
        return x, []
    ramp = int(0.015 * SR)
    atten = 10 ** (atten_db / 20)

    for prev, nxt in zip(words, words[1:]):
        gap_start = prev["end"] + 0.02
        gap_end = nxt["start"] - 0.02
        if gap_end - gap_start < 0.12:
            continue
        a, b = int(gap_start * SR), int(gap_end * SR)
        if b <= a or b > len(m):
            continue
        region = env_db[a:b]
        above = region > lo
        if not above.any():
            continue
        # blocos contíguos acima do piso
        idx = np.flatnonzero(np.diff(np.concatenate([[0], above.astype(int), [0]])))
        for s, e in zip(idx[::2], idx[1::2]):
            dur = (e - s) / SR
            if not (0.06 <= dur <= 0.7):
                continue
            seg = m[a + s: a + e]
            peak_db = float(region[s:e].max())
            if peak_db > hi:
                continue  # alto demais: sílaba, não sopro
            if spectral_centroid(seg) < 1200:
                continue  # grave demais: ruído de manuseio ou voz
            gs, ge = a + s, a + e
            gain[gs:ge] = atten
            r0 = max(0, gs - ramp)
            gain[r0:gs] = np.linspace(1.0, atten, gs - r0)
            r1 = min(len(m), ge + ramp)
            gain[ge:r1] = np.linspace(atten, 1.0, r1 - ge)
            found.append({"start": round(gs / SR, 3), "end": round(ge / SR, 3),
                          "peak_db": round(peak_db, 1)})
    if not found:
        return x, []
    return x * gain[:, None], found


def stage_level(x: np.ndarray, words: list[dict], gate_db: float,
                max_boost: float = 6.0, max_cut: float = -3.0) -> tuple[np.ndarray, list[dict]]:
    """Nivelamento por frase para a mediana da própria voz."""
    phrases = group_phrases(words)
    if len(phrases) < 3:
        return x, []
    m = mono(x)
    times, levels = frame_rms_db(m)
    per = []
    for p in phrases:
        sel = (times >= p["start"]) & (times < p["end"])
        lv = levels[sel]
        if lv.size == 0:
            continue
        p75 = speech_p75(lv, gate_db)
        per.append({**p, "level": p75})
    if len(per) < 3:
        return x, []
    target = float(np.median([p["level"] for p in per]))
    env = np.zeros(len(m), dtype=np.float32)  # em dB
    pad = int(0.05 * SR)
    report = []
    for p in per:
        g = float(np.clip(target - p["level"], max_cut, max_boost))
        a = max(0, int(p["start"] * SR) - pad)
        b = min(len(m), int(p["end"] * SR) + pad)
        env[a:b] = g
        if abs(g) >= 0.75:
            report.append({"start": round(p["start"], 2), "end": round(p["end"], 2),
                           "text": p["text"][:60], "level": round(p["level"], 1),
                           "gain": round(g, 1)})
    # rampas: média móvel de 100 ms
    k = int(0.1 * SR)
    env = np.convolve(env, np.ones(k) / k, mode="same").astype(np.float32)
    lin = (10 ** (env / 20)).astype(np.float32)
    return x * lin[:, None], sorted(report, key=lambda r: -abs(r["gain"]))


def stage_roomtone(orig: np.ndarray, floor_db: float, out: Path,
                   want_s: float = 1.5) -> dict:
    """Extrai a cama do ORIGINAL e devolve {start,end,rms_db,path}."""
    m = mono(orig)
    times, levels = frame_rms_db(m)
    quiet = levels <= floor_db
    idx = np.flatnonzero(np.diff(np.concatenate([[0], quiet.astype(int), [0]])))
    best = None
    for s, e in zip(idx[::2], idx[1::2]):
        if best is None or (e - s) > (best[1] - best[0]):
            best = (s, e)
    if best is None or (best[1] - best[0]) * FRAME / SR < 0.4:
        # sem silêncio útil: os 0,5 s mais baixos
        order = np.argsort(levels)
        s = int(order[0])
        best = (s, s + max(1, int(0.5 * SR / FRAME)))
    s_t, e_t = best[0] * FRAME / SR, best[1] * FRAME / SR
    take = min(want_s, e_t - s_t)
    mid = (s_t + e_t) / 2
    a = int(max(s_t, mid - take / 2) * SR)
    b = int(min(e_t, mid + take / 2) * SR)
    seg = orig[a:b].copy()
    fade = int(0.01 * SR)
    if len(seg) > 2 * fade:
        seg[:fade] *= np.linspace(0, 1, fade)[:, None]
        seg[-fade:] *= np.linspace(1, 0, fade)[:, None]
    rms = float(np.sqrt(np.mean(mono(seg) ** 2))) if len(seg) else 1e-6
    encode(seg, out, limiter=False)
    return {"start": round(a / SR, 2), "end": round(b / SR, 2),
            "rms_db": round(20 * math.log10(max(rms, 1e-6)), 1), "path": out.name}


def apply_bed(x: np.ndarray, bed: np.ndarray, bed_rms_db: float,
              floor_before: float) -> tuple[np.ndarray, float]:
    """Cama constante sob a faixa: alvo = piso original - 12 dB, entre -72 e -54.

    Baixa o bastante para o denoise render SNR de verdade (uma sala de -43 dB
    vira -55), alta o bastante para as pausas não virarem preto digital.
    """
    target = float(np.clip(floor_before - 12.0, -72.0, -54.0))
    if len(bed) == 0:
        return x, target
    gain = 10 ** ((target - bed_rms_db) / 20)
    reps = int(math.ceil(len(x) / len(bed)))
    tiled = np.tile(bed, (reps, 1))[: len(x)]
    if tiled.shape[1] != x.shape[1]:
        tiled = np.repeat(mono(tiled)[:, None], x.shape[1], axis=1)
    return x + tiled * gain, target


# ---------------------------------------------------------------- main

def cache_key(source: Path, params: dict) -> str:
    st = source.stat()
    blob = json.dumps({"size": st.st_size, "mtime": int(st.st_mtime), **params},
                      sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", type=Path)
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--denoise", choices=["rnnoise", "demucs", "both", "off"],
                    default="rnnoise")
    ap.add_argument("--rnn-model", choices=sorted(RNN_MODELS), default="sh")
    ap.add_argument("--rnn-mix", type=float, default=0.85,
                    help="quanto do denoise entra (1 = tudo; <1 deixa ar)")
    ap.add_argument("--no-breath", action="store_true")
    ap.add_argument("--breath-db", type=float, default=-14.0)
    ap.add_argument("--no-level", action="store_true")
    ap.add_argument("--no-bed", action="store_true", help="sem cama de tom de sala")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    source = args.source.expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"fonte não existe: {source}")
    edit_dir = args.edit_dir.expanduser().resolve()
    out_dir = edit_dir / "audio_clean"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    wav_out = out_dir / f"{stem}.wav"
    bed_out = out_dir / f"{stem}.roomtone.wav"
    json_out = out_dir / f"{stem}.json"

    params = {"denoise": args.denoise, "rnn_model": args.rnn_model,
              "rnn_mix": args.rnn_mix, "breath": not args.no_breath,
              "breath_db": args.breath_db, "level": not args.no_level,
              "bed": not args.no_bed, "v": 1}
    key = cache_key(source, params)
    if not args.force and json_out.exists() and wav_out.exists():
        try:
            if json.loads(json_out.read_text()).get("cache_key") == key:
                print(f"cache: {wav_out.name} já limpo com estes parâmetros "
                      f"(--force refaz)")
                return 0
        except json.JSONDecodeError:
            pass

    info = ffprobe_audio(source)
    channels = min(info["channels"], 2)
    print(f"{source.name}: {info['duration']:.1f}s, {channels} canal(is)")
    orig = decode(source, channels)

    _, lv0 = frame_rms_db(mono(orig))
    floor0, gate0 = floor_and_gate(lv0)
    speech0 = speech_p75(lv0, gate0)
    print(f"  original: piso {floor0:.1f} dB, fala P75 {speech0:.1f} dB, "
          f"SNR {speech0 - floor0:.0f} dB")

    words = load_words(edit_dir, stem)
    if not words:
        print("  sem transcript em edit/transcripts/ → respiração e nivelamento "
              "pulam (rode transcribe.py antes para tê-los)")

    report = {"source": str(source), "cache_key": key, "params": params,
              "duration": info["duration"], "channels": channels,
              "before": {"floor_db": round(floor0, 1), "gate_db": round(gate0, 1),
                         "speech_p75_db": round(speech0, 1)}}

    with tempfile.TemporaryDirectory(prefix="edvid-audio-") as tmp_s:
        tmp = Path(tmp_s)

        bed_info = stage_roomtone(orig, gate0, bed_out)
        report["roomtone"] = bed_info
        print(f"  tom de sala: {bed_info['start']}–{bed_info['end']}s "
              f"({bed_info['rms_db']} dB)")

        x, note = stage_denoise(orig, args.denoise, args.rnn_model, args.rnn_mix, tmp)
        report["denoise"] = note
        print(f"  denoise: {note}")

        _, lv1 = frame_rms_db(mono(x))
        floor1, gate1 = floor_and_gate(lv1)
        speech1 = speech_p75(lv1, gate1)

        if words and not args.no_breath:
            x, breaths = stage_breath(x, words, floor1, speech1, args.breath_db)
            report["breaths"] = breaths
            print(f"  respirações: {len(breaths)} atenuadas em {args.breath_db:+.0f} dB")

        if words and not args.no_level:
            x, leveled = stage_level(x, words, gate1)
            report["leveler"] = leveled
            if leveled:
                worst = leveled[0]
                print(f"  nivelamento: {len(leveled)} frase(s) ajustada(s); maior "
                      f"{worst['gain']:+.1f} dB em \"{worst['text'][:40]}…\"")
            else:
                print("  nivelamento: frases já dentro de ±0,75 dB da mediana")

        if not args.no_bed:
            bed = decode(bed_out, channels)
            x, bed_db = apply_bed(x, bed, bed_info["rms_db"], floor0)
            report["bed_db"] = round(bed_db, 1)
            print(f"  cama: {bed_db:.0f} dB constante sob a faixa")

        encode(x, wav_out)

    _, lv2 = frame_rms_db(mono(decode(wav_out, channels)))
    floor2, gate2 = floor_and_gate(lv2)
    speech2 = speech_p75(lv2, gate2)
    report["after"] = {"floor_db": round(floor2, 1), "gate_db": round(gate2, 1),
                       "speech_p75_db": round(speech2, 1)}
    json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"  limpo: piso {floor2:.1f} dB, fala P75 {speech2:.1f} dB, "
          f"SNR {speech2 - floor2:.0f} dB → {wav_out}")
    print("agora: check_audio.py para o veredito numérico e o A/B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
