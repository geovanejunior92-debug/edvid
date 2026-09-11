"""Safe local Phase-1 pipeline for Edvid Studio.

Every path is confined to the selected project.  Commands emit one JSON object
on stdout so the Studio can persist and display the result without scraping
human-oriented helper output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
PROPOSAL_LABEL = "proposta técnica por pausas, sem seleção narrativa"
HELPERS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = HELPERS_DIR.parent.resolve()
Runner = Callable[..., subprocess.CompletedProcess]


class PipelineError(RuntimeError):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        Path(raw).unlink(missing_ok=True)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"JSON inválido ou ilegível: {path.name}") from exc


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _file_fingerprint(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "size": path.stat().st_size}


def _parse_fps(raw: str) -> float:
    try:
        numerator, denominator = raw.strip().split("/", 1)
        value = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        try:
            value = float(raw.strip())
        except ValueError as exc:
            raise PipelineError("ffprobe não retornou um frame rate válido") from exc
    if value <= 0:
        raise PipelineError("ffprobe não retornou um frame rate válido")
    return round(value, 6)


class StudioPipeline:
    def __init__(self, root: Path, runner: Runner = subprocess.run):
        candidate = root.expanduser().resolve()
        if not candidate.is_dir():
            raise PipelineError("a raiz do projeto não existe ou não é uma pasta")
        if candidate == SKILL_ROOT or candidate.is_relative_to(SKILL_ROOT):
            raise PipelineError("a instalação do edvid não pode ser usada como projeto")
        self.root = candidate
        self.edit = candidate / "edit"
        self.data = self.edit / "studio-pipeline"
        self.state_path = self.data / "state.json"
        self.runner = runner
        for path in (self.edit, self.data):
            if path.exists() and not path.resolve().is_relative_to(self.root):
                raise PipelineError("edit/studio-pipeline precisa permanecer dentro do projeto")

    def _prepare_writes(self) -> None:
        self.edit.mkdir(exist_ok=True)
        self.data.mkdir(parents=True, exist_ok=True)
        if not self.edit.resolve().is_relative_to(self.root) or not self.data.resolve().is_relative_to(self.root):
            raise PipelineError("os diretórios de saída precisam permanecer dentro do projeto")

    @contextmanager
    def mutation_lock(self):
        """Serialize mutations from the app and CLI for one project."""
        import fcntl
        lock_path = self.root / ".edvid-studio-pipeline.lock"
        with lock_path.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise PipelineError("já existe uma ação do pipeline em execução neste projeto") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def confined(self, raw: str | Path, *, must_exist: bool = False) -> Path:
        path = Path(raw).expanduser()
        path = (self.root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(self.root):
            raise PipelineError("o caminho precisa permanecer dentro do projeto")
        if must_exist and not path.exists():
            raise PipelineError(f"arquivo não encontrado no projeto: {path.relative_to(self.root)}")
        return path

    def _state(self) -> dict:
        if not self.state_path.exists():
            return {"version": SCHEMA_VERSION, "project": str(self.root), "history": []}
        value = _read_json(self.state_path)
        if not isinstance(value, dict):
            raise PipelineError("state.json precisa conter um objeto")
        value.setdefault("history", [])
        return value

    def _record(self, action: str, ok: bool, **fields: Any) -> dict:
        self._prepare_writes()
        state = self._state()
        event = {"action": action, "ok": ok, "at": int(time.time()), **fields}
        state["lastCommand"] = event
        state["history"] = (state.get("history") or [])[-99:] + [event]
        _atomic_json(self.state_path, state)
        return event

    def status(self) -> dict:
        return {"ok": True, "action": "status", "state": self._state()}

    def save_brief(self, script: str | None, script_file: str | None) -> dict:
        self._prepare_writes()
        if script is not None and script_file is not None:
            raise PipelineError("use --script ou --script-file, não ambos")
        if script_file:
            source = self.confined(script_file, must_exist=True)
            if source.stat().st_size > 2_000_000:
                raise PipelineError("o arquivo de roteiro excede 2 MB")
            if source.suffix.lower() == ".json":
                raw = _read_json(source)
                if isinstance(raw, dict):
                    script = raw.get("script") or raw.get("roteiro") or raw.get("text")
                elif isinstance(raw, str):
                    script = raw
                else:
                    raise PipelineError("o JSON do roteiro precisa ser texto ou objeto com script/roteiro/text")
            else:
                script = source.read_text(encoding="utf-8")
        script = (script or "").strip()
        if not script:
            raise PipelineError("o roteiro está vazio")
        brief = {"version": 1, "script": script, "updatedAt": int(time.time())}
        out = self.data / "brief.json"
        _atomic_json(out, brief)
        event = self._record("save-brief", True, brief=str(out.relative_to(self.root)))
        return {"ok": True, **event}

    def transcribe(self, source_raw: str, language: str | None, model: str) -> dict:
        self._prepare_writes()
        source = self.confined(source_raw, must_exist=True)
        if not source.is_file():
            raise PipelineError("a fonte selecionada não é um arquivo")
        cmd = [sys.executable, str(HELPERS_DIR / "transcribe.py"), str(source),
               "--edit-dir", str(self.edit), "--model", model]
        if language:
            cmd += ["--language", language]
        run = self.runner(cmd, capture_output=True, text=True)
        transcript = self.edit / "transcripts" / f"{source.stem}.json"
        if run.returncode or not transcript.is_file():
            raise PipelineError((run.stderr or run.stdout or "a transcrição falhou").strip()[-2000:])
        data = _read_json(transcript)
        backend = str(data.get("_transcription_backend", "")) if isinstance(data, dict) else ""
        event = self._record("transcribe", True, source=str(source.relative_to(self.root)),
                             transcript=str(transcript.relative_to(self.root)), backend=backend,
                             log=(run.stdout or "")[-2000:])
        return {"ok": True, **event}

    @staticmethod
    def _word_rows(transcript: dict) -> list[dict]:
        rows = []
        for item in transcript.get("words") or []:
            if item.get("type") == "spacing":
                continue
            try:
                start, end = float(item["start"]), float(item["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if end >= start and str(item.get("text", "")).strip():
                rows.append({"start": start, "end": end, "text": str(item["text"]).strip()})
        return sorted(rows, key=lambda row: (row["start"], row["end"]))

    def propose_cut(self, source_raw: str, pause: float = 0.65) -> dict:
        self._prepare_writes()
        if pause < 0.25 or pause > 10:
            raise PipelineError("--pause precisa ficar entre 0,25 e 10 segundos")
        source = self.confined(source_raw, must_exist=True)
        transcript_path = self.edit / "transcripts" / f"{source.stem}.json"
        transcript = _read_json(transcript_path)
        backend = str(transcript.get("_transcription_backend", ""))
        if not backend.startswith("whisperx/") or "/UNALIGNED" in backend:
            raise PipelineError("a proposta exige transcript WhisperX com alinhamento; UNALIGNED não fecha bordas")
        source_fingerprint = _file_fingerprint(source)
        transcript_source_hash = str((transcript.get("_cache") or {}).get("sha256", ""))
        if not transcript_source_hash or transcript_source_hash != source_fingerprint["sha256"]:
            raise PipelineError("o transcript não pertence ao conteúdo atual da fonte; transcreva novamente")
        words = self._word_rows(transcript)
        if not words:
            raise PipelineError("o transcript alinhado não contém palavras com tempo")
        acoustic = self.runner([sys.executable, str(HELPERS_DIR / "speech_regions.py"), str(source)],
                               capture_output=True, text=True)
        if acoustic.returncode:
            raise PipelineError((acoustic.stderr or acoustic.stdout or "a análise acústica falhou").strip()[-2000:])
        regions = [(float(a), float(b)) for a, b in re.findall(r"([\d.]+)\s*->\s*([\d.]+)", acoustic.stdout or "")]
        if not regions:
            raise PipelineError("speech_regions.py não encontrou regiões acústicas de fala")
        groups: list[list[dict]] = [[words[0]]]
        for word in words[1:]:
            if word["start"] - groups[-1][-1]["end"] >= pause:
                groups.append([])
            groups[-1].append(word)
        ranges = []
        source_duration = max(b for _, b in regions)
        for index, group in enumerate(groups, 1):
            overlapping = [(a, b) for a, b in regions if b >= group[0]["start"] and a <= group[-1]["end"]]
            if not overlapping:
                raise PipelineError("uma frase alinhada não coincide com nenhuma região acústica de fala")
            start = max(0.0, overlapping[0][0] - 0.03)
            end = min(source_duration, overlapping[-1][1] + 0.06)
            item = {"source": "source", "start": round(start, 3), "end": round(end, 3),
                    "beat": f"Pausa {index}", "transcript": " ".join(x["text"] for x in group)}
            if ranges and item["start"] <= ranges[-1]["end"]:
                ranges[-1]["end"] = max(ranges[-1]["end"], item["end"])
                ranges[-1]["transcript"] += " " + item["transcript"]
                ranges[-1]["beat"] += f" + Pausa {index}"
            else:
                ranges.append(item)
        revisions = self.data / "plans"
        prior = [int(p.stem.split("-")[-1]) for p in revisions.glob("rev-*.json")
                 if p.stem.split("-")[-1].isdigit()]
        revision = max(prior, default=0) + 1
        edl = {"version": 1, "sources": {"source": str(source)}, "ranges": ranges,
               "total_duration_s": round(sum(x["end"] - x["start"] for x in ranges), 3),
               "proposal": {"kind": PROPOSAL_LABEL, "pauseThresholdS": pause,
                            "transcript": str(transcript_path.relative_to(self.root)), "backend": backend,
                            "sourceFingerprint": source_fingerprint,
                            "boundaryPolicy": "grupos por pausas do WhisperX; bordas acústicas de speech_regions.py com 30 ms antes e 60 ms depois da fala"}}
        plan_hash = _digest(edl)
        plan = {"version": 1, "revision": revision, "hash": plan_hash, "status": "proposed", "edl": edl}
        path = revisions / f"rev-{revision}.json"
        _atomic_json(path, plan)
        event = self._record("propose-cut", True, revision=revision, planHash=plan_hash,
                             proposal=PROPOSAL_LABEL, plan=str(path.relative_to(self.root)), ranges=len(ranges),
                             totalDuration=edl["total_duration_s"])
        return {"ok": True, **event}

    def _new_revision(self, edl: dict, kind: str) -> dict:
        revisions = self.data / "plans"
        prior = [int(p.stem.split("-")[-1]) for p in revisions.glob("rev-*.json")
                 if p.stem.split("-")[-1].isdigit()]
        revision = max(prior, default=0) + 1
        plan_hash = _digest(edl)
        plan = {"version": 1, "revision": revision, "hash": plan_hash,
                "status": "proposed", "kind": kind, "edl": edl}
        path = revisions / f"rev-{revision}.json"
        _atomic_json(path, plan)
        (self.data / "approved.json").unlink(missing_ok=True)
        return {"revision": revision, "planHash": plan_hash, "proposal": kind,
                "plan": str(path.relative_to(self.root)), "requiresApproval": True}

    def approve_plan(self, revision: int, plan_hash: str, approved: bool) -> dict:
        self._prepare_writes()
        if not approved:
            raise PipelineError("a aprovação explícita exige --approve")
        path = self.data / "plans" / f"rev-{revision}.json"
        plan = _read_json(path)
        if plan.get("revision") != revision or plan.get("hash") != plan_hash or _digest(plan.get("edl")) != plan_hash:
            raise PipelineError("a revisão ou o hash não corresponde à proposta salva")
        approved_doc = {"version": 1, "revision": revision, "hash": plan_hash,
                        "approvedAt": int(time.time()), "edl": plan["edl"]}
        _atomic_json(self.data / "approved.json", approved_doc)
        event = self._record("approve-plan", True, revision=revision, planHash=plan_hash)
        return {"ok": True, **event}

    def render_cut(self, revision: int, plan_hash: str, preview: bool = False) -> dict:
        self._prepare_writes()
        if not (self.data / "approved.json").exists():
            raise PipelineError("o render exige uma proposta aprovada")
        approved = _read_json(self.data / "approved.json")
        if approved.get("revision") != revision or approved.get("hash") != plan_hash:
            raise PipelineError("o render exige a revisão e o hash aprovados atuais")
        if _digest(approved.get("edl")) != plan_hash:
            raise PipelineError("o plano aprovado foi alterado")
        edl = approved["edl"]
        proposal = edl.get("proposal") or {}
        expected = proposal.get("sourceFingerprint") or {}
        for raw_source in (edl.get("sources") or {}).values():
            source = self.confined(raw_source, must_exist=True)
            actual = _file_fingerprint(source)
            if actual != expected:
                raise PipelineError("a fonte mudou depois da proposta; transcreva e aprove uma nova revisão")
        staging = self.data / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        edl_stage = staging / f"edl-r{revision}-{plan_hash[:12]}.json"
        cut_stage = staging / f"cut-r{revision}-{plan_hash[:12]}.mp4"
        _atomic_json(edl_stage, approved["edl"])
        cut_stage.unlink(missing_ok=True)
        color_reports = []
        for raw_source in (edl.get("sources") or {}).values():
            source = self.confined(raw_source, must_exist=True)
            color = self.runner([sys.executable, str(HELPERS_DIR / "detect_color.py"), str(source), "--json"],
                                capture_output=True, text=True)
            try:
                report = json.loads(color.stdout) if color.returncode == 0 else None
            except json.JSONDecodeError:
                report = None
            if not isinstance(report, dict) or not report.get("profile"):
                raise PipelineError("não foi possível determinar o perfil de cor da fonte")
            color_reports.append(report)
            if report.get("profile") != "rec709" and not edl.get("grade"):
                raise PipelineError("a fonte parece LOG/HDR e o plano aprovado não define conversão de cor")
        shot = self.runner([sys.executable, str(HELPERS_DIR / "shot_check.py"), str(edl_stage), "--json"],
                           capture_output=True, text=True)
        if shot.returncode:
            raise PipelineError((shot.stdout or shot.stderr or "shot_check reprovou o plano").strip()[-2000:])
        render_cmd = [sys.executable, str(HELPERS_DIR / "render.py"), str(edl_stage), "-o", str(cut_stage), "--no-subtitles"]
        if preview:
            render_cmd.append("--preview")
        rendered = self.runner(render_cmd, capture_output=True, text=True)
        if rendered.returncode or not cut_stage.is_file() or cut_stage.stat().st_size == 0:
            cut_stage.unlink(missing_ok=True)
            raise PipelineError((rendered.stderr or rendered.stdout or "o render falhou").strip()[-2000:])
        verified = self.runner([sys.executable, str(HELPERS_DIR / "verify_cut.py"), str(edl_stage), str(cut_stage)],
                               capture_output=True, text=True)
        if verified.returncode:
            cut_stage.unlink(missing_ok=True)
            raise PipelineError((verified.stdout or verified.stderr or "a verificação reprovou o corte").strip()[-2000:])
        fps_probe = self.runner(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=avg_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", str(cut_stage)],
            capture_output=True, text=True,
        )
        if fps_probe.returncode:
            cut_stage.unlink(missing_ok=True)
            raise PipelineError((fps_probe.stderr or "não foi possível medir o frame rate da saída").strip()[-2000:])
        output_fps = _parse_fps(fps_probe.stdout)
        live_edl, live_cut = self.edit / "edl.json", self.edit / "cut.mp4"
        if live_cut.exists():
            history = self.data / "renders"
            history.mkdir(parents=True, exist_ok=True)
            old_hash = hashlib.sha256(live_cut.read_bytes()).hexdigest()[:12]
            os.replace(live_cut, history / f"cut-{int(time.time())}-{old_hash}.mp4")
        verified_edl = _read_json(edl_stage)
        _atomic_json(live_edl, verified_edl)
        os.replace(cut_stage, live_cut)
        rendered_at = int(time.time())
        preview_state_path = self.edit / "state.json"
        preview_state = _read_json(preview_state_path) if preview_state_path.exists() else {}
        if not isinstance(preview_state, dict):
            raise PipelineError("edit/state.json precisa conter um objeto")
        preview_state.update({"video": "cut.mp4", "edl": "edl.json", "fps": output_fps,
                              "renderedAt": rendered_at})
        _atomic_json(preview_state_path, preview_state)
        event = self._record("render-cut", True, revision=revision, planHash=plan_hash,
                             output=str(live_cut.relative_to(self.root)), verified=True,
                             renderedEdlHash=_digest(verified_edl), renderedAt=rendered_at,
                             fps=output_fps,
                             deliveryStatus="technical-preview-only",
                             color=color_reports,
                             renderLog=(rendered.stdout or "")[-1200:], verifyLog=(verified.stdout or "")[-1200:])
        return {"ok": True, **event}

    def _snapshot_edl(self) -> dict:
        path = self.edit / "edl.json"
        value = _read_json(path)
        return {"edl": value, "hash": _digest(value), "at": int(time.time())}

    def apply_preview_edits(self, raw: str = "edit/preview_edits.json") -> dict:
        self._prepare_writes()
        preview = self.confined(raw, must_exist=True)
        edl_path = self.edit / "edl.json"
        if not edl_path.exists():
            raise PipelineError("não há edl.json para ajustar")
        before = self._snapshot_edl()
        undo = self.data / "undo.json"
        stack = _read_json(undo) if undo.exists() else []
        if not isinstance(stack, list):
            raise PipelineError("histórico de desfazer inválido")
        cmd = [sys.executable, str(HELPERS_DIR / "fillers.py"), str(edl_path), "--from-preview", str(preview), "--apply"]
        run = self.runner(cmd, capture_output=True, text=True)
        if run.returncode:
            raise PipelineError((run.stderr or run.stdout or "não foi possível aplicar os ajustes").strip()[-2000:])
        after = self._snapshot_edl()
        if after["hash"] == before["hash"]:
            raise PipelineError("os ajustes não produziram uma alteração de EDL")
        stack = (stack + [before])[-50:]
        _atomic_json(undo, stack)
        _atomic_json(self.data / "redo.json", [])
        proposal = self._new_revision(after["edl"], "ajuste de timeline pendente de aprovação")
        event = self._record("apply-preview-edits", True, beforeHash=before["hash"], afterHash=after["hash"],
                             log=(run.stdout or "")[-2000:], **proposal)
        return {"ok": True, **event}

    def restore(self, direction: str) -> dict:
        self._prepare_writes()
        source_name, target_name = ("undo.json", "redo.json") if direction == "undo" else ("redo.json", "undo.json")
        source_path, target_path = self.data / source_name, self.data / target_name
        stack = _read_json(source_path) if source_path.exists() else []
        if not isinstance(stack, list) or not stack:
            raise PipelineError(f"não há ação para {direction}")
        current = self._snapshot_edl()
        target = stack.pop()
        other = _read_json(target_path) if target_path.exists() else []
        if not isinstance(other, list):
            raise PipelineError("histórico de edição inválido")
        _atomic_json(self.edit / "edl.json", target["edl"])
        _atomic_json(source_path, stack)
        _atomic_json(target_path, (other + [current])[-50:])
        proposal = self._new_revision(target["edl"], f"{direction} pendente de aprovação")
        event = self._record(direction, True, edlHash=target["hash"], **proposal)
        return {"ok": True, **event}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--action", required=True, choices=["status", "save-brief", "transcribe", "propose-cut",
                                                          "approve-plan", "render-cut", "apply-preview-edits", "undo", "redo"])
    ap.add_argument("--source")
    ap.add_argument("--script")
    ap.add_argument("--script-file")
    ap.add_argument("--language")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--pause", type=float, default=0.65)
    ap.add_argument("--revision", type=int)
    ap.add_argument("--plan-hash")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--preview-edits", default="edit/preview_edits.json")
    return ap


def dispatch(args: argparse.Namespace, runner: Runner = subprocess.run) -> dict:
    pipe = StudioPipeline(args.root, runner=runner)
    if args.action == "status": return pipe.status()
    with pipe.mutation_lock():
        if args.action == "save-brief": return pipe.save_brief(args.script, args.script_file)
        if args.action == "transcribe":
            if not args.source: raise PipelineError("--source é obrigatório")
            return pipe.transcribe(args.source, args.language, args.model)
        if args.action == "propose-cut":
            if not args.source: raise PipelineError("--source é obrigatório")
            return pipe.propose_cut(args.source, args.pause)
        if args.action == "approve-plan":
            if args.revision is None or not args.plan_hash: raise PipelineError("--revision e --plan-hash são obrigatórios")
            return pipe.approve_plan(args.revision, args.plan_hash, args.approve)
        if args.action == "render-cut":
            if args.revision is None or not args.plan_hash: raise PipelineError("--revision e --plan-hash são obrigatórios")
            return pipe.render_cut(args.revision, args.plan_hash, args.preview)
        if args.action == "apply-preview-edits": return pipe.apply_preview_edits(args.preview_edits)
        return pipe.restore(args.action)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
    except PipelineError as exc:
        result = {"ok": False, "action": args.action, "error": str(exc)}
        try:
            StudioPipeline(args.root)._record(args.action, False, error=str(exc))
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
