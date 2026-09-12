#!/usr/bin/env python3
"""Apply the preview's caption text corrections to word-level transcripts.

The preview records a correction as a RANGE plus the text it should read:
`{renderedStart, renderedEnd, from, to}`. It never records timings, because the
user is fixing what was HEARD, not when it was said — "Munjaro" -> "Mounjaro"
must not move the karaoke by a millisecond.

So the rule here is deliberately asymmetric:

  same word count  -> keep every original timing, swap the text only.
  different count  -> redistribute the ORIGINAL span across the new words,
                      weighted by character length.

The first case is the common one (a misheard drug name, an accent, a plural)
and it is the one where timing accuracy matters most, so it is exact. The
second case only happens when the correction changes the shape of the phrase,
and then no honest timing exists — the words were never spoken separately.
Redistribution is a stated approximation, reported by the CLI so nobody
mistakes it for measurement.

Deleting text is NOT this helper's job: an empty correction is refused, because
removing spoken words is a CUT (fillers.py --from-preview), which has to move
the EDL and re-render, not just rewrite a caption.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

TOL = 1e-3


def _weights(words: list[str]) -> list[float]:
    # +1 per word so a one-letter word still gets airtime.
    raw = [len(w) + 1 for w in words]
    total = sum(raw)
    return [r / total for r in raw]


def _time_schema(word: dict) -> tuple[str, str, float]:
    if "start" in word and "end" in word:
        return "start", "end", 1.0
    if "startMs" in word and "endMs" in word:
        return "startMs", "endMs", 1000.0
    raise ValueError("Palavra sem start/end ou startMs/endMs")


def _seconds(word: dict) -> tuple[float, float]:
    start_key, end_key, scale = _time_schema(word)
    return float(word[start_key]) / scale, float(word[end_key]) / scale


def apply_fix(words: list[dict], start: float, end: float, text: str) -> tuple[list[dict], str]:
    """Return (new word list, one-line report). Raises ValueError when unusable."""
    new_words = str(text or '').split()
    if not new_words:
        raise ValueError('Correção vazia: apagar fala é corte (fillers.py), não correção de legenda')
    hit = []
    for i, word in enumerate(words):
        word_start, word_end = _seconds(word)
        if word_start >= start - TOL and word_end <= end + TOL:
            hit.append(i)
    if not hit:
        raise ValueError(f'Nenhuma palavra entre {start:.3f}s e {end:.3f}s')
    lo, hi = hit[0], hit[-1]
    start_key, end_key, scale = _time_schema(words[lo])
    if any(_time_schema(words[i]) != (start_key, end_key, scale) for i in hit):
        raise ValueError("O intervalo mistura esquemas de tempo incompatíveis")
    span_start, span_end = float(words[lo][start_key]), float(words[hi][end_key])
    old_text = ' '.join(words[i]['text'] for i in hit)

    if len(new_words) == len(hit):
        replaced = [{**words[i], 'text': new_words[n]} for n, i in enumerate(hit)]
        note = 'tempos preservados'
    else:
        span = max(span_end - span_start, 1e-6)
        replaced, cursor = [], span_start
        for w, share in zip(new_words, _weights(new_words)):
            nxt = cursor + span * share
            begin_value = round(cursor) if scale == 1000.0 else round(cursor, 3)
            end_value = round(nxt) if scale == 1000.0 else round(nxt, 3)
            item = {**words[lo], 'text': w, start_key: begin_value, end_key: end_value}
            if scale == 1000.0:
                item['timestampMs'] = round((begin_value + end_value) / 2)
            replaced.append(item)
            cursor = nxt
        replaced[-1][end_key] = round(span_end) if scale == 1000.0 else span_end
        if scale == 1000.0:
            replaced[-1]['timestampMs'] = round((replaced[-1][start_key] + replaced[-1][end_key]) / 2)
        note = f'{len(hit)} palavra(s) -> {len(new_words)}, tempos REDISTRIBUÍDOS (aproximação)'
    return words[:lo] + replaced + words[hi + 1:], f'«{old_text}» -> «{" ".join(new_words)}» ({note})'


def apply_fixes(words: list[dict], fixes: list[dict]) -> tuple[list[dict], list[str]]:
    """Latest range first, so an earlier fix never shifts a later one's indices."""
    out, report = list(words), []
    for fix in sorted(fixes, key=lambda f: -float(f.get('renderedStart', f.get('start', 0)))):
        start = float(fix.get('renderedStart', fix.get('start', 0)))
        end = float(fix.get('renderedEnd', fix.get('end', 0)))
        out, line = apply_fix(out, start, end, fix.get('to', ''))
        report.append(line)
    return out, list(reversed(report))


def _load_words(path: Path) -> tuple[dict, list[dict], str]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and isinstance(data.get('words'), list):
        return data, data['words'], 'words'
    if isinstance(data, list):
        return {'__list__': data}, data, '__list__'
    if isinstance(data, dict) and isinstance(data.get('captions'), list):
        return data, data['captions'], 'captions'
    raise ValueError(f'{path.name}: não encontrei uma lista de palavras')


def main() -> None:
    ap = argparse.ArgumentParser(description='Aplica textFixes do preview a um transcript/captions')
    ap.add_argument('edit_dir', type=Path)
    ap.add_argument('--targets', nargs='*', default=['transcripts/cut.json', 'remotion/public/captions.json'])
    ap.add_argument('--apply', action='store_true', help='sem isto, só mostra o que faria')
    args = ap.parse_args()

    edits = args.edit_dir / 'preview_edits.json'
    fixes = json.loads(edits.read_text()).get('textFixes', []) if edits.is_file() else []
    if not fixes:
        print('nenhum textFixes em preview_edits.json')
        return

    failed = False
    for rel in args.targets:
        path = args.edit_dir / rel
        if not path.is_file():
            print(f'· {rel}: ausente, pulando')
            continue
        try:
            container, words, key = _load_words(path)
            new_words, report = apply_fixes(words, fixes)
        except ValueError as e:
            print(f'✗ {rel}: {e}')
            failed = True
            continue
        for line in report:
            print(f'· {rel}: {line}')
        if args.apply:
            if key == '__list__':
                path.write_text(json.dumps(new_words, ensure_ascii=False, indent=2))
            else:
                container[key] = new_words
                path.write_text(json.dumps(container, ensure_ascii=False, indent=2))
    if not args.apply:
        print('\n(sem --apply: nada foi gravado)')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
