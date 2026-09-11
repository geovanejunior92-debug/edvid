import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'helpers'))
from preview_mix import validate, apply_title, mix_command
class MixTests(unittest.TestCase):
    def test_title_preserves_existing_hook(self):
        old={'hook':{'enabled':True,'endSec':4,'logo':'logo.png','lines':['old']}}
        new=apply_title({'headlineText':'Novo\ntítulo'},old)
        self.assertEqual(new['hook']['lines'],['Novo','título'])
        self.assertEqual(new['hook']['logo'],'logo.png'); self.assertEqual(old['hook']['lines'],['old'])
    def test_blank_title_preserves(self):
        self.assertEqual(apply_title({}, {'hook':{'lines':['old']}}),{'hook':{'lines':['old']}})
    def test_rejects_invalid_gains(self):
        for value in [True,float('nan'),100,'0']:
            with self.assertRaises(ValueError): validate({'audioMix':{'voiceDb':value}})
    def test_mix_no_overwrite_no_normalize(self):
        cmd=mix_command({'voice':0,'music':-12,'sfx':-6},[('voice',Path('voice.wav')),('music',Path('music.wav'))],Path('out.wav'))
        self.assertIn('-n',cmd); self.assertIn('volume=-12dB',cmd[cmd.index('-filter_complex')+1]); self.assertIn('normalize=0',cmd[cmd.index('-filter_complex')+1])
if __name__=='__main__':unittest.main()
