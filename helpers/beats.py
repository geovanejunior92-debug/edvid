"""Batidas da trilha e cortes no compasso.

Um flash ou um efeito sonoro que cai 80 ms fora da batida parece errado sem
ninguém saber por quê; em cima dela, parece intencional. Este helper acha as
batidas da trilha (sem librosa: fluxo espectral → onsets → tempo por
autocorrelação → grade de batidas com a fase que mais casa com os onsets) e
move o que é MOVÍVEL para a batida mais próxima:

  transitions[].at   flashes de corte     (no edit-data.json)
  sfxCues[].at       efeitos avulsos
  graphics[].start   entrada de gráficos

O corte em si NÃO se move: ele é da fala (regra 4/5). O que se ajusta é o
acento em cima dele, dentro de --tolerance (padrão 120 ms). Também sugere o
deslocamento da trilha que faria o maior número de CORTES (segments.json)
cair em batida — informação para você, porque o template não tem offset de
trilha ainda.

Usage:
    uv run python helpers/beats.py <edit>/remotion/public/trilha.mp3
    uv run python helpers/beats.py trilha.mp3 --snap <edit>/remotion/public/edit-data.json [--tolerance 0.12] [--apply]

Escreve <trilha>.beats.json ao lado da trilha.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

SR = 22050
N_FFT = 1024
HOP = 256


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def onset_envelope(x: np.ndarray) -> np.ndarray:
    n = 1 + (len(x) - N_FFT) // HOP
    if n <= 2:
        return np.zeros(1)
    win = np.hanning(N_FFT).astype(np.float32)
    frames = np.lib.stride_tricks.as_strided(x, shape=(n, N_FFT), strides=(x.strides[0] * HOP, x.strides[0]))
    spec = np.abs(np.fft.rfft(frames * win, axis=1))
    spec = np.log1p(spec * 10)
    flux = np.diff(spec, axis=0)
    flux = np.maximum(flux, 0).sum(axis=1)
    env = np.concatenate([[0.0], flux])
    k = 3
    env = np.convolve(env, np.ones(k) / k, mode="same")
    return env / (env.max() or 1)


def pick_onsets(env: np.ndarray, min_dist_s: float = 0.12) -> np.ndarray:
    fps = SR / HOP
    w = int(0.35 * fps)
    local = np.convolve(env, np.ones(2 * w + 1) / (2 * w + 1), mode="same")
    thr = local + 0.08
    peaks = []
    last = -1e9
    for i in range(1, len(env) - 1):
        if env[i] > thr[i] and env[i] >= env[i - 1] and env[i] >= env[i + 1]:
            if i - last >= min_dist_s * fps:
                peaks.append(i); last = i
    return np.array(peaks) / fps


def estimate_tempo(env: np.ndarray) -> float:
    fps = SR / HOP
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac /= ac[0] or 1
    lo, hi = int(fps * 60 / 200), int(fps * 60 / 60)  # 200–60 BPM
    lag = lo + int(np.argmax(ac[lo:hi]))
    bpm = 60 * fps / lag
    # prefere a faixa 80–160 (dobra ou divide)
    while bpm < 80:
        bpm *= 2
    while bpm > 160:
        bpm /= 2
    return float(bpm)


def beat_grid(onsets: np.ndarray, bpm: float, duration: float) -> np.ndarray:
    period = 60 / bpm
    best, best_score = 0.0, -1
    for phase in np.linspace(0, period, 40, endpoint=False):
        grid = np.arange(phase, duration, period)
        if not len(onsets):
            break
        d = np.abs(grid[:, None] - onsets[None, :]).min(axis=1)
        score = float((d < 0.05).sum())
        if score > best_score:
            best, best_score = phase, score
    return np.arange(best, duration, period)


def snap(edit_data: Path, beats: np.ndarray, tol: float, apply: bool, cuts: list[float]) -> None:
    d = json.loads(edit_data.read_text())
    moved = []
    def nearest(t):
        i = int(np.argmin(np.abs(beats - t)))
        return float(beats[i])
    for key, field in (("transitions", "at"), ("sfxCues", "at"), ("graphics", "start")):
        for item in d.get(key) or []:
            t = item.get(field)
            if t is None:
                continue
            b = nearest(float(t))
            if 0 < abs(b - t) <= tol:
                moved.append((key, float(t), b))
                if apply:
                    if key == "graphics" and item.get("end") is not None:
                        item["end"] = round(float(item["end"]) + (b - float(t)), 3)
                    item[field] = round(b, 3)
    for key, t, b in moved:
        print(f"  {key:<12} {t:7.3f} → {b:7.3f}  ({(b - t) * 1000:+.0f} ms)")
    if not moved:
        print("  nada a mover dentro da tolerância")
    if cuts and len(beats) > 1:
        period = float(beats[1] - beats[0])
        best_off, best_hits = 0.0, -1
        for off in np.linspace(-period / 2, period / 2, 60):
            hits = sum(1 for c in cuts if np.abs(beats + off - c).min() <= tol)
            if hits > best_hits:
                best_off, best_hits = float(off), hits
        now_hits = sum(1 for c in cuts if np.abs(beats - c).min() <= tol)
        print(f"  cortes em batida: {now_hits}/{len(cuts)} agora; deslocando a trilha {best_off*1000:+.0f} ms seriam {best_hits}/{len(cuts)}")
    if apply and moved:
        backup = edit_data.with_name(f"edit-data.json.bak-beats-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(edit_data, backup)
        edit_data.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
        print(f"  edit-data.json atualizado ({len(moved)} movidos; backup {backup.name})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("track", type=Path)
    ap.add_argument("--snap", type=Path, default=None, help="edit-data.json a ajustar")
    ap.add_argument("--tolerance", type=float, default=0.12)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    x = decode(args.track.resolve())
    duration = len(x) / SR
    env = onset_envelope(x)
    onsets = pick_onsets(env)
    bpm = estimate_tempo(env)
    beats = beat_grid(onsets, bpm, duration)
    out = args.track.with_suffix(args.track.suffix + ".beats.json")
    out.write_text(json.dumps({"bpm": round(bpm, 2), "beats": [round(float(b), 3) for b in beats],
                               "onsets": [round(float(o), 3) for o in onsets]}, indent=1) + "\n")
    hit = float((np.abs(beats[:, None] - onsets[None, :]).min(axis=1) < 0.05).mean()) if len(onsets) and len(beats) else 0
    print(f"{args.track.name}: {duration:.1f}s, {bpm:.1f} BPM, {len(beats)} batidas, {len(onsets)} onsets "
          f"({hit*100:.0f}% das batidas têm onset em cima) → {out.name}")
    if args.snap:
        cuts = []
        seg = args.snap.parent / "segments.json"
        if seg.exists():
            try:
                data = json.loads(seg.read_text())
                items = data if isinstance(data, list) else data.get("segments") or []
                cuts = [float(s.get("start", s.get("at", 0))) for s in items if isinstance(s, dict)][1:]
            except (json.JSONDecodeError, ValueError):
                cuts = []
        snap(args.snap.resolve(), beats, args.tolerance, args.apply, cuts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
