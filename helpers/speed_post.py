"""Aceleração do corte montado: uma vez só, depois do J-cut, com o tom preservado.

Padrão 1,07×. Fora o pedido dele para um vídeo específico, é sempre esse valor.
O `speed` por range do EDL não serve aqui, porque desliga o J-cut.

O que este passo faz, junto:

- guarda o corte em 1× em `cut_1x.mp4` e regrava `cut.mp4` com `setpts` + `atempo`;
- grava `speed_post` no EDL e divide `jcut_timeline` e `total_duration_s`, de modo
  que a Fase 2 indexe pelo vídeo acelerado;
- reescala `transcripts/cut.json` e `sfx_cues.json`, se já existirem.

Rodar de novo com a mesma velocidade não acelera outra vez. Com outra velocidade,
parte sempre do `cut_1x.mp4`, nunca do corte já acelerado. `render.py` gera um corte
novo em 1× e move `speed_post` para `speed_post_pedido`; a próxima execução sem
`--speed` usa o valor pedido antes em vez de voltar ao padrão.

Resolução, fps e cor seguem os da fonte.

Uso:
    uv run python helpers/speed_post.py <edit-dir> [--speed 1.07]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PADRAO = 1.07
MIN_SPEED, MAX_SPEED = 0.5, 2.0   # faixa de um único atempo
TOLERANCIA_S = 0.1
CAMPOS_JCUT = ("video_start_in_output", "video_duration",
               "audio_start_in_output", "audio_duration")


class SpeedError(RuntimeError):
    pass


def probe(path: Path) -> dict:
    run = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,r_frame_rate,pix_fmt,color_space,color_primaries,color_transfer,"
         "color_range,sample_rate:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True)
    if run.returncode:
        raise SpeedError(f"não consegui inspecionar {path.name}: {run.stderr.strip()[:200]}")
    doc = json.loads(run.stdout)
    video = next((s for s in doc["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise SpeedError(f"{path.name} não tem vídeo")
    audio = next((s for s in doc["streams"] if s["codec_type"] == "audio"), None)
    return {"video": video, "audio": audio, "duration": float(doc["format"]["duration"])}


def acelerar(origem: Path, destino: Path, speed: float) -> None:
    info = probe(origem)
    video = info["video"]
    # `setparams` e as opções só etiquetam: nenhuma conversão de cor passa por aqui.
    # As duas juntas porque o filtro zera a etiqueta de primárias e transferência.
    etiquetas, opcoes = [], []
    for campo, filtro, opcao in (("color_space", "colorspace", "-colorspace"),
                                 ("color_primaries", "color_primaries", "-color_primaries"),
                                 ("color_transfer", "color_trc", "-color_trc"),
                                 ("color_range", "range", "-color_range")):
        valor = video.get(campo)
        if valor and valor != "unknown":
            etiquetas.append(f"{filtro}={valor}")
            opcoes += [opcao, valor]
    cadeia = f"setpts=(PTS-STARTPTS)/{speed},fps={video['r_frame_rate']}"
    if etiquetas:
        cadeia += ",setparams=" + ":".join(etiquetas)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(origem), "-vf", cadeia,
           "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", video["pix_fmt"], *opcoes]
    if info["audio"]:
        cmd += ["-af", f"atempo={speed}", "-c:a", "aac", "-b:a", "192k",
                "-ar", info["audio"]["sample_rate"]]
    cmd += ["-movflags", "+faststart", str(destino)]
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode or not destino.is_file():
        destino.unlink(missing_ok=True)
        raise SpeedError(f"ffmpeg falhou: {run.stderr.strip()[-400:]}")
    esperado = info["duration"] / speed
    obtido = probe(destino)["duration"]
    if abs(obtido - esperado) > TOLERANCIA_S:
        destino.unlink(missing_ok=True)
        raise SpeedError(f"saída com {obtido:.3f}s, esperado {esperado:.3f}s")


def _atomico(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    tmp.replace(path)


def reescalar_edl(edl: dict, razao: float) -> None:
    for item in edl.get("jcut_timeline") or []:
        for campo in CAMPOS_JCUT:
            if campo in item:
                item[campo] = round(float(item[campo]) * razao, 6)
    if edl.get("total_duration_s"):
        edl["total_duration_s"] = round(float(edl["total_duration_s"]) * razao, 3)


def reescalar_transcricao(path: Path, razao: float) -> bool:
    if not path.is_file():
        return False
    doc = json.loads(path.read_text())

    def tempos(no):
        if isinstance(no, dict):
            for chave, valor in no.items():
                if chave in ("start", "end") and isinstance(valor, (int, float)):
                    no[chave] = round(valor * razao, 3)
                elif chave != "_cache":
                    tempos(valor)
        elif isinstance(no, list):
            for item in no:
                tempos(item)
    tempos(doc)
    _atomico(path, doc)
    return True


def reescalar_cues(path: Path, razao: float) -> bool:
    if not path.is_file():
        return False
    doc = json.loads(path.read_text())
    for cue in doc.get("cues") or []:
        cue["at"] = round(float(cue["at"]) * razao, 3)
    _atomico(path, doc)
    return True


def aplicar(cut: Path, edl_path: Path, cut_1x: Path, speed: float | None = None,
            transcript: Path | None = None, cues: Path | None = None) -> dict:
    edl = json.loads(edl_path.read_text())
    atual = float(edl.get("speed_post") or 1.0)
    if speed is None:
        speed = float(edl.get("speed_post") or edl.get("speed_post_pedido") or PADRAO)
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise SpeedError(f"velocidade {speed} fora de {MIN_SPEED}–{MAX_SPEED}")
    if not cut.is_file():
        raise SpeedError(f"não achei {cut}")

    dur = probe(cut)["duration"]
    base = probe(cut_1x)["duration"] if cut_1x.is_file() else None

    if "speed_post" in edl:
        if base is None:
            raise SpeedError(f"o EDL diz {atual}×, mas {cut_1x.name} não existe: "
                             "não acelero um corte que já pode estar acelerado")
        if abs(dur - base / atual) > TOLERANCIA_S:
            raise SpeedError(f"{cut.name} ({dur:.2f}s) não é {cut_1x.name} ({base:.2f}s) a {atual}×: "
                             "o corte mudou por fora do render.py")
        if abs(speed - atual) < 1e-6:
            return {"status": "ja-aplicado", "speed": speed, "duration": dur}

    # Interrupção entre trocar o vídeo e gravar o EDL: o arquivo já está acelerado.
    ja_acelerado = ("speed_post" not in edl and base is not None and speed != 1.0
                    and abs(dur - base / speed) <= TOLERANCIA_S and abs(dur - base) > TOLERANCIA_S)

    if not ja_acelerado:
        origem = cut_1x if "speed_post" in edl else cut
        tmp = cut.with_name(f".{cut.stem}.speed.mp4")
        if speed == 1.0:
            shutil.copy2(origem, tmp)
        else:
            acelerar(origem, tmp, speed)
        if origem == cut:
            os.replace(cut, cut_1x)
        os.replace(tmp, cut)

    razao = atual / speed
    if transcript:
        reescalar_transcricao(transcript, razao)
    if cues:
        reescalar_cues(cues, razao)
    reescalar_edl(edl, razao)
    edl.pop("speed_post_pedido", None)
    if speed == 1.0:
        edl.pop("speed_post", None)
    else:
        edl["speed_post"] = speed
    _atomico(edl_path, edl)
    return {"status": "aplicado", "speed": speed, "duration": probe(cut)["duration"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edit_dir", type=Path, nargs="?")
    ap.add_argument("--speed", type=float, default=None,
                    help=f"só quando ele pedir outra velocidade neste vídeo (padrão {PADRAO})")
    ap.add_argument("--edl", type=Path, help="com --cut e --cut-1x, no lugar de edit_dir")
    ap.add_argument("--cut", type=Path)
    ap.add_argument("--cut-1x", type=Path)
    args = ap.parse_args()

    transcript = cues = None
    if args.edit_dir:
        edit = args.edit_dir.expanduser().resolve()
        cut, edl_path, cut_1x = edit / "cut.mp4", edit / "edl.json", edit / "cut_1x.mp4"
        transcript, cues = edit / "transcripts" / "cut.json", edit / "sfx_cues.json"
    elif args.edl and args.cut and args.cut_1x:
        edit = None
        cut, edl_path, cut_1x = args.cut, args.edl, args.cut_1x
    else:
        ap.error("passe <edit-dir>, ou --edl, --cut e --cut-1x juntos")

    try:
        r = aplicar(cut, edl_path, cut_1x, args.speed, transcript, cues)
    except SpeedError as exc:
        print(f"speed_post: {exc}", file=sys.stderr)
        return 1
    if r["status"] == "ja-aplicado":
        print(f"speed_post: {r['speed']}× já aplicado, nada a fazer ({r['duration']:.2f}s)")
        return 0
    print(f"speed_post: {r['speed']}× aplicado → {cut.name} {r['duration']:.2f}s; 1× em {cut_1x.name}")
    if edit and (edit / "remotion" / "public" / "edit-data.json").is_file():
        print("ATENÇÃO: a Fase 2 já estava montada e os tempos dela não foram reescalados. "
              "Siga o passo \"refazer a base\" do SKILL.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
