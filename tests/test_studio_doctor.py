"""Diagnóstico de dependências.

O valor de um doctor está em duas coisas, e é isso que os testes guardam:
dizer a VERDADE sobre o estado, e trazer o conserto escrito. Um doctor que
declara "faltando" sem dizer o comando não resolve nada, e um que declara "ok"
sem checar é pior que não existir.
"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import studio_doctor


class DoctorTests(unittest.TestCase):
    def itens(self, **kw):
        return {i['item']: i for i in studio_doctor.check(**kw)}

    def test_every_missing_item_carries_the_exact_fix(self):
        for i in studio_doctor.check():
            if i['state'] == 'faltando':
                self.assertIn('fix', i, f"«{i['item']}» diz que falta e não diz como resolver")
                self.assertTrue(i['fix'].strip())

    def test_every_item_says_why_it_matters(self):
        for i in studio_doctor.check():
            self.assertTrue(i['why'].strip(), f"«{i['item']}» não explica por que importa")
            self.assertIn(i['state'], {'ok', 'aviso', 'faltando'})

    def test_it_actually_checks_ffmpeg_instead_of_assuming(self):
        # nesta máquina o ffmpeg existe; o teste garante que o caminho relatado
        # é o real, não um texto fixo
        item = self.itens()['ffmpeg']
        if item['state'] == 'ok':
            self.assertTrue(Path(item['detail']).exists())

    def test_a_project_without_remotion_is_a_warning_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / 'proj'
            (proj / 'edit').mkdir(parents=True)
            item = self.itens(project=proj)['Remotion do projeto']
            self.assertEqual(item['state'], 'aviso')
            self.assertIn('scaffold', item['fix'])

    def test_a_scaffolded_project_without_dependencies_is_the_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / 'proj'
            (proj / 'edit' / 'remotion').mkdir(parents=True)
            item = self.itens(project=proj)['Remotion do projeto']
            self.assertEqual(item['state'], 'faltando')
            self.assertIn('npm install', item['fix'])
            self.assertIn('assets/shortform', item['fix'])

    def test_installed_dependencies_report_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / 'proj'
            (proj / 'edit' / 'remotion' / 'node_modules').mkdir(parents=True)
            self.assertEqual(self.itens(project=proj)['Remotion do projeto']['state'], 'ok')

    def test_the_shared_install_is_reported_either_way(self):
        item = self.itens()['Remotion compartilhado']
        if item['state'] == 'aviso':
            self.assertIn('npm install', item['fix'])
            self.assertIn('570', item['why'])


class ScaffoldReuseTests(unittest.TestCase):
    """O scaffold aponta para a instalação compartilhada em vez de duplicar."""

    def test_scaffold_links_to_the_shared_modules_when_they_exist(self):
        import studio_phase2
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / 'proj'
            (proj / 'edit').mkdir(parents=True)
            (proj / 'edit' / 'cut.mp4').write_bytes(b'x' * 2048)
            p = studio_phase2.StudioPhase2(proj)
            compartilhado = studio_phase2.TEMPLATE / 'node_modules'
            p.scaffold()
            alvo = p.remotion / 'node_modules'
            if compartilhado.is_dir():
                self.assertTrue(alvo.is_symlink(), 'deveria apontar, não copiar')
                self.assertEqual(alvo.resolve(), compartilhado.resolve())
            else:
                self.assertFalse(alvo.exists(),
                                 'sem instalação compartilhada, o projeto pede npm install')


if __name__ == '__main__':
    unittest.main()
