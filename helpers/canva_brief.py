#!/usr/bin/env python3
"""Ponte com o Canva: prepara o pedido e recebe o que volta. Caminho B da trilha de imagem.

ONDE ESTA A FRONTEIRA, E POR QUE ESTE ARQUIVO NAO CHAMA O CANVA. As ferramentas
do Canva sao MCP — quem as chama e o AGENTE, na conversa, nao um script. Um
helper Python nao tem como invocar `generate-design`. Entao a divisao e:

  este helper    monta o pedido exato (query + design_type) a partir do
                 `post-data.json`, e depois RECEBE o arquivo exportado,
                 renomeando-o no padrao que o `qc_image.py` entende
  o agente       chama generate-design / read-design / edit-design / export-design
  o qc_image.py  julga o resultado, venha ele do Canva ou daqui

O GATE E DO EDVID, NAO DO CANVA. O que sai de la volta para a pasta do projeto e
passa pela MESMA checagem de zona segura, contraste e rosto. Design bonito que
entra na faixa de baixo do Instagram continua reprovado.

USO
  # 1. gerar o briefing que o agente vai passar ao Canva
  uv run python helpers/canva_brief.py <edit>/post-data.json --briefing

  # 2. depois que o agente exportar, trazer o arquivo para o projeto
  uv run python helpers/canva_brief.py <edit>/post-data.json --receber <url|arquivo> --slide 2

ANTES DE QUALQUER COISA o agente deve confirmar que o conector responde: uma
chamada de LEITURA (`list-brand-kits`) antes de qualquer chamada que escreve.
Em 2026-09-10 o conector estava configurado e devolvia `Connection closed` —
declarado nao e o mesmo que conectado.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Formato do edvid -> design_type que o `generate-design` aceita. A lista de
# design_type e FECHADA: pedir um que nao existe falha, e 'presentation' nao e
# aceito por essa ferramenta.
TIPO_CANVA = {
    "4x5": "instagram_post",     # o proprio Canva gera 1080x1350
    "1x1": "instagram_post",
    "9x16": "your_story",
    "16x9": "youtube_thumbnail",
}

REGRAS = """REGRAS QUE O AGENTE DEVE SEGUIR AO FALAR COM O CANVA
1. Leitura antes de escrita: `list-brand-kits` primeiro. Se falhar, PARE e peca
   ao usuario para conectar o Canva. Nao improvise.
2. Brand Kit: perguntar ao usuario se quer usar, e qual. Nunca escolher sozinho.
3. `generate-design` devolve CANDIDATOS. Mostre as opcoes e deixe ELE escolher;
   so depois `create-design-from-candidate`. Mesma regra das 2 opcoes por item
   da Shutterstock.
4. `edit-design` e transacional: `read-design` com open_transaction, aplicar
   operacoes, COMPARAR a miniatura antes/depois, e so entao commit. O commit e
   IRREVERSIVEL — confirme com o usuario antes de disparar.
5. `export-design` so depois de `get-export-formats`. Nem todo design aceita
   todo formato; chutar falha.
6. Nunca publicar, nunca comprar, nunca mexer em configuracao da conta.
7. O arquivo exportado volta por `--receber` e passa pelo `qc_image.py`."""


def briefing(dados: dict, base: Path) -> str:
    marca = dados.get("marca") or {}
    partes = ["BRIEFING PARA O CANVA", "=" * 60, ""]
    partes.append(f"Projeto: {dados.get('projeto', base.name)}")
    if marca:
        partes.append(f"Cores da marca: fundo {marca.get('fundo','#071d33')}, "
                      f"texto {marca.get('texto','#ffffff')}, destaque {marca.get('destaque','#d4b25f')}")
    partes.append("Tipografia da marca: Poppins ExtraBold (titulo), Poppins Light "
                  "(corpo), Playfair Display Italic (palavra de destaque)")
    partes.append("")
    for i, s in enumerate(dados.get("slides") or [], 1):
        fmts = dados.get("formatos") or ["4x5"]
        tipos = sorted({TIPO_CANVA.get(f, "instagram_post") for f in fmts})
        q = []
        if s.get("titulo"):
            q.append(f'titulo "{s["titulo"]}"')
        if s.get("destaque"):
            q.append(f'com a palavra "{s["destaque"]}" em destaque')
        if s.get("corpo"):
            q.append(f'corpo "{s["corpo"]}"')
        fundo = s.get("fundo") or {}
        if "video" in fundo:
            q.append(f'fundo: foto do video em {fundo.get("at",0)}s — subir por '
                     f'upload-asset-from-url e passar em asset_ids')
        elif "arquivo" in fundo:
            q.append(f'fundo: {fundo["arquivo"]} — subir por upload-asset-from-url')
        else:
            q.append(f'fundo liso {fundo.get("cor", marca.get("fundo", "#071d33"))}')
        partes.append(f"--- slide {i} ({s.get('tipo','texto')}) ---")
        partes.append(f"  design_type: {', '.join(tipos)}")
        partes.append(f"  query: post de saude para Instagram, " + "; ".join(q)
                      + ". Tom direto e clinico, sem promessa e sem tom de bula.")
        partes.append("")
    partes.append(REGRAS)
    return "\n".join(partes)


def receber(origem: str, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if origem.startswith(("http://", "https://")):
        with urllib.request.urlopen(origem, timeout=60) as r, open(destino, "wb") as f:
            f.write(r.read())
    else:
        p = Path(origem).expanduser()
        if not p.is_file():
            raise SystemExit(f"nao achei {p}")
        destino.write_bytes(p.read_bytes())
    return destino


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dados", type=Path, help="post-data.json")
    ap.add_argument("--briefing", action="store_true")
    ap.add_argument("--receber", metavar="URL_OU_ARQUIVO")
    ap.add_argument("--slide", type=int, default=1)
    ap.add_argument("--formato", default="4x5", choices=list(TIPO_CANVA))
    a = ap.parse_args()

    if not a.dados.is_file():
        print(f"nao achei {a.dados}", file=sys.stderr)
        return 1
    d = json.loads(a.dados.read_text(encoding="utf-8"))
    base = a.dados.parent

    if a.briefing:
        print(briefing(d, base))
        return 0

    if a.receber:
        slides = d.get("slides") or []
        tipo = slides[a.slide - 1].get("tipo", "texto") if 0 < a.slide <= len(slides) else "canva"
        alvo = base / "post" / f"{a.slide:02d}_{tipo}_{a.formato}.jpg"
        receber(a.receber, alvo)
        print(alvo)
        print("SEM sidecar de caixas: o qc_image.py vai checar rosto e zona segura,")
        print("mas nao consegue medir contraste do texto (nao sabe onde ele esta).")
        print(f"Rode: uv run python helpers/qc_image.py {alvo.parent}")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
