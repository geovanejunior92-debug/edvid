"""Background queue for single-source automatic cuts in the web Preview."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Callable

import preview_requests
from project_health import operation, write_json
from studio_pipeline import PROPOSAL_LABEL, StudioPipeline


PipelineFactory = Callable[[Path], StudioPipeline]


class CancellableRunner:
    """subprocess.run-compatible runner whose current process group can be stopped."""

    def __init__(self):
        self.lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        self.stopping = False

    @property
    def pid(self):
        with self.lock:
            return self.process.pid if self.process else None

    def __call__(self, command, capture_output=False, text=False, timeout=None, **_kwargs):
        with self.lock:
            if self.stopping:
                return subprocess.CompletedProcess(command, -signal.SIGTERM, "" if text else b"", "" if text else b"")
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=text,
                start_new_session=True,
            )
            self.process = process
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            self._terminate(process)
            stdout, stderr = process.communicate()
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        finally:
            with self.lock:
                if self.process is process:
                    self.process = None

    @staticmethod
    def _terminate(process):
        try:
            group = os.getpgid(process.pid)
        except ProcessLookupError:
            return
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                break
            time.sleep(.05)
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass

    def cancel(self):
        with self.lock:
            self.stopping = True
            process = self.process
        if process:
            self._terminate(process)


class AutomaticRequestQueue:
    """Run the existing verified Phase-1 pipeline for explicit automatic requests."""

    RECOVERABLE = {"queued", "transcribing", "proposing", "approving", "rendering"}
    FINAL = {"completed", "failed", "awaiting_agent"}

    def __init__(self, projects: dict[str, Path], pipeline_factory: PipelineFactory | None = None,
                 autostart: bool = True):
        self.projects = projects
        self.pipeline_factory = pipeline_factory
        self.runner = CancellableRunner()
        self.owner = uuid.uuid4().hex
        self.condition = threading.Condition()
        self.jobs: deque[tuple[Path, str]] = deque()
        self.claimed: set[tuple[str, str]] = set()
        self.stopping = False
        self.thread: threading.Thread | None = None
        self._recover()
        if autostart:
            self.thread = threading.Thread(target=self._worker, name="edvid-preview-automatic", daemon=True)
            self.thread.start()

    @staticmethod
    def _key(root: Path, request_id: str) -> tuple[str, str]:
        return str(Path(root).resolve()), request_id

    def _recover(self) -> None:
        for root in list(self.projects.values()):
            try:
                records = preview_requests.all_requests(root)
            except (OSError, ValueError):
                continue
            for record in records:
                if record.get("mode") == "automatic" and record.get("status") in self.RECOVERABLE:
                    self.enqueue(root, record)

    def enqueue(self, root: Path, record: dict) -> dict:
        root = Path(root).resolve()
        request_id = record.get("id")
        if not isinstance(request_id, str):
            raise ValueError("Pedido automático sem identificador")
        current = preview_requests.get(root, request_id)
        if current.get("mode") != "automatic" or current.get("status") in self.FINAL:
            return current
        if len(current.get("sources") or []) != 1:
            return preview_requests.update(
                root,
                request_id,
                status="awaiting_agent",
                response="O pedido usa vários vídeos e aguarda uma estratégia editorial do agente.",
                updatedAt=time.time(),
            )
        if not self._phase_one_ready(root):
            return preview_requests.update(
                root,
                request_id,
                status="awaiting_agent",
                response="O projeto já entrou na Fase 2. O agente precisa preservar ou invalidar o acabamento antes de refazer o corte.",
                updatedAt=time.time(),
            )
        source_path = Path(str(current["sources"][0].get("path", "")))
        if source_path.is_symlink():
            return preview_requests.update(
                root,
                request_id,
                status="awaiting_agent",
                response="O vídeo é um link de arquivo. O agente precisa copiá-lo para o projeto antes do corte automático.",
                updatedAt=time.time(),
            )
        key = self._key(root, request_id)
        with self.condition:
            if key in self.claimed:
                return current
        current = preview_requests.claim(root, request_id, self.owner)
        if current is None:
            return preview_requests.get(root, request_id)
        with self.condition:
            self.claimed.add(key)
            self.jobs.append((root, request_id))
            self.condition.notify()
        return current

    @staticmethod
    def _phase_one_ready(root: Path) -> bool:
        try:
            state = json.loads((Path(root) / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return (isinstance(state, dict) and state.get("phase", 1) == 1
                and not any(state.get(key) for key in ("finalVideo", "captions", "editData")))

    def process_next(self) -> bool:
        with self.condition:
            if not self.jobs:
                return False
            root, request_id = self.jobs.popleft()
        key = self._key(root, request_id)
        try:
            try:
                self._process(root, request_id)
            except Exception:
                # One damaged request must never stop the durable consumer.
                pass
        finally:
            with self.condition:
                self.claimed.discard(key)
        return True

    def _stage(self, root: Path, request_id: str, status: str, label: str, action):
        if self.stopping:
            raise InterruptedError("O servidor foi encerrado durante o corte automático.")
        preview_requests.update_owned(
            root,
            request_id,
            self.owner,
            status=status,
            response=f"{label}…",
            updatedAt=time.time(),
        )
        with operation(root, label):
            return action()

    def _process(self, root: Path, request_id: str) -> None:
        try:
            record = preview_requests.get(root, request_id)
            project = root.parent.resolve()
            source_path = Path(record["sources"][0]["path"])
            if source_path.is_symlink():
                raise ValueError("O vídeo automático precisa ser um arquivo real dentro do projeto.")
            raw_source = source_path.resolve()
            if not raw_source.is_file() or not raw_source.is_relative_to(project):
                raise ValueError("O vídeo automático não está mais disponível dentro do projeto.")
            source = str(raw_source.relative_to(project))
            pipeline = (self.pipeline_factory(project) if self.pipeline_factory
                        else StudioPipeline(project, runner=self.runner))
            with pipeline.mutation_lock():
                if not preview_requests.owns(root, request_id, self.owner):
                    return
                if not self._phase_one_ready(root):
                    preview_requests.update_owned(
                        root, request_id, self.owner, release=True,
                        status="awaiting_agent",
                        response="O projeto entrou na Fase 2 antes do corte. O agente precisa revisar os derivados.",
                        updatedAt=time.time(),
                    )
                    return
                self._stage(
                    root,
                    request_id,
                    "transcribing",
                    "Transcrevendo vídeo",
                    lambda: pipeline.transcribe(source, "pt", "large-v3-turbo"),
                )
                proposal = self._stage(
                    root,
                    request_id,
                    "proposing",
                    "Montando corte técnico",
                    lambda: pipeline.propose_cut(source),
                )
                revision = proposal["revision"]
                plan_hash = proposal["planHash"]
                preview_requests.update_owned(
                    root,
                    request_id,
                    self.owner,
                    approval={
                        "kind": "automatic-request",
                        "strategy": PROPOSAL_LABEL,
                        "revision": revision,
                        "planHash": plan_hash,
                    },
                    updatedAt=time.time(),
                )
                self._stage(
                    root,
                    request_id,
                    "approving",
                    "Confirmando estratégia automática",
                    lambda: pipeline.approve_plan(revision, plan_hash, True),
                )
                rendered = self._stage(
                    root,
                    request_id,
                    "rendering",
                    "Renderizando e verificando o corte",
                    lambda: pipeline.render_cut(revision, plan_hash, preview=True),
                )
                if not self._phase_one_ready(root):
                    raise ValueError("O projeto mudou de fase durante o corte automático.")
                state_path = root / "state.json"
                state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
                if not isinstance(state, dict):
                    raise ValueError("O estado do projeto é inválido.")
                state["message"] = "Corte automático pronto para revisão."
                write_json(state_path, state)
                preview_requests.update_owned(
                    root,
                    request_id,
                    self.owner,
                    status="completed",
                    response="Corte técnico automático concluído e verificado.",
                    result={
                        "revision": revision,
                        "planHash": plan_hash,
                        "output": rendered.get("output", "edit/cut.mp4"),
                        "verified": rendered.get("verified") is True,
                    },
                    updatedAt=time.time(),
                )
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            try:
                preview_requests.update_owned(
                    root,
                    request_id,
                    self.owner,
                    release=True,
                    status="queued" if self.stopping else "failed",
                    response=("O corte foi interrompido e será retomado quando o servidor reabrir."
                              if self.stopping else "O corte automático não foi concluído."),
                    error=message[:1000],
                    updatedAt=time.time(),
                )
            except (OSError, ValueError):
                pass

    def _worker(self) -> None:
        while True:
            with self.condition:
                while not self.jobs and not self.stopping:
                    self.condition.wait()
                if self.stopping:
                    return
            try:
                self.process_next()
            except Exception:
                continue

    def close(self) -> None:
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        self.runner.cancel()
        if self.thread:
            self.thread.join(timeout=30)
            if not self.thread.is_alive():
                self.thread = None
