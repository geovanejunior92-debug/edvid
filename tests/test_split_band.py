"""A costura da tela dividida: um número errado aqui põe sombra na junção.

Os dois casos reais aprovados no canal ancoram o teste — o Formato 1 (clipe
16:9) e a calibragem de enquadramento fechado (clipe 1080x860). Eles parecem
contradizer-se (bandH 508 contra 760) e não se contradizem: é a mesma regra
com clipes de altura diferente. Se alguém "simplificar" isso para uma
constante, um dos dois quebra.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import split_band


class BandHeightTests(unittest.TestCase):
    def test_formato_1_clip_gives_the_approved_band(self):
        # 16:9 a 1080 de largura mede 608; 608 - 100 = 508, o valor do preset.
        self.assertEqual(split_band.band_height(1920, 1080), split_band.FORMATO_1_BANDH)
        self.assertEqual(split_band.band_height(1280, 720), 508)

    def test_tall_clip_gives_the_close_framing_band(self):
        self.assertEqual(split_band.band_height(1080, 860), 760)

    def test_the_seam_lands_on_the_clips_own_bottom_edge(self):
        # a invariante que dá sentido à regra: banda + dissolução == altura natural
        for w, h in [(1920, 1080), (1080, 860), (1000, 700), (4096, 2160)]:
            natural = round(h * 1080 / w)
            self.assertEqual(split_band.band_height(w, h) + split_band.SEAM_BLEND, natural)

    def test_clip_shorter_than_the_blend_is_refused_with_the_reason(self):
        with self.assertRaises(ValueError) as cm:
            split_band.band_height(1080, 90)   # 90px de altura natural, < 100 do blend
        self.assertIn('Clipe baixo demais', str(cm.exception))

    def test_invalid_dimensions_are_refused(self):
        for w, h in [(0, 100), (100, 0), (-1, 100)]:
            with self.assertRaises(ValueError):
                split_band.band_height(w, h)

    def test_seam_blend_mirrors_the_template(self):
        template = (Path(__file__).resolve().parents[1]
                    / 'assets' / 'shortform' / 'src' / 'CustomGraphics.tsx').read_text()
        self.assertIn(f'const SEAM_BLEND = {split_band.SEAM_BLEND};', template,
                      'SEAM_BLEND saiu de sincronia com o template')


if __name__ == '__main__':
    unittest.main()
