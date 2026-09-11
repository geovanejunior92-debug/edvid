import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
from preview_requests import insert_assets, validate_media_notes

class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base/'edit'; self.root.mkdir()
        (self.base/'assets').mkdir(); (self.base/'assets/a.png').write_bytes(b'image')
        self.note = {'start':1,'end':2,'renderedStart':1,'renderedEnd':2,'text':'cena', 'media':{'kind':'video','layout':'split','provider':'shutterstock'}}
    def test_generation_remains_request(self):
        self.note['media']['status']='completed'
        validate_media_notes(self.root,[self.note])
        self.assertEqual(self.note['media']['status'],'requested')
    def test_invalid_intervals(self):
        for val in [None,True,float('nan'),-1,3]:
            n=copy.deepcopy(self.note); n['start']=val
            with self.assertRaises(ValueError): validate_media_notes(self.root,[n])
    def test_assets_and_file_validation(self):
        self.assertEqual(insert_assets(self.root),['assets/a.png'])
        self.note['media']={'kind':'file','layout':'fullscreen','file':'assets/a.png'}
        validate_media_notes(self.root,[self.note])
        for path in ['../escape.png','/etc/passwd','missing.mov']:
            self.note['media']['file']=path
            with self.assertRaises(ValueError): validate_media_notes(self.root,[self.note])
    def test_legacy_annotation(self):
        validate_media_notes(self.root,[{'text':'old note'}])
    def test_invalid_provider(self):
        self.note['media']['provider']='fake'
        with self.assertRaises(ValueError): validate_media_notes(self.root,[self.note])
    def test_client_preserves_shutterstock(self):
        module=Path(__file__).resolve().parents[1]/'assets/preview/media-controls.js'
        code=f"const m=require({json.dumps(str(module))}); console.log(JSON.stringify(m.normalize('video','split','','shutterstock')));"
        result=subprocess.run(['node','-e',code],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),{'kind':'video','layout':'split','status':'requested','provider':'shutterstock'})

if __name__=='__main__': unittest.main()
