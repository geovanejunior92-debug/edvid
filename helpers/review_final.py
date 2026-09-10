"""Assistir o vídeo entregue INTEIRO, antes de mandar — passo final do formato 1.

O usuário pediu, em 2026-08-17: *"antes de finalizar vai assistir 100% ver se
está perfeito e ai sim me enviar"*. Isto é o que torna esse pedido verificável em
vez de uma promessa:

1. **Cobertura visual completa** — amostra o vídeo de ponta a ponta no intervalo
   pedido (padrão 1s) e monta folhas de contato numeradas em `verify/review/`.
   O agente PRECISA abrir todas: a checagem numérica não vê legenda errada,
   enquadramento feio ou arte fora de contexto.
2. **Checagem numérica** do que o olho não mede: movimento da faixa em cada
   janela, presença da capa/logo/encerramento nos tempos certos, áudio (pico,
   loudness, deriva contra o cut.mp4) e duração.

Exit ≠ 0 quando algum item objetivo falha. Exit 0 NÃO quer dizer "está pronto" —
quer dizer "nada objetivo falhou, agora olhe as folhas".

Uso:
    uv run python helpers/review_final.py <edit-dir> [--every 1.0] [--cols 5] [--rows 5]
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import re
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def dur_of(p: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def motion(video: Path, t0: float, dur: float, crop: str | None = None) -> float:
    vf = (f"{crop}," if crop else "") + (
        "scale=160:-2,tblend=all_mode=difference,signalstats,"
        "metadata=print:key=lavfi.signalstats.YAVG:file=-"
    )
    # `file=-` é obrigatório; sem ele o metadata não escreve nada e a métrica
    # devolve 0.00 para tudo (já aconteceu — verificador que reprova tudo).
    r = run(["ffmpeg", "-v", "error", "-ss", str(t0), "-t", str(dur), "-i", str(video),
             "-vf", vf, "-f", "null", "-"])
    vals = [float(l.split("=")[-1]) for l in r.stdout.splitlines() if "YAVG" in l][1:]
    return sum(vals) / len(vals) if vals else 0.0


def frame_stat(video: Path, t: float) -> tuple[float, float, float]:
    """(YAVG, UAVG, VAVG) de um frame — para provar cor de tela (encerramento)."""
    r = run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
             "-vf", "signalstats,metadata=print:file=-", "-f", "null", "-"])
    got = {}
    for line in r.stdout.splitlines():
        for k in ("YAVG", "UAVG", "VAVG"):
            if f"signalstats.{k}=" in line:
                got[k] = float(line.split("=")[-1])
    return got.get("YAVG", 0.0), got.get("UAVG", 0.0), got.get("VAVG", 0.0)


def sheets(video: Path, out_dir: Path, every: float, cols: int, rows: int, total: float) -> list[Path]:
    tmp = out_dir / ".frames"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    n = int(math.floor(total / every)) + 1
    for i in range(n):
        t = min(i * every, max(0.0, total - 0.05))
        # -ss ANTES do -i aqui é seguro (o final.mp4 tem GOP normal); nos
        # recortes de banco, que saem com um keyframe só, seria depois.
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
             "-frames:v", "1", "-update", "1",
             "-vf", f"scale=216:384,drawtext=text='{t:.0f}s':x=6:y=6:fontsize=16:"
                    f"fontcolor=white:box=1:boxcolor=black@0.55",
             str(tmp / f"{i:04d}.jpg")])
    files = sorted(tmp.glob("*.jpg"))
    if not files:  # sem fonte de texto no sistema, o drawtext derruba tudo
        for i in range(n):
            t = min(i * every, max(0.0, total - 0.05))
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                 "-frames:v", "1", "-update", "1", "-vf", "scale=216:384",
                 str(tmp / f"{i:04d}.jpg")])
        files = sorted(tmp.glob("*.jpg"))
    per = cols * rows
    made = []
    for k in range(0, len(files), per):
        lote = files[k:k + per]
        lote_dir = tmp / f"lote{k // per:02d}"
        lote_dir.mkdir()
        for j, f in enumerate(lote):
            shutil.copy(f, lote_dir / f"{j:03d}.jpg")
        dest = out_dir / f"review_{k // per + 1:02d}.jpg"
        r = run(["ffmpeg", "-y", "-v", "error", "-pattern_type", "glob",
                 "-i", f"{lote_dir}/*.jpg",
                 "-vf", f"tile={cols}x{math.ceil(len(lote)/cols)}:margin=6:padding=4",
                 "-frames:v", "1", "-update", "1", str(dest)])
        if dest.exists():
            made.append(dest)
    shutil.rmtree(tmp, ignore_errors=True)
    return made


def main() -> None:
    ap = argparse.ArgumentParser(description="Revisão final: cobertura visual + checagem numérica")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--every", type=float, default=1.0, help="intervalo de amostragem, em segundos")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--rows", type=int, default=5)
    args = ap.parse_args()

    E = args.edit_dir
    final = E / "final.mp4"
    cut = E / "cut.mp4"
    data_p = E / "remotion/public/edit-data.json"
    if not final.exists():
        sys.exit(f"não achei {final}")
    d = json.loads(data_p.read_text()) if data_p.exists() else {}
    total = dur_of(final)
    falhas: list[str] = []

    print(f"REVISÃO FINAL — {final.name}  ({total:.2f}s)\n")

    # --- duração esperada ---
    esperado = d.get("durationSec")
    if isinstance(esperado, (int, float)) and abs(total - esperado) > 0.15:
        falhas.append(f"duração {total:.2f}s ≠ edit-data {esperado}s")
    print(f"duração: {total:.2f}s (edit-data: {esperado})")

    # --- o Remotion está montando sobre o corte ATUAL? ---
    pub = E / "remotion/public/cut.mp4"
    if pub.exists() and cut.exists():
        d1, d2 = dur_of(cut), dur_of(pub)
        if abs(d1 - d2) > 0.05:
            falhas.append(f"remotion/public/cut.mp4 ({d2:.2f}s) != cut.mp4 ({d1:.2f}s) — "
                          f"a Fase 2 foi montada sobre um corte VELHO; copie e re-renderize")
        print(f"base do render: public/cut.mp4 {d2:.2f}s vs cut.mp4 {d1:.2f}s "
              f"{'ok' if abs(d1-d2)<=0.05 else 'DESATUALIZADO'}")

    # --- janelas de tela dividida: a faixa está rodando? ---
    janelas = d.get("splitInserts") or []
    if janelas:
        print("\nfaixa superior — movimento por janela:")
        for i, w in enumerate(janelas, 1):
            dur = max(0.5, min(2.0, float(w["end"]) - float(w["start"]) - 0.4))
            m = motion(final, float(w["start"]) + 0.25, dur, crop="crop=1080:460:0:0")
            # Insert de IMAGEM é parado por natureza — o que ele precisa provar é
            # que o Ken-Burns está vivo, não que tem movimento de vídeo. Limiar
            # próprio e bem mais baixo (2026-08-17, quando entraram manchetes).
            eh_imagem = w.get("kind") == "image" or str(w["src"]).lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            lim = 0.05 if eh_imagem else 0.3
            ok = m >= lim
            if not ok:
                falhas.append(f"janela {i} ({w['src']}) parada: {m:.2f} < {lim}")
            marca = "ok" if ok else "PARADO"
            print(f"  {i:2d} [{w['start']:6.2f}] {Path(w['src']).name:<22} {m:5.2f} {marca}"
                  + ("  (imagem, limiar 0.05)" if eh_imagem else ""))

        primeira = min(float(w["start"]) for w in janelas)
        if primeira < 4.0:
            falhas.append(f"primeira tela dividida em {primeira:.2f}s — o formato exige depois de 4s")
        print(f"\nprimeira tela dividida: {primeira:.2f}s (regra: ≥ 4.0s)")

    # --- capa e logo saem no tempo certo ---
    hs = d.get("hookStacked") or {}
    if hs.get("enabled"):
        fim = float(hs.get("endSec", 4.0))
        antes = motion(final, max(0, fim - 0.6), 0.4)
        depois = motion(final, fim + 0.15, 0.4)
        print(f"capa até {fim:.2f}s — movimento antes {antes:.2f} / depois {depois:.2f}")
        # A linha longa demais SAI DO QUADRO e o render não reclama: no vídeo 01
        # "que ninguém comenta" virou "ue ninguém coment" e só o olho pegou
        # (2026-08-20). Medida: na fonte da capa, 15 caracteres é o limite em
        # size 100 numa tela de 1080. Acima disso a linha precisa encolher.
        LIMITE_100 = 15
        for L in hs.get("lines") or []:
            txt, size = str(L.get("text", "")), float(L.get("size", 100))
            cabe = LIMITE_100 * 100 / size if size else LIMITE_100
            if len(txt) > cabe:
                sugestao = int(100 * LIMITE_100 / len(txt))
                falhas.append(f'capa: "{txt}" ({len(txt)} car.) estoura a largura '
                              f"em size {size:.0f} — cortada na tela; usar size {sugestao}")
            else:
                print(f'  capa ok: "{txt}" {len(txt)}/{cabe:.0f} car. em size {size:.0f}')
    logo = d.get("logo") or {}
    if logo.get("enabled"):
        src = E / "remotion/public" / logo["src"]
        if not src.exists():
            falhas.append(f"logo não encontrada: {src}")
        print(f"logo: {logo['src']} até {logo.get('endSec')}s — arquivo {'ok' if src.exists() else 'FALTA'}")

    # --- termo médico que a transcrição corrompeu ---
    # "A dona do Ozempic" saiu "A dona Dozenpich" (2026-08-19) e "do Mounjaro"
    # saiu "do mongeiro" (2026-08-20). Os dois passaram por todos os números e
    # só o olho pegou, no fim. Agora o dicionário pega antes.
    dic_p = Path(__file__).parent.parent / "references/termos-medicos.json"
    if dic_p.exists():
        dic = json.loads(dic_p.read_text())
        legendas = [E / "remotion/public/captions.json",
                    E / "remotion/public/caption-cues.json",
                    E / "transcripts/cut.json"]
        achados: list[str] = []
        for arq in legendas:
            if not arq.exists():
                continue
            texto = arq.read_text().lower()
            for certo, errados in dic.items():
                if certo.startswith("_"):
                    continue
                for err in errados:
                    if re.search(r"[\"\s>]" + re.escape(err.lower()) + r"[\"\s,.<]", texto):
                        achados.append(f'{arq.name}: "{err}" deveria ser "{certo}"')
        if achados:
            for a in sorted(set(achados)):
                falhas.append("termo corrompido na legenda — " + a)
        else:
            print(f"termos médicos: nenhum dos {len(dic)-1} termos do dicionário saiu corrompido")

    # --- a tela final entra antes de o vídeo-base acabar? ---
    outro_cfg = d.get("outro") or {}
    if outro_cfg.get("enabled") and cut.exists():
        dcut = dur_of(cut)
        ini = float(outro_cfg["startSec"])
        if ini > dcut + 0.02:
            falhas.append(f"tela final entra em {ini:.2f}s mas o corte acaba em {dcut:.2f}s — "
                          f"{ini-dcut:.2f}s de imagem CONGELADA no meio")
        print(f"entrada da tela final: {ini:.2f}s vs fim do corte {dcut:.2f}s "
              f"{'ok' if ini <= dcut + 0.02 else 'CONGELA'}")

    # --- encerramento: cor de tela no fim ---
    outro = d.get("outro") or {}
    if outro.get("enabled"):
        t = float(outro["startSec"]) + float(outro.get("durationSec", 2.5)) / 2
        y, u, v = frame_stat(final, t)
        # azul escuro: luminância baixa e crominância puxando para o azul (U alto)
        azul = y < 70 and u > 135
        if not azul:
            falhas.append(f"encerramento em {t:.1f}s não parece azul escuro (Y={y:.0f} U={u:.0f} V={v:.0f})")
        print(f"encerramento em {t:.1f}s: Y={y:.0f} U={u:.0f} V={v:.0f} {'ok' if azul else 'FORA DO PADRÃO'}")

    # --- áudio ---
    r = run(["ffmpeg", "-v", "error", "-i", str(final), "-af",
             "astats=metadata=1:reset=0,ebur128=framelog=quiet", "-f", "null", "-"])
    pico = None
    for line in (r.stderr or "").splitlines():
        if "Peak:" in line and "dBFS" not in line:
            continue
    r2 = run(["ffmpeg", "-v", "info", "-i", str(final), "-af", "volumedetect", "-f", "null", "-"])
    for line in (r2.stderr or "").splitlines():
        if "max_volume" in line:
            pico = float(line.split(":")[-1].replace("dB", "").strip())
    if pico is not None:
        if pico > -0.5:
            falhas.append(f"áudio muito perto do teto ({pico:.1f} dB)")
        print(f"\náudio: pico {pico:.1f} dBFS")

    if cut.exists():
        # deriva contra o corte aprovado: tem que ser CONSTANTE nos três pontos
        try:
            import numpy as np

            def seg(p: Path, t: float, dur: float = 12.0):
                raw = subprocess.run(
                    ["ffmpeg", "-v", "quiet", "-ss", str(t), "-t", str(dur), "-i", str(p),
                     "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                    capture_output=True).stdout
                return np.frombuffer(raw, dtype=np.float32)

            lags = []
            fala = dur_of(cut)
            for t in (5, fala / 2, max(5, fala - 15)):
                a, b = seg(final, t), seg(cut, t)
                if len(a) < 16000 or len(b) < 16000:
                    continue
                n = 1 << (len(a) + len(b) - 1).bit_length()
                cc = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
                cc = np.concatenate((cc[-(len(b) - 1):], cc[:len(a)]))
                lags.append((int(np.argmax(cc)) - (len(b) - 1)) / 16000 * 1000)
            if lags:
                spread = max(lags) - min(lags)
                if spread > 20:
                    falhas.append(f"áudio derivando: {[round(x,1) for x in lags]} ms")
                print(f"sincronia com o corte: {[round(x,1) for x in lags]} ms (variação {spread:.1f} ms)")
        except ImportError:
            print("sincronia: numpy indisponível, pulei")

    # --- cobertura visual ---
    out_dir = E / "verify/review"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    feitas = sheets(final, out_dir, args.every, args.cols, args.rows, total)
    print(f"\ncobertura visual: {len(feitas)} folha(s) a cada {args.every}s → {out_dir}")
    for f in feitas:
        print(f"  {f}")
    print("\nABRIR TODAS as folhas acima. O número não vê legenda errada,")
    print("enquadramento feio nem arte fora de contexto — só o olho vê.")

    if falhas:
        print("\nFALHAS:")
        for f in falhas:
            print(f"  - {f}")
        sys.exit(1)
    print("\nNenhuma falha objetiva. Revisar as folhas antes de entregar.")


if __name__ == "__main__":
    main()
