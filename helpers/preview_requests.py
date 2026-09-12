"""Original-media catalogue and durable requests shared by both host agents."""
import hashlib
import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from project_health import write_json

EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm'}
AUTOMATIC_ACTIVE = {'queued', 'transcribing', 'proposing', 'approving', 'rendering'}


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


def _records(root, limit=None):
    folder = directory(root)
    result = []
    files = sorted(folder.glob('*.json'))
    if limit is not None:
        files = files[-limit:]
    for file in files:
        if file.is_symlink():
            continue
        try:
            data = json.loads(file.read_text())
            if isinstance(data, dict):
                result.append(data)
        except (OSError, ValueError):
            continue
    return result


def requests(root):
    return _records(root, 100)


def all_requests(root):
    return _records(root)


@contextmanager
def request_lock(root):
    folder = directory(root)
    folder.mkdir(exist_ok=True)
    path = folder / '.requests.lock'
    if path.is_symlink():
        raise ValueError('Lock de pedidos inválido')
    with path.open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _record_path(root, request_id):
    if not isinstance(request_id, str) or not re.fullmatch(r'\d+-[0-9a-f]{8}', request_id):
        raise ValueError('Identificador de pedido inválido')
    path = directory(root) / f'{request_id}.json'
    if path.is_symlink() or not path.is_file():
        raise ValueError('Pedido não encontrado')
    return path


def _get_unlocked(root, request_id):
    path = _record_path(root, request_id)
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError('Pedido inválido') from exc
    if not isinstance(record, dict) or record.get('id') != request_id:
        raise ValueError('Pedido inválido')
    return record


def get(root, request_id):
    return _get_unlocked(root, request_id)


def update(root, request_id, **fields):
    with request_lock(root):
        record = _get_unlocked(root, request_id)
        record.update(fields)
        write_json(_record_path(root, request_id), record)
        return record


def _pid_alive(value):
    try:
        pid = int(value)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def claim(root, request_id, owner):
    with request_lock(root):
        record = _get_unlocked(root, request_id)
        if (record.get('mode') != 'automatic'
                or record.get('status') not in AUTOMATIC_ACTIVE
                or len(record.get('sources') or []) != 1
                or (record.get('dispatch') or {}).get('kind') != 'single-source-automatic'):
            return None
        lease = record.get('lease')
        if (isinstance(lease, dict) and lease.get('owner') != owner
                and _pid_alive(lease.get('pid'))):
            return None
        record.update(
            status='queued',
            response='Corte automático entrou na fila.',
            updatedAt=time.time(),
            lease={'owner': owner, 'pid': os.getpid(), 'claimedAt': time.time()},
        )
        record.pop('error', None)
        write_json(_record_path(root, request_id), record)
        return record


def owns(root, request_id, owner):
    try:
        lease = get(root, request_id).get('lease')
    except ValueError:
        return False
    return isinstance(lease, dict) and lease.get('owner') == owner and lease.get('pid') == os.getpid()


def update_owned(root, request_id, owner, *, release=False, **fields):
    with request_lock(root):
        record = _get_unlocked(root, request_id)
        lease = record.get('lease')
        if not isinstance(lease, dict) or lease.get('owner') != owner or lease.get('pid') != os.getpid():
            raise ValueError('O pedido automático pertence a outro processo')
        record.update(fields)
        if release or record.get('status') in {'completed', 'failed', 'awaiting_agent'}:
            record.pop('lease', None)
        write_json(_record_path(root, request_id), record)
        return record


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
    idempotency_key = body.get('idempotencyKey') or uuid.uuid4().hex
    if (not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128
            or not re.fullmatch(r'[A-Za-z0-9._:-]+', idempotency_key)):
        raise ValueError('Chave de repetição inválida')
    key = f'{time.time_ns()}-{uuid.uuid4().hex[:8]}'
    automatic = mode == 'automatic' and len(ids) == 1
    fingerprint = hashlib.sha256(json.dumps({
        'mode': mode, 'text': text.strip(), 'sources': ids,
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    record = {'id': key, 'createdAt': time.strftime('%Y-%m-%d %H:%M:%S'),
              'status': 'queued' if automatic else 'pending', 'mode': mode, 'text': text.strip(),
              'idempotencyKey': idempotency_key,
              'requestFingerprint': fingerprint,
              'sources': [catalog[x] for x in ids]}
    if automatic:
        record.update(response='Corte automático entrou na fila.',
                      dispatch={'kind': 'single-source-automatic', 'state': 'requested'})
    folder = directory(root)
    folder.mkdir(exist_ok=True)
    with request_lock(root):
        existing = next((item for item in all_requests(root)
                         if item.get('idempotencyKey') == idempotency_key), None)
        if existing:
            if existing.get('requestFingerprint') != fingerprint:
                raise ValueError('A chave de repetição já pertence a outra solicitação')
            return existing
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


SPLIT_LAYOUTS = {'fullscreen', 'split-top', 'split-bottom', 'behind'}


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
        # 'split' é apelido histórico de 'split-top': payload antigo continua
        # válido e sobe para o nome novo aqui, para o agente nunca receber os
        # dois nomes para a mesma coisa.
        if media.get('layout') == 'split':
            media['layout'] = 'split-top'
        if media.get('layout') not in SPLIT_LAYOUTS:
            raise ValueError('Enquadramento inválido')
        if str(media.get('layout')).startswith('split'):
            # "eu na frente da faixa" (matte da pessoa) é o padrão deste usuário
            media['front'] = bool(media.get('front', True))
        else:
            media.pop('front', None)
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
