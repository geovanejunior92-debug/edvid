"""A query string tem que sobreviver ao prefixo /p/<id>/ do projeto.

Bug real, achado em 2026-09-12 ao ligar a primeira rota que depende de
parâmetro (`/api/seam-head?at=`): `_select_project` reescrevia `self.path`
descartando tudo depois do `?`. Nenhuma rota antiga usava query, então o
defeito ficou invisível — e a rota nova respondia sempre pelo segundo 0,
devolvendo uma medida plausível e errada. Este teste é o alarme para a
próxima rota com parâmetro.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import preview_server


class FakeServer:
    def __init__(self, projects, default_root):
        self.projects = projects
        self.default_root = default_root


class Handler:
    """Só o suficiente para exercitar _select_project sem abrir socket."""

    def __init__(self, path, server):
        self.path = path
        self.server = server
        self.respostas = []

    def _json(self, payload, status=200):
        self.respostas.append((status, payload))


class SelectProjectTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer({'abc123': Path('/tmp/projeto/edit')}, Path('/tmp/padrao'))
        self.select = preview_server.Handler._select_project

    def rodar(self, path):
        h = Handler(path, self.server)
        ok = self.select(h)
        return ok, h

    def test_query_sobrevive_ao_prefixo_do_projeto(self):
        ok, h = self.rodar('/p/abc123/api/seam-head?at=29.7')
        self.assertTrue(ok)
        self.assertEqual(h.path, '/api/seam-head?at=29.7')
        self.assertEqual(h.root, Path('/tmp/projeto/edit'))

    def test_rota_sem_query_continua_igual(self):
        ok, h = self.rodar('/p/abc123/api/state')
        self.assertTrue(ok)
        self.assertEqual(h.path, '/api/state')

    def test_query_vazia_nao_inventa_interrogacao(self):
        ok, h = self.rodar('/p/abc123/api/state?')
        self.assertTrue(ok)
        self.assertEqual(h.path, '/api/state?')

    def test_fora_do_prefixo_o_path_fica_intacto(self):
        ok, h = self.rodar('/api/seam-head?at=11.7')
        self.assertTrue(ok)
        self.assertEqual(h.path, '/api/seam-head?at=11.7')
        self.assertEqual(h.root, Path('/tmp/padrao'))

    def test_projeto_desconhecido_responde_404(self):
        ok, h = self.rodar('/p/nao-existe/api/state?x=1')
        self.assertFalse(ok)
        self.assertEqual(h.respostas[0][0], 404)


if __name__ == '__main__':
    unittest.main()
