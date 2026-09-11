"""Original-media catalogue and durable requests shared by both host agents."""
import hashlib
import json
import time
import uuid
from pathlib import Path
from project_health import write_json

EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm'}


def sources(root):
    root = Path(root).resolve()
    base = root.parent if root.name == 'edit' else root
    result = []
    for file in sorted(base.iterdir(), key=lambda p: p.name.casefold()):
        # Explicit project-level links are usable; never follow directories recursively.
        if file.suffix.lower() in EXTENSIONS and file.is_file():
            stat = file.stat()
            key = hashlib.sha256(f'{file.name}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:24]
            result.append({'id': key, 'name': file.name, 'size': stat.st_size, 'path': str(file)})
        if len(result) >= 200:
            break
    return result


def directory(root):
    path = Path(root) / 'agent-requests'
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Diretório de pedidos inválido')
    return path


def requests(root):
    folder = directory(root)
    result = []
    for file in sorted(folder.glob('*.json'))[-100:]:
        if file.is_symlink():
            continue
        try:
            data = json.loads(file.read_text())
            if isinstance(data, dict):
                result.append(data)
        except (OSError, ValueError):
            continue
    return result


def submit(root, body):
    text = body.get('text', '')
    mode = body.get('mode', 'adjustment')
    ids = body.get('sources', [])
    if not isinstance(text, str) or not text.strip() or len(text) > 30000:
        raise ValueError('Escreva um pedido ou roteiro de até 30 mil caracteres')
    if mode not in {'script', 'automatic', 'adjustment'}:
        raise ValueError('Tipo de pedido inválido')
    if not isinstance(ids, list) or len(ids) > 200 or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('Seleção de fontes inválida')
    catalog = {x['id']: x for x in sources(root)}
    if any(x not in catalog for x in ids):
        raise ValueError('Uma fonte mudou ou não está mais disponível. Atualize a lista.')
    if mode != 'adjustment' and not ids:
        raise ValueError('Selecione pelo menos um vídeo para o corte')
    key = f'{time.time_ns()}-{uuid.uuid4().hex[:8]}'
    record = {'id': key, 'createdAt': time.strftime('%Y-%m-%d %H:%M:%S'),
              'status': 'pending', 'mode': mode, 'text': text.strip(),
              'sources': [catalog[x] for x in ids]}
    folder = directory(root)
    folder.mkdir(exist_ok=True)
    write_json(folder / f'{key}.json', record)
    return record
