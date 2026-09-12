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
    def run_normalize(self, args):
        module=Path(__file__).resolve().parents[1]/'assets/preview/media-controls.js'
        code=f"const m=require({json.dumps(str(module))}); console.log(JSON.stringify(m.normalize({args})));"
        result=subprocess.run(['node','-e',code],capture_output=True,text=True,check=True)
        return json.loads(result.stdout)

    def test_client_preserves_shutterstock_and_upgrades_legacy_split(self):
        # 'split' era o único nome de tela dividida; sobe para 'split-top' e
        # ganha o padrão dele — a pessoa na frente da faixa.
        self.assertEqual(self.run_normalize("'video','split','','shutterstock'"),
                         {'kind':'video','layout':'split-top','front':True,'status':'requested','provider':'shutterstock'})

    def test_client_carries_each_split_treatment(self):
        self.assertEqual(self.run_normalize("'video','split-bottom','','agent',false")['layout'],'split-bottom')
        self.assertFalse(self.run_normalize("'video','split-bottom','','agent',false")['front'])
        # tela cheia e 'atrás de mim' não têm faixa, então não carregam `front`
        for layout in ('fullscreen','behind'):
            self.assertNotIn('front', self.run_normalize(f"'video','{layout}','','agent'"))

    def test_client_refuses_unknown_layout(self):
        module=Path(__file__).resolve().parents[1]/'assets/preview/media-controls.js'
        code=f"const m=require({json.dumps(str(module))}); try{{m.normalize('video','split-diagonal')}}catch(e){{console.log(JSON.stringify(e.message))}}"
        result=subprocess.run(['node','-e',code],capture_output=True,text=True,check=True)
        self.assertIn('Enquadramento', json.loads(result.stdout))

    def test_server_upgrades_legacy_split_and_defaults_front(self):
        self.note['media']={'kind':'video','layout':'split','provider':'agent'}
        validate_media_notes(self.root,[self.note])
        self.assertEqual(self.note['media']['layout'],'split-top')
        self.assertTrue(self.note['media']['front'])

    def test_server_keeps_front_false_and_strips_it_off_non_split(self):
        self.note['media']={'kind':'video','layout':'split-bottom','provider':'agent','front':False}
        validate_media_notes(self.root,[self.note])
        self.assertFalse(self.note['media']['front'])
        self.note['media']={'kind':'video','layout':'behind','provider':'agent','front':True}
        validate_media_notes(self.root,[self.note])
        self.assertNotIn('front',self.note['media'])

    def test_server_refuses_unknown_layout(self):
        self.note['media']={'kind':'video','layout':'split-diagonal','provider':'agent'}
        with self.assertRaises(ValueError): validate_media_notes(self.root,[self.note])

if __name__=='__main__': unittest.main()
