"""Tempo e blocos de legenda.

Tudo aqui guarda defeito SILENCIOSO. O Remotion desenha o que receber: bloco
vazio pisca sem texto, sobreposição põe duas legendas na tela, tempo invertido
some, e legenda depois do fim da fala aparece sobre o encerramento. Nenhum
desses levanta exceção em lugar nenhum do fluxo — aparecem no vídeo entregue.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import caption_edit
from caption_edit import CaptionError


def cue(text, a, b):
    return {'text': text, 'startMs': a, 'endMs': b, 'timestampMs': (a + b) // 2,
            'confidence': None}


BASE = [cue('Você', 100, 400), cue('começou', 420, 900), cue('errado', 950, 1400)]


class ValidateTests(unittest.TestCase):
    def test_a_clean_list_has_no_complaints(self):
        self.assertEqual(caption_edit.validate(BASE), [])

    def test_every_silent_defect_is_named(self):
        self.assertIn('vazio', ' '.join(caption_edit.validate([cue('', 100, 400)])))
        self.assertIn('não passa do início', ' '.join(caption_edit.validate([cue('x', 400, 100)])))
        sobrepostas = [cue('a', 100, 500), cue('b', 300, 700)]
        self.assertIn('antes de', ' '.join(caption_edit.validate(sobrepostas)))

    def test_a_short_block_is_a_warning_not_a_blocker(self):
        # veio do dado real: artigos de 20ms existem nas legendas já entregues
        # do canal. É cosmético — o realce pula a palavra — e reprovar por isso
        # tornaria o gate inutilizável.
        achados = caption_edit.inspect([cue('a', 100, 120)])
        self.assertEqual(achados['errors'], [])
        self.assertIn('karaokê pula', ' '.join(achados['warnings']))

    def test_an_empty_caption_list_is_an_error(self):
        self.assertIn('vazia', ' '.join(caption_edit.validate([])))

    def test_caption_past_the_video_and_over_the_outro_are_both_caught(self):
        self.assertIn('passa do fim', ' '.join(caption_edit.validate(BASE, duration_ms=1000)))
        self.assertIn('encerramento', ' '.join(caption_edit.validate(BASE, outro_start_ms=1000)))

    def test_timestamp_outside_its_own_block_is_caught(self):
        ruim = [{'text': 'x', 'startMs': 100, 'endMs': 400, 'timestampMs': 900}]
        self.assertIn('timestampMs fora', ' '.join(caption_edit.validate(ruim)))


class RetimeTests(unittest.TestCase):
    def test_moving_an_edge_keeps_the_neighbours_alone(self):
        out = caption_edit.retime(BASE, 1, end_ms=920)
        self.assertEqual(out[1]['endMs'], 920)
        self.assertEqual(out[0], caption_edit._norm(BASE[0]))
        self.assertEqual(out[2], caption_edit._norm(BASE[2]))

    def test_an_edit_that_would_overlap_is_refused_with_the_reason(self):
        with self.assertRaises(CaptionError) as cm:
            caption_edit.retime(BASE, 0, end_ms=600)   # invade «começou»
        self.assertIn('antes de', str(cm.exception))

    def test_an_edit_that_would_invert_the_block_is_refused(self):
        with self.assertRaises(CaptionError):
            caption_edit.retime(BASE, 1, start_ms=1000)

    def test_an_edit_past_the_outro_is_refused(self):
        with self.assertRaises(CaptionError):
            caption_edit.retime(BASE, 2, end_ms=2000, outro_start_ms=1500)


class SplitMergeTests(unittest.TestCase):
    def test_split_gives_each_half_its_own_time(self):
        out = caption_edit.split(BASE, 0, 'Vo', 'cê', at_ms=250)
        self.assertEqual([c['text'] for c in out[:2]], ['Vo', 'cê'])
        self.assertEqual((out[0]['startMs'], out[0]['endMs']), (100, 250))
        self.assertEqual((out[1]['startMs'], out[1]['endMs']), (250, 400))
        self.assertEqual(caption_edit.validate(out), [])

    def test_split_without_a_point_uses_the_middle(self):
        out = caption_edit.split(BASE, 0, 'Vo', 'cê')
        self.assertEqual(out[0]['endMs'], 250)

    def test_split_refuses_an_empty_side_or_a_point_outside(self):
        with self.assertRaises(CaptionError):
            caption_edit.split(BASE, 0, 'Você', '')
        with self.assertRaises(CaptionError) as cm:
            caption_edit.split(BASE, 0, 'a', 'b', at_ms=900)
        self.assertIn('dentro do bloco', str(cm.exception))

    def test_merge_spans_both_blocks_and_joins_the_text(self):
        out = caption_edit.merge(BASE, 0)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['text'], 'Vocêcomeçou')
        self.assertEqual((out[0]['startMs'], out[0]['endMs']), (100, 900))
        self.assertEqual(caption_edit.validate(out), [])

    def test_merge_accepts_the_corrected_text(self):
        out = caption_edit.merge(BASE, 0, text='Você começou')
        self.assertEqual(out[0]['text'], 'Você começou')

    def test_merge_refuses_on_the_last_block(self):
        with self.assertRaises(CaptionError):
            caption_edit.merge(BASE, 2)


class ShiftTests(unittest.TestCase):
    def test_shifting_from_an_index_leaves_the_earlier_blocks(self):
        out = caption_edit.shift(BASE, 200, from_index=1)
        self.assertEqual(out[0]['startMs'], 100)
        self.assertEqual(out[1]['startMs'], 620)
        self.assertEqual(out[2]['startMs'], 1150)

    def test_a_negative_shift_that_would_go_before_zero_is_refused(self):
        with self.assertRaises(CaptionError):
            caption_edit.shift(BASE, -500)

    def test_a_negative_shift_that_would_overlap_is_refused(self):
        with self.assertRaises(CaptionError):
            caption_edit.shift(BASE, -400, from_index=2)


class DropAfterTests(unittest.TestCase):
    def test_blocks_starting_after_the_limit_are_dropped(self):
        out = caption_edit.drop_after(BASE, 940)
        self.assertEqual([c['text'] for c in out], ['Você', 'começou'])

    def test_a_block_straddling_the_limit_is_trimmed_not_dropped(self):
        out = caption_edit.drop_after(BASE, 700)
        self.assertEqual([c['text'] for c in out], ['Você', 'começou'])
        self.assertEqual(out[1]['endMs'], 700)
        self.assertLessEqual(out[1]['timestampMs'], 700)

    def test_a_sliver_left_by_trimming_is_dropped_instead_of_blinking(self):
        out = caption_edit.drop_after(BASE, 430)
        self.assertEqual([c['text'] for c in out], ['Você'])


class RealFormatTests(unittest.TestCase):
    def test_it_reads_the_remotion_word_list_shape(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'captions.json'
            path.write_text(json.dumps(BASE))
            self.assertEqual(len(caption_edit.load(path)), 3)
            path.write_text(json.dumps({'captions': BASE}))
            self.assertEqual(len(caption_edit.load(path)), 3)
            path.write_text(json.dumps({'nada': 1}))
            with self.assertRaises(CaptionError):
                caption_edit.load(path)


if __name__ == '__main__':
    unittest.main()
