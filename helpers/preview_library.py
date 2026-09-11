"""Create isolated preview projects and copy selected uploads without moving originals."""
import hashlib
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
