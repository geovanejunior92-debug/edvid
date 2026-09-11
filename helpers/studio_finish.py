"""Bounded local finishing for an existing, explicitly approved Studio cut.

This additive path supports burned captions, one headline, local fullscreen or
split inserts, and a local music bed.  It deliberately does not modify the cut,
EDL, Remotion project, or calibrated Format 1 templates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
HELPERS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = HELPERS_DIR.parent.resolve()
Runner = Callable[..., subprocess.CompletedProcess]
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class FinishError(RuntimeError):
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
        raise FinishError(f"JSON inválido ou ilegível: {path.name}") from exc


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _fingerprint(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "size": path.stat().st_size}


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise FinishError(f"{label} precisa ser número")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FinishError(f"{label} precisa ser número") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise FinishError(f"{label} precisa ser finito")
    return result


class StudioFinish:
    def __init__(self, root: Path, runner: Runner = subprocess.run):
        candidate = root.expanduser().resolve()
        if not candidate.is_dir():
            raise FinishError("a raiz do projeto não existe ou não é uma pasta")
        if candidate == SKILL_ROOT or candidate.is_relative_to(SKILL_ROOT):
            raise FinishError("a instalação do edvid não pode ser usada como projeto")
        self.root = candidate
        self.edit = candidate / "edit"
        self.cut = self.edit / "cut.mp4"
        self.data = self.edit / "studio-finish"
        self.state_path = self.data / "state.json"
        self.runner = runner
        for path in (self.edit, self.data):
            if path.exists() and not path.resolve().is_relative_to(self.root):
                raise FinishError("edit/studio-finish precisa permanecer dentro do projeto")

    def _prepare(self) -> None:
        if not self.cut.is_file() or self.cut.stat().st_size == 0:
            raise FinishError("não há edit/cut.mp4 existente para finalizar")
        self.data.mkdir(parents=True, exist_ok=True)
        if not self.data.resolve().is_relative_to(self.root):
            raise FinishError("o diretório de finalização precisa permanecer dentro do projeto")

    @contextmanager
    def mutation_lock(self):
        import fcntl
        lock = self.root / ".edvid-studio-finish.lock"
        with lock.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise FinishError("já existe uma finalização em execução neste projeto") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def confined(self, raw: str | Path, *, must_exist: bool = False) -> Path:
        path = Path(raw).expanduser()
        path = (self.root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(self.root):
            raise FinishError("o caminho precisa permanecer dentro do projeto")
        if must_exist and (not path.is_file() or path.stat().st_size == 0):
            raise FinishError(f"arquivo não encontrado no projeto: {path.relative_to(self.root)}")
        return path

    def _state(self) -> dict:
        if not self.state_path.exists():
            return {"version": SCHEMA_VERSION, "project": str(self.root), "profile": "manual-local-subset"}
        state = _read_json(self.state_path)
        if not isinstance(state, dict):
            raise FinishError("state.json precisa conter um objeto")
        return state

    def _update_state(self, **fields: Any) -> None:
        state = self._state()
        state.update(fields)
        _atomic_json(self.state_path, state)

    def status(self) -> dict:
        return {"ok": True, "action": "status", "state": self._state()}

    def _probe(self) -> dict:
        run = self.runner([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height,avg_frame_rate,color_primaries,color_transfer,color_space",
            "-of", "json", str(self.cut),
        ], capture_output=True, text=True)
        try:
            info = json.loads(run.stdout) if run.returncode == 0 else {}
            duration = float(info["format"]["duration"])
            video = next(x for x in info["streams"] if x.get("codec_type") == "video")
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FinishError("ffprobe não conseguiu medir o corte atual") from exc
        if duration <= 0:
            raise FinishError("o corte atual tem duração inválida")
        primaries = str(video.get("color_primaries") or "unknown").lower()
        transfer = str(video.get("color_transfer") or "unknown").lower()
        if primaries in {"bt2020", "smpte431", "smpte432"} or transfer in {"smpte2084", "arib-std-b67"}:
            raise FinishError("o corte está marcado como HDR/wide gamut; converta-o de verdade para Rec.709 antes da finalização")
        return {"duration": duration, "width": int(video["width"]), "height": int(video["height"]),
                "fps": str(video.get("avg_frame_rate") or "30/1"), "colorPrimaries": primaries,
                "colorTransfer": transfer, "colorSpace": str(video.get("color_space") or "unknown")}

    def _parse_cues(self, captions: dict, duration: float) -> list[dict]:
        mode = captions.get("mode", "none")
        if mode not in {"none", "manual", "import"}:
            raise FinishError("captions.mode precisa ser none, manual ou import")
        if mode == "none":
            return []
        if mode == "import":
            source = self.confined(str(captions.get("file") or ""), must_exist=True)
            raw = _read_json(source)
            if isinstance(raw, dict):
                raw = raw.get("cues") or raw.get("captions") or raw.get("words")
            if not isinstance(raw, list):
                raise FinishError("o arquivo de legendas precisa conter uma lista de cues")
        else:
            raw = captions.get("cues")
            if not isinstance(raw, list):
                raise FinishError("captions.cues precisa ser uma lista")
        cues = []
        for index, cue in enumerate(raw, 1):
            if not isinstance(cue, dict):
                raise FinishError(f"legenda {index} precisa ser um objeto")
            millis = "startMs" in cue or "endMs" in cue
            start = _number(cue.get("startMs" if millis else "start"), f"legenda {index}.start")
            end = _number(cue.get("endMs" if millis else "end"), f"legenda {index}.end")
            if millis:
                start, end = start / 1000, end / 1000
            text = str(cue.get("text") or "").strip()
            if not text or start < 0 or end <= start or end > duration + 0.001:
                raise FinishError(f"legenda {index} tem texto ou intervalo inválido")
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        return sorted(cues, key=lambda x: (x["start"], x["end"]))

    def _assert_video_insert_sdr(self, source: Path) -> None:
        if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
            return
        run = self.runner(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=color_primaries,color_transfer", "-of", "json", str(source)],
                          capture_output=True, text=True)
        try:
            stream = (json.loads(run.stdout).get("streams") or [{}])[0] if run.returncode == 0 else {}
        except json.JSONDecodeError as exc:
            raise FinishError(f"ffprobe não conseguiu inspecionar o insert {source.name}") from exc
        primaries = str(stream.get("color_primaries") or "unknown").lower()
        transfer = str(stream.get("color_transfer") or "unknown").lower()
        if primaries in {"bt2020", "smpte431", "smpte432"} or transfer in {"smpte2084", "arib-std-b67"}:
            raise FinishError(f"o insert {source.name} está marcado como HDR/wide gamut; converta-o para Rec.709")

    def _validate(self, raw: Any) -> tuple[dict, dict]:
        if not isinstance(raw, dict) or raw.get("version") != SCHEMA_VERSION:
            raise FinishError("settings precisa ser objeto com version 1")
        info = self._probe()
        duration = info["duration"]
        captions = raw.get("captions") or {"mode": "none"}
        if not isinstance(captions, dict):
            raise FinishError("captions precisa ser um objeto")
        clean_captions = {"mode": captions.get("mode", "none"),
                          "burn": bool(captions.get("burn", True)),
                          "fontSize": int(captions.get("fontSize", 54))}
        if clean_captions["fontSize"] < 16 or clean_captions["fontSize"] > 160:
            raise FinishError("captions.fontSize precisa ficar entre 16 e 160")
        clean_captions["cues"] = self._parse_cues(captions, duration)

        headline = raw.get("headline") or {"enabled": False}
        if not isinstance(headline, dict):
            raise FinishError("headline precisa ser um objeto")
        enabled = bool(headline.get("enabled", False))
        clean_headline = {"enabled": enabled}
        if enabled:
            text = str(headline.get("text") or "").strip()
            start = _number(headline.get("start", 0), "headline.start")
            end = _number(headline.get("end", min(4, duration)), "headline.end")
            if not text or len(text) > 180 or start < 0 or end <= start or end > duration + 0.001:
                raise FinishError("headline tem texto ou intervalo inválido")
            clean_headline.update({"text": text, "start": round(start, 3), "end": round(end, 3),
                                   "fontSize": int(headline.get("fontSize", 64))})

        inserts = raw.get("inserts") or []
        if not isinstance(inserts, list) or len(inserts) > 40:
            raise FinishError("inserts precisa ser uma lista com no máximo 40 itens")
        clean_inserts = []
        for index, item in enumerate(inserts, 1):
            if not isinstance(item, dict):
                raise FinishError(f"insert {index} precisa ser um objeto")
            source = self.confined(str(item.get("file") or ""), must_exist=True)
            self._assert_video_insert_sdr(source)
            start = _number(item.get("start"), f"insert {index}.start")
            end = _number(item.get("end"), f"insert {index}.end")
            layout = item.get("layout")
            if layout not in {"fullscreen", "split"}:
                raise FinishError(f"insert {index}.layout precisa ser fullscreen ou split")
            if start < 0 or end <= start or end > duration + 0.001:
                raise FinishError(f"insert {index} ultrapassa a duração do corte")
            clean_inserts.append({"file": str(source.relative_to(self.root)), "start": round(start, 3),
                                  "end": round(end, 3), "layout": layout})

        music = raw.get("music") or {"enabled": False}
        if not isinstance(music, dict):
            raise FinishError("music precisa ser um objeto")
        clean_music = {"enabled": bool(music.get("enabled", False))}
        if clean_music["enabled"]:
            source = self.confined(str(music.get("file") or ""), must_exist=True)
            gain = _number(music.get("gainDb", -18), "music.gainDb")
            fade_in = _number(music.get("fadeIn", 0.4), "music.fadeIn")
            fade_out = _number(music.get("fadeOut", 1.0), "music.fadeOut")
            duck = _number(music.get("duckingDb", -10), "music.duckingDb")
            if not -60 <= gain <= 0 or not -30 <= duck <= 0 or min(fade_in, fade_out) < 0:
                raise FinishError("ganho, ducking ou fades da música estão fora do limite")
            clean_music.update({"file": str(source.relative_to(self.root)), "gainDb": gain,
                                "fadeIn": min(fade_in, duration), "fadeOut": min(fade_out, duration),
                                "duckingDb": duck})
        platform = raw.get("platform", "reels")
        if platform not in {"reels", "tiktok", "shorts"}:
            raise FinishError("platform precisa ser reels, tiktok ou shorts")
        clean = {"version": 1, "profile": "manual-local-subset", "platform": platform,
                 "captions": clean_captions, "headline": clean_headline,
                 "inserts": clean_inserts, "music": clean_music,
                 "limitations": ["sem matte, logo, outro ou efeitos dinâmicos do Formato 1",
                                 "não substitui o projeto Remotion existente"]}
        return clean, info

    def save(self, settings: Any) -> dict:
        self._prepare()
        clean, info = self._validate(settings)
        cut_fp = _fingerprint(self.cut)
        folder = self.data / "settings"
        prior = [int(p.stem.split("-")[-1]) for p in folder.glob("rev-*.json")
                 if p.stem.split("-")[-1].isdigit()]
        revision = max(prior, default=0) + 1
        assets = sorted({item["file"] for item in clean["inserts"]}
                        | ({clean["music"]["file"]} if clean["music"]["enabled"] else set()))
        asset_fingerprints = {path: _fingerprint(self.root / path) for path in assets}
        settings_hash = _digest({"settings": clean, "cutFingerprint": cut_fp,
                                 "assetFingerprints": asset_fingerprints})
        doc = {"version": 1, "revision": revision, "settingsHash": settings_hash,
               "cutFingerprint": cut_fp, "assetFingerprints": asset_fingerprints,
               "cutInfo": info, "settings": clean, "savedAt": int(time.time())}
        path = folder / f"rev-{revision}.json"
        _atomic_json(path, doc)
        approval = self.data / "approved.json"
        approval.unlink(missing_ok=True)
        result = {"ok": True, "action": "save", "revision": revision, "settingsHash": settings_hash,
                  "cutFingerprint": cut_fp, "settings": str(path.relative_to(self.root)),
                  "requiresApproval": True, "profile": "manual-local-subset"}
        self._update_state(latest=result, approval=None, render=None, review=None)
        return result

    def _revision(self, revision: int, settings_hash: str) -> dict:
        if revision < 1 or not HASH_RE.fullmatch(settings_hash or ""):
            raise FinishError("a revisão ou o hash das configurações é inválido")
        path = self.data / "settings" / f"rev-{revision}.json"
        if not path.exists():
            raise FinishError("a revisão ou o hash não corresponde às configurações salvas")
        doc = _read_json(path)
        expected = _digest({"settings": doc.get("settings"), "cutFingerprint": doc.get("cutFingerprint"),
                            "assetFingerprints": doc.get("assetFingerprints") or {}})
        if doc.get("revision") != revision or doc.get("settingsHash") != settings_hash or expected != settings_hash:
            raise FinishError("a revisão ou o hash não corresponde às configurações salvas")
        return doc

    def _assert_cut(self, doc: dict) -> None:
        if not self.cut.is_file() or _fingerprint(self.cut) != doc.get("cutFingerprint"):
            raise FinishError("o corte mudou; salve e aprove uma nova revisão de finalização")

    def _assert_assets(self, doc: dict) -> None:
        for raw, expected in (doc.get("assetFingerprints") or {}).items():
            source = self.confined(raw, must_exist=True)
            if _fingerprint(source) != expected:
                raise FinishError(f"o asset {raw} mudou; salve e aprove uma nova revisão de finalização")

    def approve(self, revision: int, settings_hash: str, approved: bool) -> dict:
        self._prepare()
        if approved is not True:
            raise FinishError("a aprovação explícita exige --approve")
        doc = self._revision(revision, settings_hash)
        self._assert_cut(doc)
        self._assert_assets(doc)
        approval = {"version": 1, "revision": revision, "settingsHash": settings_hash,
                    "cutFingerprint": doc["cutFingerprint"], "approvedAt": int(time.time()),
                    "scope": "finishing-settings-for-current-cut"}
        _atomic_json(self.data / "approved.json", approval)
        result = {"ok": True, "action": "approve", **approval}
        self._update_state(approval=result, render=None, review=None)
        return result

    def _loudness_target(self) -> float:
        run = self.runner(["ffmpeg", "-hide_banner", "-nostats", "-i", str(self.cut),
                           "-af", "ebur128=peak=true", "-f", "null", "-"],
                          capture_output=True, text=True)
        summary = (run.stderr or "")[(run.stderr or "").rfind("Summary:"):]
        match = re.search(r"I:\s*(-?[\d.]+)", summary)
        measured = float(match.group(1)) if match else -10.0
        # The configured social target is -10 LUFS, but a louder source is never reduced.
        return round(max(-10.0, measured), 1)

    def _text_card(self, text: str, path: Path, width: int, height: int, font_size: int,
                   y_fraction: float) -> None:
        """Rasterize text portably because this Mac's FFmpeg lacks drawtext/libass."""
        from PIL import Image, ImageDraw, ImageFont
        import textwrap

        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        font_path = HELPERS_DIR.parent / "assets" / "fonts" / "Poppins-ExtraBold.ttf"
        font = ImageFont.truetype(str(font_path), font_size)
        max_chars = max(8, int(width / max(1, font_size) * 1.55))
        lines = textwrap.wrap(text, width=max_chars, break_long_words=False) or [text]
        spacing = max(6, font_size // 5)
        boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=4) for line in lines]
        block_h = sum(box[3] - box[1] for box in boxes) + spacing * (len(lines) - 1)
        y = int(height * y_fraction - block_h / 2)
        for line, box in zip(lines, boxes):
            line_w, line_h = box[2] - box[0], box[3] - box[1]
            x = (width - line_w) // 2
            # Keep the outline inside legal-range SDR; pure black makes qc_final's
            # broadcast-level gate correctly flag every frame carrying text.
            draw.text((x, y), line, font=font, fill=(245, 245, 245, 255),
                      stroke_width=5, stroke_fill=(24, 24, 24, 255))
            y += line_h + spacing
        image.save(path)

    def build_render_command(self, doc: dict, output: Path) -> tuple[list[str], Path | None]:
        settings, info = doc["settings"], doc["cutInfo"]
        duration, width, height = float(info["duration"]), int(info["width"]), int(info["height"])
        command = ["ffmpeg", "-y", "-v", "error", "-i", str(self.cut)]
        input_index = 1
        text_overlays = []
        headline = settings["headline"]
        if headline["enabled"]:
            card = output.parent / "headline.png"
            self._text_card(headline["text"], card, width, height, headline["fontSize"], .14)
            command += ["-loop", "1", "-framerate", "30", "-i", str(card)]
            text_overlays.append((input_index, headline["start"], headline["end"]))
            input_index += 1
        captions = settings["captions"]
        if captions["burn"]:
            for number, cue in enumerate(captions["cues"], 1):
                card = output.parent / f"caption-{number:04d}.png"
                self._text_card(cue["text"], card, width, height, captions["fontSize"], .66)
                command += ["-loop", "1", "-framerate", "30", "-i", str(card)]
                text_overlays.append((input_index, cue["start"], cue["end"]))
                input_index += 1
        insert_indexes = []
        image_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
        for insert in settings["inserts"]:
            source = self.root / insert["file"]
            if source.suffix.lower() in image_suffixes:
                command += ["-loop", "1", "-framerate", "30", "-i", str(source)]
            else:
                command += ["-stream_loop", "-1", "-i", str(source)]
            insert_indexes.append(input_index)
            input_index += 1
        music_index = None
        if settings["music"]["enabled"]:
            music_index = input_index
            command += ["-stream_loop", "-1", "-i", str(self.root / settings["music"]["file"])]

        filters = ["[0:v]format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,setpts=PTS-STARTPTS[v0]"]
        current = "v0"
        for number, (insert, idx) in enumerate(zip(settings["inserts"], insert_indexes), 1):
            if insert["layout"] == "fullscreen":
                shape = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
                y = "0"
            else:
                split_h = height // 2
                shape = f"scale={width}:{split_h}:force_original_aspect_ratio=increase,crop={width}:{split_h}"
                y = "0"
            # Shift the insert onto its timeline interval. Without +start/TB a
            # video insert beginning at 10 s has already consumed 10 s of media.
            filters.append(f"[{idx}:v]{shape},setsar=1,setpts=PTS-STARTPTS+{insert['start']}/TB[ins{number}]")
            next_label = f"v{number}"
            filters.append(f"[{current}][ins{number}]overlay=0:{y}:enable='between(t,{insert['start']},{insert['end']})':eof_action=pass[{next_label}]")
            current = next_label

        for number, (idx, start, end) in enumerate(text_overlays, 1):
            next_label = f"vtext{number}"
            filters.append(f"[{current}][{idx}:v]overlay=0:0:enable='between(t,{start},{end})':eof_action=pass[{next_label}]")
            current = next_label

        target = self._loudness_target()
        if music_index is not None:
            music = settings["music"]
            fade_out_start = max(0, duration - music["fadeOut"])
            threshold = max(0.003, min(0.1, 10 ** (music["duckingDb"] / 20)))
            filters += [
                f"[0:a]loudnorm=I={target}:TP=-1.0:LRA=11[voice_norm]",
                "[voice_norm]asplit=2[voice][side]",
                f"[{music_index}:a]volume={music['gainDb']}dB,afade=t=in:st=0:d={music['fadeIn']},"
                f"afade=t=out:st={fade_out_start}:d={music['fadeOut']},atrim=0:{duration}[bed]",
                f"[bed][side]sidechaincompress=threshold={threshold:.5f}:ratio=8:attack=20:release=300[ducked]",
                "[voice][ducked]amix=inputs=2:duration=first:normalize=0,"
                "alimiter=limit=0.891251:level=false:latency=true[aout]",
            ]
        else:
            filters.append(f"[0:a]loudnorm=I={target}:TP=-1.0:LRA=11[aout]")
        command += ["-filter_complex", ";".join(filters), "-map", f"[{current}]", "-map", "[aout]",
                    "-t", f"{duration:.6f}", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                    "-movflags", "+faststart", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-colorspace", "bt709", "-color_range", "tv", str(output)]
        return command, None

    def render(self, revision: int, settings_hash: str) -> dict:
        self._prepare()
        doc = self._revision(revision, settings_hash)
        self._assert_cut(doc)
        self._assert_assets(doc)
        approval_path = self.data / "approved.json"
        if not approval_path.exists():
            raise FinishError("o render exige aprovação explícita desta finalização")
        approval = _read_json(approval_path)
        if approval.get("revision") != revision or approval.get("settingsHash") != settings_hash:
            raise FinishError("o render exige a revisão e o hash aprovados atuais")
        self._assert_cut({"cutFingerprint": approval.get("cutFingerprint")})
        attempt = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        run_dir = self.data / "staging" / f"r{revision}-{settings_hash[:12]}-{attempt}"
        run_dir.mkdir(parents=True)
        stage = run_dir / "final.mp4"
        command, srt = self.build_render_command(doc, stage)
        rendered = self.runner(command, capture_output=True, text=True)
        if rendered.returncode or not stage.is_file() or stage.stat().st_size == 0:
            raise FinishError((rendered.stderr or "o FFmpeg não concluiu o render").strip()[-2000:])
        caption_qc = run_dir / "captions.json"
        _atomic_json(caption_qc, doc["settings"]["captions"]["cues"])
        qc_cmd = [sys.executable, str(HELPERS_DIR / "qc_final.py"), str(stage), "--cut", str(self.cut),
                  "--captions", str(caption_qc), "--platform", doc["settings"]["platform"],
                  "--target-i", str(self._loudness_target()), "--target-tp", "-1", "--json"]
        qc = self.runner(qc_cmd, capture_output=True, text=True)
        try:
            report = json.loads(qc.stdout)
        except json.JSONDecodeError:
            report = {"fails": ["qc_final não retornou JSON"], "log": (qc.stdout or qc.stderr or "")[-2000:]}
        if qc.returncode or report.get("fails"):
            self._update_state(render={"deliveryStatus": "qc-failed", "revision": revision,
                                       "settingsHash": settings_hash, "staging": str(run_dir.relative_to(self.root)),
                                       "qc": report}, review=None)
            raise FinishError("QC final reprovou o render: " + "; ".join(report.get("fails") or ["falha desconhecida"]))

        output_hash = _fingerprint(stage)["sha256"]
        duration = float(doc["cutInfo"]["duration"])
        times = sorted(set(round(x, 3) for x in [0, duration * .25, duration * .5, duration * .75,
                                                 max(0, duration - 0.2)]))
        sheet = run_dir / "review-sheet.jpg"
        sheet_cmd = [sys.executable, str(HELPERS_DIR / "contact_sheet.py"), str(stage), "--times",
                     *[str(x) for x in times], "-o", str(sheet)]
        made = self.runner(sheet_cmd, capture_output=True, text=True)
        if made.returncode or not sheet.is_file():
            raise FinishError("não foi possível gerar a folha de revisão visual")
        published = self.data / "renders" / f"r{revision}-{output_hash[:12]}-{attempt}"
        published.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(run_dir, published)
        except OSError as exc:
            raise FinishError("não foi possível publicar o render sem sobrescrever uma exportação anterior") from exc
        output = published / "final.mp4"
        report["file"] = str(output)
        _atomic_json(published / "verify" / "qc_final.json", report)
        result = {"ok": True, "action": "render", "revision": revision, "settingsHash": settings_hash,
                  "output": str(output.relative_to(self.root)), "outputHash": output_hash, "qc": report,
                  "reviewSheets": [str((published / sheet.name).relative_to(self.root))],
                  "reviewScope": "sampled-contact-sheet-only", "deliveryStatus": "awaiting-visual-review"}
        self._update_state(render=result, review=None)
        return result

    def review_approve(self, output_hash: str, full_review: bool) -> dict:
        if full_review is not True:
            raise FinishError("a aprovação exige confirmação de revisão integral do vídeo, não só das folhas")
        if not HASH_RE.fullmatch(output_hash or ""):
            raise FinishError("o hash da saída é inválido")
        state = self._state()
        render = state.get("render") or {}
        if render.get("deliveryStatus") != "awaiting-visual-review" or render.get("outputHash") != output_hash:
            raise FinishError("o hash não corresponde à saída atual aguardando revisão")
        output = self.confined(render.get("output") or "", must_exist=True)
        if _fingerprint(output)["sha256"] != output_hash:
            raise FinishError("o arquivo de saída mudou depois do render")
        review = {"ok": True, "action": "review-approve", "output": render["output"],
                  "outputHash": output_hash, "reviewedAt": int(time.time()),
                  "reviewScope": "full-video-confirmed", "deliveryStatus": "approved"}
        render = {**render, "deliveryStatus": "approved"}
        self._update_state(render=render, review=review)
        return review


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--action", required=True, choices=["status", "save", "approve", "render", "review-approve"])
    ap.add_argument("--settings-file")
    ap.add_argument("--settings-json")
    ap.add_argument("--revision", type=int)
    ap.add_argument("--settings-hash")
    ap.add_argument("--output-hash")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--full-review", action="store_true")
    return ap


def dispatch(args: argparse.Namespace, runner: Runner = subprocess.run) -> dict:
    engine = StudioFinish(args.root, runner=runner)
    if args.action == "status":
        return engine.status()
    with engine.mutation_lock():
        if args.action == "save":
            if bool(args.settings_file) == bool(args.settings_json):
                raise FinishError("use exatamente um de --settings-file ou --settings-json")
            if args.settings_file:
                raw = _read_json(engine.confined(args.settings_file, must_exist=True))
            else:
                try:
                    raw = json.loads(args.settings_json)
                except json.JSONDecodeError as exc:
                    raise FinishError("--settings-json não contém JSON válido") from exc
            return engine.save(raw)
        if args.action in {"approve", "render"}:
            if args.revision is None or not args.settings_hash:
                raise FinishError("--revision e --settings-hash são obrigatórios")
            if args.action == "approve":
                return engine.approve(args.revision, args.settings_hash, args.approve)
            return engine.render(args.revision, args.settings_hash)
        if not args.output_hash:
            raise FinishError("--output-hash é obrigatório")
        return engine.review_approve(args.output_hash, args.full_review)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
    except FinishError as exc:
        print(json.dumps({"ok": False, "action": args.action, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
