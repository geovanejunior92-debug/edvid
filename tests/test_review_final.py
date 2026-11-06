"""Toda fonte de áudio do render aparece na lista antes de alguém ouvir.

O clique da legenda stacked não está em `sfxCues`: quando caiu numa palavra sem
sentido, só o ouvido do dono pegou. Efeito que não se lista não se revisa.
"""
import json
from pathlib import Path
import sys
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'helpers'))
import review_final


class FontesDeAudioTests(unittest.TestCase):
    def test_lista_trilha_transicoes_e_sfxcues(self):
        linhas = review_final.fontes_de_audio({
            'soundtrack': {'enabled': True, 'file': 'trilha.mp3', 'volume': 0.07},
            'transitions': [{'at': 5, 'variant': 'corte'}, {'at': 9, 'variant': 'saida'},
                            {'at': 12, 'variant': 'corte', 'sfx': 'shutter.mp3'}],
            'sfxCues': [{'at': 20, 'src': 'hit.mp3'}]})
        texto = '\n'.join(linhas)
        for esperado in ('trilha.mp3', 'cut-click.mp3', 'whoosh.mp3', 'shutter.mp3', 'hit.mp3'):
            self.assertIn(esperado, texto)
        self.assertEqual(len(linhas), 5)

    def test_clique_da_legenda_aparece_e_e_contado(self):
        cues = [{'preset': 'SOLO_BIG'}, {'preset': 'SOLO_OUTLINE'}, {'preset': 'STACK_MIXED'}]
        linhas = review_final.fontes_de_audio({'captions': {'enabled': True, 'style': 'stacked'}}, cues)
        self.assertIn('2 caption-click.mp3', linhas[0])
        self.assertIn('1 caption-scratch.mp3', linhas[0])

    def test_clique_desligado_nao_aparece(self):
        cues = [{'preset': 'SOLO_BIG'}]
        cap = {'enabled': True, 'style': 'stacked', 'sfx': {'enabled': False}}
        self.assertEqual(review_final.fontes_de_audio({'captions': cap}, cues), [])

    def test_grafico_com_sfx_false_nao_conta(self):
        linhas = review_final.fontes_de_audio({'graphics': [{'sfx': False}, {'kind': 'stat'}]})
        self.assertIn('até 1 whoosh', linhas[0])

    def test_trilha_desligada_nao_aparece(self):
        self.assertEqual(review_final.fontes_de_audio({'soundtrack': {'enabled': False}}), [])


class PresetTests(unittest.TestCase):
    def test_formato_1_sai_com_o_clique_da_legenda_desligado(self):
        preset = json.loads((SKILL / 'assets/presets/formato-1.json').read_text())
        self.assertIs(preset['captions']['sfx']['enabled'], False)


if __name__ == '__main__':
    unittest.main()
