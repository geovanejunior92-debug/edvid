import json
from pathlib import Path
import sys
import tempfile
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
        self.assertEqual(code,200); self.assertEqual(json.loads(raw)['request']['status'],'pending')
        code, raw = self.call('GET','/p/test/api/requests'); self.assertEqual(len(json.loads(raw)['requests']),1)
    def test_http_rejects_cross_origin(self):
        code,_ = self.call('POST','/p/test/api/requests',{'text':'x'},'https://example.com')
        self.assertEqual(code,403); self.assertEqual(requests.requests(self.root),[])

if __name__ == '__main__': unittest.main()
