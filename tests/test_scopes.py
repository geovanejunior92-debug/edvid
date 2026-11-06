"""Sem rosto, o scopes diz que não leu a pele, em vez de omitir em silêncio.

O passo do `skin_protect` consome esse número: se a leitura some sem aviso, o
passo some junto e ninguém percebe.
"""
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import scopes

QUADRO = np.full((120, 120, 3), 128, np.uint8)
ROSTO = (30, 30, 60, 60)


class LeituraDePeleTests(unittest.TestCase):
    def analisar(self, caixas):
        with mock.patch.object(scopes, 'face_box', side_effect=caixas), \
                mock.patch.object(scopes, 'frame_at', return_value=QUADRO):
            return scopes.analyze_take(Path('x.mp4'), 0.0, 3.0, True, samples=len(caixas))

    def test_sem_rosto_avisa_e_conta_as_amostras(self):
        rep = self.analisar([None, None, None])
        self.assertNotIn('skin', rep)
        self.assertIn('rosto detectado em 0 de 3', rep['skin_warning'])
        self.assertIn('AVISO', scopes.fmt(rep))

    def test_rosto_em_minoria_das_amostras_tambem_avisa(self):
        rep = self.analisar([ROSTO, None, None])
        self.assertNotIn('skin', rep)
        self.assertIn('rosto detectado em 1 de 3', rep['skin_warning'])

    def test_com_rosto_nao_ha_aviso(self):
        rep = self.analisar([ROSTO, ROSTO, None])
        self.assertIn('skin', rep)
        self.assertNotIn('skin_warning', rep)
        self.assertNotIn('AVISO', scopes.fmt(rep))

    def test_no_face_pedido_nao_avisa(self):
        with mock.patch.object(scopes, 'frame_at', return_value=QUADRO):
            rep = scopes.analyze_take(Path('x.mp4'), 0.0, 3.0, False, samples=2)
        self.assertNotIn('skin_warning', rep)


if __name__ == '__main__':
    unittest.main()
