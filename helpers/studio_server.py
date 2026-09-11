"""Local HTTP service for Edvid Studio projects, jobs, and preview editing."""
from __future__ import annotations

import argparse
import fcntl
from http import cookies
import json
import os
from pathlib import Path
import secrets
import signal
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import preview_server


APP_DIR = Path(__file__).resolve().parent.parent / "assets" / "studio"
PREVIEW_DIR = Path(__file__).resolve().parent.parent / "assets" / "preview"


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def _read_json(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


class ProjectRegistry:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "projects.json"
        self.lock = threading.RLock()
        raw = _read_json(self.path, {"version": 1, "projects": []})
        items = raw.get("projects", []) if isinstance(raw, dict) else []
        self.items = {x["id"]: x for x in items if isinstance(x, dict) and isinstance(x.get("id"), str)}

    def list(self) -> list[dict]:
        with self.lock:
            return sorted((dict(x) for x in self.items.values()), key=lambda x: x.get("updatedAt", 0), reverse=True)

    def get(self, project_id: str) -> dict | None:
        with self.lock:
            item = self.items.get(project_id)
            return dict(item) if item else None

    def add(self, path: Path, create: bool = False) -> dict:
        if not str(path).strip() or str(path) == ".":
            raise ValueError("Informe a pasta do projeto.")
        path = path.expanduser().resolve()
        if create:
            path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise ValueError("Escolha uma pasta existente ou marque a opção para criá-la.")
        is_edit = path.name == "edit" and ((path / "state.json").exists() or (path / "edl.json").exists())
        edit = path if is_edit else path / "edit"
        project_path = path.parent if is_edit else path
        edit.mkdir(exist_ok=True)
        now = time.time()
        project_id = uuid.uuid5(uuid.NAMESPACE_URL, str(project_path)).hex[:20]
        with self.lock:
            item = self.items.get(project_id, {"id": project_id, "createdAt": now})
            item.update({"name": project_path.name or str(project_path), "path": str(project_path),
                         "editPath": str(edit), "updatedAt": now})
            self.items[project_id] = item
            self._save()
            return dict(item)

    def _save(self) -> None:
        atomic_json(self.path, {"version": 1, "projects": list(self.items.values())})


class JobQueue:
    FINAL = {"completed", "failed", "cancelled", "interrupted"}

    def __init__(self, data_dir: Path, projects: ProjectRegistry, command_builder=None):
        self.path = data_dir / "queue.json"
        self.projects = projects
        self.command_builder = command_builder or self._build_command
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.process: subprocess.Popen | None = None
        self.running_id: str | None = None
        self.stopping = False
        raw = _read_json(self.path, {"version": 1, "jobs": []})
        jobs = raw.get("jobs", []) if isinstance(raw, dict) else []
        self.jobs = [x for x in jobs if isinstance(x, dict) and isinstance(x.get("id"), str)]
        changed = False
        for job in self.jobs:
            if job.get("status") in {"queued", "running"}:
                job.update(status="interrupted", finishedAt=time.time(), error="O aplicativo foi encerrado durante esta tarefa.")
                changed = True
        if changed:
            self._save()
        self.thread = threading.Thread(target=self._worker, name="edvid-studio-queue", daemon=True)
        self.thread.start()

    def list(self) -> list[dict]:
        with self.lock:
            return [dict(x) for x in reversed(self.jobs)]

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            job = next((x for x in self.jobs if x["id"] == job_id), None)
            return dict(job) if job else None

    def enqueue(self, project_id: str, kind: str, input_path: Path) -> dict:
        project = self.projects.get(project_id)
        if not project:
            raise ValueError("Projeto não encontrado.")
        if kind not in {"probe", "proxy"}:
            raise ValueError("Tipo de tarefa não permitido.")
        root = Path(project["path"]).resolve()
        source = input_path.expanduser().resolve()
        if not source.is_file() or not source.is_relative_to(root):
            raise ValueError("O arquivo precisa estar dentro do projeto selecionado.")
        now = time.time()
        job = {"id": uuid.uuid4().hex, "projectId": project_id, "kind": kind,
               "input": str(source), "status": "queued", "createdAt": now, "updatedAt": now}
        with self.condition:
            self.jobs.append(job)
            self._save()
            self.condition.notify()
        return dict(job)

    def cancel(self, job_id: str) -> bool:
        process = None
        with self.condition:
            job = next((x for x in self.jobs if x["id"] == job_id), None)
            if not job or job.get("status") in self.FINAL:
                return False
            if job.get("status") == "queued":
                job.update(status="cancelled", finishedAt=time.time(), updatedAt=time.time())
                self._save()
                return True
            job["cancelRequested"] = True
            job["updatedAt"] = time.time()
            self._save()
            if self.running_id == job_id:
                process = self.process
        if process:
            self._terminate(process)
        return True

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)

    def close(self) -> None:
        with self.condition:
            self.stopping = True
            process = self.process
            self.condition.notify_all()
        if process and process.poll() is None:
            self._terminate(process)
        self.thread.join(timeout=3)

    def _save(self) -> None:
        atomic_json(self.path, {"version": 1, "jobs": self.jobs})

    def _build_command(self, job: dict) -> list[str]:
        source = job["input"]
        if job["kind"] == "probe":
            return ["ffprobe", "-v", "error", "-show_entries", "format=duration,size,format_name",
                    "-of", "json", source]
        project = self.projects.get(job["projectId"])
        if not project:
            raise ValueError("Projeto removido da biblioteca.")
        folder = Path(project.get("editPath") or Path(project["path"]) / "edit") / "proxies"
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / f"{Path(source).stem}-{job['id'][:8]}.mp4"
        job["output"] = str(output)
        return ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", source,
                "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "28", "-c:a", "aac", "-b:a", "128k", str(output)]

    def _worker(self) -> None:
        while True:
            with self.condition:
                job = next((x for x in self.jobs if x.get("status") == "queued"), None)
                while job is None and not self.stopping:
                    self.condition.wait()
                    job = next((x for x in self.jobs if x.get("status") == "queued"), None)
                if self.stopping:
                    return
                job.update(status="running", startedAt=time.time(), updatedAt=time.time())
                self.running_id = job["id"]
                self._save()
            try:
                with self.lock:
                    if job.get("cancelRequested") or self.stopping:
                        job.update(status="cancelled" if job.get("cancelRequested") else "interrupted",
                                   error="Tarefa cancelada." if job.get("cancelRequested") else "O aplicativo foi encerrado durante esta tarefa.")
                        continue
                command = self.command_builder(job)
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                with self.lock:
                    self.process = process
                    self._save()
                    terminate_now = bool(job.get("cancelRequested") or self.stopping)
                if terminate_now:
                    self._terminate(process)
                stdout, stderr = process.communicate()
                with self.lock:
                    cancelled = bool(job.get("cancelRequested"))
                    if self.stopping and not cancelled:
                        job.update(status="interrupted", error="O aplicativo foi encerrado durante esta tarefa.")
                    elif cancelled:
                        job.update(status="cancelled", error="Tarefa cancelada.")
                    elif process.returncode == 0:
                        job.update(status="completed")
                        if job["kind"] == "probe":
                            job["result"] = json.loads(stdout or "{}")
                    else:
                        tool = "ffprobe" if job["kind"] == "probe" else "FFmpeg"
                        detail = (stderr or "terminou sem explicar o erro.").strip()[-3900:]
                        message = f"{tool}: {detail}"
                        job.update(status="failed", error=message)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                with self.lock:
                    job.update(status="failed", error=str(exc))
            finally:
                with self.condition:
                    job.update(finishedAt=time.time(), updatedAt=time.time())
                    self.process = None
                    self.running_id = None
                    self._save()
                    self.condition.notify_all()
                if job.get("status") != "completed" and job.get("output"):
                    try:
                        Path(job["output"]).unlink(missing_ok=True)
                    except OSError as exc:
                        with self.condition:
                            job["cleanupError"] = f"Não foi possível apagar o proxy parcial: {exc}"
                            self._save()


class StudioApp:
    def __init__(self, data_dir: Path, token: str | None = None):
        self.data_dir = data_dir.expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock_handle = (self.data_dir / ".studio.lock").open("a+")
        try:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock_handle.close()
            raise RuntimeError("O Edvid Studio já está usando esta pasta de dados.")
        self.token = token or secrets.token_urlsafe(32)
        self.session = secrets.token_urlsafe(32)
        self.projects = ProjectRegistry(self.data_dir)
        self.queue = JobQueue(self.data_dir, self.projects)

    def close(self) -> None:
        self.queue.close()
        if not self._lock_handle.closed:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            self._lock_handle.close()


class StudioHandler(preview_server.Handler):
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> StudioApp:
        return self.server.app

    def _cookie_ok(self) -> bool:
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            return False
        value = jar.get("edvid_session")
        return bool(value and secrets.compare_digest(value.value, self.app.session))

    def _authorize(self) -> tuple[bool, bool]:
        query = parse_qs(urlsplit(self.path).query)
        supplied = query.get("token", [""])[0]
        bootstrap = bool(supplied and secrets.compare_digest(supplied, self.app.token))
        return self._cookie_ok() or bootstrap, bootstrap

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return False
        parsed = urlsplit(origin)
        return parsed.scheme == "http" and parsed.netloc == self.headers.get("Host")

    def _json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 1024 * 1024:
                raise ValueError
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, json.JSONDecodeError):
            raise ValueError("Pedido inválido.")

    def _auth_error(self) -> None:
        self._json({"error": "Sessão inválida. Feche e abra o Edvid Studio novamente."}, 401)

    def _serve_studio_index(self, bootstrap: bool) -> None:
        path = APP_DIR / "index.html"
        if not path.is_file():
            self._json({"error": "Interface não encontrada."}, 500)
            return
        body = path.read_bytes()
        extra = None
        if bootstrap:
            extra = {"Set-Cookie": f"edvid_session={self.app.session}; Path=/; HttpOnly; SameSite=Strict"}
        self._hdr(200, "text/html; charset=utf-8", len(body), extra)
        self.wfile.write(body)

    def _media_candidates(self, library: Path) -> None:
        files = []
        for base, dirs, names in os.walk(library):
            dirs[:] = [name for name in dirs if not name.startswith(".") and name not in {"node_modules", "transcripts"}]
            for name in names:
                file = Path(base, name)
                if file.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm"}:
                    resolved = file.resolve()
                    if resolved.is_file() and resolved.is_relative_to(library):
                        files.append({"path": str(resolved), "name": str(resolved.relative_to(library))})
                if len(files) >= 300:
                    break
            if len(files) >= 300:
                break
        self._json({"files": sorted(files, key=lambda item: item["name"])})

    def _relink_at(self, body: dict, library: Path) -> None:
        if preview_server.health(self.root, {}).get("code") == "processing" or (self.root / "preview_edits.json").exists():
            raise ValueError("Aguarde o processamento ou a aplicação dos ajustes antes de recuperar a mídia.")
        field = body.get("field")
        if field not in {"video", "finalVideo"}:
            raise ValueError("Escolha o corte ou a versão final.")
        source = Path(str(body.get("path", ""))).expanduser().resolve()
        if not source.is_file() or not source.is_relative_to(library):
            raise ValueError("Escolha um arquivo dentro do projeto selecionado.")
        if source.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm"} or preview_server.probe_duration(source) <= 0:
            raise ValueError("O arquivo escolhido não é um vídeo legível.")
        state_path = self.root / "state.json"
        state = _read_json(state_path, None)
        if not isinstance(state, dict):
            raise ValueError("O estado do projeto é inválido.")
        folder = self.root / "recovered"
        folder.mkdir(exist_ok=True)
        destination = folder / f"{uuid.uuid4().hex}{source.suffix.lower()}"
        temp = destination.with_suffix(".tmp")
        try:
            shutil.copy2(source, temp)
            temp.replace(destination)
            preview_server.write_json(self.root / ".recovery" / f"{uuid.uuid4().hex}.json", state)
            state[field] = str(destination.relative_to(self.root))
            preview_server.write_json(state_path, state)
        finally:
            temp.unlink(missing_ok=True)
        self._json({"ok": True})

    def _editor(self, method: str) -> bool:
        path = urlsplit(self.path).path
        parts = path.split("/", 3)
        if len(parts) < 3 or parts[1] != "editor":
            return False
        project = self.app.projects.get(parts[2])
        if not project:
            self._json({"error": "Projeto não encontrado."}, 404)
            return True
        edit = Path(project.get("editPath") or Path(project["path"]) / "edit").resolve()
        library = Path(project["path"]).resolve()
        self.server.projects[parts[2]] = edit
        remainder = parts[3] if len(parts) == 4 else ""
        if method == "GET" and remainder in {"", "index.html"}:
            text = (PREVIEW_DIR / "index.html").read_text(encoding="utf-8")
            prefix = f"/editor/{parts[2]}/assets/"
            text = text.replace('"/assets/', f'"{prefix}').replace("'/assets/", f"'{prefix}")
            body = text.encode()
            self._hdr(200, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
            return True
        if method == "GET" and remainder == "api/media-candidates":
            self._media_candidates(library)
            return True
        if method == "POST" and remainder == "api/relink":
            try:
                with self.server.recovery_lock:
                    self.root = edit
                    self._relink_at(self._json_body(), library)
            except (ValueError, OSError) as exc:
                self._json({"error": str(exc)}, 400)
            return True
        self.path = f"/p/{parts[2]}/{remainder}"
        if method == "GET":
            super().do_GET()
        else:
            super().do_POST()
        return True

    def do_GET(self) -> None:
        authorized, bootstrap = self._authorize()
        if not authorized:
            self._auth_error()
            return
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._serve_studio_index(bootstrap)
        elif path == "/projects":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path.startswith("/assets/"):
            file = self._safe(PREVIEW_DIR, path[len("/assets/"):])
            self._send_file(file) if file else self._json({"error": "Caminho inválido."}, 400)
        elif path.startswith("/studio/"):
            rel = path[len("/studio/"):]
            file = self._safe(APP_DIR, rel)
            self._send_file(file) if file else self._json({"error": "Caminho inválido."}, 400)
        elif path == "/api/projects":
            items = []
            for item in self.app.projects.list():
                copy = dict(item)
                copy["available"] = Path(item["path"]).is_dir()
                items.append(copy)
            self._json({"projects": items})
        elif path == "/api/jobs":
            self._json({"jobs": self.app.queue.list()})
        elif path == "/api/diagnostics":
            self._json({"python": sys.version.split()[0], "ffmpeg": shutil.which("ffmpeg"),
                        "ffprobe": shutil.which("ffprobe"), "dataDir": str(self.app.data_dir),
                        "queueRunning": self.app.queue.running_id})
        elif path.startswith("/project-media/"):
            project_id = path[len("/project-media/"):]
            project = self.app.projects.get(project_id)
            raw = parse_qs(urlsplit(self.path).query).get("path", [""])[0]
            if not project or not raw:
                self._json({"error": "Arquivo não encontrado."}, 404)
                return
            root = Path(project["path"]).resolve()
            media = Path(raw).expanduser().resolve()
            if not media.is_file() or not media.is_relative_to(root):
                self._json({"error": "O arquivo precisa estar dentro do projeto selecionado."}, 400)
                return
            self._send_file(media)
        elif self._editor("GET"):
            return
        else:
            self._json({"error": "Rota não encontrada."}, 404)

    def do_POST(self) -> None:
        authorized, _ = self._authorize()
        if not authorized:
            self._auth_error()
            return
        if not self._same_origin():
            self._json({"error": "Origem não permitida."}, 403)
            return
        path = urlsplit(self.path).path
        if path.startswith("/editor/"):
            parts = path.split("/", 3)
            active = self.app.queue.get(self.app.queue.running_id) if self.app.queue.running_id else None
            if active and len(parts) > 2 and active.get("projectId") == parts[2]:
                self._json({"error": "Aguarde a tarefa do projeto terminar antes de salvar no editor."}, 409)
                return
            self._editor("POST")
            return
        try:
            body = self._json_body()
            if path == "/api/projects":
                item = self.app.projects.add(Path(str(body.get("path", ""))), bool(body.get("create")))
                self._json(item, 201)
            elif path == "/api/jobs":
                job = self.app.queue.enqueue(str(body.get("projectId", "")), str(body.get("kind", "")), Path(str(body.get("input", ""))))
                self._json(job, 202)
            elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path.split("/")[3]
                if not self.app.queue.cancel(job_id):
                    self._json({"error": "Tarefa não encontrada ou já encerrada."}, 409)
                else:
                    self._json({"ok": True})
            else:
                self._json({"error": "Rota não encontrada."}, 404)
        except (ValueError, OSError) as exc:
            self._json({"error": str(exc)}, 400)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def make_server(app: StudioApp, port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), StudioHandler)
    server.app = app
    server.default_root = app.data_dir
    server.library = app.data_dir
    server.projects = {}
    server.recovery_lock = threading.Lock()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Serviço local do Edvid Studio")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    app = StudioApp(args.data_dir)
    server = make_server(app, args.port)
    url = f"http://127.0.0.1:{server.server_port}/?token={app.token}"
    print(json.dumps({"url": url}), flush=True)
    def stop_server(_signum, _frame):
        # shutdown() must run outside the serve_forever() thread.
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop_server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()


if __name__ == "__main__":
    main()
