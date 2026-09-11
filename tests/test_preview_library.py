import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'helpers'))
import preview_library as lib
class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.key,self.root=lib.create(self.base,'Novo vídeo')
    def test_create_isolated(self):
        self.assertTrue(self.root.is_relative_to(self.base));self.assertEqual(json.loads((self.root/'state.json').read_text())['project'],'Novo vídeo')
        _,other=lib.create(self.base,'Novo vídeo');self.assertNotEqual(self.root,other)
    def test_import_copies_exact_bytes(self):
        name=lib.receive(self.root,'clipe.mov',io.BytesIO(b'video'),5);self.assertEqual((self.root.parent/name).read_bytes(),b'video')
    def test_existing_file_never_overwritten(self):
        lib.receive(self.root,'clipe.mov',io.BytesIO(b'a'),1)
        name=lib.receive(self.root,'clipe.mov',io.BytesIO(b'b'),1)
        self.assertNotEqual(name,'clipe.mov');self.assertEqual((self.root.parent/'clipe.mov').read_bytes(),b'a')
    def test_interrupt_cleans_partial(self):
        with self.assertRaises(ValueError):lib.receive(self.root,'clipe.mov',io.BytesIO(b'a'),5)
        self.assertFalse((self.root.parent/'clipe.mov').exists());self.assertEqual(list(self.root.parent.glob('.upload*')),[])
    def test_rejects_paths_and_nonvideo(self):
        for name in ['../clipe.mov','/tmp/clipe.mov','a\\b.mov','x.txt']:
            with self.assertRaises(ValueError):lib.receive(self.root,name,io.BytesIO(b'a'),1)
    def test_rejects_unmarked_project(self):
        (self.root/'.preview-import-project').unlink()
        with self.assertRaises(ValueError):lib.receive(self.root,'a.mov',io.BytesIO(b'a'),1)
    def test_limits(self):
        for size in [0,lib.MAX_UPLOAD+1]:
            with self.assertRaises(ValueError):lib.receive(self.root,'a.mov',io.BytesIO(b'a'),size)
if __name__=='__main__':unittest.main()
