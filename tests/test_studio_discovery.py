"""O aplicativo tem que ver os projetos que a versão web vê.

Antes disto o registro nativo só conhecia pasta adicionada à mão: o app abria
com a biblioteca VAZIA enquanto o Preview web listava oito projetos no mesmo
disco. Compartilhar o identificador (2026-09-11) não resolveu — identificar é
uma coisa, descobrir é outra.
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import preview_library
import studio_server


class BibliotecaFalsa:
    """Uma biblioteca no formato real: <lib>/<projeto>/<edit>/state.json."""

    def __init__(self, tmp: Path):
        self.lib = tmp / 'Videos'
        self.lib.mkdir(parents=True)

    def projeto(self, pasta: str, edit: str = 'edit', nome: str | None = None) -> Path:
        d = self.lib / pasta / edit
        d.mkdir(parents=True)
        (d / 'state.json').write_text(json.dumps({'project': nome or pasta, 'phase': 1}))
        return d


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.b = BibliotecaFalsa(Path(self.tmp.name))

    def test_acha_cada_projeto_uma_vez(self):
        a = self.b.projeto('C014'); c = self.b.projeto('video05')
        achados = preview_library.scan_library(self.b.lib)
        self.assertEqual(sorted(achados), sorted([a.resolve(), c.resolve()]))

    def test_nao_desce_dentro_de_um_projeto(self):
        # um state.json dentro do remotion/public de um projeto não é projeto
        edit = self.b.projeto('C014')
        fundo = edit / 'remotion' / 'public'
        fundo.mkdir(parents=True)
        (fundo / 'state.json').write_text('{}')
        self.assertEqual(preview_library.scan_library(self.b.lib), [edit.resolve()])

    def test_biblioteca_inexistente_devolve_vazio(self):
        self.assertEqual(preview_library.scan_library(self.b.lib / 'nao-existe'), [])


class DescobertaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.b = BibliotecaFalsa(self.raiz)
        self.dados = self.raiz / 'dados'

    def app(self):
        a = studio_server.StudioApp(self.dados, libraries=[self.b.lib])
        self.addCleanup(a.close)
        return a

    def test_registro_vazio_encontra_os_projetos_do_disco(self):
        self.b.projeto('C014'); self.b.projeto('video05')
        itens = self.app().projects.list()
        self.assertEqual(len(itens), 2)
        self.assertEqual({i['name'] for i in itens}, {'C014', 'video05'})

    def test_o_nome_vem_do_state_e_nao_da_pasta(self):
        self.b.projeto('pasta-feia', nome='Sono e cérebro — video 02')
        self.assertEqual(self.app().projects.list()[0]['name'], 'Sono e cérebro — video 02')

    def test_pasta_de_edicao_com_outro_nome_tambem_conta(self):
        # a biblioteca real dele tem seis projetos em `edit_tireoide`, `edit_v01`…
        self.b.projeto('teste', edit='edit_tireoide', nome='Tireoide — 4 hábitos')
        itens = self.app().projects.list()
        self.assertEqual(len(itens), 1)
        self.assertEqual(Path(itens[0]['editPath']).name, 'edit_tireoide')

    def test_nao_cria_pasta_edit_dentro_de_pasta_de_edicao(self):
        # o defeito que a própria descoberta causou: cinco `edit/` vazios
        # nasceram dentro de edit_c028, edit_v01 e companhia (2026-09-12)
        edit = self.b.projeto('teste', edit='edit_c028')
        self.app()
        self.assertFalse((edit / 'edit').exists(), 'criou uma subpasta edit dentro do edit')

    def test_id_e_o_mesmo_da_biblioteca_web(self):
        edit = self.b.projeto('C014')
        self.assertEqual(self.app().projects.list()[0]['id'], preview_library.project_key(edit))

    def test_projeto_novo_aparece_sem_reiniciar(self):
        self.b.projeto('C014')
        app = self.app()
        self.assertEqual(len(app.projects.list()), 1)
        self.b.projeto('video05')
        self.assertEqual(app.projects.discover(force=True), 1)
        self.assertEqual(len(app.projects.list()), 2)

    def test_a_varredura_nao_repete_dentro_do_intervalo(self):
        self.b.projeto('C014')
        app = self.app()
        self.b.projeto('video05')
        self.assertEqual(app.projects.discover(), 0, 'varreu antes do intervalo terminar')

    def test_pasta_registrada_fora_da_biblioteca_passa_a_ser_varrida(self):
        outra = self.raiz / 'OutroLugar'
        p = outra / 'projeto-x' / 'edit'; p.mkdir(parents=True)
        (p / 'state.json').write_text(json.dumps({'project': 'projeto x'}))
        app = self.app()
        app.projects.add(p)                       # ele adiciona uma pasta à mão
        vizinho = outra / 'projeto-y' / 'edit'; vizinho.mkdir(parents=True)
        (vizinho / 'state.json').write_text(json.dumps({'project': 'projeto y'}))
        app.projects.discover(force=True)
        self.assertEqual({i['name'] for i in app.projects.list()}, {'projeto x', 'projeto y'})

    def test_sem_biblioteca_nao_varre_nada(self):
        # o padrão de ambiente é do CLI: um StudioApp sem bibliotecas não pode
        # sair varrendo ~/Videos e registrando os projetos reais do usuário
        self.b.projeto('C014')
        app = studio_server.StudioApp(self.dados, libraries=None)
        self.addCleanup(app.close)
        self.assertEqual(app.projects.list(), [])

    def test_o_cli_e_quem_traz_o_padrao(self):
        padrao = studio_server.default_libraries()
        self.assertTrue(padrao and padrao[0].name == 'Videos')

    def test_registro_sobrevive_ao_reinicio(self):
        self.b.projeto('C014')
        self.app().close()
        gravado = json.loads((self.dados / 'projects.json').read_text())
        self.assertEqual(len(gravado['projects']), 1)


if __name__ == '__main__':
    unittest.main()
