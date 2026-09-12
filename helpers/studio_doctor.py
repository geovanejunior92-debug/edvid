#!/usr/bin/env python3
"""O que falta nesta máquina para o Studio funcionar — com o conserto escrito.

O aplicativo depende de coisas que não vêm dentro dele: ffmpeg, o ambiente
Python da skill, o modelo de transcrição, e o Node com a instalação compartilhada
do Remotion. Quando falta uma, o sintoma aparece longe da causa: o
render do Remotion falha no meio, a transcrição morre com traceback, o corte
sai sem limpeza de áudio.

Este helper troca isso por uma lista. Cada item diz o estado, por que importa,
e **o comando exato** que resolve. Nada aqui instala nada sozinho: instalar
mexe na máquina dele, e a decisão é dele.

Três estados, e a diferença importa:
  ok       — funciona
  faltando — impede alguma função, e o conserto está escrito
  aviso    — funciona pior, ou é opcional
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
SKILL = HELPERS.parent


def _run(argv, **kw):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=20, **kw)
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(argv, 127, "", "não consegui executar")


def _version(argv) -> str | None:
    run = _run(argv)
    if run.returncode != 0:
        return None
    return (run.stdout or run.stderr).strip().splitlines()[0] if (run.stdout or run.stderr) else ""


def check(project: Path | None = None) -> list[dict]:
    itens: list[dict] = []

    def add(nome, estado, porque, conserto=None, detalhe=None):
        itens.append({"item": nome, "state": estado, "why": porque,
                      **({"fix": conserto} if conserto else {}),
                      **({"detail": detalhe} if detalhe else {})})

    # --- ffmpeg / ffprobe: sem eles nada corta, nada mede, nada renderiza
    for exe in ("ffmpeg", "ffprobe"):
        caminho = shutil.which(exe)
        if caminho:
            add(exe, "ok", "corte, medição e render dependem dele", detalhe=caminho)
        else:
            add(exe, "faltando", "sem ele o Studio não corta nem mede nada",
                "brew install ffmpeg")

    # --- ambiente Python da skill
    venv = SKILL / ".venv" / "bin" / "python"
    if venv.is_file():
        add("ambiente Python", "ok", "os helpers rodam nele", detalhe=str(venv))
        faltando = []
        for modulo in ("whisperx", "cv2", "numpy"):
            run = _run([str(venv), "-c", f"import {modulo}"])
            if run.returncode != 0:
                faltando.append(modulo)
        if faltando:
            add("pacotes Python", "faltando",
                f"sem {', '.join(faltando)} a transcrição ou a análise de imagem param",
                f"uv sync --frozen  (em {SKILL})", detalhe=", ".join(faltando))
        else:
            add("pacotes Python", "ok", "transcrição e análise de imagem disponíveis")
    else:
        add("ambiente Python", "faltando", "nenhum helper roda sem ele",
            f"cd {SKILL} && uv sync --frozen")

    # --- Node: só a Fase 2 precisa, e a versão importa
    node = shutil.which("node")
    if not node:
        add("node", "faltando", "a Fase 2 (Remotion) não renderiza sem ele",
            "brew install node")
    else:
        bruto = _version(["node", "--version"]) or ""
        try:
            maior = int(bruto.lstrip("v").split(".")[0])
        except ValueError:
            maior = 0
        if maior >= 18:
            add("node", "ok", "a Fase 2 renderiza", detalhe=bruto)
        else:
            add("node", "faltando", f"o Remotion pede 18 ou mais; aqui é {bruto}",
                "brew upgrade node", detalhe=bruto)

    # --- modelo de transcrição em cache
    cache = Path.home() / "Library" / "Application Support" / "Edvid" / "cache" / "parakeet"
    if cache.is_dir() and any(cache.iterdir()):
        add("modelo Parakeet", "ok", "transcrição rápida de fonte longa disponível")
    else:
        add("modelo Parakeet", "aviso",
            "sem ele, fonte longa transcreve no WhisperX (~16x mais devagar)",
            detalhe=str(cache))

    # --- espaço: render de vídeo enche disco calado
    try:
        livre = shutil.disk_usage(Path.home()).free / 1024 ** 3
        if livre < 5:
            add("espaço em disco", "faltando", f"só {livre:.1f} GB livres; um render enche isso",
                "libere espaço antes de renderizar")
        elif livre < 20:
            add("espaço em disco", "aviso", f"{livre:.1f} GB livres — apertado para vídeo 4K")
        else:
            add("espaço em disco", "ok", f"{livre:.1f} GB livres")
    except OSError:
        add("espaço em disco", "aviso", "não consegui medir")

    # --- instalação compartilhada do Remotion: evita 570 MB por projeto
    compartilhado = SKILL / "assets" / "shortform" / "node_modules"
    if compartilhado.is_dir():
        add("Remotion compartilhado", "ok",
            "projetos novos apontam para esta instalação em vez de duplicar",
            detalhe=str(compartilhado))
    else:
        add("Remotion compartilhado", "aviso",
            "sem ela, a Fase 2 fica bloqueada e não deve duplicar ~570 MB por projeto",
            f"cd '{SKILL / 'assets' / 'shortform'}' && npm install")

    # --- cada projeto aponta para a instalação compartilhada
    if project:
        remotion = Path(project) / "edit" / "remotion"
        if not remotion.is_dir():
            add("Remotion do projeto", "aviso",
                "este projeto ainda não foi levado à Fase 2",
                "studio_phase2.py --root <projeto> --action scaffold")
        elif (remotion / "node_modules").is_dir():
            add("Remotion do projeto", "ok", "a Fase 2 pode renderizar")
        else:
            add("Remotion do projeto", "faltando",
                "o projeto perdeu o vínculo com a instalação compartilhada",
                f"cd '{SKILL / 'assets' / 'shortform'}' && npm install && "
                f"'{sys.executable}' '{HELPERS / 'studio_phase2.py'}' --root '{Path(project)}' --action scaffold")
    return itens


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnóstico de dependências do Edvid Studio")
    ap.add_argument("--project", type=Path, help="checa também o Remotion deste projeto")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    itens = check(args.project)
    if args.json:
        print(json.dumps({"items": itens}, ensure_ascii=False, indent=2))
    else:
        marca = {"ok": "✓", "aviso": "·", "faltando": "✗"}
        for i in itens:
            print(f"{marca[i['state']]} {i['item']}: {i['why']}")
            if i.get("detail"):
                print(f"    {i['detail']}")
            if i.get("fix"):
                print(f"    conserto: {i['fix']}")
        faltando = [i for i in itens if i["state"] == "faltando"]
        print(f"\n{len(itens)} itens · {len(faltando)} impedem alguma função")
    sys.exit(1 if any(i["state"] == "faltando" for i in itens) else 0)


if __name__ == "__main__":
    main()
