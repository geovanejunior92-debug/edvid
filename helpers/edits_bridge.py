"""Ponte edvid ↔ Edits: leva o corte pro app da Meta e traz os ajustes de volta.

Mesmo contrato das pontes do OpenCut e do Concat: o edl.json é a fonte da verdade
e o Edits só decide ONDE cada take começa, termina e em que ordem entra. Cor,
J-cut, fades, concat lossless e Fase 2 seguem no render.py.

    python helpers/edits_bridge.py open --edit-dir <edit> [--rebuild]
    python helpers/edits_bridge.py pull --edit-dir <edit> [--force]
    python helpers/edits_bridge.py status --edit-dir <edit>
    python helpers/edits_bridge.py export --edit-dir <edit> [--out <arquivo>]
    python helpers/edits_bridge.py clean --edit-dir <edit>

O Edits roda em sandbox e só abre o que está em ~/Movies, então as fontes entram
por link físico em ~/Movies/edvid-edits/<id>/: nada é duplicado no disco. O
projeto fica na biblioteca do app; `pull` lê a timeline ao vivo, salva ou não.

Exit codes: 0 = ok, 1 = erro de uso, projeto inválido ou Edits fora do ar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from concat_bridge import absorb_rounding, edl_fingerprint, load_edl
from edits_mcp_proxy import read_token
from opencut_bridge import merge_back, probe

ENDPOINT = os.environ.get("EDITS_MCP_URL", "http://127.0.0.1:19501/mcp")
MOVIES = Path(os.environ.get("EDITS_MOVIES_DIR", "~/Movies")).expanduser()
STATE_DIR = "edits"
STATE_FILE = "built_from.json"
ASPECTS = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1.0, "4:5": 4 / 5}
FRAME_RATES = (24, 30, 60)


class EditsError(SystemExit):
    pass


class Edits:
    """Cliente mínimo do servidor de automação do app, por HTTP local."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token if token is not None else read_token()
        if not self.token:
            raise EditsError(
                "token do Edits ausente: guarde o de Ajustes > Automation com "
                "`security add-generic-password -U -s edits-mcp-token -a \"$USER\" -w <token>`")

    def tool(self, tool_name: str, /, **arguments) -> dict:
        request = urllib.request.Request(ENDPOINT, json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }).encode(), {"Content-Type": "application/json", "Accept": "application/json",
                      "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=300) as reply:
                body = json.load(reply)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise EditsError("o Edits recusou o token; ele foi regenerado no app?")
            raise EditsError(f"{tool_name}: HTTP {error.code}")
        except (urllib.error.URLError, OSError) as error:
            raise ConnectionError(str(error))
        if "error" in body:
            raise EditsError(f"{tool_name}: {body['error']}")
        result = body["result"]
        text = (result.get("content") or [{}])[0].get("text") or "{}"
        if result.get("isError"):
            raise EditsError(f"{tool_name}: {text}")
        data = json.loads(text)
        if data.get("ok") is False:
            raise EditsError(f"{tool_name}: {data.get('error', text)}")
        return data


def connect() -> Edits:
    """Abre o app se preciso e espera o servidor responder."""
    edits = Edits()
    try:
        edits.tool("appState")
        return edits
    except ConnectionError:
        subprocess.run(["open", "-a", "Edits"], check=False)
    for _ in range(30):
        time.sleep(1)
        try:
            edits.tool("appState")
            return edits
        except ConnectionError:
            continue
    raise EditsError("o Edits não respondeu em 127.0.0.1:19501. Confira Ajustes > "
                     "Automation > Enable Automation Server.")


# ---------------------------------------------------------------- ida

def nearest_aspect(width: int, height: int) -> tuple[str, bool]:
    """Proporção do app mais próxima da fonte, e se ela é exata (até 1%)."""
    ratio = width / height
    name = min(ASPECTS, key=lambda key: abs(ASPECTS[key] - ratio))
    return name, abs(ASPECTS[name] - ratio) / ratio <= 0.01


def nearest_rate(fps: float) -> int:
    return min(FRAME_RATES, key=lambda rate: abs(rate - fps))


def media_folder(edit_dir: Path) -> Path:
    tag = hashlib.sha256(str(edit_dir).encode()).hexdigest()[:10]
    return MOVIES / "edvid-edits" / f"{edit_dir.parent.name}-{tag}"


def expose_source(key: str, source: Path, folder: Path) -> Path:
    """Põe a fonte onde o sandbox alcança: link físico, cópia só em outro volume."""
    if MOVIES.resolve() in source.parents:
        return source
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{key}{source.suffix}"
    if target.exists():
        same = target.stat().st_ino == source.stat().st_ino
        if same or target.stat().st_size == source.stat().st_size:
            return target
        target.unlink()
    try:
        os.link(source, target)
    except OSError:
        print(f"fonte '{key}' em outro volume: copiando {source.name} para {folder}")
        shutil.copy2(source, target)
    return target


def build_project(edit_dir: Path, edl: dict, edits: Edits) -> dict:
    """Cria o projeto: um clipe por take, em ordem, na trilha principal."""
    infos, paths = {}, {}
    for key, raw in edl["sources"].items():
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise EditsError(f"fonte '{key}' não existe: {path}")
        paths[key], infos[key] = path, probe(path)
    for r in edl["ranges"]:
        if r["source"] not in infos:
            raise EditsError(f"range usa a fonte desconhecida '{r['source']}'")

    first = infos[edl["ranges"][0]["source"]]
    aspect, exact = nearest_aspect(first["width"], first["height"])
    rate = nearest_rate(first["fps"])
    if not exact:
        print(f"aviso: o Edits não tem a proporção {first['width']}x{first['height']}; "
              f"usando {aspect}")

    project_id = edits.tool("newProject")["id"]
    title = f"edvid {edit_dir.parent.name}"
    try:
        edits.tool("setTitle", name=title)
        edits.tool("setCanvas", aspect=aspect, frameRate=rate)

        folder = media_folder(edit_dir)
        aliases = {}
        for key, path in paths.items():
            visible = expose_source(key, path, folder)
            aliases[key] = edits.tool("importToMediaPanel",
                                      path=str(visible))["aliasIds"][0]

        # Com startTime/sourceIn o app põe o clipe em trilha de sobreposição, e o
        # seek não passa do fim da timeline. Daí: entra inteiro, apara, reordena.
        for position, r in enumerate(edl["ranges"]):
            start, end = float(r["start"]), float(r["end"])
            edits.tool("seek", seconds=0)
            added = edits.tool("addMediaPanelItemsToTimeline",
                               aliasIds=[aliases[r["source"]]])["added"][0]
            whole = float(added["duration"])
            if end < whole:
                edits.tool("trim", id=added["id"], side="right",
                           deltaSeconds=whole - end)
            if start > 0:
                edits.tool("trim", id=added["id"], side="left", deltaSeconds=start)
            edits.tool("reorderClip", id=added["id"], position=position)

        edits.tool("saveProject")
        verify_built(edl["ranges"], main_lane(edits.tool("elements")["elements"]), rate)
    except EditsError:
        # O projeto foi criado aqui e não recebeu edição de ninguém: não deixa lixo.
        edits.tool("closeProject")
        edits.tool("deleteProject", id=project_id)
        raise
    return {"project": project_id, "title": title, "rate": rate, "aliases": aliases}


def main_lane(elements: list[dict]) -> list[dict]:
    lane = [e for e in elements
            if e.get("trackType") == "video" and e.get("sourceMediaType") == "video"]
    return sorted(lane, key=lambda e: e["startTime"])


def verify_built(ranges: list[dict], clips: list[dict], rate: int) -> None:
    """Corte errado montado em silêncio seria pior que nenhum: confere take a take."""
    if len(clips) != len(ranges):
        raise EditsError(f"montou {len(clips)} clipes para {len(ranges)} takes")
    tolerance = 1 / rate + 0.002
    for index, (r, clip) in enumerate(zip(ranges, clips), 1):
        if (abs(clip["sourceInPoint"] - float(r["start"])) > tolerance
                or abs(clip["sourceOutPoint"] - float(r["end"])) > tolerance):
            raise EditsError(
                f"take {index}: pedi [{r['start']}, {r['end']}] e o Edits montou "
                f"[{clip['sourceInPoint']:.3f}, {clip['sourceOutPoint']:.3f}]")


# ---------------------------------------------------------------- volta

def ranges_from_elements(elements: list[dict], state: dict, edl: dict
                         ) -> tuple[list[dict], list[str]]:
    """Traduz a timeline em ranges do edl.json. Devolve (ranges, avisos)."""
    keys = {alias: key for key, alias in state["aliases"].items()}
    clips = main_lane(elements)
    if not clips:
        raise EditsError("a trilha principal do Edits está vazia")

    ranges, notes = [], []
    previous_end = 0.0
    for clip in clips:
        key = keys.get(clip.get("aliasId"))
        if key is None:
            raise EditsError(
                f"o clipe em {clip['startTime']:.2f}s usa mídia de fora do edl.json. "
                "Tire o clipe ou declare a fonte antes de devolver.")
        speed = float(clip.get("speed", 1.0))
        if abs(speed - 1.0) > 1e-6:
            notes.append(f"clipe em {clip['startTime']:.2f}s tem velocidade {speed:g}× "
                         "no Edits; o edl.json guarda só as bordas, a velocidade não volta")
        ranges.append({"source": key, "start": float(clip["sourceInPoint"]),
                       "end": float(clip["sourceOutPoint"])})
        if clip["startTime"] - previous_end > 0.02:
            notes.append(f"vão de {clip['startTime'] - previous_end:.2f}s antes de "
                         f"{clip['startTime']:.2f}s será fechado")
        previous_end = clip["endTime"]

    in_main = {clip["id"] for clip in clips}
    others = [e for e in elements if e["id"] not in in_main]
    if others:
        kinds = ", ".join(sorted({str(e.get("trackType")) for e in others}))
        notes.append(f"{len(others)} elemento(s) fora da trilha principal ({kinds}) ficam "
                     "só no Edits; legenda, insert e trilha continuam na Fase 2")
    return absorb_rounding(ranges, edl["ranges"]), notes


# ---------------------------------------------------------------- cli

def state_path(edit_dir: Path) -> Path:
    return edit_dir / STATE_DIR / STATE_FILE


def read_state(edit_dir: Path) -> dict | None:
    path = state_path(edit_dir)
    return json.loads(path.read_text()) if path.exists() else None


def write_state(edit_dir: Path, state: dict, edl: dict) -> None:
    path = state_path(edit_dir)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        **state, "fingerprint": edl_fingerprint(edl),
        "at": datetime.now().strftime("%Y%m%d-%H%M%S"),
    }, indent=1) + "\n")


def is_stale(state: dict, edl: dict) -> bool:
    return state.get("fingerprint") != edl_fingerprint(edl)


def show_app() -> None:
    subprocess.run(["open", "-a", "Edits"], check=False)


def cmd_open(args: argparse.Namespace) -> int:
    edit_dir = Path(args.edit_dir).expanduser().resolve()
    edl = load_edl(edit_dir)
    edits = connect()
    state = read_state(edit_dir)

    if state and not args.rebuild:
        edits.tool("openProject", id=state["project"])
        print(f"reusando o projeto '{state['title']}' do Edits")
        if is_stale(state, edl):
            print("ATENÇÃO: o edl.json mudou desde a montagem. Use --rebuild para partir "
                  "do corte atual; o `pull` vai recusar enquanto isso.")
    else:
        if state:
            print(f"o projeto antigo '{state['title']}' continua na biblioteca do Edits")
        write_state(edit_dir, build_project(edit_dir, edl, edits), edl)
        total = sum(float(r["end"]) - float(r["start"]) for r in edl["ranges"])
        print(f"{len(edl['ranges'])} takes, {total:.1f}s montados no Edits")
    show_app()
    print("Edits aberto. Ajuste e rode `edits_bridge.py pull`.")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    edit_dir = Path(args.edit_dir).expanduser().resolve()
    edl = load_edl(edit_dir)
    state = read_state(edit_dir)
    if not state:
        raise EditsError("este corte ainda não foi para o Edits: rode `open` antes")
    if not args.force and is_stale(state, edl):
        raise EditsError(
            "o edl.json mudou depois da montagem (preview, OpenCut ou Concat). Devolver "
            "agora apagaria essa mudança. Use `open --rebuild` para partir do corte "
            "atual, ou `pull --force` para descartá-la.")
    edits = connect()
    if edits.tool("appState").get("screen") != "editor" \
            or edits.tool("title").get("title") != state["title"]:
        edits.tool("openProject", id=state["project"])
    ranges, notes = ranges_from_elements(edits.tool("elements")["elements"], state, edl)
    print(merge_back(edit_dir, ranges, editor="Edits", state_dir=STATE_DIR))
    for note in notes:
        print(f"  aviso: {note}")
    write_state(edit_dir, state, load_edl(edit_dir))
    print("Próximo passo: verify_cut.py → render.py → gate.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.edit_dir).expanduser().resolve() / STATE_DIR / "last_return.json"
    if not path.exists():
        print("nenhuma devolução do Edits ainda neste projeto")
        return 0
    data = json.loads(path.read_text())
    print(f"última devolução: {data['at']}\n{data['summary']}")
    return 0


def export_preset(width: int, height: int, rate: int, dynamic_range: str) -> dict:
    """Preset completo na resolução da fonte; o padrão do app sai 1440×2560."""
    short = min(width, height)
    tier = "4K" if short >= 2160 else "2K" if short >= 1440 else "HD" if short >= 1080 else "720p"
    aspect = {"9:16": "nineBySixteen", "16:9": "sixteenByNine", "1:1": "oneByOne",
              "4:5": "fourByFive"}[nearest_aspect(width, height)[0]]
    return {"resolutionType": tier, "aspectRatio": aspect, "quality": "High",
            "dynamicRange": dynamic_range, "frameRate": rate}


def cmd_export(args: argparse.Namespace) -> int:
    """Exporta pelo Edits. Sai SEM a cor, o J-cut e a Fase 2 do edvid."""
    edit_dir = Path(args.edit_dir).expanduser().resolve()
    edl = load_edl(edit_dir)
    state = read_state(edit_dir)
    if not state:
        raise EditsError("este corte ainda não foi para o Edits: rode `open` antes")
    first = probe(Path(edl["sources"][edl["ranges"][0]["source"]]).expanduser())
    out = Path(args.out).expanduser().resolve() if args.out \
        else edit_dir / STATE_DIR / "export.mp4"

    edits = connect()
    if edits.tool("appState").get("screen") != "editor" \
            or edits.tool("title").get("title") != state["title"]:
        edits.tool("openProject", id=state["project"])
    dynamic = edits.tool("projectDynamicRange")
    dynamic = str(dynamic.get("range") or dynamic.get("dynamicRange") or "SDR")
    edits.tool("setExportSettings", **export_preset(
        first["width"], first["height"], state["rate"], dynamic))

    folder = media_folder(edit_dir)  # o sandbox só escreve em ~/Movies
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / "export.mp4"
    partial.unlink(missing_ok=True)
    edits.tool("export", path=str(partial))
    while True:
        status = edits.tool("exportStatus")
        if status.get("state") == "complete":
            break
        if status.get("state") in ("failed", "cancelled", "idle"):
            raise EditsError(f"export parou: {status}")
        time.sleep(2)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(partial), out)
    print(f"{out} (sem a cor, o J-cut e a Fase 2 do edvid)")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    """Tira os links de ~/Movies. A fonte original não é tocada."""
    folder = media_folder(Path(args.edit_dir).expanduser().resolve())
    if not folder.exists():
        print("nada a limpar")
        return 0
    shutil.rmtree(folder)
    print(f"removido {folder}. O projeto no Edits fica com a mídia offline; "
          "`open --rebuild` monta de novo.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    opener = sub.add_parser("open", help="monta o projeto e abre o Edits")
    opener.add_argument("--edit-dir", required=True)
    opener.add_argument("--rebuild", action="store_true",
                        help="monta outro projeto a partir do edl.json atual")
    opener.set_defaults(func=cmd_open)

    pull = sub.add_parser("pull", help="traz a timeline de volta pro edl.json")
    pull.add_argument("--edit-dir", required=True)
    pull.add_argument("--force", action="store_true",
                      help="devolve mesmo que o edl.json tenha mudado por fora")
    pull.set_defaults(func=cmd_pull)

    status = sub.add_parser("status", help="mostra a última devolução")
    status.add_argument("--edit-dir", required=True)
    status.set_defaults(func=cmd_status)

    export = sub.add_parser("export", help="exporta pelo Edits, na resolução da fonte")
    export.add_argument("--edit-dir", required=True)
    export.add_argument("--out", help="padrão: <edit>/edits/export.mp4")
    export.set_defaults(func=cmd_export)

    clean = sub.add_parser("clean", help="remove os links das fontes em ~/Movies")
    clean.add_argument("--edit-dir", required=True)
    clean.set_defaults(func=cmd_clean)

    args = parser.parse_args()
    try:
        return args.func(args)
    except ConnectionError as error:
        raise EditsError(f"o Edits não respondeu: {error}")


if __name__ == "__main__":
    sys.exit(main())
