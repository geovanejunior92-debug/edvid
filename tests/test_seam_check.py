"""A falha silenciosa da tela dividida, virada número.

O caso que este teste existe para pegar é o `focusY` 400 do layout padrão: ele
renderiza, passa em todos os outros gates, e produz uma faixa reta — o recorte
da pessoa não aparece em lugar nenhum. Os valores de referência vêm da
calibragem real registrada na memória do canal: 560 encosta, 640 entra, 720 lê
como a referência.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import seam_check


# Cabeça medida numa fonte real deste canal: topo do cabelo em 455, ~660 de alto.
HEAD_TOP, HEAD_BOTTOM = 455.0, 1115.0
BAND_H, ZOOM = 508.0, 1.25


def verdict(focus_y, band_h=BAND_H, zoom=ZOOM, layout='top'):
    return seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, focus_y, zoom, band_h, layout)['verdict']


class SeamPositionTests(unittest.TestCase):
    def test_template_default_focus_reads_as_a_straight_band(self):
        # focusY 400: a cabeça inteira cai abaixo da costura. É a falha silenciosa.
        self.assertEqual(verdict(400), 'FAIXA RETA')

    def test_the_three_calibrated_values_land_where_they_were_described(self):
        # memória do canal: 560 "encosta", 640 "entra", 720 "lê como a referência"
        self.assertEqual(verdict(560), 'RASPANDO')
        self.assertEqual(verdict(640), 'OK')
        self.assertEqual(verdict(720), 'OK')
        self.assertAlmostEqual(
            seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, 720, ZOOM, BAND_H)['fraction'],
            seam_check.REFERENCE, places=1)

    def test_the_band_term_is_what_flips_the_verdict(self):
        # Sem o `+ bandH` da fórmula do template, focusY 400 pareceria cruzar a
        # cabeça. Este é o erro que o helper existe para não deixar acontecer.
        r = seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, 400, ZOOM, BAND_H)
        self.assertLess(r['fraction'], 0)
        sem_termo = (BAND_H - (HEAD_TOP - 400) * ZOOM) / ((HEAD_BOTTOM - HEAD_TOP) * ZOOM)
        self.assertGreater(sem_termo, 0)   # a conclusão errada, para registro

    def test_seam_crossing_the_face_is_flagged(self):
        # focusY alto demais empurra a pessoa para cima e a costura desce no rosto
        self.assertEqual(verdict(1000), 'BAIXA DEMAIS')

    def test_fraction_grows_as_the_person_rises(self):
        fracs = [seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, f, ZOOM, BAND_H)['fraction']
                 for f in (400, 560, 640, 720)]
        self.assertEqual(fracs, sorted(fracs), 'subir o focusY tem que descer a costura na cabeça')
        self.assertLess(fracs[0], 0)   # 400 nem cruza

    def test_bottom_layout_is_refused_instead_of_guessed(self):
        with self.assertRaises(ValueError) as cm:
            seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, 720, ZOOM, BAND_H, 'bottom')
        self.assertIn('não foi medida', str(cm.exception))

    def test_invalid_inputs_are_refused(self):
        with self.assertRaises(ValueError):
            seam_check.seam_position(500, 500, 400, 1.25, BAND_H)
        with self.assertRaises(ValueError):
            seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, 400, 0, BAND_H)

    def test_seam_blend_mirrors_the_template(self):
        template = (Path(__file__).resolve().parents[1]
                    / 'assets' / 'shortform' / 'src' / 'CustomGraphics.tsx').read_text()
        self.assertIn(f'const SEAM_BLEND = {seam_check.SEAM_BLEND};', template)


class WideBlendTests(unittest.TestCase):
    """Formato 2: sem matte, quem faz o efeito é a largura da dissolução."""

    BAND, BLEND = 874.0, 192.0

    def wide(self, focus_y):
        return seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, focus_y, ZOOM,
                                        self.BAND, 'top', self.BLEND)

    def test_head_top_inside_the_dissolve_is_the_criterion(self):
        r = self.wide(400)
        self.assertEqual(r['verdict'], 'OK')
        self.assertEqual(r['criterion'], 'dissolução larga')
        self.assertTrue(seam_check.BLEND_MIN <= r['blendFraction'] <= seam_check.BLEND_MAX)

    def test_head_starting_after_the_dissolve_is_a_straight_band(self):
        # cabeça baixa demais: a arte já sumiu antes de ela começar
        r = seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, 250, ZOOM, self.BAND, 'top', self.BLEND)
        self.assertEqual(r['verdict'], 'FAIXA RETA')

    def test_head_entering_above_the_dissolve_is_flagged(self):
        self.assertEqual(self.wide(600)['verdict'], 'ALTA DEMAIS')

    def test_narrow_blend_keeps_the_old_criterion(self):
        r = seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, 720, ZOOM, BAND_H, 'top', 100)
        self.assertEqual(r['criterion'], 'costura estreita')
        self.assertEqual(r['verdict'], 'OK')

    def test_zero_blend_is_refused(self):
        with self.assertRaises(ValueError):
            seam_check.seam_position(HEAD_TOP, HEAD_BOTTOM, 400, ZOOM, self.BAND, 'top', 0)


class PresetTests(unittest.TestCase):
    def test_formato_2_preset_carries_the_measured_geometry(self):
        import json
        preset = json.loads((Path(__file__).resolve().parents[1] /
                             'assets' / 'presets' / 'formato-2.json').read_text())
        modelo = preset['_splitInserts_modelo']
        self.assertEqual(modelo['bandH'], 874)
        self.assertEqual(modelo['seamBlend'], 192)
        self.assertEqual(modelo['layout'], 'top')
        # o preset NÃO pode pedir matte: nele o efeito vem da dissolução
        self.assertNotIn('matte', modelo)
        self.assertIn('_sem_matte', modelo)

    def test_bottom_layout_defaults_to_the_wide_division(self):
        # pedido dele: "para a arte em baixo quero a divisão dessa forma"
        template = (Path(__file__).resolve().parents[1] /
                    'assets' / 'shortform' / 'src' / 'CustomGraphics.tsx').read_text()
        self.assertIn("{top: SEAM_BLEND, bottom: 192}", template)
        self.assertIn('const blend = seamBlend ?? LAYOUT_BLEND[layout];', template)

    def test_template_accepts_a_per_window_blend(self):
        template = (Path(__file__).resolve().parents[1] /
                    'assets' / 'shortform' / 'src' / 'CustomGraphics.tsx').read_text()
        self.assertIn('seamBlend?: number;', template)
        self.assertIn('const blend = seamBlend ?? LAYOUT_BLEND[layout];', template)


if __name__ == '__main__':
    unittest.main()
