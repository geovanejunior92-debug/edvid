"""Safe local Phase-1 pipeline for Edvid Studio.

Every path is confined to the selected project.  Commands emit one JSON object
on stdout so the Studio can persist and display the result without scraping
human-oriented helper output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
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


def _same_range(a: dict, b: dict, tolerance: float = 0.001) -> bool:
    try:
        return (a.get("source") == b.get("source") and a.get("beat", "") == b.get("beat", "")
                and abs(float(a["start"]) - float(b["start"])) <= tolerance
                and abs(float(a["end"]) - float(b["end"])) <= tolerance)
    except (KeyError, TypeError, ValueError):
        return False


def _parse_saved_at(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())
        except ValueError:
            return None
    return None


def _first_float(text: str) -> float | None:
    """O primeiro número da saída de um helper. Serve para ler a tremida que o
    stabilize.py --report imprime sem acoplar ao formato da frase inteira."""
    m = re.search(r"(\d+[.,]\d+|\d+)", text or "")
    return float(m.group(1).replace(",", ".")) if m else None


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

    def align_script(self, min_score: float = 0.62) -> dict:
        """Casa o roteiro salvo com as transcrições e PROPÕE as tomadas.

        Proposta, não decisão: a regra do Studio é revisão humana antes de o
        corte técnico virar editorial. Linha regravada volta com todas as
        tomadas; linha que não foi encontrada volta marcada; fala que existe e
        não está no roteiro volta como improviso. Nada disso vira EDL sozinho.
        """
        self._prepare_writes()
        import script_align
        brief_path = self.data / "brief.json"
        if not brief_path.is_file():
            raise PipelineError("salve o roteiro antes de alinhar")
        brief = _read_json(brief_path)
        script = (brief or {}).get("script") if isinstance(brief, dict) else None
        if not script:
            raise PipelineError("o roteiro salvo está vazio")
        folder = self.edit / "transcripts"
        sources = {}
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            if path.stem == "cut":
                continue  # é o resultado, não a matéria-prima
            data = _read_json(path)
            rows = self._word_rows(data) if isinstance(data, dict) else []
            if rows:
                sources[path.stem] = rows
        if not sources:
            raise PipelineError("transcreva ao menos uma fonte antes de alinhar")
        try:
            alignment = script_align.align(script, sources, min_score)
        except ValueError as exc:
            raise PipelineError(str(exc)) from exc
        out = self.data / "alignment.json"
        _atomic_json(out, alignment)
        event = self._record("align-script", True, alignment=str(out.relative_to(self.root)),
                             summary=alignment["summary"])
        return {"ok": True, **event, "summary": alignment["summary"]}

    # ---- tratamento técnico -------------------------------------------------
    # O Studio renderizava sem limpeza de áudio e sem casamento de cor entre
    # tomadas, enquanto o processo da skill diz que a limpeza é PADRÃO e não
    # opção. Esta ação roda a cadeia técnica sobre o EDL aprovado em proposta,
    # liga só o que passou no próprio gate, e devolve um relatório dizendo o
    # que foi corrigido e o que continua bloqueado — em vez de ligar tudo e
    # torcer.
    def _probe_treat(self, argv: list[str]) -> tuple[int, str]:
        run = self.runner(argv, capture_output=True, text=True)
        saida = ((getattr(run, "stdout", "") or "") + (getattr(run, "stderr", "") or "")).strip()
        return int(getattr(run, "returncode", 1)), saida

    def treat(self, denoise: str = "rnnoise", stabilize: bool = True,
              match_takes: bool = True) -> dict:
        self._prepare_writes()
        edl_path = self.edit / "edl.json"
        if not edl_path.is_file():
            raise PipelineError("proponha um corte antes de tratar")
        edl = _read_json(edl_path)
        if not isinstance(edl, dict) or not edl.get("ranges"):
            raise PipelineError("o edl.json não tem ranges")
        if denoise not in {"rnnoise", "demucs", "off"}:
            raise PipelineError("denoise precisa ser rnnoise, demucs ou off")
        fontes = {str(v) for v in (edl.get("sources") or {}).values()}
        if not fontes:
            raise PipelineError("o edl.json não declara fontes")

        aplicado, bloqueado = [], []

        # 1) NÍVEL de voz: o transcript é cego a volume. Um aparte sussurrado
        # lê como fala normal e some no celular.
        for fonte in sorted(fontes):
            code, saida = self._probe_treat(
                [sys.executable, str(HELPERS_DIR / "voice_levels.py"), fonte,
                 "--edit-dir", str(self.edit), "--edl", str(edl_path)])
            (aplicado if code == 0 else bloqueado).append(
                {"etapa": "voice_levels", "fonte": Path(fonte).name,
                 "detalhe": saida[-400:] or ("medido" if code == 0 else "falhou")})

        # 2) LIMPEZA de diálogo, com gate próprio. Se o check_audio reprovar,
        # renderiza SEM limpeza e diz por quê — nunca com um WAV pior.
        if denoise != "off":
            for fonte in sorted(fontes):
                code, _ = self._probe_treat(
                    [sys.executable, str(HELPERS_DIR / "audio_clean.py"), fonte,
                     "--edit-dir", str(self.edit), "--denoise", denoise])
                if code != 0:
                    bloqueado.append({"etapa": "audio_clean", "fonte": Path(fonte).name,
                                      "detalhe": "a limpeza falhou; render segue com o áudio original"})
                    continue
                gate, saida = self._probe_treat(
                    [sys.executable, str(HELPERS_DIR / "check_audio.py"), fonte,
                     "--edit-dir", str(self.edit)])
                if gate == 0:
                    edl["audio_clean"] = ({"denoise": denoise} if denoise != "rnnoise" else True)
                    aplicado.append({"etapa": "audio_clean", "fonte": Path(fonte).name,
                                     "detalhe": f"denoise {denoise}, aprovado no check_audio"})
                else:
                    edl.pop("audio_clean", None)
                    bloqueado.append({"etapa": "check_audio", "fonte": Path(fonte).name,
                                      "detalhe": saida[-400:] or "gate reprovou; render segue sem limpeza"})
                    break

        # 3) ESTABILIZAÇÃO só quando há tremida medida. Em tripé é zoom de graça.
        if stabilize:
            for fonte in sorted(fontes):
                code, saida = self._probe_treat(
                    [sys.executable, str(HELPERS_DIR / "stabilize.py"), fonte,
                     "--edit-dir", str(self.edit), "--report"])
                tremida = _first_float(saida)
                if code != 0:
                    bloqueado.append({"etapa": "stabilize", "fonte": Path(fonte).name,
                                      "detalhe": "não consegui medir a tremida"})
                elif tremida is not None and tremida >= 0.35:
                    edl["stabilize"] = True
                    aplicado.append({"etapa": "stabilize", "fonte": Path(fonte).name,
                                     "detalhe": f"tremida {tremida:.2f} px/quadro, acima de 0,35"})
                else:
                    aplicado.append({"etapa": "stabilize", "fonte": Path(fonte).name,
                                     "detalhe": f"fonte estável ({tremida if tremida is not None else '?'}) — não vale o zoom"})

        # 4) CASAMENTO de cor entre tomadas, antes do look.
        if match_takes and len(edl["ranges"]) > 1:
            code, saida = self._probe_treat(
                [sys.executable, str(HELPERS_DIR / "match_takes.py"), str(edl_path), "--apply"])
            if code == 0:
                atualizado = _read_json(edl_path)
                if isinstance(atualizado, dict) and atualizado.get("ranges"):
                    for antes, depois in zip(edl["ranges"], atualizado["ranges"]):
                        if depois.get("grade_pre"):
                            antes["grade_pre"] = depois["grade_pre"]
                casados = sum(1 for r in edl["ranges"] if r.get("grade_pre"))
                aplicado.append({"etapa": "match_takes",
                                 "detalhe": f"{casados} de {len(edl['ranges'])} tomadas ganharam correção"})
            else:
                bloqueado.append({"etapa": "match_takes", "detalhe": saida[-400:] or "falhou"})

        _atomic_json(edl_path, edl)
        revision = self._new_revision(edl, "treat")
        relatorio = {"version": 1, "applied": aplicado, "blocked": bloqueado,
                     "flags": {k: edl.get(k) for k in ("audio_clean", "stabilize") if k in edl}}
        _atomic_json(self.data / "treatment.json", relatorio)
        event = self._record("treat", True, **revision, applied=len(aplicado), blocked=len(bloqueado))
        return {"ok": True, **event, "report": relatorio}

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
        verified_edl = _read_json(edl_stage)
        if not isinstance(verified_edl, dict) or not isinstance(verified_edl.get("ranges"), list):
            cut_stage.unlink(missing_ok=True)
            raise PipelineError("o render produziu um EDL inválido")
        preview_state_path = self.edit / "state.json"
        preview_state = _read_json(preview_state_path) if preview_state_path.exists() else {}
        if not isinstance(preview_state, dict):
            cut_stage.unlink(missing_ok=True)
            raise PipelineError("edit/state.json precisa conter um objeto")
        rendered_at = int(time.time())
        preview_state.update({"video": "cut.mp4", "edl": "edl.json", "fps": output_fps,
                              "renderedAt": rendered_at})
        live_edl, live_cut = self.edit / "edl.json", self.edit / "cut.mp4"
        if live_cut.exists():
            history = self.data / "renders"
            history.mkdir(parents=True, exist_ok=True)
            old_hash = _file_fingerprint(live_cut)["sha256"][:12]
            os.replace(live_cut, history / f"cut-{int(time.time())}-{old_hash}.mp4")
        _atomic_json(live_edl, verified_edl)
        os.replace(cut_stage, live_cut)
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

    def _speech_regions(self, edl: dict) -> dict[str, list[tuple[float, float]]]:
        regions: dict[str, list[tuple[float, float]]] = {}
        for name, raw in (edl.get("sources") or {}).items():
            source = self.confined(raw, must_exist=True)
            run = self.runner([sys.executable, str(HELPERS_DIR / "speech_regions.py"), str(source)],
                              capture_output=True, text=True)
            if run.returncode:
                raise PipelineError((run.stderr or run.stdout or "a validação acústica falhou").strip()[-2000:])
            found = [(float(a), float(b)) for a, b in re.findall(r"([\d.]+)\s*->\s*([\d.]+)", run.stdout or "")]
            if not found:
                raise PipelineError(f"speech_regions.py não encontrou fala em {source.name}")
            regions[str(name)] = found
        return regions

    def _source_durations(self, edl: dict) -> dict[str, float]:
        durations: dict[str, float] = {}
        for name, raw in (edl.get("sources") or {}).items():
            source = self.confined(raw, must_exist=True)
            run = self.runner(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                               "-of", "default=noprint_wrappers=1:nokey=1", str(source)],
                              capture_output=True, text=True)
            try:
                duration = float((run.stdout or "").strip())
            except ValueError as exc:
                raise PipelineError(f"não foi possível medir a duração de {source.name}") from exc
            if run.returncode or not math.isfinite(duration) or duration <= 0:
                raise PipelineError(f"não foi possível medir a duração de {source.name}")
            durations[str(name)] = duration
        return durations

    @staticmethod
    def _outside_speech(value: float, regions: list[tuple[float, float]], tolerance: float = 0.015) -> bool:
        return not any(a + tolerance < value < b - tolerance for a, b in regions)

    def _manual_ranges(self, before: dict, payload: dict) -> tuple[list[dict], dict[int, dict]]:
        spec = payload.get("edl")
        if spec is None:
            return [dict(r) for r in before["ranges"]], {}
        if not isinstance(spec, dict) or not all(isinstance(spec.get(k, []), list)
                                                for k in ("ranges", "changes", "removed")):
            raise PipelineError("ajustes manuais malformados")
        saved, changes, removed = spec.get("ranges", []), spec.get("changes", []), spec.get("removed", [])
        if len(saved) + len(removed) != len(before["ranges"]):
            raise PipelineError("o preview não corresponde mais à timeline atual")
        used: set[int] = set()
        changed: dict[int, dict] = {}
        matched_order: list[int] = []
        result: list[dict] = []
        for item in saved:
            if not isinstance(item, dict):
                raise PipelineError("range salvo malformado")
            try:
                item_start, item_end = float(item["start"]), float(item["end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PipelineError("trim inválido ou curto demais") from exc
            if not math.isfinite(item_start) or not math.isfinite(item_end):
                raise PipelineError("trim inválido ou curto demais")
            matches = []
            for index, original in enumerate(before["ranges"]):
                if index in used:
                    continue
                for change in changes:
                    change_from = ({"source": change.get("source"), "beat": change.get("beat", ""),
                                    **(change.get("from") or {})} if isinstance(change, dict) else {})
                    change_to = ({"source": change.get("source"), "beat": change.get("beat", ""),
                                  **(change.get("to") or {})} if isinstance(change, dict) else {})
                    if (isinstance(change, dict) and _same_range(change_from, original)
                            and item.get("source") == original.get("source")
                            and item.get("beat", "") == original.get("beat", "")
                            and _same_range(item, change_to)):
                        matches.append((index, change))
                if _same_range(item, original):
                    matches.append((index, None))
            unique = {index for index, _ in matches}
            if len(unique) != 1:
                raise PipelineError("range ambíguo ou obsoleto no preview")
            index = unique.pop()
            chosen_change = next((c for i, c in matches if i == index and c is not None), None)
            rebuilt = dict(before["ranges"][index])
            rebuilt["start"], rebuilt["end"] = item_start, item_end
            if (not math.isfinite(rebuilt["start"]) or not math.isfinite(rebuilt["end"])
                    or rebuilt["start"] < 0 or rebuilt["end"] - rebuilt["start"] < 0.05):
                raise PipelineError("trim inválido ou curto demais")
            if chosen_change is not None:
                changed[index] = rebuilt
            used.add(index)
            matched_order.append(index)
            result.append(rebuilt)
        removed_indexes: set[int] = set()
        for item in removed:
            matches = [i for i, original in enumerate(before["ranges"])
                       if i not in used and _same_range(item, original)] if isinstance(item, dict) else []
            if len(matches) != 1:
                raise PipelineError("remoção ambígua ou obsoleta no preview")
            used.add(matches[0]); removed_indexes.add(matches[0])
        if used != set(range(len(before["ranges"]))) or len(changes) != len(changed):
            raise PipelineError("ranges/changes/removed são inconsistentes")
        original_order = [i for i in range(len(before["ranges"])) if i not in removed_indexes]
        if matched_order != original_order:
            raise PipelineError("o preview não pode reordenar ranges")
        return result, changed

    @staticmethod
    def _map_text_cuts(before: dict, cuts: Any) -> list[dict]:
        if cuts is None:
            return []
        if not isinstance(cuts, list):
            raise PipelineError("textCuts precisa ser uma lista")
        jt = before.get("jcut_timeline") or []
        if jt and len(jt) != len(before.get("ranges") or []):
            raise PipelineError("a timeline J-cut está obsoleta")
        slots = []
        offset = 0.0
        for index, r in enumerate(before["ranges"]):
            speed = float(r.get("speed", 1) or 1)
            if speed <= 0:
                raise PipelineError("velocidade inválida no EDL")
            if jt:
                start, duration = float(jt[index]["video_start_in_output"]), float(jt[index]["video_duration"])
            else:
                start, duration = offset, (float(r["end"]) - float(r["start"])) / speed
                offset += duration + float(r.get("freeze_end", 0) or 0)
            slots.append((start, start + duration, index, speed))
        mapped = []
        for cut in cuts:
            try:
                a = float(cut["renderedStart"] if "renderedStart" in cut else cut["start"])
                b = float(cut["renderedEnd"] if "renderedEnd" in cut else cut["end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PipelineError("textCut malformado ou sem posição renderizada") from exc
            if not math.isfinite(a) or not math.isfinite(b) or not 0 <= a < b:
                raise PipelineError("textCut possui intervalo inválido")
            hits = [slot for slot in slots if a >= slot[0] - 0.001 and b <= slot[1] + 0.001]
            if len(hits) != 1:
                raise PipelineError("textCut cruza takes ou possui mapeamento ambíguo")
            o0, _, index, speed = hits[0]
            r = before["ranges"][index]
            mapped.append({"index": index, "source": r["source"],
                           "start": float(r["start"]) + (a - o0) * speed,
                           "end": float(r["start"]) + (b - o0) * speed})
        return mapped

    def apply_preview_edits(self, raw: str = "edit/preview_edits.json") -> dict:
        self._prepare_writes()
        preview = self.confined(raw, must_exist=True)
        edl_path = self.edit / "edl.json"
        if not edl_path.exists():
            raise PipelineError("não há edl.json para ajustar")
        before = self._snapshot_edl()
        payload = _read_json(preview)
        if not isinstance(payload, dict) or payload.get("type") not in (None, "timeline-edits"):
            raise PipelineError("preview_edits.json não contém ajustes de timeline")
        payload_hash = _digest(payload)
        consumed_path = self.data / "consumed-preview.json"
        consumed = _read_json(consumed_path) if consumed_path.exists() else []
        if not isinstance(consumed, list):
            raise PipelineError("registro de previews consumidos inválido")
        if payload_hash in consumed:
            raise PipelineError("estes ajustes de preview já foram aplicados")
        expected_hash = payload.get("edlHash") or payload.get("timelineFingerprint")
        if expected_hash and expected_hash != before["hash"]:
            raise PipelineError("o preview foi salvo sobre outra revisão da timeline")
        saved_at = _parse_saved_at(payload.get("savedAt"))
        state = _read_json(self.edit / "state.json") if (self.edit / "state.json").exists() else {}
        if saved_at is not None and isinstance(state, dict) and saved_at < int(state.get("renderedAt", 0)):
            raise PipelineError("o preview é anterior ao render atual")
        manual, changed = self._manual_ranges(before["edl"], payload)
        mapped_cuts = self._map_text_cuts(before["edl"], payload.get("textCuts"))
        if not changed and not mapped_cuts and len(manual) == len(before["edl"]["ranges"]):
            raise PipelineError("os ajustes não contêm trims, remoções ou textCuts")
        acoustic = self._speech_regions(before["edl"])
        durations = self._source_durations(before["edl"])
        if any(float(item["end"]) > durations[item["source"]] + 0.001 for item in manual):
            raise PipelineError("um trim ultrapassa a duração física da fonte")
        for item in changed.values():
            if (not self._outside_speech(float(item["start"]), acoustic[item["source"]])
                    or not self._outside_speech(float(item["end"]), acoustic[item["source"]])):
                raise PipelineError("o trim cai dentro de fala; ajuste a borda para uma pausa acústica")
        for cut in mapped_cuts:
            # Expand a selected word interval to the enclosing acoustic speech block,
            # then keep the Edvid 30 ms safety pad outside speech.
            overlaps = [(a, b) for a, b in acoustic[cut["source"]] if b >= cut["start"] and a <= cut["end"]]
            if not overlaps:
                raise PipelineError("textCut não coincide com fala detectada")
            if cut["start"] - (overlaps[0][0] - 0.03) > 0.15 or (overlaps[-1][1] + 0.03) - cut["end"] > 0.15:
                raise PipelineError("a seleção de texto exigiria remover fala vizinha; selecione uma frase com bordas em pausas")
            original = before["edl"]["ranges"][cut["index"]]
            cut["start"] = max(float(original["start"]), overlaps[0][0] - 0.03)
            cut["end"] = min(float(original["end"]), overlaps[-1][1] + 0.03)
        for cut in sorted(mapped_cuts, key=lambda x: (x["index"], x["start"]), reverse=True):
            original = before["edl"]["ranges"][cut["index"]]
            candidates = [i for i, r in enumerate(manual) if r.get("source") == original.get("source")
                          and r.get("beat", "") == original.get("beat", "")
                          and float(r["start"]) <= cut["start"] + 0.001
                          and float(r["end"]) >= cut["end"] - 0.001]
            if len(candidates) != 1:
                raise PipelineError("textCut não cabe de forma inequívoca após os trims/removals")
            pos = candidates[0]; item = manual.pop(pos)
            pieces = []
            if cut["start"] - float(item["start"]) >= 0.05:
                pieces.append({**item, "end": round(cut["start"], 3)})
            if float(item["end"]) - cut["end"] >= 0.05:
                tail = {**item, "start": round(cut["end"], 3)}
                if pieces and tail.get("beat"):
                    tail["beat"] = f"{tail['beat']} (2)"
                pieces.append(tail)
            manual[pos:pos] = pieces
        if not manual:
            raise PipelineError("os ajustes removeriam todo o corte")
        staged = dict(before["edl"])
        staged["ranges"] = manual
        staged.pop("jcut_timeline", None)
        staged["total_duration_s"] = round(sum(float(r["end"]) - float(r["start"]) for r in manual), 3)
        after = {"edl": staged, "hash": _digest(staged), "at": int(time.time())}
        if after["hash"] == before["hash"]:
            raise PipelineError("os ajustes não produziram uma alteração de EDL")
        undo = self.data / "undo.json"
        stack = _read_json(undo) if undo.exists() else []
        if not isinstance(stack, list):
            raise PipelineError("histórico de desfazer inválido")
        _atomic_json(edl_path, staged)
        stack = (stack + [before])[-50:]
        _atomic_json(undo, stack)
        _atomic_json(self.data / "redo.json", [])
        proposal = self._new_revision(after["edl"], "ajuste de timeline pendente de aprovação")
        archive = self.data / "consumed-previews" / f"{payload_hash}.json"
        _atomic_json(archive, payload)
        preview.unlink()
        _atomic_json(consumed_path, (consumed + [payload_hash])[-200:])
        event = self._record("apply-preview-edits", True, beforeHash=before["hash"], afterHash=after["hash"],
                             previewHash=payload_hash, **proposal)
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
    ap.add_argument("--action", required=True, choices=["status", "save-brief", "transcribe", "align-script", "propose-cut", "treat",
                                                          "approve-plan", "render-cut", "apply-preview-edits", "undo", "redo"])
    ap.add_argument("--source")
    ap.add_argument("--script")
    ap.add_argument("--script-file")
    ap.add_argument("--language")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--pause", type=float, default=0.65)
    ap.add_argument("--min-score", type=float, default=0.62)
    ap.add_argument("--denoise", default="rnnoise", choices=["rnnoise", "demucs", "off"])
    ap.add_argument("--no-stabilize", action="store_true")
    ap.add_argument("--no-match-takes", action="store_true")
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
        if args.action == "align-script": return pipe.align_script(args.min_score)
        if args.action == "treat":
            return pipe.treat(args.denoise, not args.no_stabilize, not args.no_match_takes)
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
