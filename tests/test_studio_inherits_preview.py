"""O aplicativo não pode ficar para trás do editor web em silêncio.

O Studio monta o MESMO `assets/preview/index.html` em `/editor/<id>/` e a classe
dele herda de `preview_server.Handler`. Na prática, toda melhoria da interface
web chega ao aplicativo de graça — e é fácil alguém "otimizar" isso criando uma
cópia própria do HTML dentro de `assets/studio/`, que passaria a divergir sem
ninguém notar. Este teste é a trava: se o app deixar de servir o editor
compartilhado, ou se um controle entregue no web sumir do que o app serve, a
suíte reclama.

A lista abaixo é o que foi entregue no editor em 2026-09-11 e que o usuário
pediu explicitamente para existir também no aplicativo.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import preview_server
import studio_server

PREVIEW = Path(preview_server.__file__).resolve().parent.parent / 'assets' / 'preview'

CONTROLES = {
    'corrigir texto da legenda': ('index.html', 'wordBarFix'),
    'botão de correção': ('index.html', 'corrigir texto'),
    'tela dividida — arte em cima': ('index.html', 'split-top'),
    'tela dividida 2 — arte embaixo': ('index.html', 'split-bottom'),
    'sem divisão': ('index.html', 'Sem divisão'),
    'eu na frente da faixa': ('index.html', 'noteMediaFront'),
    'headline personalizada': ('index.html', 'hlCustom'),
    'cor da linha 1': ('index.html', 'hlc_color'),
    'catálogo com personalizada': ('app.js', "id: 'personalizada'"),
    'payload de correção de texto': ('app.js', 'textFixes'),
    'tratamentos de tela dividida': ('media-controls.js', 'split-bottom'),
}


class StudioInheritsPreviewTests(unittest.TestCase):
    def test_the_app_serves_the_shared_editor_not_a_copy(self):
        self.assertEqual(studio_server.PREVIEW_DIR.resolve(), PREVIEW.resolve())
        # e o handler do app é o do preview, não um paralelo
        self.assertTrue(issubclass(studio_server.StudioHandler, preview_server.Handler))

    def test_every_control_delivered_on_the_web_is_in_what_the_app_serves(self):
        faltando = []
        for rotulo, (arquivo, marca) in CONTROLES.items():
            if marca not in (PREVIEW / arquivo).read_text(encoding='utf-8'):
                faltando.append(f'{rotulo} ({arquivo})')
        self.assertEqual(faltando, [], 'o app deixou de oferecer: ' + ', '.join(faltando))

    def test_the_app_has_no_second_copy_of_the_editor_html(self):
        studio_assets = Path(studio_server.APP_DIR)
        if not studio_assets.is_dir():
            self.skipTest('assets/studio ainda não existe')
        for candidato in studio_assets.rglob('*.html'):
            texto = candidato.read_text(encoding='utf-8', errors='ignore')
            self.assertNotIn('id="wordBar"', texto,
                             f'{candidato.name} parece uma cópia do editor — ele deve ser servido, não duplicado')


if __name__ == '__main__':
    unittest.main()
