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

ASSET_EXTENSIONS = EXTENSIONS | {'.png', '.jpg', '.jpeg', '.webp'}

def insert_assets(root):
    root = Path(root).resolve()
    base = root.parent if root.name == 'edit' else root
    items = []
    for folder in (base, base / 'assets', root / 'assets'):
        if not folder.is_dir() or not folder.resolve().is_relative_to(base):
            continue
        for file in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
            if file.suffix.lower() in ASSET_EXTENSIONS and file.is_file() and file.resolve().is_relative_to(base):
                items.append(str(file.relative_to(base)))
            if len(items) >= 500: break
        if len(items) >= 500: break
    return sorted(set(items))


def validate_media_notes(root, notes):
    import math
    if not isinstance(notes, list) or len(notes) > 500:
        raise ValueError('Lista de marcações inválida')
    base = Path(root).resolve()
    if base.name == 'edit': base = base.parent
    for note in notes:
        if not isinstance(note, dict): raise ValueError('Marcação inválida')
        media = note.get('media')
        if media is None: continue  # legacy text annotations are unchanged
        if not isinstance(media, dict) or media.get('kind') not in {'image', 'video', 'file'}:
            raise ValueError('Tipo de mídia inválido')
        if media.get('layout') not in {'fullscreen', 'split'}:
            raise ValueError('Enquadramento inválido')
        for start, end in [('start', 'end'), ('renderedStart', 'renderedEnd')]:
            a, b = note.get(start), note.get(end)
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (a, b)) or a < 0 or b <= a:
                raise ValueError('Intervalo de mídia inválido')
        if not isinstance(note.get('text'), str) or not note['text'].strip():
            raise ValueError('Descreva a cena desejada')
        if media['kind'] == 'file':
            raw = media.get('file')
            if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
                raise ValueError('Use um caminho relativo ao projeto')
            file = (base / raw).resolve()
            if not file.is_relative_to(base) or not file.is_file() or file.suffix.lower() not in ASSET_EXTENSIONS:
                raise ValueError('Arquivo de mídia não encontrado dentro do projeto')
        if media['kind'] != 'file' and media.get('provider', 'agent') not in {'agent', 'shutterstock'}:
            raise ValueError('Provedor de geração inválido')
        media['status'] = 'requested'  # the UI cannot claim generation completed
