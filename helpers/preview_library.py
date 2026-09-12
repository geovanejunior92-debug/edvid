"""Create isolated preview projects and copy selected uploads without moving originals."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from project_health import write_json

MAX_UPLOAD = 8 * 1024**3
EXTENSIONS = {'.mov', '.mp4', '.m4v', '.webm'}


def create(library, name):
    library = Path(library).resolve()
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError('Dê um nome ao projeto (até 100 caracteres)')
    slug = re.sub(r'[^\w-]+', '-', name.strip(), flags=re.UNICODE).strip('-_')[:60] or 'video'
    project = library / f'{slug}-{uuid.uuid4().hex[:8]}'
    project.mkdir()
    root = project / 'edit'; root.mkdir()
    write_json(root / 'state.json', {'project': name.strip(), 'phase': 1, 'message': 'Selecione as fontes e peça o primeiro corte.'})
    (root / '.preview-import-project').write_text('1')
    key = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return key, root


def receive(root, filename, stream, length):
    root = Path(root).resolve()
    if root.name != 'edit' or not (root / '.preview-import-project').is_file():
        raise ValueError('Importação permitida apenas em projetos criados pela biblioteca')
    if not isinstance(filename, str) or not filename or Path(filename).name != filename or '\\' in filename or len(filename) > 240 or '\x00' in filename:
        raise ValueError('Nome de arquivo inválido')
    if Path(filename).suffix.lower() not in EXTENSIONS:
        raise ValueError('Selecione um vídeo MOV, MP4, M4V ou WEBM')
    if not isinstance(length, int) or not 0 < length <= MAX_UPLOAD:
        raise ValueError('O vídeo precisa ter entre 1 byte e 8 GB')
    target = root.parent / filename
    # Every import gets a unique name: even concurrent uploads cannot overwrite.
    if target.exists(): target = target.with_name(f'{target.stem}-{uuid.uuid4().hex[:8]}{target.suffix}')
    temp = root.parent / f'.upload-{uuid.uuid4().hex}.part'
    try:
        with temp.open('xb') as out:
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk: raise ValueError('Envio interrompido; selecione o vídeo e tente novamente')
                out.write(chunk); remaining -= len(chunk)
        # link creates target exclusively rather than replacing an existing file.
        os.link(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target.name


# ---- library registry -------------------------------------------------------
# Pin, archive and rename are LIBRARY state, not project state: they describe how
# the shelf is organised, not what the edit is. They live in one small file next
# to the projects so a project folder stays portable — copy it elsewhere and it
# carries its edit, not someone's shelf preferences.
#
# Archiving NEVER touches files. It hides the card and nothing else; the acceptance
# test for this is "remove only the library entry without deleting files". A
# rename is the one flag that does reach the project, because the name shown on
# the card IS state.json's `project` field — storing a second name here would give
# one project two names that drift apart.
REGISTRY = '.edvid-library.json'


def registry_path(library) -> Path:
    return Path(library).resolve() / REGISTRY


def load_registry(library) -> dict:
    """Never raises: a corrupt or missing registry means "no preferences yet"."""
    try:
        data = json.loads(registry_path(library).read_text())
    except (OSError, ValueError):
        return {}
    entries = data.get('entries') if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    clean = {}
    for key, value in entries.items():
        if isinstance(key, str) and isinstance(value, dict):
            clean[key] = {'pinned': bool(value.get('pinned')), 'archived': bool(value.get('archived'))}
    return clean


def set_flags(library, key, *, pinned=None, archived=None) -> dict:
    if not isinstance(key, str) or not key:
        raise ValueError('Projeto inválido')
    entries = load_registry(library)
    entry = entries.get(key, {'pinned': False, 'archived': False})
    if pinned is not None:
        entry['pinned'] = bool(pinned)
    if archived is not None:
        entry['archived'] = bool(archived)
    entries[key] = entry
    # A default entry carries no information — drop it so the file stays small
    # and a project that was never touched never appears here.
    entries = {k: v for k, v in entries.items() if v['pinned'] or v['archived']}
    write_json(registry_path(library), {'version': 1, 'entries': entries})
    return entry


def rename(root, name) -> str:
    """Rename the project by rewriting state.json's own `project` field."""
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError('Dê um nome ao projeto (até 100 caracteres)')
    root = Path(root).resolve()
    state_path = root / 'state.json'
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        raise ValueError('Este projeto não tem estado legível para renomear')
    if not isinstance(state, dict):
        raise ValueError('Este projeto não tem estado legível para renomear')
    state['project'] = name.strip()
    write_json(state_path, state)
    return state['project']
