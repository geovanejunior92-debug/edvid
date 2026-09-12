"""Pin, rename and archive — the library shelf, and the placeholder-root card.

Archiving is the one that needs a test with teeth: it must hide a card and
touch nothing on disk. A regression there deletes someone's edit.
"""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import preview_library as lib
import preview_server


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.key, self.root = lib.create(self.base, 'Tireoide')

    def test_flags_persist_and_defaults_are_not_stored(self):
        lib.set_flags(self.base, self.key, pinned=True)
        self.assertEqual(lib.load_registry(self.base)[self.key], {'pinned': True, 'archived': False})
        lib.set_flags(self.base, self.key, archived=True)
        self.assertEqual(lib.load_registry(self.base)[self.key], {'pinned': True, 'archived': True})
        # Back to defaults: the entry carries no information and is dropped.
        lib.set_flags(self.base, self.key, pinned=False, archived=False)
        self.assertEqual(lib.load_registry(self.base), {})

    def test_corrupt_registry_reads_as_no_preferences(self):
        lib.registry_path(self.base).write_text('{ not json')
        self.assertEqual(lib.load_registry(self.base), {})
        lib.set_flags(self.base, self.key, pinned=True)
        self.assertTrue(lib.load_registry(self.base)[self.key]['pinned'])

    def test_rename_rewrites_state_and_rejects_empty(self):
        self.assertEqual(lib.rename(self.root, '  Tireoide — 4 hábitos '), 'Tireoide — 4 hábitos')
        state = json.loads((self.root / 'state.json').read_text())
        self.assertEqual(state['project'], 'Tireoide — 4 hábitos')
        self.assertEqual(state['phase'], 1)  # the rest of the state survives
        for bad in ('', '   ', 'x' * 101, None):
            with self.assertRaises(ValueError):
                lib.rename(self.root, bad)


class ShelfServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.key, self.root = lib.create(self.base, 'Sono e cérebro')
        self.placeholder = self.base / '.edvid-preview' / 'edit'
        self.placeholder.mkdir(parents=True)
        self.server = preview_server.make_server(self.placeholder, self.base, host='127.0.0.1', port=0)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get_projects(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('GET', '/api/projects')
        body = json.loads(conn.getresponse().read())
        conn.close()
        return body['projects']

    def post_update(self, payload):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('POST', '/api/projects/update', body=json.dumps(payload),
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        return response.status, body

    def test_placeholder_root_is_not_listed_as_a_project(self):
        listed = self.get_projects()
        self.assertEqual([p['name'] for p in listed], ['Sono e cérebro'])
        # It still routes: dropping it from the listing must not unregister it.
        placeholder_id = next(k for k, r in self.server.projects.items() if r == self.placeholder.resolve())
        self.assertIn(placeholder_id, self.server.projects)

    def test_archive_hides_the_card_and_keeps_every_file(self):
        before = sorted(p.name for p in self.root.iterdir())
        status, body = self.post_update({'id': self.key, 'archived': True})
        self.assertEqual(status, 200)
        self.assertTrue(body['archived'])
        self.assertTrue([p for p in self.get_projects() if p['id'] == self.key][0]['archived'])
        self.assertTrue(self.root.is_dir())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        self.post_update({'id': self.key, 'archived': False})
        self.assertFalse([p for p in self.get_projects() if p['id'] == self.key][0]['archived'])

    def test_pinned_project_sorts_first(self):
        other_key, _ = lib.create(self.base, 'Mounjaro')
        self.server.projects = preview_server.discover_projects(self.base, self.placeholder)
        self.post_update({'id': self.key, 'pinned': True})
        self.assertEqual([p['name'] for p in self.get_projects()][0], 'Sono e cérebro')
        self.post_update({'id': self.key, 'pinned': False})
        self.post_update({'id': other_key, 'pinned': True})
        self.assertEqual([p['name'] for p in self.get_projects()][0], 'Mounjaro')

    def test_rename_through_the_api_and_unknown_project_refused(self):
        status, body = self.post_update({'id': self.key, 'name': 'Sono — v2'})
        self.assertEqual(status, 200)
        self.assertEqual(body['name'], 'Sono — v2')
        self.assertEqual([p['name'] for p in self.get_projects() if p['id'] == self.key], ['Sono — v2'])
        status, body = self.post_update({'id': 'nao-existe', 'archived': True})
        self.assertEqual(status, 400)
        self.assertIn('error', body)


if __name__ == '__main__':
    unittest.main()
