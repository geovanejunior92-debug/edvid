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
import treblo_music


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
    PIPELINE_ACTIONS = {"status", "save-brief", "transcribe", "propose-cut", "approve-plan",
                        "render-cut", "apply-preview-edits", "undo", "redo"}
    FINISH_ACTIONS = {"save", "approve", "render", "review-approve"}

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
            return [self._public_job(x) for x in reversed(self.jobs)]

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            job = next((x for x in self.jobs if x["id"] == job_id), None)
            return self._public_job(job) if job else None

    @staticmethod
    def _manifest_provider(job: dict) -> dict | None:
        raw = job.get("manifest")
        if not raw:
            return None
        value = _read_json(Path(raw), None)
        if not isinstance(value, dict):
            return None
        task_id = value.get("task_id")
        status = value.get("status")
        provider = {}
        if isinstance(task_id, str) and task_id:
            provider["taskId"] = task_id
        if isinstance(status, str) and status:
            provider["status"] = status
        return provider or None

    def _public_job(self, job: dict) -> dict:
        result = dict(job)
        provider = self._manifest_provider(job)
        if provider:
            result["provider"] = provider
        return result

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

    def enqueue_music(self, project_id: str, prompt: str, length_min: int,
                      length_max: int, confirmed: bool) -> dict:
        project = self.projects.get(project_id)
        if not project:
            raise ValueError("Projeto não encontrado.")
        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 2000:
            raise ValueError("Descreva a música em até 2.000 caracteres.")
        if confirmed is not True:
            raise ValueError("Confirme que autoriza o uso de créditos da Treblo.")
        if (isinstance(length_min, bool) or isinstance(length_max, bool)
                or not isinstance(length_min, int) or not isinstance(length_max, int)
                or length_min < 0 or length_max > 300
                or length_min % 30 or length_max % 30 or length_min >= length_max):
            raise ValueError("As durações devem ser múltiplos de 30, entre 0 e 300, com mínimo menor que máximo.")
        try:
            treblo_music.load_api_key()
        except RuntimeError:
            raise ValueError("A Treblo ainda não está configurada neste computador.") from None
        project_root = Path(project["path"]).resolve()
        folder = Path(project.get("editPath") or project_root / "edit") / "music"
        folder.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        output = folder / f"{job_id}.mp3"
        manifest = folder / f"{job_id}.json"
        now = time.time()
        job = {"id": job_id, "projectId": project_id, "kind": "music", "prompt": prompt,
               "lengthMin": length_min, "lengthMax": length_max, "output": str(output),
               "manifest": str(manifest), "status": "queued", "createdAt": now, "updatedAt": now}
        with self.condition:
            self.jobs.append(job)
            self._save()
            self.condition.notify()
        return dict(job)

    def enqueue_pipeline(self, project_id: str, action: str, options: dict) -> dict:
        project = self.projects.get(project_id)
        if not project:
            raise ValueError("Projeto não encontrado.")
        if action not in self.PIPELINE_ACTIONS:
            raise ValueError("Ação da Fase 1 não permitida.")
        root = Path(project["path"]).resolve()
        now = time.time()
        job = {"id": uuid.uuid4().hex, "projectId": project_id, "kind": "pipeline",
               "action": action, "status": "queued", "createdAt": now, "updatedAt": now}
        if action in {"transcribe", "propose-cut"}:
            source = Path(str(options.get("source", ""))).expanduser().resolve()
            if not source.is_file() or not source.is_relative_to(root):
                raise ValueError("O vídeo da Fase 1 precisa estar dentro do projeto selecionado.")
            job["source"] = str(source.relative_to(root))
        if action == "save-brief":
            script = options.get("script")
            if not isinstance(script, str) or not script.strip() or len(script) > 100_000:
                raise ValueError("Informe um roteiro de até 100.000 caracteres.")
            job["script"] = script
        if action == "transcribe":
            language = options.get("language", "pt")
            if language not in {"pt", "en", "es"}:
                raise ValueError("Idioma de transcrição não permitido.")
            job["language"] = language
        if action in {"approve-plan", "render-cut"}:
            revision = options.get("revision")
            plan_hash = options.get("planHash")
            if (isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
                    or not isinstance(plan_hash, str) or len(plan_hash) != 64
                    or any(char not in "0123456789abcdef" for char in plan_hash.lower())):
                raise ValueError("A revisão e o hash do plano exibido são obrigatórios.")
            if action == "approve-plan" and options.get("approve") is not True:
                raise ValueError("A aprovação precisa ser confirmada explicitamente.")
            job.update(revision=revision, planHash=plan_hash)
            if action == "approve-plan":
                job["approve"] = True
        if action == "apply-preview-edits":
            raw = str(options.get("previewEdits", "edit/preview_edits.json"))
            candidate = Path(raw).expanduser()
            preview_edits = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            if not preview_edits.is_file() or not preview_edits.is_relative_to(root) or preview_edits.suffix.lower() != ".json":
                raise ValueError("Os ajustes de preview precisam ser um JSON dentro do projeto.")
            job["previewEdits"] = str(preview_edits.relative_to(root))
        with self.condition:
            if action != "status" and any(x.get("kind") == "pipeline" and x.get("projectId") == project_id
                                          and x.get("status") in {"queued", "running"} and x.get("action") != "status"
                                          for x in self.jobs):
                raise ValueError("Este projeto já tem uma ação da Fase 1 na fila.")
            self.jobs.append(job)
            self._save()
            self.condition.notify()
        return dict(job)

    @staticmethod
    def _valid_hash(value: object) -> bool:
        return (isinstance(value, str) and len(value) == 64
                and all(char in "0123456789abcdef" for char in value.lower()))

    PHASE2_ACTIONS = ("status", "scaffold", "save", "approve", "render")

    def enqueue_phase2(self, project_id: str, action: str, options: dict) -> dict:
        """Fase 2 (Remotion). Mesma disciplina do finish: uma ação de edição por
        projeto de cada vez, aprovação explícita, hash do que está na tela."""
        project = self.projects.get(project_id)
        if not project:
            raise ValueError("Projeto não encontrado.")
        if action not in self.PHASE2_ACTIONS:
            raise ValueError("Ação de Fase 2 não permitida.")
        now = time.time()
        job = {"id": uuid.uuid4().hex, "projectId": project_id, "kind": "phase2",
               "action": action, "status": "queued", "createdAt": now, "updatedAt": now}
        if action == "save":
            raw = options.get("editData")
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError("O caminho do edit-data dentro do projeto é obrigatório.")
            job["editData"] = raw.strip()
        elif action in {"approve", "render"}:
            revision, data_hash = options.get("revision"), options.get("dataHash")
            if (isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
                    or not self._valid_hash(data_hash)):
                raise ValueError("A revisão e o hash exibidos são obrigatórios.")
            if action == "approve" and options.get("approve") is not True:
                raise ValueError("A aprovação da Fase 2 precisa ser confirmada explicitamente.")
            job.update(revision=revision, dataHash=data_hash)
            if action == "approve":
                job["approve"] = True
        with self.condition:
            if any(x.get("projectId") == project_id and x.get("status") in {"queued", "running"}
                   and x.get("kind") in {"pipeline", "finish", "phase2"} and x.get("action") != "status"
                   for x in self.jobs):
                raise ValueError("Este projeto já tem uma ação de edição na fila.")
            self.jobs.append(job)
            self.condition.notify_all()
        return job

    def enqueue_finish(self, project_id: str, action: str, options: dict) -> dict:
        project = self.projects.get(project_id)
        if not project:
            raise ValueError("Projeto não encontrado.")
        if action not in self.FINISH_ACTIONS:
            raise ValueError("Ação de finalização não permitida.")
        now = time.time()
        job = {"id": uuid.uuid4().hex, "projectId": project_id, "kind": "finish",
               "action": action, "status": "queued", "createdAt": now, "updatedAt": now}
        if action == "save":
            settings = options.get("settings")
            if not isinstance(settings, dict):
                raise ValueError("As configurações de finalização são obrigatórias.")
            encoded = json.dumps(settings, ensure_ascii=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > 1024 * 1024:
                raise ValueError("As configurações de finalização excedem o limite permitido.")
            job["settings"] = settings
        elif action in {"approve", "render"}:
            revision = options.get("revision")
            settings_hash = options.get("settingsHash")
            if (isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
                    or not self._valid_hash(settings_hash)):
                raise ValueError("A revisão e o hash das configurações exibidas são obrigatórios.")
            if action == "approve" and options.get("approve") is not True:
                raise ValueError("A aprovação das configurações precisa ser confirmada explicitamente.")
            job.update(revision=revision, settingsHash=settings_hash)
            if action == "approve":
                job["approve"] = True
        else:
            output_hash = options.get("outputHash")
            if not self._valid_hash(output_hash) or options.get("fullReview") is not True:
                raise ValueError("O hash do arquivo e a revisão visual integral precisam ser confirmados explicitamente.")
            job.update(outputHash=output_hash, fullReview=True)
        with self.condition:
            if any(x.get("projectId") == project_id and x.get("status") in {"queued", "running"}
                   and x.get("kind") in {"pipeline", "finish", "phase2"} and x.get("action") != "status"
                   for x in self.jobs):
                raise ValueError("Este projeto já tem uma ação de edição na fila.")
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
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
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
        if job["kind"] == "music":
            return [sys.executable, str(Path(__file__).with_name("treblo_music.py")), job["prompt"],
                    "-o", job["output"], "--length-min", str(job["lengthMin"]),
                    "--length-max", str(job["lengthMax"]), "--manifest", job["manifest"]]
        if job["kind"] == "pipeline":
            project = self.projects.get(job["projectId"])
            if not project:
                raise ValueError("Projeto removido da biblioteca.")
            command = [sys.executable, str(Path(__file__).with_name("studio_pipeline.py")),
                       "--root", str(Path(project["path"]).resolve()), "--action", job["action"]]
            if job.get("source"):
                command.extend(["--source", job["source"]])
            if job["action"] == "save-brief":
                command.extend(["--script", job["script"]])
            if job["action"] == "transcribe":
                command.extend(["--language", job["language"], "--model", "large-v3-turbo"])
            if job["action"] in {"approve-plan", "render-cut"}:
                command.extend(["--revision", str(job["revision"]), "--plan-hash", job["planHash"]])
            if job["action"] == "approve-plan":
                command.append("--approve")
            if job["action"] == "apply-preview-edits":
                command.extend(["--preview-edits", job["previewEdits"]])
            return command
        if job["kind"] == "phase2":
            project = self.projects.get(job["projectId"])
            if not project:
                raise ValueError("Projeto removido da biblioteca.")
            command = [sys.executable, str(Path(__file__).with_name("studio_phase2.py")),
                       "--root", str(Path(project["path"]).resolve()), "--action", job["action"]]
            if job["action"] == "save":
                command.extend(["--edit-data", job["editData"]])
            if job["action"] in {"approve", "render"}:
                command.extend(["--revision", str(job["revision"]), "--data-hash", job["dataHash"]])
            if job["action"] == "approve":
                command.append("--approve")
            return command
        if job["kind"] == "finish":
            project = self.projects.get(job["projectId"])
            if not project:
                raise ValueError("Projeto removido da biblioteca.")
            command = [sys.executable, str(Path(__file__).with_name("studio_finish.py")),
                       "--root", str(Path(project["path"]).resolve()), "--action", job["action"]]
            if job["action"] == "save":
                command.extend(["--settings-json", json.dumps(job["settings"], ensure_ascii=False,
                                                               separators=(",", ":"))])
            if job["action"] in {"approve", "render"}:
                command.extend(["--revision", str(job["revision"]),
                                "--settings-hash", job["settingsHash"]])
            if job["action"] == "approve":
                command.append("--approve")
            if job["action"] == "review-approve":
                command.extend(["--output-hash", job["outputHash"], "--full-review"])
            return command
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
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                           start_new_session=True)
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
                        if job["kind"] in {"probe", "pipeline", "finish", "phase2"}:
                            job["result"] = json.loads(stdout or "{}")
                    else:
                        if job["kind"] in {"pipeline", "finish", "phase2"}:
                            try:
                                failure = json.loads(stdout or "{}")
                            except (ValueError, TypeError):
                                failure = {}
                            detail = failure.get("error") if isinstance(failure, dict) else None
                            fallback = "A ação da Fase 1 não foi concluída." if job["kind"] == "pipeline" else "A finalização não foi concluída."
                            message = detail if isinstance(detail, str) and 0 < len(detail) <= 500 else fallback
                        elif job["kind"] == "music":
                            message = "A operação local não terminou. Consulte o ID da tarefa antes de usar a recuperação pela linha de comando."
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
                if job.get("kind") == "proxy" and job.get("status") != "completed" and job.get("output"):
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
        elif path.startswith("/api/pipeline/"):
            project_id = path[len("/api/pipeline/"):]
            project = self.app.projects.get(project_id)
            if not project:
                self._json({"error": "Projeto não encontrado."}, 404)
                return
            state_path = Path(project.get("editPath") or Path(project["path"]) / "edit") / "studio-pipeline" / "state.json"
            if not state_path.is_file():
                self._json({"state": None})
                return
            try:
                if state_path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError
                state = _read_json(state_path, None)
                if not isinstance(state, dict):
                    raise ValueError
            except (OSError, ValueError):
                self._json({"error": "O estado da Fase 1 não pôde ser lido."}, 400)
                return
            self._json({"state": state})
        elif path.startswith("/api/phase2/"):
            project_id = path[len("/api/phase2/"):]
            project = self.app.projects.get(project_id)
            if not project:
                self._json({"error": "Projeto não encontrado."}, 404)
                return
            state_path = (Path(project.get("editPath") or Path(project["path"]) / "edit")
                          / "studio-phase2" / "state.json")
            if not state_path.is_file():
                self._json({"state": None})
                return
            try:
                if state_path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError
                phase2_state = _read_json(state_path, None)
                if not isinstance(phase2_state, dict):
                    raise ValueError
            except (OSError, ValueError):
                self._json({"state": None})
                return
            self._json({"state": phase2_state})
        elif path.startswith("/api/finish/"):
            project_id = path[len("/api/finish/"):]
            project = self.app.projects.get(project_id)
            if not project:
                self._json({"error": "Projeto não encontrado."}, 404)
                return
            state_path = Path(project.get("editPath") or Path(project["path"]) / "edit") / "studio-finish" / "state.json"
            if not state_path.is_file():
                self._json({"state": None})
                return
            try:
                if state_path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError
                finish_state = _read_json(state_path, None)
                if not isinstance(finish_state, dict):
                    raise ValueError
            except (OSError, ValueError):
                self._json({"error": "O estado da finalização não pôde ser lido."}, 400)
                return
            self._json({"state": finish_state})
        elif path == "/api/providers/treblo":
            try:
                treblo_music.load_api_key()
                configured = True
            except RuntimeError:
                configured = False
            self._json({"configured": configured})
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
                if body.get("kind") == "music":
                    job = self.app.queue.enqueue_music(str(body.get("projectId", "")), str(body.get("prompt", "")),
                                                       body.get("lengthMin"), body.get("lengthMax"),
                                                       body.get("confirmed") is True)
                elif body.get("kind") == "pipeline":
                    job = self.app.queue.enqueue_pipeline(str(body.get("projectId", "")),
                                                          str(body.get("action", "")), body)
                elif body.get("kind") == "finish":
                    job = self.app.queue.enqueue_finish(str(body.get("projectId", "")),
                                                        str(body.get("action", "")), body)
                elif body.get("kind") == "phase2":
                    job = self.app.queue.enqueue_phase2(str(body.get("projectId", "")),
                                                        str(body.get("action", "")), body)
                else:
                    job = self.app.queue.enqueue(str(body.get("projectId", "")), str(body.get("kind", "")), Path(str(body.get("input", ""))))
                self._json(job, 202)
            elif path == "/api/providers/treblo/check":
                try:
                    key = treblo_music.load_api_key()
                    balance = treblo_music.check_connection(key)
                    safe = {name: balance.get(name) for name in ("num_credits", "num_credits_payg") if name in balance}
                    self._json({"authenticated": True, "balance": safe})
                except (RuntimeError, OSError, ValueError):
                    self._json({"error": "Não foi possível autenticar na Treblo. Confira a configuração e tente novamente."}, 400)
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
