"""Edvid instalável no celular: a casca vem do Mac e a porta da Tailscale é guardada.

O servidor fixo atrás do `tailscale serve` recebe todo pedido de 127.0.0.1,
então a única coisa que separa o dono de qualquer outro aparelho da tailnet é a
identidade que a Tailscale injeta. Estes testes travam três promessas: pedido
via proxy sem login permitido não entra, o código do edvid nunca é servido com
cache (atualização não fica escondida), e projeto criado depois de o servidor
subir aparece sem reiniciar.
"""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'helpers'))
import preview_library as lib
import preview_server

PREVIEW = ROOT / 'assets' / 'preview'


class PwaServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.key, self.root = lib.create(self.base, 'Sono e cérebro')
        self.placeholder = self.base / '.edvid-preview' / 'edit'
        self.placeholder.mkdir(parents=True)
        self.server = preview_server.make_server(self.placeholder, self.base, host='127.0.0.1', port=0)
        self.server.tailscale_logins = {'dono@exemplo.com'}
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('GET', path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def test_proxied_request_without_allowed_login_is_refused(self):
        resp, _ = self.get('/api/projects', {'X-Forwarded-For': '100.64.0.9'})
        self.assertEqual(resp.status, 403)
        resp, _ = self.get('/api/projects', {'Tailscale-User-Login': 'outra@pessoa.com'})
        self.assertEqual(resp.status, 403)

    def test_proxied_request_from_the_owner_passes(self):
        resp, body = self.get('/api/projects', {'Tailscale-User-Login': 'Dono@Exemplo.com',
                                                'X-Forwarded-For': '100.64.0.9'})
        self.assertEqual(resp.status, 200)
        self.assertEqual([p['name'] for p in json.loads(body)['projects']], ['Sono e cérebro'])

    def test_without_configured_login_the_proxy_is_closed(self):
        self.server.tailscale_logins = set()
        resp, _ = self.get('/', {'Tailscale-User-Login': 'dono@exemplo.com'})
        self.assertEqual(resp.status, 403)

    def test_local_requests_are_unchanged(self):
        resp, _ = self.get('/')
        self.assertEqual(resp.status, 200)

    def test_manifest_and_worker_are_served_without_cache(self):
        resp, body = self.get('/manifest.webmanifest')
        self.assertEqual(resp.status, 200)
        self.assertIn('manifest+json', resp.getheader('Content-Type'))
        self.assertEqual(json.loads(body)['display'], 'standalone')
        resp, _ = self.get('/sw.js')
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader('Cache-Control'), 'no-store')
        resp, _ = self.get('/assets/app.js')
        self.assertEqual(resp.getheader('Cache-Control'), 'no-store')

    def test_project_created_after_start_appears_without_restart(self):
        key, _ = lib.create(self.base, 'Projeto novo')
        self.server.projects.pop(key, None)
        _, body = self.get('/api/projects')
        self.assertIn('Projeto novo', [p['name'] for p in json.loads(body)['projects']])
        resp, _ = self.get(f'/p/{key}/api/state')
        self.assertEqual(resp.status, 200)


class WorkerContractTests(unittest.TestCase):
    def test_worker_never_caches_edvid_code(self):
        sw = (PREVIEW / 'sw.js').read_text()
        # só terceiros com versão fixa entram no cache
        self.assertIn('cdnjs', sw)
        self.assertIn('fonts', sw)
        self.assertNotIn("caches.open(CASCA).then((c) => c.put(req", sw)
        self.assertIn("req.mode === 'navigate'", sw)
        pwa = (PREVIEW / 'pwa.js').read_text()
        self.assertIn("updateViaCache: 'none'", pwa)

    def test_icons_exist(self):
        manifest = json.loads((PREVIEW / 'manifest.webmanifest').read_text())
        for icon in manifest['icons']:
            self.assertTrue((PREVIEW / icon['src'].removeprefix('/assets/')).is_file(), icon['src'])


if __name__ == '__main__':
    unittest.main()
