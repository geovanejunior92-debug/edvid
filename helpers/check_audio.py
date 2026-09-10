"""Gate: a limpeza de áudio melhorou o que devia e não estragou o que não devia?

`audio_clean.py` limpa e diz o que fez. Este é quem julga — em número, antes
de qualquer ouvido, e depois monta o A/B para o ouvido decidir o resto. Mede
original e limpo nos MESMOS trechos (as regiões de fala e de silêncio são
definidas pelo original, para a comparação ser justa):

  SNR          fala P75 − piso, em dB. Tem que subir.
  fala P75     nível da voz. Não pode cair mais de 2 dB: se caiu, o denoise
               comeu voz, não ruído.
  ar (4–12k)   energia de agudos nos quadros de fala, limpo ÷ original. Abaixo
               de 0,55 é o som "debaixo d'água" do denoise agressivo — o erro
               clássico, e o que nenhum medidor de loudness vê.
  espalhamento desvio das frases em torno da mediana. O nivelador tem que
               reduzi-lo, nunca aumentar.
  respirações  energia nas regiões marcadas, antes/depois.

Exit 1 em qualquer falha. Saídas em <edit>/audio_clean/:
  <stem>.ab.wav      8 s do original → 0,7 s de silêncio → os mesmos 8 s limpos
  <stem>.ab.png      espectrogramas lado a lado (o "debaixo d'água" aparece
                     como o topo do espectro apagado no limpo)

Usage:
    uv run python helpers/check_audio.py <source> --edit-dir <edit>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_clean import (  # noqa: E402
    SR, FRAME, decode, encode, ffprobe_audio, floor_and_gate, frame_rms_db,
    group_phrases, load_words, mono, speech_p75,
)

MAX_SPEECH_DROP_DB = 2.0
MIN_AIR_RATIO = 0.55


def band_energy(m: np.ndarray, mask: np.ndarray, lo_hz: float, hi_hz: float) -> float:
    """Energia média na banda, só nos quadros marcados em `mask`."""
    n = len(m) // FRAME
    blocks = m[: n * FRAME].reshape(n, FRAME)[mask[:n]]
    if blocks.shape[0] == 0:
        return 0.0
    win = np.hanning(FRAME)
    spec = np.abs(np.fft.rfft(blocks * win, axis=1)) ** 2
    freqs = np.fft.rfftfreq(FRAME, 1 / SR)
    sel = (freqs >= lo_hz) & (freqs < hi_hz)
    return float(spec[:, sel].mean())


def phrase_spread(levels: np.ndarray, times: np.ndarray, phrases: list[dict],
                  gate: float) -> float | None:
    per = []
    for p in phrases:
        sel = (times >= p["start"]) & (times < p["end"])
        if sel.any():
            per.append(speech_p75(levels[sel], gate))
    if len(per) < 3:
        return None
    return float(np.std(per))


def loudest_window(levels: np.ndarray, times: np.ndarray, gate: float,
                   want_s: float = 8.0) -> tuple[float, float]:
    """Janela de 8 s com mais fala, para o A/B ser representativo."""
    speech = (levels > gate).astype(float)
    k = max(1, int(want_s * SR / FRAME))
    if len(speech) <= k:
        return 0.0, float(times[-1]) if len(times) else want_s
    density = np.convolve(speech, np.ones(k), mode="valid")
    i = int(np.argmax(density))
    return float(times[i]), float(times[i]) + want_s


def spectrogram_pair(orig_wav: Path, clean_wav: Path, start: float, dur: float,
                     out_png: Path) -> None:
    tmp = out_png.with_suffix(".tmp.png")
    parts = []
    for i, src in enumerate((orig_wav, clean_wav)):
        png = out_png.with_name(f"{out_png.stem}.{i}.png")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}",
                        "-t", f"{dur:.2f}", "-i", str(src),
                        "-lavfi", "showspectrumpic=s=900x360:legend=0:scale=log:"
                                  "color=intensity:stop=12000",
                        str(png)], check=True)
        parts.append(png)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(parts[0]),
                    "-i", str(parts[1]), "-filter_complex", "[0][1]vstack",
                    str(tmp)], check=True)
    tmp.replace(out_png)
    for p in parts:
        p.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", type=Path)
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    source = args.source.expanduser().resolve()
    edit_dir = args.edit_dir.expanduser().resolve()
    stem = source.stem
    clean_wav = edit_dir / "audio_clean" / f"{stem}.wav"
    report_json = edit_dir / "audio_clean" / f"{stem}.json"
    if not clean_wav.exists():
        print(f"FALHA: {clean_wav} não existe — rode audio_clean.py antes")
        return 1

    channels = min(ffprobe_audio(source)["channels"], 2)
    orig = mono(decode(source, channels))
    clean = mono(decode(clean_wav, channels))
    n = min(len(orig), len(clean))
    orig, clean = orig[:n], clean[:n]

    times, lv_o = frame_rms_db(orig)
    _, lv_c = frame_rms_db(clean)
    floor_o, gate_o = floor_and_gate(lv_o)
    speech_mask = lv_o > gate_o
    silence_mask = lv_o < floor_o + 3

    floor_c = float(np.median(lv_c[silence_mask])) if silence_mask.any() else floor_o
    p75_o = speech_p75(lv_o, gate_o)
    p75_c = float(np.percentile(lv_c[speech_mask], 75)) if speech_mask.any() else p75_o
    snr_o, snr_c = p75_o - floor_o, p75_c - floor_c

    air_o = band_energy(orig, speech_mask, 4000, 12000)
    air_c = band_energy(clean, speech_mask, 4000, 12000)
    air_ratio = air_c / air_o if air_o > 0 else 1.0

    words = load_words(edit_dir, stem)
    phrases = group_phrases(words) if words else []
    spread_o = phrase_spread(lv_o, times, phrases, gate_o)
    spread_c = phrase_spread(lv_c, times, phrases, gate_o)

    breath_o = breath_c = None
    try:
        rep = json.loads(report_json.read_text())
    except (OSError, json.JSONDecodeError):
        rep = {}
    breaths = rep.get("breaths") or []
    if breaths:
        e_o = e_c = 0.0
        for b in breaths:
            a, z = int(b["start"] * SR), int(b["end"] * SR)
            e_o += float(np.mean(orig[a:z] ** 2)) if z > a else 0.0
            e_c += float(np.mean(clean[a:z] ** 2)) if z > a else 0.0
        if e_o > 0:
            breath_o, breath_c = 10 * np.log10(e_o), 10 * np.log10(max(e_c, 1e-12))

    failures = []
    if snr_c < snr_o + 1.0:
        failures.append(f"SNR não melhorou ({snr_o:.0f} → {snr_c:.0f} dB)")
    if p75_o - p75_c > MAX_SPEECH_DROP_DB:
        failures.append(f"fala caiu {p75_o - p75_c:.1f} dB (limite {MAX_SPEECH_DROP_DB})")
    if air_ratio < MIN_AIR_RATIO:
        failures.append(f"agudos da voz em {air_ratio:.2f} do original (limite "
                        f"{MIN_AIR_RATIO}) — som 'debaixo d'água'")
    if spread_o is not None and spread_c is not None and spread_c > spread_o + 0.3:
        failures.append(f"espalhamento entre frases subiu ({spread_o:.1f} → {spread_c:.1f} dB)")

    # A/B + espectrogramas
    ab_start, ab_end = loudest_window(lv_o, times, gate_o)
    a, z = int(ab_start * SR), int(min(ab_end * SR, n))
    gap = np.zeros(int(0.7 * SR), dtype=np.float32)
    ab = np.concatenate([orig[a:z], gap, clean[a:z]]).astype(np.float32)[:, None]
    ab_wav = edit_dir / "audio_clean" / f"{stem}.ab.wav"
    encode(ab, ab_wav, limiter=False)
    ab_png = edit_dir / "audio_clean" / f"{stem}.ab.png"
    spectrogram_pair(source, clean_wav, ab_start, ab_end - ab_start, ab_png)

    result = {
        "snr_db": [round(snr_o, 1), round(snr_c, 1)],
        "speech_p75_db": [round(p75_o, 1), round(p75_c, 1)],
        "floor_db": [round(floor_o, 1), round(floor_c, 1)],
        "air_ratio": round(air_ratio, 2),
        "phrase_spread_db": [None if spread_o is None else round(spread_o, 2),
                             None if spread_c is None else round(spread_c, 2)],
        "breath_energy_db": None if breath_o is None else [round(breath_o, 1), round(breath_c, 1)],
        "ab": {"wav": ab_wav.name, "png": ab_png.name,
               "window": [round(ab_start, 1), round(ab_end, 1)]},
        "failures": failures,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{stem}: original → limpo")
        print(f"  SNR           {snr_o:6.1f} → {snr_c:6.1f} dB")
        print(f"  fala P75      {p75_o:6.1f} → {p75_c:6.1f} dB")
        print(f"  piso          {floor_o:6.1f} → {floor_c:6.1f} dB")
        print(f"  ar 4–12 kHz   {air_ratio:6.2f} × o original")
        if spread_o is not None and spread_c is not None:
            print(f"  espalhamento  {spread_o:6.2f} → {spread_c:6.2f} dB entre frases")
        if breath_o is not None:
            print(f"  respirações   {breath_o:6.1f} → {breath_c:6.1f} dB ({len(breaths)} marcadas)")
        print(f"  A/B: {ab_wav}  ({ab_start:.0f}–{ab_end:.0f}s)")
        print(f"  espectro: {ab_png}")
        if failures:
            print("FALHA:")
            for f in failures:
                print(f"  - {f}")
        else:
            print("OK: limpeza dentro dos limites")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
