"""Fase 2 (Remotion) dentro do Studio — o que faltava para o Formato 1 rodar no app.

Até aqui o Studio ia da importação ao corte aprovado e parava. O acabamento que
existia (`studio_finish.py`) é um perfil PRÓPRIO, por ffmpeg, com legenda
queimada e cartão em PNG — e ele mesmo declara que não substitui o Remotion.
Consequência medida na auditoria de 2026-09-11: o Formato 1, que é o formato de
entrega do usuário, não rodava dentro do aplicativo. Legenda karaokê, tela
dividida com matte, zoom e flash da linguagem aprovada, logo e encerramento são
todos Remotion.

Este módulo é a ponte, e ele respeita as regras duras da skill em vez de
contorná-las:

- **Hard Rule 11**: o template é IMUTÁVEL. `scaffold` COPIA
  `assets/shortform` para dentro do projeto e nunca sobrescreve um projeto
  Remotion existente. Nada aqui escreve TSX; o vídeo é descrito em
  `public/edit-data.json`.
- **Hard Rule 10**: a Fase 2 é Remotion. Este módulo não desenha texto por
  ffmpeg — quem faz isso é o perfil manual, que continua existindo e continua
  sendo outra coisa.
- **`check_inserts.py` é obrigatório** antes de todo render, e aqui é gate de
  verdade: exit ≠ 0 aborta. Os dois defeitos que ele pega (insert congelado e
  insert ampliado) já atravessaram um render inteiro até o usuário apontar.
- **`qc_final.py`** roda depois e reprova a entrega, não só avisa.

A aprovação é vinculada a revisão + hash + impressão digital do corte, igual ao
resto do Studio: mexeu no corte, a aprovação anterior morre.

**Limite honesto:** o render real exige as dependências do Remotion. Nesta
instalação elas ficam compartilhadas no template e o scaffold cria um link no
projeto; num clone sem essa instalação, o Studio explica como preparar o
template. O comando montado continua testável sem baixar dependências.
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
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1
HELPERS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = HELPERS_DIR.parent.resolve()
TEMPLATE = SKILL_ROOT / "assets" / "shortform"
COMPOSITION = "Reels"
Runner = Callable[..., subprocess.CompletedProcess]
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

# Campos de edit-data.json que apontam para arquivo dentro de public/.
ASSET_FIELDS = (
    ("soundtrack", "file"),
    ("logo", "src"),
    ("hook", "logo"),
    ("hook", "sign"),
)
# Cada lista é declarada com os campos que o template realmente entrega a
# staticFile(). Não trate toda chave chamada `src` como mídia: os gráficos são
# dados puros e podem ganhar campos homônimos sem que virem arquivo.
ASSET_LIST_FIELDS = {
    "splitInserts": (("src", ""), ("matte", "")),
    "inserts": (("src", ""),),
    "behind": (("src", ""), ("matte", "")),
    "behindVideos": (("src", ""), ("matte", "")),
    "sfxCues": (("src", "sfx"),),
    "transitions": (("sfx", "sfx"),),
}
LIST_FIELDS = tuple(ASSET_LIST_FIELDS) + ("graphics", "titleCards")


def render_scale(layout_w: int, layout_h: int, cut_w: int, cut_h: int) -> int | None:
    """Fator inteiro entre o layout do edit-data e o cut.mp4 (1 = mesmo tamanho).

    O template é desenhado em 1080×1920; um corte nativo 4K (2160×3840) renderiza
    com --scale 2. None quando não é múltiplo inteiro exato: aí a Fase 2 sairia
    esticada ou fora de posição.
    """
    if layout_w <= 0 or layout_h <= 0 or cut_w % layout_w or cut_h % layout_h:
        return None
    k = cut_w // layout_w
    return k if k >= 1 and cut_h // layout_h == k else None


class Phase2Error(RuntimeError):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Phase2Error(f"não consegui ler {path.name}") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _fingerprint(path: Path) -> dict:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"size": stat.st_size, "sha256": digest.hexdigest()}


class StudioPhase2:
    def __init__(self, root: Path, runner: Runner = subprocess.run):
        candidate = Path(root).expanduser().resolve()
        if not candidate.is_dir():
            raise Phase2Error("a raiz do projeto não existe ou não é uma pasta")
        if candidate == SKILL_ROOT or candidate.is_relative_to(SKILL_ROOT):
            raise Phase2Error("a instalação do edvid não pode ser usada como projeto")
        self.root = candidate
        self.edit = candidate / "edit"
        self.cut = self.edit / "cut.mp4"
        self.remotion = self.edit / "remotion"
        self.public = self.remotion / "public"
        self.data = self.edit / "studio-phase2"
        self.state_path = self.data / "state.json"
        self.runner = runner

    # ---- infraestrutura, no mesmo padrão do resto do Studio ----
    @contextmanager
    def mutation_lock(self):
        import fcntl
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / ".edvid-studio-phase2.lock"
        with lock.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Phase2Error("já existe uma Fase 2 em execução neste projeto") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def confined(self, raw: str | Path, *, must_exist: bool = False) -> Path:
        path = Path(raw).expanduser()
        path = (self.root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(self.root):
            raise Phase2Error("o caminho precisa permanecer dentro do projeto")
        if must_exist and (not path.is_file() or path.stat().st_size == 0):
            raise Phase2Error(f"arquivo não encontrado no projeto: {raw}")
        return path

    def _state(self) -> dict:
        if not self.state_path.exists():
            return {"version": SCHEMA_VERSION, "project": str(self.root), "profile": "remotion-phase-2"}
        state = _read_json(self.state_path)
        if not isinstance(state, dict):
            raise Phase2Error("state.json precisa conter um objeto")
        return state

    def _update_state(self, **fields: Any) -> None:
        state = self._state()
        state.update(fields)
        _atomic_json(self.state_path, state)

    def status(self) -> dict:
        return {"ok": True, "action": "status", "scaffolded": self.remotion.is_dir(),
                "state": self._state()}

    # ---- scaffold ----
    def scaffold(self) -> dict:
        """Copia o template para dentro do projeto. Nunca sobrescreve."""
        if not self.cut.is_file() or self.cut.stat().st_size == 0:
            raise Phase2Error("não há edit/cut.mp4 aprovado para levar à Fase 2")
        if not TEMPLATE.is_dir():
            raise Phase2Error("o template shortform não está na instalação da skill")
        created = False
        if not self.remotion.exists():
            # ignora o que não deve viajar: dependências e saídas de render
            shutil.copytree(TEMPLATE, self.remotion,
                            ignore=shutil.ignore_patterns("node_modules", "out", ".git", "*.log"))
            created = True
        # node_modules do Remotion pesa ~570 MB POR PROJETO. Com três projetos
        # isso já são 1,7 GB nesta máquina, e cresce a cada vídeo. Quando existe
        # uma instalação compartilhada no template, o projeto aponta para ela em
        # vez de duplicar — e ainda renderiza na hora, sem `npm install`.
        # NÃO copio: um symlink é reversível (apague e rode npm install local).
        compartilhado = TEMPLATE / "node_modules"
        alvo_modulos = self.remotion / "node_modules"
        if compartilhado.is_dir() and not alvo_modulos.exists():
            try:
                alvo_modulos.symlink_to(compartilhado, target_is_directory=True)
            except OSError:
                pass   # sem link, o projeto simplesmente pede npm install
        self.public.mkdir(parents=True, exist_ok=True)
        target = self.public / "cut.mp4"
        if not target.exists() or _fingerprint(target) != _fingerprint(self.cut):
            shutil.copy2(self.cut, target)
        self._update_state(scaffold={"created": created, "at": int(time.time())})
        return {"ok": True, "action": "scaffold", "created": created,
                "remotion": str(self.remotion.relative_to(self.root)),
                "note": "template copiado; os TSX não devem ser editados (Hard Rule 11)"}

    # ---- validação do edit-data ----
    def _cut_info(self) -> dict:
        run = self.runner(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,r_frame_rate", "-show_entries", "format=duration",
                           "-of", "json", str(self.cut)], capture_output=True, text=True)
        if getattr(run, "returncode", 1) != 0:
            raise Phase2Error("não consegui inspecionar edit/cut.mp4")
        doc = json.loads(run.stdout)
        stream = doc["streams"][0]
        num, _, den = str(stream["r_frame_rate"]).partition("/")
        fps = float(num) / float(den or 1)
        return {"width": int(stream["width"]), "height": int(stream["height"]),
                "fps": round(fps, 3), "duration": float(doc["format"]["duration"])}

    def _collect_assets(self, data: dict) -> list[str]:
        found: list[str] = []
        for section, key in ASSET_FIELDS:
            block = data.get(section)
            if isinstance(block, dict) and block.get("enabled") is not False and block.get(key):
                found.append(str(block[key]))
        for name, fields in ASSET_LIST_FIELDS.items():
            for item in data.get(name) or []:
                if not isinstance(item, dict):
                    continue
                for key, prefix in fields:
                    if item.get(key):
                        value = Path(str(item[key]))
                        if prefix and value.parts[:1] != (prefix,):
                            value = Path(prefix) / value
                        found.append(str(value))
        return found

    def _validate_stacked_cues(self, *, duration_ms: int,
                               outro_start_ms: int | None) -> None:
        path = self.public / "caption-cues.json"
        if not path.is_file():
            raise Phase2Error("legenda stacked ligada, mas public/caption-cues.json não existe")
        cues = _read_json(path)
        if not isinstance(cues, list) or not cues:
            raise Phase2Error("legenda stacked ligada, mas caption-cues.json está vazio")
        previous_end = 0
        for index, cue in enumerate(cues):
            try:
                start = int(cue["startMs"])
                end = int(cue["endMs"])
                lines = cue["lines"]
                words = [word for line in lines for word in line]
                word_times = [(str(word["text"]).strip(), int(word["fromMs"]),
                               int(word["toMs"])) for word in words]
            except (KeyError, TypeError, ValueError):
                raise Phase2Error(f"caption-cues.json: cue {index} tem estrutura inválida") from None
            if start < previous_end or end <= start:
                raise Phase2Error(f"caption-cues.json: cue {index} tem tempo inválido ou sobreposto")
            if not word_times or any(not text or begin < start or finish > end or finish <= begin
                                     for text, begin, finish in word_times):
                raise Phase2Error(f"caption-cues.json: cue {index} tem palavra vazia ou fora do próprio tempo")
            if end > duration_ms:
                raise Phase2Error(f"caption-cues.json: cue {index} passa do fim do vídeo")
            if outro_start_ms is not None and end > outro_start_ms:
                raise Phase2Error(f"caption-cues.json: cue {index} cai em cima do encerramento")
            previous_end = end

    def validate(self, data: Any) -> dict:
        """As invariantes que quebram um render inteiro em silêncio."""
        if not isinstance(data, dict):
            raise Phase2Error("edit-data precisa ser um objeto")
        info = self._cut_info()
        for key in ("width", "height", "fps", "durationSec"):
            if key not in data:
                raise Phase2Error(f"edit-data sem `{key}`")
        try:
            width = int(data["width"])
            height = int(data["height"])
            fps = float(data["fps"])
            duration = float(data["durationSec"])
        except (TypeError, ValueError):
            raise Phase2Error("width, height, fps e durationSec precisam ser números") from None
        if not math.isfinite(fps) or not math.isfinite(duration):
            raise Phase2Error("fps e durationSec precisam ser números finitos")
        for key in LIST_FIELDS:
            if key in data and not isinstance(data[key], list):
                raise Phase2Error(f"`{key}` precisa ser uma lista, não um marcador de texto")
        # fps: a skill avisa que o edit-data tem que casar com o cut.mp4 gerado.
        # Errar aqui desloca TODA a linha do tempo da Fase 2 sem erro nenhum.
        if abs(fps - info["fps"]) > 0.05:
            raise Phase2Error(
                f"fps do edit-data ({data['fps']}) não bate com o cut.mp4 ({info['fps']}) — "
                "a Fase 2 inteira sai fora de sincronia")
        if render_scale(width, height, info["width"], info["height"]) is None:
            raise Phase2Error(
                f"dimensões do edit-data ({data['width']}x{data['height']}) não batem com o "
                f"cut.mp4 ({info['width']}x{info['height']}) nem como múltiplo inteiro dele")
        if duration <= 0:
            raise Phase2Error("durationSec precisa ser maior que zero")
        outro = data.get("outro") or {}
        if not isinstance(outro, dict):
            raise Phase2Error("`outro` precisa ser um objeto")
        outro_start_ms = None
        fim_esperado = info["duration"]
        limite_final = fim_esperado + 0.25
        if outro.get("enabled"):
            try:
                outro_start = float(outro["startSec"])
                outro_duration = float(outro.get("durationSec", 2.6))
            except (KeyError, TypeError, ValueError):
                raise Phase2Error("encerramento ligado exige startSec e durationSec numéricos") from None
            if (not math.isfinite(outro_start) or not math.isfinite(outro_duration)
                    or outro_start < 0 or outro_duration <= 0):
                raise Phase2Error("encerramento precisa ter início válido e duração maior que zero")
            if outro_start > info["duration"] + 0.02:
                raise Phase2Error("o encerramento começa depois do fim do corte e congelaria a imagem")
            outro_start_ms = round(outro_start * 1000)
            fim_esperado = max(fim_esperado, outro_start + outro_duration)
            limite_final = fim_esperado + 0.25
        if duration < fim_esperado - 0.25:
            raise Phase2Error(
                f"durationSec ({duration}s) termina antes do conteúdo esperado ({fim_esperado:.1f}s)")
        # A única extensão legítima é a que o encerramento descreve. O limite
        # antigo de 15 s aceitava qualquer silêncio/quadro congelado sem motivo.
        if duration > limite_final:
            raise Phase2Error(
                f"durationSec ({duration}s) passa {duration - info['duration']:.1f}s do corte "
                f"({info['duration']:.1f}s) sem um encerramento que explique a diferença")
        # Legenda com bloco vazio ou sobreposta renderiza sem erro e estraga o
        # vídeo entregue. Achado em projeto real: 90 blocos vazios seguidos,
        # metade do vídeo com tempo e sem texto, invisível até existir gate.
        # Só quando a legenda está LIGADA: o template vem com captions.json
        # vazio, e lista vazia é problema de quem vai exibir legenda, não de
        # quem desligou. Foi o que os testes mostraram ao quebrar todo
        # projeto recém-scaffoldado.
        captions_config = data.get("captions") or {}
        if not isinstance(captions_config, dict):
            raise Phase2Error("`captions` precisa ser um objeto")
        quer_legenda = bool(captions_config.get("enabled"))
        captions = self.public / "captions.json"
        if quer_legenda and not captions.is_file():
            raise Phase2Error("legenda ligada, mas public/captions.json não existe")
        if quer_legenda:
            import caption_edit
            try:
                cues = caption_edit.load(captions)
            except caption_edit.CaptionError as exc:
                raise Phase2Error(str(exc)) from exc
            limite = int(duration * 1000)
            erros = caption_edit.validate(cues, duration_ms=limite,
                                           outro_start_ms=outro_start_ms)
            if erros:
                raise Phase2Error("legenda inválida: " + "; ".join(erros[:3])
                                  + (f" (e mais {len(erros) - 3})" if len(erros) > 3 else ""))
            if captions_config.get("style") == "stacked":
                self._validate_stacked_cues(duration_ms=limite,
                                            outro_start_ms=outro_start_ms)
                sfx_config = captions_config.get("sfx") or {}
                if not isinstance(sfx_config, dict):
                    raise Phase2Error("`captions.sfx` precisa ser um objeto")
                if sfx_config.get("enabled", True) is not False:
                    for required in ("sfx/caption-click.mp3", "sfx/caption-scratch.mp3"):
                        if not (self.public / required).is_file():
                            raise Phase2Error(f"asset ausente em public/: {required}")
        missing = []
        for raw in self._collect_assets(data):
            if Path(raw).is_absolute() or ".." in Path(raw).parts:
                raise Phase2Error(f"asset com caminho inseguro: {raw}")
            if not (self.public / raw).is_file():
                missing.append(raw)
        if missing:
            raise Phase2Error("assets ausentes em public/: " + ", ".join(sorted(set(missing))))
        return info

    # ---- revisões ----
    def save(self, edit_data_raw: str) -> dict:
        self.scaffold()
        source = self.confined(edit_data_raw, must_exist=True)
        data = _read_json(source)
        info = self.validate(data)
        _atomic_json(self.public / "edit-data.json", data)
        state = self._state()
        revision = int(state.get("revision") or 0) + 1
        doc = {"revision": revision, "editData": data, "cutInfo": info,
               "cutFingerprint": _fingerprint(self.cut), "savedAt": int(time.time())}
        doc["dataHash"] = _digest({"editData": data, "cutFingerprint": doc["cutFingerprint"]})
        _atomic_json(self.data / "revisions" / f"rev-{revision}.json", doc)
        (self.data / "approved.json").unlink(missing_ok=True)
        self._update_state(revision=revision, dataHash=doc["dataHash"], approval=None,
                           render=None, delivery=None)
        return {"ok": True, "action": "save", "revision": revision, "dataHash": doc["dataHash"]}

    def _revision(self, revision: int, data_hash: str) -> dict:
        if revision < 1 or not HASH_RE.fullmatch(data_hash or ""):
            raise Phase2Error("a revisão ou o hash é inválido")
        path = self.data / "revisions" / f"rev-{revision}.json"
        if not path.exists():
            raise Phase2Error("a revisão ou o hash não corresponde ao que foi salvo")
        doc = _read_json(path)
        expected = _digest({"editData": doc.get("editData"), "cutFingerprint": doc.get("cutFingerprint")})
        if doc.get("revision") != revision or doc.get("dataHash") != data_hash or expected != data_hash:
            raise Phase2Error("a revisão ou o hash não corresponde ao que foi salvo")
        return doc

    def approve(self, revision: int, data_hash: str, approved: bool) -> dict:
        if approved is not True:
            raise Phase2Error("a aprovação explícita exige --approve")
        doc = self._revision(revision, data_hash)
        if _fingerprint(self.cut) != doc.get("cutFingerprint"):
            raise Phase2Error("o corte mudou; salve e aprove uma nova revisão da Fase 2")
        approval = {"version": 1, "revision": revision, "dataHash": data_hash,
                    "approvedAt": int(time.time()), "scope": "phase-2-for-current-cut"}
        _atomic_json(self.data / "approved.json", approval)
        self._update_state(approval=approval, render=None)
        return {"ok": True, "action": "approve", **approval}

    # ---- render ----
    def build_render_command(self, output: Path, scale: int = 1) -> list[str]:
        # Qualidade primeiro (regra de 2026-09-22): quadros JPEG a 95 em vez do
        # padrão 80 do Remotion e CRF 16. Com o corte em 4K, --scale 2 desenha o
        # layout de 1080×1920 em 2160×3840 e o vídeo entra na resolução inteira.
        cmd = ["npx", "--no-install", "remotion", "render", COMPOSITION, str(output),
               "--log", "error", "--jpeg-quality", "95", "--crf", "16"]
        if scale > 1:
            cmd += ["--scale", str(scale)]
        return cmd

    def _render_scale(self) -> int:
        try:
            data = json.loads((self.public / "edit-data.json").read_text())
            info = self._cut_info()
            return render_scale(int(data["width"]), int(data["height"]),
                                info["width"], info["height"]) or 1
        except Exception:  # noqa: BLE001 — sem escala o render sai no tamanho do layout
            return 1

    def _gate(self, argv: list[str], label: str) -> None:
        run = self.runner(argv, capture_output=True, text=True)
        if getattr(run, "returncode", 1) != 0:
            detail = (getattr(run, "stdout", "") or "") + (getattr(run, "stderr", "") or "")
            raise Phase2Error(f"{label} reprovou: {detail.strip()[:600]}")

    def render(self, revision: int, data_hash: str) -> dict:
        doc = self._revision(revision, data_hash)
        approval = self._state().get("approval") or {}
        if approval.get("revision") != revision or approval.get("dataHash") != data_hash:
            raise Phase2Error("esta revisão da Fase 2 não está aprovada")
        if _fingerprint(self.cut) != doc.get("cutFingerprint"):
            raise Phase2Error("o corte mudou depois da aprovação; aprove de novo")
        if not (self.remotion / "node_modules").is_dir():
            raise Phase2Error(
                "as dependências do Remotion não estão disponíveis — prepare a instalação "
                "compartilhada no template com `npm install` e execute Preparar Fase 2 novamente")
        # Gate obrigatório: insert congelado ou ampliado passa em silêncio.
        self._gate([sys.executable, str(HELPERS_DIR / "check_inserts.py"),
                    str(self.public / "edit-data.json")], "check_inserts")
        output = self.edit / "final.mp4"
        staged = self.edit / f".final-phase2-r{revision}-{data_hash[:12]}.mp4"
        staged.unlink(missing_ok=True)
        try:
            run = self.runner(self.build_render_command(staged, self._render_scale()),
                              cwd=str(self.remotion),
                              capture_output=True, text=True)
            if getattr(run, "returncode", 1) != 0:
                detail = (getattr(run, "stderr", "") or "")[:600]
                raise Phase2Error(f"o render do Remotion falhou: {detail.strip()}")
            if not staged.is_file() or staged.stat().st_size == 0:
                raise Phase2Error("o render terminou sem produzir o vídeo da Fase 2")
            self._gate([sys.executable, str(HELPERS_DIR / "qc_final.py"), str(staged)], "qc_final")
            if output.is_file():
                history = self.data / "renders"
                history.mkdir(parents=True, exist_ok=True)
                old = _fingerprint(output)
                os.replace(output, history / f"final-{int(time.time())}-{old['sha256'][:12]}.mp4")
            os.replace(staged, output)
        finally:
            staged.unlink(missing_ok=True)
        result = {"ok": True, "action": "render", "revision": revision,
                  "output": str(output.relative_to(self.root)),
                  "fingerprint": _fingerprint(output)}
        self._update_state(render=result, delivery=None)
        return result

    def review_approve(self, output_hash: str, full_review: bool) -> dict:
        if full_review is not True or not HASH_RE.fullmatch(output_hash or ""):
            raise Phase2Error("a revisão visual integral e o hash do arquivo são obrigatórios")
        render = self._state().get("render") or {}
        output_raw = render.get("output")
        expected = (render.get("fingerprint") or {}).get("sha256")
        if not output_raw or not expected or output_hash != expected:
            raise Phase2Error("o hash não corresponde ao último render aprovado pelos gates")
        output = self.confined(output_raw, must_exist=True)
        if _fingerprint(output).get("sha256") != output_hash:
            raise Phase2Error("o vídeo mudou depois do render; assista e aprove o arquivo atual")
        delivery = {"version": 1, "output": str(output.relative_to(self.root)),
                    "outputHash": output_hash, "fullReview": True,
                    "approvedAt": int(time.time()), "status": "approved-for-delivery"}
        _atomic_json(self.data / "delivery.json", delivery)
        self._update_state(delivery=delivery)
        return {"ok": True, "action": "review-approve", **delivery}


ACTIONS = ("status", "scaffold", "save", "approve", "render", "review-approve")


def parser() -> argparse.ArgumentParser:
    # `--action`, como studio_pipeline.py e studio_finish.py — um estilo só para
    # os três módulos do Studio, porque é o servidor que monta o argv dos três.
    ap = argparse.ArgumentParser(description="Fase 2 (Remotion) do Edvid Studio")
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--action", required=True, choices=ACTIONS)
    ap.add_argument("--edit-data")
    ap.add_argument("--revision", type=int)
    ap.add_argument("--data-hash")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--output-hash")
    ap.add_argument("--full-review", action="store_true")
    return ap


def dispatch(args: argparse.Namespace, runner: Runner = subprocess.run) -> dict:
    phase2 = StudioPhase2(args.root, runner=runner)
    if args.action == "status":
        return phase2.status()
    with phase2.mutation_lock():
        if args.action == "scaffold":
            return phase2.scaffold()
        if args.action == "save":
            if not args.edit_data:
                raise Phase2Error("save exige --edit-data")
            return phase2.save(args.edit_data)
        if args.action == "review-approve":
            return phase2.review_approve(args.output_hash or "", args.full_review)
        if args.revision is None or not args.data_hash:
            raise Phase2Error(f"{args.action} exige --revision e --data-hash")
        if args.action == "approve":
            return phase2.approve(args.revision, args.data_hash, args.approve)
        if args.action == "render":
            return phase2.render(args.revision, args.data_hash)
    raise Phase2Error("ação desconhecida")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        print(json.dumps(dispatch(args), ensure_ascii=False))
        return 0
    except Phase2Error as exc:
        print(json.dumps({"ok": False, "action": args.action, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
