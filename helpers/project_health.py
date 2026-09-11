"""Project health and atomic operation reports for the local preview."""
from __future__ import annotations
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


@contextmanager
def operation(root: Path, label: str):
    report = root / '.processing' / (uuid.uuid4().hex + '.json')
    data = {'label': label, 'status': 'running', 'pid': os.getpid(), 'startedAt': time.time()}
    write_json(report, data)
    try:
        yield
    except BaseException:
        data.update(status='failed', finishedAt=time.time())
        write_json(report, data)
        raise
    else:
        data.update(status='completed', finishedAt=time.time())
        write_json(report, data)


def latest_operation(root: Path) -> dict:
    reports = []
    for p in (root / '.processing').glob('*.json'):
        try:
            d = json.loads(p.read_text())
            if d.get('status') == 'running':
                try:
                    os.kill(int(d['pid']), 0)
                except ProcessLookupError:
                    d['status'] = 'interrupted'
                except PermissionError:
                    pass
            reports.append(d)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    running = [d for d in reports if d.get('status') == 'running']
    return max(running or reports, key=lambda d: d.get('startedAt', 0), default={})


def health(root: Path, state: dict) -> dict:
    missing = []
    for field in ('video', 'finalVideo'):
        rel = state.get(field)
        if rel and not (root / rel).is_file():
            missing.append({'field': field, 'name': Path(rel).name})
    job = latest_operation(root)
    if state.get('error'):
        code, message = 'error', 'Não foi possível ler este projeto.'
    elif job.get('status') == 'running':
        code, message = 'processing', job.get('label', 'Processando') + '…'
    elif job.get('status') in ('failed', 'interrupted'):
        code, message = 'error', 'O último processamento falhou ou foi interrompido. Confira os arquivos antes de continuar.'
    elif missing and (state.get('phase', 1) > 1 or (root / '.preview_cache/thumbs/meta.json').exists() or state.get('renderedAt') or (job.get('status') == 'completed' and job.get('label') == 'Renderizando vídeo')):
        code, message = 'missing', 'Vídeo não encontrado. Localize uma cópia do corte ou da versão final.'
    elif missing or not state.get('video'):
        code, message = 'waiting', 'Este projeto ainda não tem um corte disponível.'
    else:
        code, message = 'ready', 'Corte disponível para revisão.'
    return {'code': code, 'message': message, 'missing': missing, 'operation': job}
