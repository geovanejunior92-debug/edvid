"""Edvid preview server — serves the standard editing interface + session media.

The interface app (assets/preview/) is IMMUTABLE and lives in the skill repo;
per-session it is fed by data only:
  - <edit>/state.json          written by the skill (phase, files, message)
  - <edit>/edl.json            the cut (segments shown/trimmed on the timeline)
  - <edit>/cut.mp4             current render (played + scrubbed)
  - <edit>/preview_edits.json  WRITTEN BY THE UI when the user saves timeline
                               adjustments — the skill reads, validates, applies
                               and re-renders. The UI never touches edl.json.
  - <edit>/preview_style.json  WRITTEN BY THE UI at the Fase 1 → Fase 2 gate:
                               editing style, caption style, edit elements.

Routes:
  /                     the app (from <skill>/assets/preview/)
  /assets/<file>        app files (css/js/logo)
  /media/<path>         files under --root (the edit dir) — Range supported
  /gen/waveform.json    min/max audio peaks of cut.mp4 (auto-(re)generated)
  /gen/thumbs/<n>.jpg   timeline filmstrip thumbs (auto-generated, 1 per 2s)
  /api/state    GET     state.json + mtimes (UI polls this to hot-reload)
  /api/save     POST    body → <edit>/preview_edits.json (atomic), or
                        <edit>/preview_style.json when body.type=="style-setup"

Usage:
    uv run helpers/preview_server.py --root <videos_dir>/edit [--port 4820]
"""
from __future__ import annotations

import hashlib
import os
import secrets
import signal
import uuid
from http import cookies
from urllib.parse import parse_qs, urlsplit, unquote
from project_health import health, write_json
import preview_requests
import preview_automatic
import preview_mix
import preview_library
import argparse
import array
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "assets" / "preview"
PEAKS_PER_SEC = 40
THUMB_EVERY_S = 2.0
THUMB_HEIGHT = 90

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".srt": "text/plain; charset=utf-8",
}

_thumb_lock = threading.Lock()
_thumb_state: dict[str, float] = {}  # video path -> mtime generated


def probe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        return float(out)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return 0.0


def gen_waveform(video: Path, out_json: Path) -> None:
    """Decode audio to mono s16 and store min/max peak pairs per bucket (0-100)."""
    rate = 8000
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True,
    ).stdout
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    per_bucket = max(1, rate // PEAKS_PER_SEC)
    mins: list[int] = []
    maxs: list[int] = []
    for i in range(0, len(samples), per_bucket):
        chunk = samples[i:i + per_bucket]
        if not chunk:
            continue
        mins.append(round(min(chunk) / 32768 * 100))
        maxs.append(round(max(chunk) / 32768 * 100))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_json.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "peaksPerSec": PEAKS_PER_SEC,
        "duration": len(samples) / rate,
        "min": mins,
        "max": maxs,
        "srcMtime": video.stat().st_mtime,
    }))
    tmp.replace(out_json)


def gen_thumbs(video: Path, out_dir: Path) -> None:
    """Filmstrip thumbs: one small jpg every THUMB_EVERY_S seconds."""
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video),
         "-vf", f"fps=1/{THUMB_EVERY_S},scale=-2:{THUMB_HEIGHT}",
         "-q:v", "6", str(out_dir / "%04d.jpg")],
        check=False, capture_output=True,
    )
    (out_dir / "meta.json").write_text(json.dumps({
        "everySec": THUMB_EVERY_S,
        "count": len(list(out_dir.glob("*.jpg"))),
        "srcMtime": video.stat().st_mtime,
    }))


class Handler(BaseHTTPRequestHandler):
    root: Path  # set on the class by main()
    protocol_version = "HTTP/1.1"

    # ---- helpers ----
    def _hdr(self, code: int, ctype: str, length: int | None = None,
             extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Accept-Ranges", "bytes")
        if length is not None:
            self.send_header("Content-Length", str(length))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, obj: object, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self._hdr(code, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        """Static file with HTTP Range support (video scrubbing needs it)."""
        if not path.is_file():
            self._json({"error": f"not found: {path.name}"}, 404)
            return
        size = path.stat().st_size
        ctype = MIME.get(path.suffix.lower(), "application/octet-stream")
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                elif m.group(2):  # suffix range: last N bytes
                    start = max(0, size - int(m.group(2)))
                code = 206
        length = end - start + 1
        extra = {"Content-Range": f"bytes {start}-{end}/{size}"} if code == 206 else None
        self._hdr(code, ctype, length, extra)
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1 << 16, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    def _safe(self, base: Path, rel: str) -> Path | None:
        p = (base / rel.lstrip("/")).resolve()
        return p if p.is_relative_to(base.resolve()) else None

    def _cookie_ok(self) -> bool:
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            return False
        value = jar.get("edvid_preview_session")
        expected = getattr(self.server, "session", "")
        return bool(value and expected and secrets.compare_digest(value.value, expected))

    def _authorize(self) -> tuple[bool, bool]:
        supplied = parse_qs(urlsplit(self.path).query).get("token", [""])[0]
        expected = getattr(self.server, "token", "")
        bootstrap = bool(supplied and expected and secrets.compare_digest(supplied, expected))
        return self._cookie_ok() or bootstrap, bootstrap

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return False
        parsed = urlsplit(origin)
        return parsed.scheme == "http" and parsed.netloc == self.headers.get("Host")

    def _auth_error(self) -> None:
        self._json({"error": "Sessão inválida. Abra novamente o link seguro do Edvid."}, 401)

    def _current_video(self) -> Path | None:
        state_p = self.root / "state.json"
        rel = "cut.mp4"
        if state_p.exists():
            try:
                rel = json.loads(state_p.read_text()).get("video") or rel
            except json.JSONDecodeError:
                pass
        p = self._safe(self.root, rel)
        return p if p and p.exists() else None

    def _select_project(self) -> bool:
        self.root = self.server.default_root
        path = self.path.split('?', 1)[0]
        self.project_scoped = path.startswith('/p/')
        if self.project_scoped:
            parts = path.split('/', 3)
            if len(parts) < 4 or parts[2] not in self.server.projects:
                self._json({'error': 'Projeto não encontrado'}, 404)
                return False
            self.root = self.server.projects[parts[2]]
            self.path = '/' + parts[3]
        return True

    def _projects(self) -> None:
        items = []
        flags = preview_library.load_registry(self.server.library)
        active = getattr(self.server, 'default_root', None)
        for key, root in list(self.server.projects.items()):
            # The active root is always in `projects` so /p/<id>/ can route to it,
            # but a root with no state.json is not a project the user made — it is
            # the placeholder the server was pointed at. Listing it produced a
            # permanent "PRECISA DE ATENÇÃO — Projeto indisponível" card that
            # nothing could fix, because there was nothing wrong.
            if root == active and not (root / 'state.json').is_file():
                continue
            entry = flags.get(key, {})
            mark = {'pinned': bool(entry.get('pinned')), 'archived': bool(entry.get('archived'))}
            try:
                state = json.loads((root / 'state.json').read_text())
                status = health(root, state)
                thumbs = sorted((root / '.preview_cache' / 'thumbs').glob('*.jpg'))
                # A frame from the MIDDLE of the filmstrip: frame one is
                # routinely a slate, a black fade-in or a closed eye.
                thumbs = thumbs[len(thumbs) // 2:] or thumbs
                items.append({'id': key, 'name': state.get('project') or root.parent.name,
                              'updatedAt': (root / 'state.json').stat().st_mtime,
                              'status': status['code'], 'message': status['message'],
                              'thumbnail': f'/p/{key}/media/.preview_cache/thumbs/{thumbs[0].name}' if thumbs else None,
                              **mark})
            except (OSError, ValueError, TypeError):
                items.append({'id': key, 'name': root.parent.name, 'updatedAt': 0,
                              'status': 'error', 'message': 'Projeto indisponível', 'thumbnail': None,
                              **mark})
        self._json({'projects': sorted(items, key=lambda x: (not x['pinned'], -x['updatedAt']))})

    def _project_update(self, body: dict) -> None:
        key = body.get('id')
        root = self.server.projects.get(key) if isinstance(key, str) else None
        if root is None:
            raise ValueError('Projeto não encontrado')
        result = {'ok': True, 'id': key}
        if 'name' in body:
            result['name'] = preview_library.rename(root, body.get('name'))
        if 'pinned' in body or 'archived' in body:
            result.update(preview_library.set_flags(
                self.server.library, key,
                pinned=body.get('pinned') if 'pinned' in body else None,
                archived=body.get('archived') if 'archived' in body else None))
        self._json(result)

    def _relink(self, body: dict) -> None:
        if health(self.root, {}).get('code') == 'processing' or (self.root / 'preview_edits.json').exists():
            raise ValueError('Aguarde o processamento ou a aplicação dos ajustes antes de recuperar a mídia.')
        field = body.get('field')
        if field not in ('video', 'finalVideo'):
            raise ValueError('Escolha o corte ou a versão final.')
        source = Path(str(body.get('path', ''))).expanduser().resolve()
        if not source.is_relative_to(self.server.library) or not source.is_file():
            raise ValueError('Escolha um arquivo dentro da pasta de projetos configurada.')
        if source.suffix.lower() not in ('.mp4', '.mov', '.m4v', '.webm') or probe_duration(source) <= 0:
            raise ValueError('O arquivo escolhido não é um vídeo legível.')
        # Copy instead of moving or hard-linking: the selected original stays untouched.
        state_path = self.root / 'state.json'
        state = json.loads(state_path.read_text())
        if not isinstance(state, dict):
            raise ValueError('O estado do projeto é inválido.')
        folder = self.root / 'recovered'
        folder.mkdir(exist_ok=True)
        dest = folder / (uuid.uuid4().hex + source.suffix.lower())
        temp = dest.with_suffix('.tmp')
        try:
            shutil.copy2(source, temp)
            temp.replace(dest)
            write_json(self.root / '.recovery' / (uuid.uuid4().hex + '.json'), state)
            state[field] = str(dest.relative_to(self.root))
            write_json(state_path, state)
        finally:
            temp.unlink(missing_ok=True)
        self._json({'ok': True})

    # ---- routes ----
    def do_GET(self) -> None:  # noqa: N802
        if getattr(self.server, "auth_required", False):
            authorized, bootstrap = self._authorize()
            if not authorized:
                self._auth_error()
                return
            if bootstrap:
                self.send_response(302)
                self.send_header("Location", urlsplit(self.path).path or "/")
                self.send_header("Set-Cookie", f"edvid_preview_session={self.server.session}; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        if not self._select_project():
            return
        path = self.path.split("?", 1)[0]
        if path == '/api/media-candidates':
            files = []
            for base, dirs, names in os.walk(self.server.library):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'transcripts')]
                for name in names:
                    file = Path(base, name)
                    if file.suffix.lower() in ('.mp4', '.mov', '.m4v', '.webm') and file.is_file() and file.resolve().is_relative_to(self.server.library):
                        files.append({'path': str(file.resolve()), 'name': str(file.relative_to(self.server.library))})
                    if len(files) >= 300:
                        break
                if len(files) >= 300:
                    break
            self._json({'files': sorted(files, key=lambda x: x['name'])})
            return
        if path == '/api/projects':
            self._projects()
            return
        if path == '/projects':
            self._send_file(APP_DIR / 'projects.html')
            return
        if path in ("/", "/index.html"):
            self._send_file(APP_DIR / ("index.html" if self.project_scoped else "projects.html"))
        elif path.startswith("/assets/"):
            p = self._safe(APP_DIR, path[len("/assets/"):])
            self._send_file(p) if p else self._json({"error": "bad path"}, 400)
        elif path.startswith("/media/"):
            p = self._safe(self.root, path[len("/media/"):])
            self._send_file(p) if p else self._json({"error": "bad path"}, 400)
        elif path == "/gen/waveform.json":
            self._waveform()
        elif path.startswith("/gen/thumbs/"):
            self._thumbs(path[len("/gen/thumbs/"):])
        elif path == "/api/insert-assets":
            self._json({"assets": preview_requests.insert_assets(self.root)})
        elif path == "/api/sources":
            self._json({"sources": [{k: v for k, v in item.items() if k != 'path'} for item in preview_requests.sources(self.root)]})
        elif path.startswith("/source-media/"):
            key = path.rsplit('/', 1)[-1]
            item = next((x for x in preview_requests.sources(self.root) if x['id'] == key), None)
            self._send_file(Path(item['path'])) if item else self._json({'error': 'Fonte indisponível'}, 404)
        elif path == "/api/requests":
            try:
                self._json({'requests': preview_requests.requests(self.root)})
            except ValueError as e:
                self._json({'error': str(e)}, 400)
        elif path == "/api/state":
            self._state()
        else:
            self._json({"error": "unknown route"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if getattr(self.server, "auth_required", False):
            if not self._cookie_ok():
                self._auth_error()
                return
            if not self._same_origin():
                self._json({'error': 'Origem não permitida'}, 403)
                return
        if not self._select_project():
            return
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            self._json({'error': 'Origem não permitida'}, 403)
            return
        if self.path.split('?', 1)[0] == '/api/import':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                self.connection.settimeout(120)
                name = preview_library.receive(self.root, unquote(self.headers.get('X-Filename', '')), self.rfile, length)
                self._json({'ok': True, 'filename': name})
            except (ValueError, OSError) as e:
                self.close_connection = True
                self._json({'error': str(e)}, 400)
            return
        if self.path.split("?", 1)[0] not in ("/api/save", "/api/relink", "/api/requests", "/api/projects/create", "/api/projects/update"):
            self._json({"error": "unknown route"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 1024 * 1024:
                raise ValueError('Request too large')
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError('Expected object')
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "invalid JSON"}, 400)
            return
        if self.path.split('?', 1)[0] == '/api/projects/create':
            try:
                key, root = preview_library.create(self.server.library, body.get('name'))
                self.server.projects[key] = root
                self._json({'ok': True, 'id': key, 'url': f'/p/{key}/'})
            except (ValueError, OSError) as e:
                self._json({'error': str(e)}, 400)
            return
        if self.path.split('?', 1)[0] == '/api/projects/update':
            try:
                self._project_update(body)
            except (ValueError, OSError) as e:
                self._json({'error': str(e)}, 400)
            return
        if self.path.split('?', 1)[0] == '/api/requests':
            try:
                record = preview_requests.submit(self.root, body)
                automatic = getattr(self.server, 'automatic_requests', None)
                if automatic:
                    record = automatic.enqueue(self.root, record)
                self._json({'ok': True, 'request': record})
            except (ValueError, OSError) as e:
                self._json({'error': str(e)}, 400)
            return
        if self.path.split('?', 1)[0] == '/api/relink':
            try:
                with self.server.recovery_lock:
                    self._relink(body)
            except (ValueError, OSError) as e:
                self._json({'error': str(e)}, 400)
            return
        if body.get('type') == 'style-setup':
            try:
                preview_mix.validate(body)
            except ValueError as e:
                self._json({'error': str(e)}, 400)
                return
        if 'notes' in body:
            try:
                preview_requests.validate_media_notes(self.root, body['notes'])
            except ValueError as e:
                self._json({'error': str(e)}, 400)
                return
        body["savedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        # The style pick goes to its own file. It is a one-time setup decision,
        # not a correction, and sharing preview_edits.json would make one save
        # clobber the other (they are written at different moments, by different
        # screens, and the skill consumes+deletes them independently).
        name = "preview_style.json" if body.get("type") == "style-setup" else "preview_edits.json"
        out = self.root / name
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2))
        tmp.replace(out)
        self._json({"ok": True, "file": str(out)})

    # ---- dynamic bits ----
    def _state(self) -> None:
        state_p = self.root / "state.json"
        state: dict = {}
        try:
            if state_p.exists():
                state = json.loads(state_p.read_text())
                if not isinstance(state, dict):
                    raise ValueError('Expected object')
        except (json.JSONDecodeError, ValueError):
            state = {"error": "state.json inválido"}
        except OSError as e:
            # A read that is refused (macOS privacy, or a permission change made
            # after startup) used to raise here and 500 the endpoint, which the
            # UI shows as its ordinary waiting screen — indistinguishable from
            # "the cut is not rendered yet". Say what happened instead.
            state = {"error": f"sem permissão para ler state.json: {e}"}
        # attach small data files + mtimes so the UI hot-reloads on change
        mtimes: dict[str, float] = {}
        for key in ("video", "finalVideo", "edl", "captions", "editData"):
            rel = state.get(key)
            if not rel:
                continue
            p = self._safe(self.root, rel)
            if p and p.exists():
                mtimes[key] = p.stat().st_mtime
        # Faixa de transcrição e painel de diagnóstico (2026-09-01): arquivos
        # que os helpers escrevem sem mexer no state.json — entram no mtime
        # para o poll do preview recarregar quando eles aparecem ou mudam.
        for key, rel in (("transcript", state.get("transcript") or "transcripts/cut.json"),
                         ("diagnostics", "diagnostics.json")):
            p = self._safe(self.root, rel)
            if p and p.exists():
                mtimes[key] = p.stat().st_mtime
        edl = None
        rel = state.get("edl") or "edl.json"
        p = self._safe(self.root, rel)
        if p and p.exists():
            try:
                edl = json.loads(p.read_text())
            except json.JSONDecodeError:
                pass
        pending_style = None
        style_path = self._safe(self.root, "preview_style.json")
        if style_path and style_path.is_file():
            try:
                candidate = json.loads(style_path.read_text())
                if isinstance(candidate, dict): pending_style = candidate
            except (ValueError, OSError): pass
        edits_p = self.root / "preview_edits.json"
        video = self._current_video()
        duration = probe_duration(video) if video else 0
        project_health = health(self.root, state)
        if video and duration <= 0 and project_health['code'] != 'processing':
            project_health.update(code='error', message='O vídeo existe, mas não foi possível abri-lo. Verifique o arquivo e o ffprobe.')
        self._json({
            "state": state,
            "pendingStyle": pending_style,
            "health": project_health,
            "edl": edl,
            "mtimes": mtimes,
            "videoDuration": duration,
            "hasPendingEdits": edits_p.exists(),
            "now": time.time(),
        })

    def _waveform(self) -> None:
        video = self._current_video()
        if not video:
            self._json({"error": "sem vídeo ainda"}, 404)
            return
        out = self.root / ".preview_cache" / "waveform.json"
        stale = True
        if out.exists():
            try:
                stale = json.loads(out.read_text()).get("srcMtime") != video.stat().st_mtime
            except json.JSONDecodeError:
                pass
        if stale:
            gen_waveform(video, out)
        self._send_file(out)

    def _thumbs(self, name: str) -> None:
        video = self._current_video()
        if not video:
            self._json({"error": "sem vídeo ainda"}, 404)
            return
        out_dir = self.root / ".preview_cache" / "thumbs"
        meta = out_dir / "meta.json"
        with _thumb_lock:
            stale = True
            if meta.exists():
                try:
                    stale = json.loads(meta.read_text()).get("srcMtime") != video.stat().st_mtime
                except json.JSONDecodeError:
                    pass
            if stale:
                gen_thumbs(video, out_dir)
        p = self._safe(out_dir, name)
        self._send_file(p) if p else self._json({"error": "bad path"}, 400)

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # quiet


def _check_access(root: Path) -> None:
    """Fail loudly, at startup, when the edit dir cannot be read or written.

    Without this the failure is silent in the worst way: the server starts, the
    UI opens on its waiting screen, and it waits forever for a state.json that
    the skill was never allowed to write. The user sees a working preview with
    no video and nothing to act on.

    The errno is the diagnosis on macOS. Its privacy layer (TCC) guards
    ~/Documents, ~/Desktop, ~/Downloads and iCloud Drive, and denies with
    EPERM (1) "Operation not permitted" — an app the user never granted Files
    and Folders access to gets that even though the file permissions are fine.
    Ordinary permission or ownership problems come back as EACCES (13). The two
    need completely different fixes, so do not merge the messages.
    """
    probe = root / ".edvid_write_probe"
    err: OSError | None = None
    try:
        probe.write_text("ok")
        probe.unlink()
        for _ in root.iterdir():
            break
    except OSError as exc:
        # Bind outside the handler: Python deletes the `except` name on exit.
        err = exc
    if err is None:
        return

    where = f"{root}"
    if getattr(err, "errno", None) == 1 and sys.platform == "darwin":
        raise SystemExit(
            f"sem permissão para escrever em {where}\n"
            "\n"
            "No macOS isso é a proteção de privacidade do sistema, não a permissão\n"
            "do arquivo: ~/Documents, ~/Desktop, ~/Downloads e o iCloud Drive são\n"
            "protegidos, e o app precisa ser autorizado uma vez.\n"
            "\n"
            "  Ajustes do Sistema → Privacidade e Segurança → Arquivos e Pastas\n"
            "  (ou Acesso Total ao Disco) → ligue para o Claude / o Terminal\n"
            "\n"
            "Depois feche e reabra o app.\n"
            "\n"
            "SE AS PERMISSÕES JÁ ESTIVEREM LIGADAS: reinicie o Mac. O cache de\n"
            "permissões do macOS às vezes fica preso mostrando a chave ativa sem\n"
            "conceder o acesso, e só o reinício resolve. (Visto em produção — foi\n"
            "exatamente isso, e nenhuma mexida nos Ajustes tinha efeito.)\n"
            "\n"
            "Se preferir não lidar com permissão, mova a pasta dos vídeos para fora\n"
            "dessas três pastas — por exemplo ~/Videos."
        )
    raise SystemExit(
        f"sem permissão para ler/escrever em {where}: {err}\n"
        "Confira o dono e as permissões da pasta."
    )


def discover_projects(library: Path, active: Path) -> dict[str, Path]:
    library, active = library.resolve(), active.resolve()
    projects = {hashlib.sha256(str(active).encode()).hexdigest()[:16]: active}
    for base, dirs, files in os.walk(library):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'remotion', 'transcripts')]
        if 'state.json' in files:
            path = Path(base).resolve()
            if path.is_relative_to(library.resolve()):
                projects[hashlib.sha256(str(path).encode()).hexdigest()[:16]] = path
            dirs[:] = []
    return projects


def make_server(root: Path, library: Path, host: str = "127.0.0.1", port: int = 4820,
                automatic_factory=preview_automatic.AutomaticRequestQueue,
                require_auth: bool | None = None, token: str | None = None) -> ThreadingHTTPServer:
    root = Path(root).resolve()
    library = Path(library).resolve()
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.default_root = root
    srv.library = library
    srv.projects = discover_projects(library, root)
    srv.recovery_lock = threading.Lock()
    srv.auth_required = (host not in {"127.0.0.1", "localhost", "::1"}
                         if require_auth is None else require_auth)
    srv.token = token or secrets.token_urlsafe(32)
    srv.session = secrets.token_urlsafe(32)
    srv.automatic_requests = automatic_factory(srv.projects)
    Handler.root = root
    return srv


def main() -> None:
    ap = argparse.ArgumentParser(description="Edvid preview interface server")
    ap.add_argument("--root", type=Path, required=True, help="the session <edit> dir")
    ap.add_argument('--library', type=Path, help='folder containing projects; defaults to the active project parent')
    ap.add_argument("--port", type=int, default=4820)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 libera o preview para a rede local (celular na mesma Wi-Fi)")
    ap.add_argument("--token", help="token opcional para o acesso pela rede local")
    args = ap.parse_args()

    root = args.root.resolve()
    if not root.exists():
        raise SystemExit(f"edit dir not found: {root}")
    _check_access(root)
    if not (APP_DIR / "index.html").exists():
        raise SystemExit(f"app not found at {APP_DIR}")

    # 127.0.0.1 por padrão: o preview serve a pasta da edição, então não fica
    # aberto na rede sem alguém pedir. Com --host 0.0.0.0 ele passa a aceitar
    # conexão da rede local, que é como o usuário assiste e marca correções pelo
    # celular enquanto o Mac faz o trabalho (2026-08-17).
    library = (args.library or root.parent).resolve()
    srv = make_server(root, library, args.host, args.port, token=args.token)
    suffix = f"/?token={srv.token}" if srv.auth_required else "/"
    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"Edvid preview → http://{display_host}:{srv.server_port}{suffix}  (root: {root})", flush=True)
    if args.host == "0.0.0.0":
        print("Em outro dispositivo, troque 127.0.0.1 pelo IP deste Mac.", flush=True)
    def stop_server(_signum, _frame):
        threading.Thread(target=srv.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop_server)
    try:
        srv.serve_forever()
    finally:
        srv.automatic_requests.close()
        srv.server_close()


if __name__ == "__main__":
    main()
