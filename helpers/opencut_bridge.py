"""Ponte edvid ↔ OpenCut: leva o corte pra uma timeline de verdade e traz de volta.

O que ela resolve: depois do gate da Fase 1 o ajuste fino de um take ("entra
meio segundo antes", "corta o 'né' do final") hoje volta pro chat como pedido,
vira uma edição no edl.json e um re-render. Com o OpenCut instalado, esse ajuste
vira arrastar a borda do clipe numa timeline — e o resultado volta pro edl.json,
que continua sendo a fonte da verdade. A cor, o J-cut, os fades de 30ms e o
concat lossless seguem sendo do render.py; o OpenCut só decide ONDE cada take
começa e termina.

    python helpers/opencut_bridge.py serve --edit-dir <edit> [--port 4840]
    python helpers/opencut_bridge.py status --edit-dir <edit>

`serve` monta o bundle a partir do edl.json, sobe um servidor local com CORS
(o OpenCut roda em outra origem) e imprime a URL de importação. Deixe rodando
em background enquanto ele edita. Quando ele clicar em "Devolver", o servidor
reescreve o edl.json — com backup — e imprime, take a take, o que mudou.

Os metadados de cada take (beat, quote, reason, gain_db, chapter) NÃO se perdem
na volta: cada range devolvido herda os do range original com maior sobreposição.
`grade`, `voice_master` e `jcut` são preservados intactos — o OpenCut não os
conhece e não tem como opinar sobre eles.

Exit codes: 0 = ok, 1 = erro de uso ou edl.json inválido.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_PORT = 4840
DEFAULT_OPENCUT = "http://localhost:3000"
CARRY_FIELDS = ("beat", "quote", "reason", "gain_db", "chapter")


# ---------------------------------------------------------------- ffprobe

def probe(path: Path) -> dict:
    """Dimensões, duração, fps e presença de áudio de uma fonte."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError(f"{path.name}: nenhuma trilha de vídeo")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])

    num, _, den = video.get("r_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0

    duration = float(data["format"].get("duration") or video.get("duration") or 0.0)
    if duration <= 0:
        raise ValueError(f"{path.name}: ffprobe não achou a duração")

    return {
        "duration": duration,
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": fps,
        "hasAudio": has_audio,
    }


def fps_fraction(fps: float) -> dict:
    """FrameRate do OpenCut ({numerator, denominator}) a partir de um fps float."""
    for num, den in ((24000, 1001), (30000, 1001), (60000, 1001)):
        if abs(fps - num / den) < 0.01:
            return {"numerator": num, "denominator": den}
    return {"numerator": int(round(fps)), "denominator": 1}


# ---------------------------------------------------------------- bundle

def build_bundle(edit_dir: Path, port: int, name: str | None,
                 canvas: str | None) -> tuple[dict, dict[str, Path]]:
    edl_path = edit_dir / "edl.json"
    if not edl_path.exists():
        raise SystemExit(f"não achei {edl_path} — rode a Fase 1 antes")

    edl = json.loads(edl_path.read_text())
    sources = edl.get("sources") or {}
    ranges = edl.get("ranges") or []
    if not sources:
        raise SystemExit("edl.json sem 'sources'")
    if not ranges:
        raise SystemExit("edl.json sem 'ranges'")

    paths: dict[str, Path] = {}
    media = []
    for key, raw in sources.items():
        path = Path(raw).expanduser()
        if not path.exists():
            raise SystemExit(f"fonte '{key}' não existe: {path}")
        info = probe(path)
        paths[key] = path
        media.append({
            "key": key,
            "name": path.name,
            "url": f"http://127.0.0.1:{port}/media/{key}",
            **info,
        })

    first = media[0]
    if canvas:
        match = re.fullmatch(r"(\d+)x(\d+)", canvas)
        if not match:
            raise SystemExit("--canvas espera LARGURAxALTURA, ex 1080x1920")
        canvas_size = {"width": int(match[1]), "height": int(match[2])}
    elif first["height"] > first["width"]:
        canvas_size = {"width": 1080, "height": 1920}
    else:
        canvas_size = {"width": 1920, "height": 1080}

    bundle = {
        "kind": "edvid-opencut-bundle",
        "version": 1,
        "project": {
            "name": name or f"{edit_dir.parent.name} (edvid)",
            "fps": fps_fraction(first["fps"]),
            "canvas": canvas_size,
        },
        "media": media,
        "ranges": [
            {
                "source": r["source"],
                "start": float(r["start"]),
                "end": float(r["end"]),
                "label": r.get("beat") or r.get("quote", "")[:40] or None,
            }
            for r in ranges
        ],
        "postUrl": f"http://127.0.0.1:{port}/edl",
        "editDir": str(edit_dir),
    }
    return bundle, paths


# ---------------------------------------------------------------- volta

def merge_back(edit_dir: Path, incoming: list[dict]) -> str:
    """Reescreve edl.json com os ranges vindos do OpenCut. Devolve o resumo."""
    edl_path = edit_dir / "edl.json"
    edl = json.loads(edl_path.read_text())
    original = edl.get("ranges") or []

    def best_match(new: dict) -> dict | None:
        """Range original com maior sobreposição temporal na mesma fonte."""
        best, best_overlap = None, 0.0
        for old in original:
            if old["source"] != new["source"]:
                continue
            overlap = min(old["end"], new["end"]) - max(old["start"], new["start"])
            if overlap > best_overlap:
                best, best_overlap = old, overlap
        return best

    merged, lines, used = [], [], set()
    for index, new in enumerate(incoming):
        old = best_match(new)
        entry = {"source": new["source"],
                 "start": round(float(new["start"]), 3),
                 "end": round(float(new["end"]), 3)}
        if old is not None:
            for field in CARRY_FIELDS:
                if field in old:
                    entry[field] = old[field]
            used.add(id(old))
            d_start = entry["start"] - old["start"]
            d_end = entry["end"] - old["end"]
            if abs(d_start) > 0.005 or abs(d_end) > 0.005:
                lines.append(
                    f"  {index + 1:>2}. {entry.get('beat', new['source'])}: "
                    f"início {d_start:+.2f}s, fim {d_end:+.2f}s "
                    f"→ [{entry['start']:.2f}, {entry['end']:.2f}]"
                )
        else:
            entry["reason"] = "range novo, criado no OpenCut"
            lines.append(
                f"  {index + 1:>2}. NOVO {new['source']} "
                f"[{entry['start']:.2f}, {entry['end']:.2f}]"
            )
        merged.append(entry)

    dropped = [r for r in original if id(r) not in used]
    for old in dropped:
        lines.append(
            f"  — REMOVIDO {old.get('beat', old['source'])} "
            f"[{old['start']:.2f}, {old['end']:.2f}]"
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = edit_dir / f"edl.json.bak-{stamp}"
    shutil.copy2(edl_path, backup)

    edl["ranges"] = merged
    edl["total_duration_s"] = round(sum(r["end"] - r["start"] for r in merged), 3)
    edl_path.write_text(json.dumps(edl, indent=2, ensure_ascii=False) + "\n")

    header = (
        f"edl.json reescrito: {len(original)} → {len(merged)} takes, "
        f"{edl['total_duration_s']:.1f}s (backup: {backup.name})"
    )
    summary = header + ("\n" + "\n".join(lines) if lines else "\n  (nenhuma borda mudou)")

    (edit_dir / "opencut").mkdir(exist_ok=True)
    (edit_dir / "opencut" / "last_return.json").write_text(
        json.dumps({"at": stamp, "summary": summary, "takes": len(merged)},
                   indent=2, ensure_ascii=False) + "\n"
    )
    return summary


# ---------------------------------------------------------------- servidor

def make_handler(bundle: dict, paths: dict[str, Path], edit_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route in ("/bundle.json", "/"):
                payload = json.dumps(bundle).encode()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if route.startswith("/media/"):
                key = route[len("/media/"):]
                path = paths.get(key)
                if path is None:
                    self.send_error(404, "fonte desconhecida")
                    return
                self._send_file(path)
                return

            self.send_error(404)

        def _send_file(self, path: Path) -> None:
            size = path.stat().st_size
            start, end = 0, size - 1
            status = 200
            header = self.headers.get("Range")
            if header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
                if match:
                    if match[1]:
                        start = int(match[1])
                        end = int(match[2]) if match[2] else size - 1
                    elif match[2]:
                        start = max(0, size - int(match[2]))
                    status = 206

            length = max(0, end - start + 1)
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/edl":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                incoming = payload.get("ranges") or []
                if not incoming:
                    raise ValueError("nenhum range recebido")
                summary = merge_back(edit_dir, incoming)
            except Exception as error:  # devolve o motivo pra UI, não só 500
                body = f"ERRO: {error}".encode()
                self.send_response(400)
                self._cors()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            print("\n" + summary, flush=True)
            body = summary.encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            pass

    return Handler


# ---------------------------------------------------------------- cli

def cmd_serve(args: argparse.Namespace) -> int:
    edit_dir = Path(args.edit_dir).expanduser().resolve()
    bundle, paths = build_bundle(edit_dir, args.port, args.name, args.canvas)

    out_dir = edit_dir / "opencut"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "bundle.json").write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
    )

    total = sum(r["end"] - r["start"] for r in bundle["ranges"])
    print(f"{len(bundle['ranges'])} takes, {total:.1f}s, "
          f"{len(bundle['media'])} fonte(s), "
          f"canvas {bundle['project']['canvas']['width']}x"
          f"{bundle['project']['canvas']['height']}")

    if args.no_serve:
        print(f"bundle escrito em {out_dir / 'bundle.json'} (sem servidor)")
        return 0

    # Porta ocupada normalmente significa outra ponte no ar, de OUTRO projeto.
    # Cair na porta seguinte é melhor que morrer: dois cortes abertos ao mesmo
    # tempo é uso legítimo, e reusar a porta importaria o projeto errado.
    server, port = None, args.port
    for candidate in range(args.port, args.port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate),
                                         make_handler(bundle, paths, edit_dir))
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit(f"portas {args.port}–{args.port + 9} ocupadas")

    if port != args.port:
        # As URLs de mídia dentro do bundle carregam a porta: refaça-as.
        for media in bundle["media"]:
            media["url"] = f"http://127.0.0.1:{port}/media/{media['key']}"
        bundle["postUrl"] = f"http://127.0.0.1:{port}/edl"
        (out_dir / "bundle.json").write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
        )
        print(f"porta {args.port} ocupada → usando {port}")

    url = f"{args.opencut.rstrip('/')}/edvid?bundle=http://127.0.0.1:{port}/bundle.json"
    print(f"\nAbra: {url}\n")
    print("Ctrl-C encerra. Ao clicar em 'Devolver' no OpenCut, "
          "o resumo do que mudou aparece aqui.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado")
    finally:
        server.server_close()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.edit_dir).expanduser().resolve() / "opencut" / "last_return.json"
    if not path.exists():
        print("nenhuma devolução do OpenCut ainda neste projeto")
        return 0
    data = json.loads(path.read_text())
    print(f"última devolução: {data['at']}\n{data['summary']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="monta o bundle e serve pro OpenCut")
    serve.add_argument("--edit-dir", required=True)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--opencut", default=DEFAULT_OPENCUT)
    serve.add_argument("--name", default=None, help="nome do projeto no OpenCut")
    serve.add_argument("--canvas", default=None, help="ex 1080x1920")
    serve.add_argument("--no-serve", action="store_true",
                       help="só escreve opencut/bundle.json")
    serve.set_defaults(func=cmd_serve)

    status = sub.add_parser("status", help="mostra a última devolução")
    status.add_argument("--edit-dir", required=True)
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
