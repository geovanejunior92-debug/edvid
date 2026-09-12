"""Alinhamento roteiro × transcrição.

O caso de aceite que o usuário escreveu é literal: "colar um roteiro com uma
linha omitida e outra regravada; o Studio deve propor os takes corretos e
avisar a omissão". Os dois primeiros testes são exatamente isso.

O resto guarda o que faz esse tipo de código mentir: casar por acaso com uma
frase parecida, escolher a tomada sozinho, e perder a fala improvisada que não
está no roteiro.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import script_align


def words(frase, inicio=0.0, passo=0.4, source='C001'):
    """Transforma texto em palavras cronometradas, como um transcript."""
    out, t = [], inicio
    for palavra in frase.split():
        out.append({'text': palavra, 'start': round(t, 3), 'end': round(t + passo, 3)})
        t += passo
    return out, t


class AlignTests(unittest.TestCase):
    def test_a_line_recorded_twice_returns_both_takes_and_picks_none(self):
        fala, t = words('o implante hormonal nao engorda')
        pausa, t = words('deixa eu comecar de novo', t + 1)
        segunda, _ = words('o implante hormonal nao engorda', t + 1)
        r = script_align.align('O implante hormonal não engorda.',
                               {'C001': fala + pausa + segunda})
        linha = r['lines'][0]
        self.assertEqual(linha['status'], 'multiple')
        self.assertEqual(len(linha['candidates']), 2)
        self.assertEqual(r['summary']['multiple'], 1)
        # as duas tomadas são trechos diferentes do mesmo material
        a, b = linha['candidates']
        self.assertNotAlmostEqual(a['start'], b['start'], places=2)

    def test_a_line_never_recorded_is_reported_as_missing(self):
        fala, _ = words('o implante hormonal nao engorda')
        r = script_align.align('O implante hormonal não engorda.\n'
                               'A reposição precisa de acompanhamento médico.',
                               {'C001': fala})
        self.assertEqual([l['status'] for l in r['lines']], ['ok', 'missing'])
        self.assertEqual(r['summary']['missing'], 1)
        self.assertIn('não achei', r['lines'][1]['why'])

    def test_transcription_noise_does_not_break_the_match(self):
        # acento perdido, pontuação, e uma palavra trocada pelo Whisper
        fala, _ = words('o implante hormonal nao engorda mesmo')
        r = script_align.align('O implante hormonal não engorda.', {'C001': fala})
        self.assertEqual(r['lines'][0]['status'], 'ok')
        self.assertGreater(r['lines'][0]['candidates'][0]['score'], 0.7)

    def test_a_different_sentence_is_not_matched_by_accident(self):
        fala, _ = words('hoje eu quero falar sobre tireoide e cansaco')
        r = script_align.align('O implante hormonal não engorda.', {'C001': fala})
        self.assertEqual(r['lines'][0]['status'], 'missing')

    def test_speech_outside_the_script_is_surfaced(self):
        roteiro, t = words('o implante hormonal nao engorda')
        improviso, _ = words('e isso eu vejo no consultorio toda semana com paciente', t + 1)
        r = script_align.align('O implante hormonal não engorda.',
                               {'C001': roteiro + improviso})
        self.assertGreaterEqual(r['summary']['offScript'], 1)
        self.assertIn('consultorio', ' '.join(x['text'] for x in r['offScript']))

    def test_multiple_sources_keep_their_identity(self):
        a, _ = words('o implante hormonal nao engorda', source='C001')
        b, _ = words('o implante hormonal nao engorda', source='C002')
        r = script_align.align('O implante hormonal não engorda.', {'C001': a, 'C002': b})
        fontes = {c['source'] for c in r['lines'][0]['candidates']}
        self.assertEqual(fontes, {'C001', 'C002'})

    def test_a_candidate_never_splices_the_end_of_one_file_to_the_next(self):
        a, _ = words('uma frase termina com implante hormonal', source='C001')
        b, _ = words('nao engorda e outra fala continua', source='C002')
        r = script_align.align('Implante hormonal não engorda.', {'C001': a, 'C002': b})
        candidates = r['lines'][0]['candidates']
        self.assertTrue(candidates)  # aproximações parciais ainda podem ser propostas
        self.assertFalse(any('implante' in x['text'] and 'engorda' in x['text']
                             for x in candidates),
                         'nenhuma candidata pode costurar palavras de dois arquivos')

    def test_the_take_with_fewer_fillers_wins_a_tie(self):
        limpa, t = words('o implante hormonal nao engorda')
        suja, _ = words('o implante hormonal ne nao engorda', t + 1)
        r = script_align.align('O implante hormonal não engorda.', {'C001': limpa + suja})
        melhor = r['lines'][0]['candidates'][0]
        self.assertEqual(melhor['fillers'], 0)

    def test_a_two_word_line_is_flagged_instead_of_guessed(self):
        fala, _ = words('o implante hormonal nao engorda')
        r = script_align.align('Olha.', {'C001': fala})
        self.assertEqual(r['lines'][0]['status'], 'curta')

    def test_empty_inputs_are_refused(self):
        fala, _ = words('alguma coisa dita')
        with self.assertRaises(ValueError):
            script_align.align('', {'C001': fala})
        with self.assertRaises(ValueError):
            script_align.align('uma linha qualquer', {'C001': []})


class ScriptSplitTests(unittest.TestCase):
    def test_lines_break_on_newline_and_on_sentence_end(self):
        linhas = script_align.script_lines('Primeira frase. Segunda frase!\n\nTerceira?')
        self.assertEqual(linhas, ['Primeira frase.', 'Segunda frase!', 'Terceira?'])

    def test_blank_lines_do_not_become_entries(self):
        self.assertEqual(script_align.script_lines('\n\n  \n'), [])


class DraftTests(unittest.TestCase):
    def test_draft_uses_the_best_take_and_says_it_is_a_draft(self):
        fala, t = words('primeira fala do video')
        segunda, _ = words('segunda fala do video', t + 1)
        r = script_align.align('Primeira fala do vídeo.\nSegunda fala do vídeo.',
                               {'C001': fala + segunda})
        edl = script_align.draft_edl(r, {'C001': '/tmp/C001.mp4'})
        self.assertEqual([x['beat'] for x in edl['ranges']], ['L0', 'L1'])
        self.assertIn('speech_regions', edl['_draft'])
        self.assertGreater(edl['total_duration_s'], 0)

    def test_a_missing_line_does_not_become_a_range(self):
        fala, _ = words('primeira fala do video')
        r = script_align.align('Primeira fala do vídeo.\nUma linha que nunca foi gravada aqui.',
                               {'C001': fala})
        edl = script_align.draft_edl(r, {'C001': '/tmp/C001.mp4'})
        self.assertEqual(len(edl['ranges']), 1)


if __name__ == '__main__':
    unittest.main()
