"""A rota da Fase 2 responde no servidor real, autenticada como o app autentica.

Os testes de módulo provam a lógica e os de fila provam o comando. Faltava a
ponta que o aplicativo realmente usa: uma requisição HTTP, com a mesma sessão
que o Studio cria, chegando em `/api/phase2/<id>`. Sem isto, a rota podia estar
escrita e não registrada, e todo o resto continuaria verde.
"""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import studio_server


class Phase2RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.project = base / 'proj'
        (self.project / 'edit').mkdir(parents=True)
        (self.project / 'edit' / 'cut.mp4').write_bytes(b'x' * 2048)
        self.app = studio_server.StudioApp(base / 'data')
        self.addCleanup(self.app.close)
        self.item = self.app.projects.add(self.project)
        self.server = studio_server.make_server(self.app, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('GET', path, headers={'Cookie': f'edvid_session={self.app.session}'})
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response.status, body

    def test_route_is_registered_and_reports_no_state_yet(self):
        status, body = self.get(f'/api/phase2/{self.item["id"]}')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'state': None})

    def test_route_returns_the_state_written_by_the_module(self):
        state = {'version': 1, 'profile': 'remotion-phase-2', 'revision': 3}
        path = self.project / 'edit' / 'studio-phase2' / 'state.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(state))
        status, body = self.get(f'/api/phase2/{self.item["id"]}')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['state'], state)

    def test_unknown_project_is_404_not_a_traceback(self):
        status, body = self.get('/api/phase2/naoexiste')
        self.assertEqual(status, 404)
        self.assertIn('não encontrado', json.loads(body)['error'])

    def test_corrupt_state_is_reported_as_absent_instead_of_crashing(self):
        path = self.project / 'edit' / 'studio-phase2' / 'state.json'
        path.parent.mkdir(parents=True)
        path.write_text('{ isto não é json')
        status, body = self.get(f'/api/phase2/{self.item["id"]}')
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)['state'])

    def post(self, path, payload):
        import json as _json
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('POST', path, body=_json.dumps(payload),
                     headers={'Cookie': f'edvid_session={self.app.session}',
                              'Content-Type': 'application/json',
                              'Origin': f'http://127.0.0.1:{self.server.server_port}',
                              'Host': f'127.0.0.1:{self.server.server_port}'})
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response.status, body

    def test_the_app_can_pin_a_project_and_the_listing_follows(self):
        status, body = self.post('/api/projects/flags',
                                 {'projectId': self.item['id'], 'pinned': True})
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)['pinned'])
        self.assertTrue(self.app.projects.list()[0]['pinned'])

    def test_flags_route_refuses_nonsense(self):
        for payload in ({'projectId': self.item['id']},
                        {'projectId': self.item['id'], 'pinned': 'sim'},
                        {'projectId': 'naoexiste', 'pinned': True}):
            status, _ = self.post('/api/projects/flags', payload)
            self.assertEqual(status, 400)

    def test_without_the_session_the_route_refuses(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('GET', f'/api/phase2/{self.item["id"]}')
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()


if __name__ == '__main__':
    unittest.main()
