"""A headline "personalizada" existe em TRÊS arquivos que precisam concordar.

Não há como rodar o Remotion aqui, então este teste guarda o que um teste de
unidade consegue guardar de verdade: que as três pontas do contrato continuam
presentes e com os mesmos nomes. É pouco, e é de propósito — a alternativa
seria um teste que finge renderizar. O que ele pega é o caso real: alguém
apagar a entrada de um lado e o preview passar a oferecer um estilo que o
render não conhece (ou o contrário), que é silencioso nos dois sentidos.
"""
from pathlib import Path
import re
import unittest

SKILL = Path(__file__).resolve().parents[1]
MAIN = SKILL / 'assets' / 'shortform' / 'src' / 'Main.tsx'
APP = SKILL / 'assets' / 'preview' / 'app.js'
SHORTFORM = SKILL / 'references' / 'shortform.md'


class HeadlinePersonalizadaTests(unittest.TestCase):
    def setUp(self):
        self.main = MAIN.read_text()
        self.app = APP.read_text()

    def test_template_declares_the_style_and_its_knobs(self):
        self.assertRegex(self.main, r"style\?:[^;]*'personalizada'")
        self.assertRegex(self.main, r"\n  personalizada: \{weights: \[")
        for knob in ('color?: string', 'accentColor?: string', 'weights?: [number, number]'):
            self.assertIn(knob, self.main, f'o template perdeu o campo {knob}')
        self.assertIn("if (styleId === 'personalizada')", self.main)

    def test_weight_override_happens_before_the_line_break(self):
        # twoLines/fitHeadline medem no peso real; sobrescrever depois deixaria
        # a linha balanceada numa largura que não é a que vai à tela.
        override = self.main.index('H.weights ? {...base, weights: H.weights}')
        break_call = self.main.index('const lines = twoLines(')
        self.assertLess(override, break_call)

    def test_preview_offers_it_and_mirrors_the_geometry(self):
        self.assertIn("{id: 'personalizada', name: 'Personalizada', hl: 'personalizada'}", self.app)
        self.assertRegex(self.app, r"\n  personalizada: \{ weights: \[")
        # o cartão tem que desenhar a escolha viva, não um preset fixo
        self.assertIn("o.hl === 'personalizada' ? S.style.headlineCustom : null", self.app)

    def test_custom_block_only_travels_when_the_style_is_custom(self):
        self.assertIn("...(S.style.headline === 'personalizada' ? {headlineCustom:", self.app)

    def test_every_ui_knob_is_documented_with_its_edit_data_target(self):
        doc = SHORTFORM.read_text()
        for knob in ('color', 'accentColor', 'weight1', 'weight2', 'maxFontPx', 'paddingTop'):
            self.assertIn(knob, doc, f'{knob} não está documentado em shortform.md')

    def test_ui_knobs_and_default_state_agree(self):
        fields = re.search(r"const HL_CUSTOM_FIELDS = \[([^\]]+)\]", self.app).group(1)
        fields = set(re.findall(r"'(\w+)'", fields))
        defaults = re.search(r"headlineCustom: \{([^}]+)\}", self.app).group(1)
        defaults = set(re.findall(r"(\w+):", defaults))
        self.assertEqual(fields, defaults)


if __name__ == '__main__':
    unittest.main()
