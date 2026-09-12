import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import preview_requests as requests

class RequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / 'edit'; self.root.mkdir()
        (self.base / 'a.mov').write_bytes(b'a')
        (self.base / 'b.mp4').write_bytes(b'b')
        (self.base / 'private.txt').write_text('not a video')
    def test_catalog_does_not_move_or_recurse(self):
        (self.base / 'nested').mkdir(); (self.base / 'nested/c.mov').write_bytes(b'c')
        self.assertEqual([x['name'] for x in requests.sources(self.root)], ['a.mov', 'b.mp4'])
        self.assertTrue((self.base / 'private.txt').exists())
    def test_order_and_pending_saved_separately(self):
        ids = [x['id'] for x in requests.sources(self.root)][::-1]
        result = requests.submit(self.root, {'mode': 'script', 'text': 'Meu roteiro', 'sources': ids})
        self.assertEqual(result['status'], 'pending')
        self.assertEqual([x['name'] for x in result['sources']], ['b.mp4', 'a.mov'])
        self.assertEqual(len(requests.requests(self.root)), 1)
        self.assertFalse((self.root / 'edl.json').exists())
    def test_idempotency_key_returns_existing_request(self):
        source = requests.sources(self.root)[0]
        body = {'mode': 'automatic', 'text': 'corte', 'sources': [source['id']],
                'idempotencyKey': 'upload-project-12345678'}
        first = requests.submit(self.root, body)
        second = requests.submit(self.root, body)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['status'], 'queued')
        self.assertEqual(first['dispatch']['kind'], 'single-source-automatic')
        self.assertEqual(len(requests.all_requests(self.root)), 1)
        changed = dict(body, text='outro corte')
        with self.assertRaisesRegex(ValueError, 'outra solicitação'):
            requests.submit(self.root, changed)
    def test_claim_never_reopens_a_final_request(self):
        source = requests.sources(self.root)[0]
        record = requests.submit(self.root, {
            'mode': 'automatic', 'text': 'corte', 'sources': [source['id']],
        })
        requests.update(self.root, record['id'], status='completed')
        self.assertIsNone(requests.claim(self.root, record['id'], 'new-owner'))
        self.assertEqual(requests.get(self.root, record['id'])['status'], 'completed')
    def test_changed_source_rejected(self):
        key = requests.sources(self.root)[0]['id']; (self.base / 'a.mov').write_bytes(b'changed')
        with self.assertRaises(ValueError): requests.submit(self.root, {'mode': 'automatic', 'text': 'corte', 'sources': [key]})
    def test_validation(self):
        for body in [{'mode':'automatic','text':'corte'}, {'text':''}, {'text':'x','sources':['../private.txt']}, {'text':'x','mode':'execute'}, {'text':'x','sources':[{}]}]:
            with self.assertRaises(ValueError): requests.submit(self.root, body)
    def test_no_symlink_requests_escape(self):
        (self.root / 'agent-requests').symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError): requests.submit(self.root, {'text':'x'})
    def test_project_video_symlink_supported(self):
        (self.base / 'linked.mov').symlink_to(self.base / 'a.mov')
        self.assertIn('linked.mov', [x['name'] for x in requests.sources(self.root)])
    def test_request_history_skips_invalid(self):
        requests.submit(self.root, {'text':'ajustar'})
        (self.root/'agent-requests/broken.json').write_text('invalid')
        self.assertEqual(len(requests.requests(self.root)), 1)


class RequestHTTPTests(unittest.TestCase):
    def setUp(self):
        RequestTests.setUp(self)
        import threading
        from http.server import ThreadingHTTPServer
        import preview_server
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), preview_server.Handler)
        self.server.default_root = self.root
        self.server.library = self.base
        self.server.projects = {'test': self.root}
        self.server.recovery_lock = threading.Lock()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.stop_server)
    def stop_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
    def call(self, method, path, body=None, origin=None):
        import http.client
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Content-Type': 'application/json'}
        if origin: headers['Origin'] = origin
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = c.getresponse(); raw = response.read(); status = response.status; c.close()
        return status, raw
    def test_http_project_routes(self):
        code, raw = self.call('GET','/p/test/api/sources'); self.assertEqual(code,200)
        item = json.loads(raw)['sources'][0]; self.assertNotIn('path',item)
        code, media = self.call('GET',f"/p/test/source-media/{item['id']}"); self.assertEqual((code,media),(200,b'a'))
        code, raw = self.call('POST','/p/test/api/requests',{'mode':'automatic','text':'cortar','sources':[item['id']]})
        self.assertEqual(code,200); self.assertEqual(json.loads(raw)['request']['status'],'queued')
        code, raw = self.call('GET','/p/test/api/requests'); self.assertEqual(len(json.loads(raw)['requests']),1)
    def test_http_rejects_cross_origin(self):
        code,_ = self.call('POST','/p/test/api/requests',{'text':'x'},'https://example.com')
        self.assertEqual(code,403); self.assertEqual(requests.requests(self.root),[])

    def test_server_factory_dispatches_single_video_automatic_request(self):
        import preview_server

        class FakeAutomatic:
            def __init__(self, projects):
                self.projects = projects
                self.received = []
                self.closed = False

            def enqueue(self, root, record):
                self.received.append((Path(root), record['id']))
                return requests.update(root, record['id'], status='queued')

            def close(self):
                self.closed = True

        holder = {}
        def factory(projects):
            holder['queue'] = FakeAutomatic(projects)
            return holder['queue']

        server = preview_server.make_server(
            self.root, self.base, host='127.0.0.1', port=0,
            automatic_factory=factory,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            item = requests.sources(self.root)[0]
            project_id = next(key for key, root in server.projects.items() if root == self.root.resolve())
            import http.client
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            conn.request('POST', f'/p/{project_id}/api/requests', body=json.dumps({
                'mode': 'automatic', 'text': 'corte', 'sources': [item['id']],
            }), headers={'Content-Type': 'application/json'})
            response = conn.getresponse()
            payload = json.loads(response.read())
            conn.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(payload['request']['status'], 'queued')
            self.assertEqual(holder['queue'].received[0][0], self.root.resolve())
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
            server.automatic_requests.close()
        self.assertTrue(holder['queue'].closed)

    def test_network_server_requires_bootstrap_cookie_and_same_origin(self):
        import http.client
        import preview_server

        class PassiveAutomatic:
            def __init__(self, projects): self.projects = projects
            def enqueue(self, root, record): return record
            def close(self): pass

        server = preview_server.make_server(
            self.root, self.base, host='127.0.0.1', port=0,
            automatic_factory=PassiveAutomatic, require_auth=True,
            token='network-secret',
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            def call(method, path, body=None, cookie=None, origin=None):
                headers = {}
                if body is not None:
                    headers['Content-Type'] = 'application/json'; body = json.dumps(body)
                if cookie: headers['Cookie'] = cookie
                if origin: headers['Origin'] = origin
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse(); payload = response.read(); response_headers = dict(response.getheaders()); conn.close()
                return response.status, payload, response_headers

            self.assertEqual(call('GET', '/')[0], 401)
            code, _, headers = call('GET', '/?token=network-secret')
            self.assertEqual(code, 302)
            cookie = headers['Set-Cookie'].split(';', 1)[0]
            self.assertEqual(call('GET', '/', cookie=cookie)[0], 200)
            project_id = next(key for key, root in server.projects.items() if root == self.root.resolve())
            source = requests.sources(self.root)[0]
            body = {'mode': 'automatic', 'text': 'corte', 'sources': [source['id']]}
            self.assertEqual(call('POST', f'/p/{project_id}/api/requests', body)[0], 401)
            self.assertEqual(call('POST', f'/p/{project_id}/api/requests', body, cookie=cookie)[0], 403)
            origin = f'http://127.0.0.1:{server.server_port}'
            self.assertEqual(call('POST', f'/p/{project_id}/api/requests', body, cookie=cookie, origin=origin)[0], 200)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2); server.automatic_requests.close()

if __name__ == '__main__': unittest.main()
