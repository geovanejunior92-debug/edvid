"""Generate a background instrumental soundtrack with the Treblo API (Phase 3).

Async: start a generation → poll until SUCCESS → download the mp3. On FAILURE
no credit is charged. Result URLs expire ~168h, so we download immediately.

Needs TREBLO_API_KEY (env or .env at the edvid repo root).

Usage:
    python helpers/treblo_music.py "warm lo-fi ambient, unobtrusive" -o remotion/public/trilha.mp3
    python helpers/treblo_music.py "<vibe>" -o out.mp3 --length-min 30 --length-max 60
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import signal
from urllib.parse import urlsplit
import os
import sys
import time
from pathlib import Path

import requests

BASE = "https://api.treblo.com/v1"


def build_music_prompt(vibe: str) -> str:
    """Frame the caller's vibe as a real, composed instrumental piece.

    Treblo returns sound-design/SFX-like output when the prompt reads as
    texture ("bed", "beat", "sound design") instead of music. Wrapping the vibe
    in an explicit "composed instrumental song" frame — and banning SFX/risers/
    vocals — reliably yields an actual musical track. The caller's vibe should
    still name a genre, instruments, tempo and mood (see the skill's Phase-3
    guidance); this frame only guarantees it renders AS music.
    """
    vibe = vibe.strip().rstrip(".")
    return (
        "Instrumental music track with a full musical arrangement — a clear "
        "melody, chords/harmony and a steady rhythm section that develops over "
        f"time. Style and mood: {vibe}. It must sound like a composed song, "
        "NOT sound design: no isolated sound effects, no risers/whooshes/impacts, "
        "no ambient drones, and no vocals."
    )


def load_api_key() -> str:
    value = os.environ.get("TREBLO_API_KEY", "").strip()
    if value:
        return value
    # Only trusted skill locations, never a media project's .env.
    candidates = [Path(__file__).resolve().parent.parent / ".env",
                  Path.home() / ".agents/skills/edvid/.env"]
    for candidate in candidates:
        if candidate.is_file():
            for line in candidate.read_text().splitlines():
                if line.strip().startswith("TREBLO_API_KEY="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return value
    raise RuntimeError("Configure TREBLO_API_KEY no ambiente ou no .env da skill compartilhada.")


def validate_request(prompt: str, length_min: int | None, length_max: int | None) -> None:
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000:
        raise ValueError("Descreva a trilha em até 2000 caracteres.")
    if length_min is None and length_max is None:
        return
    if (type(length_min) is not int or type(length_max) is not int or
            length_min % 30 or length_max % 30 or
            not 0 <= length_min < length_max <= 300):
        raise ValueError("Use durações múltiplas de 30: mínimo de 0 a 270, máximo de 30 a 300, máximo maior que mínimo.")


def _manifest(path: Path | None, data: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def _response(response, operation: str):
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"Treblo: {operation} falhou (HTTP {response.status_code}). Consulte sua conta; não repita uma geração de resultado incerto.")
    try:
        return response.json()
    except ValueError:
        raise RuntimeError(f"Treblo: resposta inválida ao {operation}.") from None


def check_connection(api_key: str) -> dict:
    """Read-only credential validation; never creates a generation."""
    try:
        result = _response(requests.get(f"{BASE}/credits/balance",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=20), "consultar saldo")
    except requests.RequestException:
        raise RuntimeError("Treblo indisponível ao consultar saldo. Nenhuma geração foi solicitada.") from None
    if not isinstance(result, dict):
        raise RuntimeError("Treblo retornou saldo inválido.")
    return {key: result.get(key) for key in ("num_credits", "num_credits_payg")}


def generate(prompt: str, out: Path, api_key: str,
             length_min: int | None, length_max: int | None,
             bit_rate: int = 192, timeout_s: int = 600, raw: bool = False,
             manifest: Path | None = None, resume: str | None = None) -> None:
    validate_request(prompt, length_min, length_max)
    if out.exists():
        raise ValueError("O arquivo de destino já existe; escolha outro nome para preservá-lo.")
    if bit_rate not in (128, 192, 256, 320):
        raise ValueError("Bitrate inválido.")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    final_prompt = prompt if raw else build_music_prompt(prompt)
    payload = {"prompt": final_prompt, "instrumental": True,
               "output_format": "mp3", "output_bit_rate": bit_rate}
    if length_min is not None:
        payload["length_range"] = [length_min, length_max]
    state = {"provider": "treblo", "status": "submitting", "createdAt": time.time()}
    if manifest and manifest.exists() and not resume:
        raise ValueError("Existe uma solicitação registrada. Consulte seu task_id antes de gerar novamente.")
    task_id = resume
    partial = out.with_suffix(out.suffix + ".part")
    owns_partial = False
    try:
        if not task_id:
            _manifest(manifest, state)
            # Never retry this POST automatically: outcome may be billable even on timeout.
            response = _response(requests.post(f"{BASE}/generations/v3", json=payload,
                                               headers=headers, timeout=60), "solicitar geração")
            task_id = response.get("task_id") if isinstance(response, dict) else None
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
            raise RuntimeError("Treblo não retornou um identificador válido. Verifique a conta antes de tentar novamente.")
        state.update(task_id=task_id, status="submitted")
        _manifest(manifest, state)
        print(f"Treblo: tarefa {task_id} registrada; aguardando resultado.", flush=True)
        started = time.monotonic()
        while True:
            result = _response(requests.get(f"{BASE}/generations/status/{task_id}", headers=headers, timeout=30), "consultar geração")
            status = result if isinstance(result, str) else result.get("status") if isinstance(result, dict) else None
            if not isinstance(status, str):
                raise RuntimeError("Treblo retornou estado inválido.")
            state["status"] = status
            _manifest(manifest, state)
            if status == "SUCCESS":
                break
            if status == "FAILURE":
                raise RuntimeError("A geração falhou na Treblo. Consulte o estado antes de tentar outra vez.")
            if time.monotonic() - started > timeout_s:
                raise RuntimeError("Tempo local esgotado. A tarefa remota pode continuar; consulte o task_id registrado.")
            time.sleep(5)
        generation = _response(requests.get(f"{BASE}/generations/{task_id}", headers=headers, timeout=30), "obter resultado")
        paths = generation.get("song_paths") if isinstance(generation, dict) else None
        if not isinstance(paths, list) or not paths or not isinstance(paths[0], str):
            raise RuntimeError("Treblo não disponibilizou áudio para essa tarefa.")
        url = urlsplit(paths[0])
        if url.scheme != "https" or not url.hostname or not (url.hostname == "treblo.com" or url.hostname.endswith(".treblo.com")) or url.username or url.password:
            raise RuntimeError("Domínio de download não reconhecido; confira o resultado na Treblo.")
        out.parent.mkdir(parents=True, exist_ok=True)
        # No Authorization header is forwarded to the audio CDN.
        with requests.get(paths[0], stream=True, allow_redirects=False, timeout=180) as audio:
            if audio.status_code != 200:
                raise RuntimeError(f"Não foi possível baixar o áudio (HTTP {audio.status_code}).")
            size = 0
            with partial.open("xb") as handle:
                owns_partial = True
                for chunk in audio.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise RuntimeError("Áudio excedeu o limite local de 100 MB.")
                    handle.write(chunk)
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(partial)],
                               capture_output=True, text=True, timeout=30)
        if probe.returncode != 0 or "audio" not in probe.stdout:
            raise RuntimeError("O resultado baixado não contém áudio legível.")
        # Exclusive destination creation avoids clobbering a file created while waiting.
        os.link(partial, out)
        partial.unlink()
        state.update(status="downloaded", output=str(out), finishedAt=time.time())
        _manifest(manifest, state)
        print(f"Trilha salva: {out}", flush=True)
    except requests.RequestException:
        state["localError"] = "Falha de rede; a tarefa pode continuar na Treblo. Não reenviar automaticamente."
        _manifest(manifest, state)
        raise RuntimeError(state["localError"]) from None
    except Exception:
        state["localError"] = "Operação local interrompida ou falhou; consulte o estado remoto pelo task_id."
        _manifest(manifest, state)
        raise
    finally:
        try:
            if owns_partial:
                partial.unlink(missing_ok=True)
        except OSError:
            state["cleanupError"] = "Arquivo parcial preservado por falha de permissão."
            _manifest(manifest, state)


def main() -> None:
    ap = argparse.ArgumentParser(description="Treblo instrumental soundtrack")
    ap.add_argument("prompt", help="MUSICAL vibe for the video's context: name a "
                    "genre + instruments + tempo/BPM + mood (e.g. 'upbeat modern "
                    "electronic, catchy synth melody, warm bass, light drums, ~110 "
                    "BPM, bright and motivational'). Avoid SFX-y words like 'bed', "
                    "bare 'beat', or 'sound design'. It is auto-framed as a composed "
                    "instrumental song unless --raw is passed.")
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--length-min", type=int, default=None, help="min seconds (multiple of 30)")
    ap.add_argument("--length-max", type=int, default=None, help="max seconds (multiple of 30)")
    ap.add_argument("--bit-rate", type=int, default=192)
    ap.add_argument("--raw", action="store_true", help="send the prompt verbatim "
                    "(skip the composed-music framing)")
    ap.add_argument("--manifest", type=Path, help="registro local da tarefa remota para recuperação")
    ap.add_argument("--resume", help="consultar tarefa existente, sem solicitar outra geração")
    args = ap.parse_args()
    def interrupted(_signum, _frame):
        raise RuntimeError("Espera local cancelada; a tarefa pode continuar na Treblo.")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        generate(args.prompt, args.output.resolve(), load_api_key(),
                 args.length_min, args.length_max, args.bit_rate, raw=args.raw,
                 manifest=args.manifest, resume=args.resume)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
