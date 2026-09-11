"""Apply preview gain offsets to separate audio stems before final QC/remux.
Never accepts a mixed video as three independent tracks.
"""
import argparse
import json
import math
import subprocess
from pathlib import Path
from project_health import write_json


def validate(style):
    text = style.get('headlineText', '')
    if not isinstance(text, str) or len(text) > 180: raise ValueError('Título inválido (máximo 180 caracteres)')
    mix = style.get('audioMix', {})
    if not isinstance(mix, dict): raise ValueError('Mixagem inválida')
    gains = {}
    for key in ('voice', 'music', 'sfx'):
        value = mix.get(key + 'Db', 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not (-24 if key == 'voice' else -48) <= value <= 12:
            raise ValueError('Ganho fora da faixa: ' + key)
        gains[key] = value
    return text.strip(), gains


def apply_title(style, data):
    import copy
    text, _ = validate(style)
    result = copy.deepcopy(data)
    if text:
        result.setdefault('hook', {})['lines'] = text.splitlines()
    return result


def mix_command(gains, stems, output):
    command = ['ffmpeg', '-v', 'error', '-n']
    for _, path in stems: command += ['-i', str(path)]
    filters = [f'[{i}:a]volume={gains[key]}dB[a{i}]' for i, (key, _) in enumerate(stems)]
    labels = ''.join(f'[a{i}]' for i in range(len(stems)))
    filters.append(f'{labels}amix=inputs={len(stems)}:duration=first:normalize=0,alimiter=limit=0.891251:level=false:latency=true[out]')
    return command + ['-filter_complex', ';'.join(filters), '-map', '[out]', '-ar', '48000', '-c:a', 'pcm_s24le', str(output)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--style', required=True, type=Path)
    parser.add_argument('--edit-data', type=Path)
    parser.add_argument('--voice', type=Path)
    parser.add_argument('--music', type=Path)
    parser.add_argument('--sfx', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--apply', action='store_true', help='Write title and/or new WAV; otherwise show plan')
    args = parser.parse_args()
    style = json.loads(args.style.read_text()); text, gains = validate(style)
    stems = [(key, getattr(args, key)) for key in ('voice','music','sfx') if getattr(args,key)]
    if stems and (not args.voice or not args.output): raise ValueError('Mixagem exige --voice e --output')
    if args.output and (args.output.exists() or args.output.suffix.lower() != '.wav'): raise ValueError('Use um novo arquivo .wav')
    for _, path in stems:
        if not path.is_file(): raise ValueError('Stem de áudio inexistente')
    updated = apply_title(style, json.loads(args.edit_data.read_text())) if args.edit_data else None
    command = mix_command(gains, stems, args.output) if stems else None
    if args.apply:
        # Render before changing title so a failed mix cannot update the document.
        if command: subprocess.run(command, check=True)
        if updated is not None: write_json(args.edit_data, updated)
    print(json.dumps({'applied':args.apply, 'title':text, 'gainsDb':gains, 'command':command},ensure_ascii=False))

if __name__ == '__main__': main()
