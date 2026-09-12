"""Uma biblioteca, não duas que discordam.

Até 2026-09-11 o mesmo projeto tinha DOIS identificadores: a biblioteca web
derivava sha256 do caminho de `edit`, a nativa derivava uuid5 do caminho do
projeto. Fixar ou arquivar num lado não aparecia no outro, e o usuário via duas
listas que discordavam sobre a mesma pasta. O registro nativo ainda estava vazio
neste Mac, então a unificação saiu sem migrar dado real — mas o caminho de
migração existe e está testado aqui, porque outra máquina pode ter dados.
"""
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import preview_library
import preview_server
import studio_server


class UnifiedKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / 'Tireoide'
        self.edit = self.project / 'edit'
        self.edit.mkdir(parents=True)
        (self.edit / 'state.json').write_text('{"project": "Tireoide", "phase": 1}')

    def test_web_and_native_agree_on_the_same_project(self):
        web = preview_server.discover_projects(self.base, self.edit)
        registry = studio_server.ProjectRegistry(self.base / 'data')
        native = registry.add(self.project)
        web_id = next(k for k, v in web.items() if v == self.edit)
        self.assertEqual(web_id, native['id'],
                         'o mesmo projeto precisa ter UM identificador nos dois lados')

    def test_the_flags_file_is_the_same_one(self):
        registry = studio_server.ProjectRegistry(self.base / 'data')
        item = registry.add(self.project)
        registry.set_flags(item['id'], pinned=True)
        # ...e o web lê exatamente essa marca
        entries = preview_library.load_registry(self.base)
        self.assertTrue(entries[item['id']]['pinned'])
        self.assertTrue(registry.list()[0]['pinned'])

    def test_archiving_in_the_app_is_visible_to_the_web_and_vice_versa(self):
        registry = studio_server.ProjectRegistry(self.base / 'data')
        item = registry.add(self.project)
        preview_library.set_flags(self.base, item['id'], archived=True)   # lado web
        self.assertTrue(registry.flags(item)['archived'])                 # lado app
        registry.set_flags(item['id'], archived=False)                    # lado app
        self.assertEqual(preview_library.load_registry(self.base), {})    # lado web

    def test_pinned_projects_sort_first_in_the_native_library(self):
        outro = self.base / 'Sono'
        (outro / 'edit').mkdir(parents=True)
        registry = studio_server.ProjectRegistry(self.base / 'data')
        a = registry.add(self.project)
        b = registry.add(outro)
        registry.set_flags(b['id'], pinned=True)
        self.assertEqual(registry.list()[0]['id'], b['id'])
        registry.set_flags(b['id'], pinned=False)
        self.assertEqual({x['id'] for x in registry.list()}, {a['id'], b['id']})

    def test_a_legacy_entry_is_rekeyed_instead_of_duplicated(self):
        data = self.base / 'data'
        registry = studio_server.ProjectRegistry(data)
        legacy_id = uuid.uuid5(uuid.NAMESPACE_URL, str(self.project.resolve())).hex[:20]
        registry.items[legacy_id] = {'id': legacy_id, 'createdAt': 111.0,
                                     'name': 'Tireoide', 'path': str(self.project),
                                     'editPath': str(self.edit), 'updatedAt': 111.0}
        item = registry.add(self.project)
        self.assertNotEqual(item['id'], legacy_id)
        self.assertNotIn(legacy_id, registry.items, 'a entrada antiga não pode sobreviver ao lado da nova')
        self.assertEqual(len(registry.list()), 1)
        self.assertEqual(item['createdAt'], 111.0, 'a data de criação original tem que sobreviver')

    def test_unknown_project_cannot_have_flags_set(self):
        registry = studio_server.ProjectRegistry(self.base / 'data')
        with self.assertRaises(ValueError):
            registry.set_flags('naoexiste', pinned=True)

    def test_corrupt_flags_file_does_not_break_the_listing(self):
        registry = studio_server.ProjectRegistry(self.base / 'data')
        registry.add(self.project)
        preview_library.registry_path(self.base).write_text('{ quebrado')
        listing = registry.list()
        self.assertEqual(len(listing), 1)
        self.assertFalse(listing[0]['pinned'])


if __name__ == '__main__':
    unittest.main()
