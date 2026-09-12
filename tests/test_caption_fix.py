"""Caption text corrections — the timing contract is what these guard.

A one-for-one correction (the common case: a misheard drug name) must not move
the karaoke by a millisecond. A correction that changes the word count has no
honest timing, so it is redistributed and SAID to be an approximation.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import caption_fix


def words(*triples):
    return [{'text': t, 'start': s, 'end': e} for t, s, e in triples]


class ApplyFixTests(unittest.TestCase):
    def setUp(self):
        self.w = words(('o', 0.0, 0.2), ('Munjaro', 0.2, 0.9), ('ajuda', 0.9, 1.4), ('muito', 1.4, 1.9))

    def test_same_word_count_keeps_every_timing(self):
        out, line = caption_fix.apply_fix(self.w, 0.2, 0.9, 'Mounjaro')
        self.assertEqual([x['text'] for x in out], ['o', 'Mounjaro', 'ajuda', 'muito'])
        self.assertEqual((out[1]['start'], out[1]['end']), (0.2, 0.9))
        self.assertIn('preservados', line)
        # everything outside the fix is untouched, object for object
        self.assertEqual(out[0], self.w[0])
        self.assertEqual(out[2:], self.w[2:])

    def test_more_words_redistribute_inside_the_original_span(self):
        out, line = caption_fix.apply_fix(self.w, 0.2, 0.9, 'Mounjaro semanal')
        self.assertEqual([x['text'] for x in out], ['o', 'Mounjaro', 'semanal', 'ajuda', 'muito'])
        self.assertEqual(out[1]['start'], 0.2)          # span start held
        self.assertEqual(out[2]['end'], 0.9)            # span end held
        self.assertLess(out[1]['end'], 0.9)
        self.assertEqual(out[1]['end'], out[2]['start'])  # no gap, no overlap
        self.assertIn('REDISTRIBUÍDOS', line)

    def test_fewer_words_also_hold_the_span(self):
        out, _ = caption_fix.apply_fix(self.w, 0.2, 1.4, 'Mounjaro')
        self.assertEqual([x['text'] for x in out], ['o', 'Mounjaro', 'muito'])
        self.assertEqual((out[1]['start'], out[1]['end']), (0.2, 1.4))

    def test_multi_word_span_replaced_one_for_one_keeps_each_timing(self):
        out, _ = caption_fix.apply_fix(self.w, 0.9, 1.9, 'melhora bastante')
        self.assertEqual([(x['text'], x['start'], x['end']) for x in out[2:]],
                         [('melhora', 0.9, 1.4), ('bastante', 1.4, 1.9)])

    def test_empty_correction_is_refused_as_a_cut(self):
        for empty in ('', '   ', None):
            with self.assertRaises(ValueError) as cm:
                caption_fix.apply_fix(self.w, 0.2, 0.9, empty)
            self.assertIn('corte', str(cm.exception))

    def test_range_matching_nothing_is_refused(self):
        with self.assertRaises(ValueError):
            caption_fix.apply_fix(self.w, 5.0, 6.0, 'qualquer')

    def test_partially_overlapping_word_is_not_swallowed(self):
        # 0.3 starts mid-"Munjaro": that word is not fully inside, so only
        # "ajuda" is replaced — a fix never rewrites a word it does not cover.
        out, _ = caption_fix.apply_fix(self.w, 0.3, 1.4, 'auxilia')
        self.assertEqual([x['text'] for x in out], ['o', 'Munjaro', 'auxilia', 'muito'])


class ApplyFixesTests(unittest.TestCase):
    def test_several_fixes_do_not_shift_each_other(self):
        w = words(('um', 0.0, 0.3), ('dois', 0.3, 0.6), ('tres', 0.6, 0.9), ('quatro', 0.9, 1.2))
        out, report = caption_fix.apply_fixes(w, [
            {'renderedStart': 0.0, 'renderedEnd': 0.3, 'to': 'UM'},
            {'renderedStart': 0.6, 'renderedEnd': 0.9, 'to': 'TRÊS extra'},
        ])
        self.assertEqual([x['text'] for x in out], ['UM', 'dois', 'TRÊS', 'extra', 'quatro'])
        self.assertEqual(len(report), 2)
        self.assertIn('«um»', report[0])   # reported in timeline order
        self.assertIn('«tres»', report[1])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.edit = Path(self.temp.name)
        (self.edit / 'transcripts').mkdir()
        self.target = self.edit / 'transcripts' / 'cut.json'
        self.target.write_text(json.dumps(
            {'words': [{'text': 'Munjaro', 'start': 0.2, 'end': 0.9, 'score': 0.8}]}))
        (self.edit / 'preview_edits.json').write_text(json.dumps(
            {'textFixes': [{'renderedStart': 0.2, 'renderedEnd': 0.9,
                            'from': 'Munjaro', 'to': 'Mounjaro'}]}))

    def run_cli(self, *extra):
        argv = sys.argv
        sys.argv = ['caption_fix.py', str(self.edit), '--targets', 'transcripts/cut.json', *extra]
        try:
            with self.assertRaises(SystemExit) as cm:
                caption_fix.main()
            return cm.exception.code
        finally:
            sys.argv = argv

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(json.loads(self.target.read_text())['words'][0]['text'], 'Munjaro')

    def test_apply_rewrites_and_keeps_the_other_fields(self):
        self.assertEqual(self.run_cli('--apply'), 0)
        word = json.loads(self.target.read_text())['words'][0]
        self.assertEqual(word['text'], 'Mounjaro')
        self.assertEqual(word['score'], 0.8)     # untouched sibling fields survive
        self.assertEqual((word['start'], word['end']), (0.2, 0.9))


if __name__ == '__main__':
    unittest.main()
