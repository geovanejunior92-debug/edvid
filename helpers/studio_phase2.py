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

**Limite honesto:** o render real exige as dependências do Remotion instaladas
(`npm install` em `edit/remotion`). Sem elas, `render` falha com a instrução —
não com um traceback. O comando montado é testável sem instalar nada, que é
como `studio_finish.py` também se testa.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
)
ASSET_LISTS = ("splitInserts", "inserts", "behind", "behindVideos", "graphics", "sfxCues")


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
        for name in ASSET_LISTS:
            for item in data.get(name) or []:
                if not isinstance(item, dict):
                    continue
                for key in ("src", "matte"):
                    if item.get(key):
                        found.append(str(item[key]))
        return found

    def validate(self, data: Any) -> dict:
        """As invariantes que quebram um render inteiro em silêncio."""
        if not isinstance(data, dict):
            raise Phase2Error("edit-data precisa ser um objeto")
        info = self._cut_info()
        for key in ("width", "height", "fps", "durationSec"):
            if key not in data:
                raise Phase2Error(f"edit-data sem `{key}`")
        # fps: a skill avisa que o edit-data tem que casar com o cut.mp4 gerado.
        # Errar aqui desloca TODA a linha do tempo da Fase 2 sem erro nenhum.
        if abs(float(data["fps"]) - info["fps"]) > 0.05:
            raise Phase2Error(
                f"fps do edit-data ({data['fps']}) não bate com o cut.mp4 ({info['fps']}) — "
                "a Fase 2 inteira sai fora de sincronia")
        if int(data["width"]) != info["width"] or int(data["height"]) != info["height"]:
            raise Phase2Error(
                f"dimensões do edit-data ({data['width']}x{data['height']}) não batem com o "
                f"cut.mp4 ({info['width']}x{info['height']})")
        duration = float(data["durationSec"])
        if duration <= 0:
            raise Phase2Error("durationSec precisa ser maior que zero")
        # a Fase 2 pode passar do corte por causa do encerramento, mas não muito
        if duration > info["duration"] + 15:
            raise Phase2Error(
                f"durationSec ({duration}s) passa {duration - info['duration']:.1f}s do corte "
                f"({info['duration']:.1f}s) — mais do que um encerramento explica")
        # Legenda com bloco vazio ou sobreposta renderiza sem erro e estraga o
        # vídeo entregue. Achado em projeto real: 90 blocos vazios seguidos,
        # metade do vídeo com tempo e sem texto, invisível até existir gate.
        # Só quando a legenda está LIGADA: o template vem com captions.json
        # vazio, e lista vazia é problema de quem vai exibir legenda, não de
        # quem desligou. Foi o que os testes mostraram ao quebrar todo
        # projeto recém-scaffoldado.
        quer_legenda = bool((data.get("captions") or {}).get("enabled"))
        captions = self.public / "captions.json"
        if quer_legenda and captions.is_file():
            import caption_edit
            try:
                cues = caption_edit.load(captions)
            except caption_edit.CaptionError as exc:
                raise Phase2Error(str(exc)) from exc
            limite = int(float(data["durationSec"]) * 1000)
            erros = caption_edit.validate(cues, duration_ms=limite)
            if erros:
                raise Phase2Error("legenda inválida: " + "; ".join(erros[:3])
                                  + (f" (e mais {len(erros) - 3})" if len(erros) > 3 else ""))
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
        self._update_state(revision=revision, dataHash=doc["dataHash"], approval=None, render=None)
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
    def build_render_command(self, output: Path) -> list[str]:
        return ["npx", "--no-install", "remotion", "render", COMPOSITION, str(output),
                "--log", "error"]

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
                "as dependências do Remotion não estão instaladas neste projeto — "
                f"rode `npm install` em {self.remotion.relative_to(self.root)} e tente de novo")
        # Gate obrigatório: insert congelado ou ampliado passa em silêncio.
        self._gate([sys.executable, str(HELPERS_DIR / "check_inserts.py"),
                    str(self.public / "edit-data.json")], "check_inserts")
        output = self.edit / "final.mp4"
        run = self.runner(self.build_render_command(output), cwd=str(self.remotion),
                          capture_output=True, text=True)
        if getattr(run, "returncode", 1) != 0:
            detail = (getattr(run, "stderr", "") or "")[:600]
            raise Phase2Error(f"o render do Remotion falhou: {detail.strip()}")
        if not output.is_file() or output.stat().st_size == 0:
            raise Phase2Error("o render terminou sem produzir edit/final.mp4")
        self._gate([sys.executable, str(HELPERS_DIR / "qc_final.py"), str(output)], "qc_final")
        result = {"ok": True, "action": "render", "revision": revision,
                  "output": str(output.relative_to(self.root)),
                  "fingerprint": _fingerprint(output)}
        self._update_state(render=result)
        return result


ACTIONS = ("status", "scaffold", "save", "approve", "render")


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
