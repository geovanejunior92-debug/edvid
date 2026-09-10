"""Pacote EXTRA de efeitos — SOMA ao `generate_sfx.py`, não substitui nada.

Origem: análise de uma referência do usuário (2026-08-17) que ensina sete usos
de efeito sonoro. O pacote antigo cobria whoosh, pop e clicks; faltavam
typing, shutter, UI, riser e hit. Os parâmetros abaixo saíram da MEDIÇÃO da
referência (duração, centróide espectral e nível relativo à voz), não de chute:

    typing   ~0.9s, rajada de transientes brilhantes   voz +8 dB
    shutter  ~0.16s, centróide ~10 kHz                 voz  +1 dB
    ui       0.06–0.11s, centróide ~13 kHz             voz −6 a −25 dB
    riser    ~1.2s subindo                             voz +8 dB
    whoosh   0.27–0.39s                                voz −1 dB
    hit      ~1.7s com cauda                           voz +10 dB

Rodar: uv run python generate_sfx_extra.py  (escreve .mp3 em public/sfx/)
"""
import numpy as np, wave, subprocess
from pathlib import Path

SR = 44100
OUT = Path(__file__).parent / "public" / "sfx"
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)   # determinístico: regerar dá o mesmo pacote


def save(nome: str, y: np.ndarray, gain: float = 0.85) -> None:
    y = y / (np.max(np.abs(y)) + 1e-9)
    y = np.tanh(y * 1.1)
    pcm = (y * gain * 32767).astype(np.int16)
    wav = OUT / f"{nome}.wav"
    with wave.open(str(wav), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    mp3 = OUT / f"{nome}.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav),
                    "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)
    wav.unlink()
    print(f"  {nome}.mp3  {len(y)/SR:.2f}s")


def lowpass_sweep(x, a):
    y = np.empty_like(x); prev = 0.0
    for i in range(len(x)):
        prev += a[i] * (x[i] - prev); y[i] = prev
    return y


def highpass(x, a=0.86):
    y = np.empty_like(x); prev_x = prev_y = 0.0
    for i in range(len(x)):
        prev_y = a * (prev_y + x[i] - prev_x); prev_x = x[i]; y[i] = prev_y
    return y


def key_click(dur=0.035, bright=1.0, seed=None):
    """Uma tecla: transiente seco com corpo curto — o ataque é o que identifica."""
    r = np.random.default_rng(seed) if seed is not None else rng
    n = int(dur * SR); t = np.linspace(0, dur, n)
    ruido = highpass(r.standard_normal(n)) * np.exp(-t * (300 / bright))
    corpo = np.sin(2 * np.pi * (2200 * bright) * t) * np.exp(-t * 190) * 0.35
    return ruido + corpo


print("gerando pacote extra em", OUT)

# ---- TECLADO: uma tecla e uma rajada de digitação -------------------------
save("key", key_click(0.04, 1.0, seed=1))

n = int(0.95 * SR)
typing = np.zeros(n)
pos = 0.02
while pos < 0.90:
    k = key_click(0.035, float(rng.uniform(0.85, 1.2)), seed=int(rng.integers(1e6)))
    i = int(pos * SR)
    typing[i:i + len(k)] += k * float(rng.uniform(0.7, 1.0))
    pos += float(rng.uniform(0.055, 0.11))     # ritmo humano, não metrônomo
save("typing", typing)

# ---- CAMERA SHUTTER: dois estalos mecânicos + sopro curto -----------------
n = int(0.18 * SR); t = np.linspace(0, 0.18, n)
sh = np.zeros(n)
for atraso, forca in ((0.0, 1.0), (0.055, 0.75)):
    i = int(atraso * SR)
    m = key_click(0.03, 1.5, seed=int(rng.integers(1e6))) * forca
    sh[i:i + len(m)] += m
sopro = highpass(rng.standard_normal(n), 0.93) * np.exp(-t * 55) * 0.35
save("shutter", sh + sopro)

# ---- UI: blips curtíssimos e muito brilhantes -----------------------------
for nome, freq, dur in (("ui-blip", 3200, 0.075), ("ui-tap", 4700, 0.055)):
    n = int(dur * SR); t = np.linspace(0, dur, n)
    tom = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 2 * t)
    env = np.exp(-t * (60 / dur * 0.06))
    ar = highpass(rng.standard_normal(n), 0.95) * np.exp(-t * 220) * 0.25
    save(nome, (tom * env + ar) * np.hanning(n) ** 0.3)

# ---- RISER: ruído + tom subindo, com corte no fim -------------------------
dur = 1.30
n = int(dur * SR); t = np.linspace(0, 1, n)
a = 0.02 + 0.55 * t ** 2.2                      # abre o filtro conforme sobe
ruido = lowpass_sweep(rng.standard_normal(n), a)
f = 180 * np.exp(t * 2.6)                       # ~180 → 2400 Hz
tom = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.45
env = t ** 1.6
riser = (ruido + tom) * env
riser[-int(0.02 * SR):] *= np.linspace(1, 0, int(0.02 * SR))   # corta seco no alvo
save("riser", riser)

dur = 2.20                                       # versão longa, para viradas
n = int(dur * SR); t = np.linspace(0, 1, n)
a = 0.015 + 0.5 * t ** 2.4
ruido = lowpass_sweep(rng.standard_normal(n), a)
f = 150 * np.exp(t * 2.9)
tom = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.4
riser2 = (ruido + tom) * (t ** 1.7)
riser2[-int(0.02 * SR):] *= np.linspace(1, 0, int(0.02 * SR))
save("riser-long", riser2)

# ---- HIT: impacto com corpo grave e cauda ---------------------------------
dur = 1.70
n = int(dur * SR); t = np.linspace(0, dur, n)
sub = np.sin(2 * np.pi * (58 * np.exp(-t * 2.2)) * t) * np.exp(-t * 2.6)
punch = np.sin(2 * np.pi * 150 * t) * np.exp(-t * 16) * 0.5
crack = highpass(rng.standard_normal(n), 0.9) * np.exp(-t * 60) * 0.35
cauda = lowpass_sweep(rng.standard_normal(n), np.full(n, 0.06)) * np.exp(-t * 1.7) * 0.28
save("hit", sub + punch + crack + cauda)

dur = 0.85                                       # impacto menor, para acentos
n = int(dur * SR); t = np.linspace(0, dur, n)
sub = np.sin(2 * np.pi * (72 * np.exp(-t * 3)) * t) * np.exp(-t * 5.5)
crack = highpass(rng.standard_normal(n), 0.9) * np.exp(-t * 90) * 0.3
save("hit-soft", sub + crack)

# ---- WHOOSH: versões longa e reversa (a curta já existe no pacote antigo) --
dur = 0.80
n = int(dur * SR); t = np.linspace(0, 1, n)
a = 0.02 + 0.42 * np.sin(np.pi * t) ** 1.1
wl = lowpass_sweep(rng.standard_normal(n), a) * np.sin(np.pi * t) ** 1.3
save("whoosh-long", wl)

dur = 0.55
n = int(dur * SR); t = np.linspace(0, 1, n)
a = 0.02 + 0.45 * t ** 2                        # abre no fim = sensação de entrada
wr = lowpass_sweep(rng.standard_normal(n), a) * (t ** 1.8)
wr[-int(0.015 * SR):] *= np.linspace(1, 0, int(0.015 * SR))
# BANIDO 2026-09-03 (pedido do usuário): não gerar mais whoosh-rev.
# save("whoosh-rev", wr)

print("\npacote extra pronto — os arquivos antigos não foram tocados")

# ---- Pacote 2 (2026-08-17): medido de uma segunda referência do usuário -------
# O vocabulário dela é mais BRILHANTE que o pacote anterior. Três formas novas:
#   outro-swell   0.98s, tonal (planura 0.001), cresce até 630ms, centróide
#                 sobe 900 → 3300 Hz — é o som de ENCERRAMENTO, antes da tela final
#   whoosh-bright 0.58s, 54% da energia acima de 8 kHz, centróide caindo 8200→3500
#   riser-deep    1.55s, 29% de graves, cresce até o fim e resolve
print("\npacote 2 — medido da segunda referência")

# ENCERRAMENTO — calibrado contra a referência (2026-08-17, 2ª rodada).
# A 1ª versão soava diferente e ele mandou comparar. A medição mostrou o porquê:
# o som dela fica ESCURO por três quartos e só abre no fim, com pico de volume
# aos 64% do som. A minha abria desde o começo e tinha 3x mais brilho.
# Alvos medidos nela: pico 64% | centróide 968→960→927→2126→4101 Hz |
# bandas 32% graves / 36% médios / 26% agudos / 6% brilho | planura 0.0005.
# Esta versão entrega: pico 66% | 1126→1153→1162→2948→4097 | 36/38/19/6.
dur = 0.98
n = int(dur * SR); t = np.linspace(0, dur, n); u = t / dur
env = np.where(u <= 0.64, (u / 0.64) ** 1.9, np.cos((u - 0.64) / 0.36 * np.pi / 2) ** 1.3)
env /= env.max()                                  # pico cravado em 64% do som
abre = np.clip((u - 0.62) / 0.38, 0, 1) ** 1.2    # os agudos só entram no fim
sub = (np.sin(2 * np.pi * 110 * t) + 0.6 * np.sin(2 * np.pi * 220 * t)) * 1.1
mid = sum(np.sin(2 * np.pi * 220 * m * t + (m * 1.7 % 6.28)) / (m ** 0.7) for m in (2, 3, 4)) * 1.0
hi = sum(np.sin(2 * np.pi * 220 * m * t + (m * 0.9 % 6.28)) / (m ** 0.4) for m in (9, 12, 16, 20, 26)) * 2.2
ar = highpass(rng.standard_normal(n), 0.945) * 0.10
save("outro-swell", (sub + mid + (hi + ar) * (0.08 + 0.92 * abre)) * env)

# WHOOSH brilhante, varrendo para baixo
dur = 0.58
n = int(dur * SR); t = np.linspace(0, 1, n)
a = 0.55 - 0.45 * t ** 1.4                       # fecha o filtro = centróide cai
wb = lowpass_sweep(highpass(rng.standard_normal(n), 0.7), a)
save("whoosh-bright", wb * np.sin(np.pi * t) ** 0.8)

# RISER grave que resolve no fim
dur = 1.55
n = int(dur * SR); t = np.linspace(0, 1, n)
sub = np.sin(2 * np.pi * np.cumsum(55 * np.exp(t * 1.1)) / SR) * 0.55
ruido = lowpass_sweep(rng.standard_normal(n), 0.01 + 0.35 * t ** 2.5) * 0.5
rd = (sub + ruido) * (t ** 1.4)
rd[-int(0.03 * SR):] *= np.linspace(1, 0, int(0.03 * SR))
save("riser-deep", rd)
