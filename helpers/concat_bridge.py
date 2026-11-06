"""Ponte edvid ↔ Concat: leva o corte pro editor nativo e traz os ajustes de volta.

Mesmo contrato da ponte do OpenCut: o edl.json é a fonte da verdade e o Concat
só decide ONDE cada take começa, termina e em que ordem entra. Cor, J-cut, fades
de 30ms, concat lossless e Fase 2 seguem no render.py. A diferença é o caminho:
o projeto é montado sem janela pelo MCP do próprio Concat, a mídia fica no disco
(nada de copiar a fonte pro navegador) e a volta lê o projeto salvo.

    python helpers/concat_bridge.py open --edit-dir <edit> [--rebuild] [--no-window]
    python helpers/concat_bridge.py pull --edit-dir <edit> [--force]
    python helpers/concat_bridge.py status --edit-dir <edit>

`open` reusa o projeto que já existe, para não perder o que foi arrastado nele;
`--rebuild` guarda o antigo ao lado e monta outro a partir do edl.json atual.
`pull` lê o que foi SALVO no Concat (Cmd+S) e reescreve o edl.json, com backup.
Se o edl.json mudou por outro caminho desde a montagem, ele recusa; `--force`
descarta essa outra mudança.
Falar com o binário pelo protocolo dele, em vez de ligar código, mantém a AGPL
do Concat fora do edvid.

Exit codes: 0 = ok, 1 = erro de uso, projeto inválido ou Concat ausente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from opencut_bridge import fps_fraction, merge_back, probe

CONCAT_BIN = Path(os.environ.get(
    "CONCAT_BIN", "/Applications/Concat.app/Contents/MacOS/concat"))
STATE_DIR = "concat"
PROJECT_NAME = "corte"
TOLERANCE_S = 0.02  # abaixo de um quadro a 60 fps é arredondamento, não ajuste


# ---------------------------------------------------------------- MCP

class ConcatError(SystemExit):
    pass


class Concat:
    """Cliente mínimo do `concat --mcp headless`: JSON-RPC por linha, em stdio."""

    def __init__(self, binary: Path = CONCAT_BIN) -> None:
        if not binary.exists():
            raise ConcatError(f"Concat não encontrado em {binary}")
        self.proc = subprocess.Popen(
            [str(binary), "--mcp", "headless"], text=True, bufsize=1,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.next_id = 0
        self._rpc("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "edvid-concat-bridge", "version": "1"},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, message: dict) -> None:
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def _rpc(self, method: str, params: dict) -> dict:
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": self.next_id,
                    "method": method, "params": params})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise ConcatError("o Concat encerrou sem responder")
            reply = json.loads(line)
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise ConcatError(f"{method}: {reply['error']}")
                return reply["result"]

    def tool(self, tool_name: str, /, **arguments) -> dict:
        result = self._rpc("tools/call", {"name": tool_name, "arguments": arguments})
        text = (result.get("content") or [{}])[0].get("text") or "{}"
        if result.get("isError"):
            raise ConcatError(f"{tool_name}: {text}")
        return json.loads(text)

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()


# ---------------------------------------------------------------- ida

def edl_fingerprint(edl: dict) -> str:
    """Identifica os takes e fontes, para avisar quando o projeto ficou para trás."""
    essence = {"sources": edl.get("sources"),
               "ranges": [[r["source"], r["start"], r["end"]]
                          for r in edl.get("ranges") or []]}
    return hashlib.sha256(json.dumps(essence, sort_keys=True).encode()).hexdigest()


def is_stale(edit_dir: Path, edl: dict) -> bool:
    """O edl.json mudou por outro caminho desde a última montagem ou devolução?"""
    built = edit_dir / STATE_DIR / "built_from.json"
    if not built.exists():
        return False
    return json.loads(built.read_text()).get("fingerprint") != edl_fingerprint(edl)


def load_edl(edit_dir: Path) -> dict:
    path = edit_dir / "edl.json"
    if not path.exists():
        raise ConcatError(f"não achei {path} — rode a Fase 1 antes")
    edl = json.loads(path.read_text())
    if not edl.get("sources"):
        raise ConcatError("edl.json sem 'sources'")
    if not edl.get("ranges"):
        raise ConcatError("edl.json sem 'ranges'")
    return edl


def build_project(edit_dir: Path, edl: dict, client: Concat | None = None) -> Path:
    """Monta <edit>/concat/corte: um clipe por take, em ordem, na resolução da fonte."""
    infos, paths = {}, {}
    for key, raw in edl["sources"].items():
        path = Path(raw).expanduser()
        if not path.exists():
            raise ConcatError(f"fonte '{key}' não existe: {path}")
        paths[key], infos[key] = path.resolve(), probe(path)
    for r in edl["ranges"]:
        if r["source"] not in infos:
            raise ConcatError(f"range usa a fonte desconhecida '{r['source']}'")

    state = edit_dir / STATE_DIR
    state.mkdir(exist_ok=True)
    project = state / PROJECT_NAME

    first = infos[edl["ranges"][0]["source"]]
    rate = fps_fraction(first["fps"])
    owned = client is None
    concat = client or Concat()
    try:
        concat.tool("project_create", location=str(state), name=PROJECT_NAME, video={
            "width": first["width"], "height": first["height"],
            "rateNum": rate["numerator"], "rateDen": rate["denominator"],
        })
        media_ids = {
            key: concat.tool("media_import", path=str(project), file=str(path))["createdId"]
            for key, path in paths.items()
        }
        cursor = 0.0
        for r in edl["ranges"]:
            start, end = float(r["start"]), float(r["end"])
            clip = concat.tool("clip_add", path=str(project),
                               mediaId=media_ids[r["source"]], trackId="T1",
                               start=cursor)["createdId"]
            concat.tool("clip_trim", path=str(project), clipId=clip, edge="start",
                        delta=start, ripple=True)
            concat.tool("clip_trim", path=str(project), clipId=clip, edge="end",
                        delta=end - infos[r["source"]]["duration"], ripple=True)
            label = r.get("beat") or r.get("quote", "")[:40]
            if label:
                concat.tool("clip_update", path=str(project), clipId=clip,
                            patch={"name": label})
            cursor += end - start

        clips = concat.tool("timeline_read", path=str(project))["timeline"]["clips"]
        verify_built(edl["ranges"], clips)
        concat.tool("project_close", path=str(project), save=True)
    finally:
        if owned:
            concat.close()

    (state / "built_from.json").write_text(json.dumps({
        "fingerprint": edl_fingerprint(edl),
        "at": datetime.now().strftime("%Y%m%d-%H%M%S"),
    }) + "\n")
    return project


def verify_built(ranges: list[dict], clips: list[dict]) -> None:
    """Corte errado montado em silêncio seria pior que nenhum: confere take a take."""
    if len(clips) != len(ranges):
        raise ConcatError(f"montou {len(clips)} clipes para {len(ranges)} takes")
    for index, (r, clip) in enumerate(zip(ranges, clips), 1):
        start, duration = float(r["start"]), float(r["end"]) - float(r["start"])
        if (abs(clip["sourceStart"] - start) > TOLERANCE_S
                or abs(clip["duration"] - duration) > TOLERANCE_S):
            raise ConcatError(
                f"take {index}: pedi [{start:.3f}, {start + duration:.3f}] e o Concat "
                f"montou início {clip['sourceStart']:.3f}, duração {clip['duration']:.3f}"
            )


# ---------------------------------------------------------------- volta

def ranges_from_project(project: Path, edl: dict) -> tuple[list[dict], list[str]]:
    """Traduz a timeline salva em ranges do edl.json. Devolve (ranges, avisos)."""
    doc_path = project / "concat.json"
    if not doc_path.exists():
        raise ConcatError(f"não achei {doc_path} — rode `open` antes")
    doc = json.loads(doc_path.read_text())

    active = doc.get("activeTimelineId")
    timeline = next((t for t in doc.get("timelines") or [] if t.get("id") == active), None)
    clips = (timeline or doc).get("clips") or []

    sources = {str(Path(raw).expanduser().resolve()): key
               for key, raw in edl["sources"].items()}
    media = {m["id"]: m for m in doc.get("media") or []}

    video = [c for c in clips if c.get("kind") == "video"]
    if not video:
        raise ConcatError("a timeline salva não tem nenhum clipe de vídeo")
    lanes = {c.get("trackId") for c in video}
    if len(lanes) > 1:
        raise ConcatError(
            f"há vídeo em {len(lanes)} trilhas ({', '.join(sorted(map(str, lanes)))}). "
            "O edl.json só conhece uma sequência: junte tudo numa trilha e salve de novo."
        )

    ranges, notes = [], []
    previous_end = 0.0
    for clip in sorted(video, key=lambda c: c["start"]):
        path = (media.get(clip.get("mediaId")) or {}).get("path", "")
        key = sources.get(str(Path(path).resolve())) if path else None
        if key is None:
            raise ConcatError(
                f"'{clip.get('name')}' usa mídia de fora do edl.json ({path or '?'}). "
                "Tire o clipe ou declare a fonte antes de devolver."
            )
        speed = float(clip.get("speed", 1.0))
        if abs(speed - 1.0) > 1e-6:
            notes.append(f"'{clip.get('name')}' tem velocidade {speed:g}× no Concat; "
                         "o edl.json guarda só as bordas, a velocidade não volta")
        start = float(clip["sourceStart"])
        ranges.append({"source": key, "start": start,
                       "end": start + float(clip["duration"]) * speed})
        if clip["start"] - previous_end > TOLERANCE_S:
            notes.append(f"vão de {clip['start'] - previous_end:.2f}s antes de "
                         f"'{clip.get('name')}' será fechado")
        previous_end = clip["start"] + clip["duration"]

    others = [c for c in clips if c.get("kind") != "video"]
    if others:
        kinds = ", ".join(sorted({str(c.get("kind")) for c in others}))
        notes.append(f"{len(others)} clipe(s) que não são vídeo ({kinds}) ficam só no "
                     "Concat; legenda, insert e trilha continuam na Fase 2")

    return absorb_rounding(ranges, edl["ranges"]), notes


def absorb_rounding(ranges: list[dict], original: list[dict]) -> list[dict]:
    """Borda dentro da tolerância volta ao valor exato: não é ajuste de ninguém."""
    for new in ranges:
        for old in original:
            if old["source"] != new["source"]:
                continue
            if abs(old["start"] - new["start"]) <= TOLERANCE_S:
                new["start"] = old["start"]
            if abs(old["end"] - new["end"]) <= TOLERANCE_S:
                new["end"] = old["end"]
    return ranges


# ---------------------------------------------------------------- cli

def open_window(project: Path) -> None:
    app = CONCAT_BIN.parents[2]
    subprocess.run(["open", "-n", str(app), "--args", "--project", str(project)],
                   check=True)


def cmd_open(args: argparse.Namespace) -> int:
    edit_dir = Path(args.edit_dir).expanduser().resolve()
    edl = load_edl(edit_dir)
    project = edit_dir / STATE_DIR / PROJECT_NAME

    if project.exists() and args.rebuild:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        old = project.with_name(f"{PROJECT_NAME}.bak-{stamp}")
        project.rename(old)
        print(f"projeto antigo guardado em {old.name}")

    if project.exists():
        print(f"reusando {project}")
        if is_stale(edit_dir, edl):
            print("ATENÇÃO: o edl.json mudou desde que este projeto foi montado. "
                  "Use --rebuild para partir do corte atual; o `pull` vai recusar "
                  "enquanto isso.")
    else:
        project = build_project(edit_dir, edl)
        total = sum(float(r["end"]) - float(r["start"]) for r in edl["ranges"])
        print(f"{len(edl['ranges'])} takes, {total:.1f}s → {project}")

    if args.no_window:
        return 0
    open_window(project)
    print("Concat aberto. Ajuste, salve com Cmd+S e rode `concat_bridge.py pull`.")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    edit_dir = Path(args.edit_dir).expanduser().resolve()
    edl = load_edl(edit_dir)
    if not args.force and is_stale(edit_dir, edl):
        raise ConcatError(
            "o edl.json mudou depois que este projeto foi montado (preview ou OpenCut). "
            "Devolver agora apagaria essa mudança. Use `open --rebuild` para partir do "
            "corte atual, ou `pull --force` para descartá-la."
        )
    ranges, notes = ranges_from_project(edit_dir / STATE_DIR / PROJECT_NAME, edl)
    summary = merge_back(edit_dir, ranges, editor="Concat", state_dir=STATE_DIR)
    print(summary)
    for note in notes:
        print(f"  aviso: {note}")
    # O projeto e o edl.json voltaram a falar do mesmo corte.
    (edit_dir / STATE_DIR / "built_from.json").write_text(json.dumps({
        "fingerprint": edl_fingerprint(load_edl(edit_dir)),
        "at": datetime.now().strftime("%Y%m%d-%H%M%S"),
    }) + "\n")
    print("Próximo passo: verify_cut.py → render.py → gate.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.edit_dir).expanduser().resolve() / STATE_DIR / "last_return.json"
    if not path.exists():
        print("nenhuma devolução do Concat ainda neste projeto")
        return 0
    data = json.loads(path.read_text())
    print(f"última devolução: {data['at']}\n{data['summary']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    opener = sub.add_parser("open", help="monta o projeto e abre o Concat")
    opener.add_argument("--edit-dir", required=True)
    opener.add_argument("--rebuild", action="store_true",
                        help="guarda o projeto atual e monta outro do edl.json")
    opener.add_argument("--no-window", action="store_true",
                        help="só monta o projeto")
    opener.set_defaults(func=cmd_open)

    pull = sub.add_parser("pull", help="traz o projeto salvo de volta pro edl.json")
    pull.add_argument("--edit-dir", required=True)
    pull.add_argument("--force", action="store_true",
                      help="devolve mesmo que o edl.json tenha mudado por fora")
    pull.set_defaults(func=cmd_pull)

    status = sub.add_parser("status", help="mostra a última devolução")
    status.add_argument("--edit-dir", required=True)
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
