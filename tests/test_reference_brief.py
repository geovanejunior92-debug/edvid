"""O resumo de referência mede o que diz que mede.

Um vídeo sintético de três planos com cortes secos em 2,0 s e 4,0 s: cor
parada, padrão rolando e cor parada de novo. Se o detector perder um corte,
se o fluxo óptico chamar o rolamento de "parado" ou se a validação deixar
passar planos com buraco, algum teste aqui falha.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import reference_brief as rb


def make_video(dest: Path) -> Path:
    """2 s vermelho parado | 2 s padrão rolando | 1,5 s azul parado, com tom."""
    out = dest / 'ref.mp4'
    graph = ('color=c=red:s=320x568:r=30:d=2[a];'
             'testsrc2=s=320x568:r=30:d=2,scroll=h=0.01[b];'
             'color=c=blue:s=320x568:r=30:d=1.5[c];'
             '[a][b][c]concat=n=3:v=1:a=0,format=yuv420p[v]')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-filter_complex', graph,
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=5.5',
                    '-map', '[v]', '-map', '0:a', '-c:v', 'libx264', '-c:a', 'aac',
                    '-shortest', str(out)], check=True)
    return out


@unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg ausente')
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.video = make_video(root)
        dest = rb.build(str(cls.video), root / 'out', transcribe=False, language=None,
                        threshold=rb.SCENE_THRESHOLD)
        cls.brief = json.loads(dest.read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_finds_both_hard_cuts(self):
        cuts = self.brief['cortes']
        self.assertEqual(len(cuts), 2, cuts)
        self.assertAlmostEqual(cuts[0], 2.0, delta=0.1)
        self.assertAlmostEqual(cuts[1], 4.0, delta=0.1)

    def test_motion_separates_still_from_scrolling(self):
        mov = [s['movimento'] for s in self.brief['planos']]
        self.assertEqual(mov, ['parado', 'movimento', 'parado'])

    def test_brief_is_valid_and_sheets_exist(self):
        self.assertEqual(rb.validate_brief(self.brief), [])
        self.assertTrue(self.brief['folhas']['planos'])
        self.assertTrue(self.brief['folhas']['cenas'])
        self.assertEqual(set(self.brief['para_o_agente']), set(rb.AGENT_FIELDS))
        self.assertTrue(all(v is None for v in self.brief['para_o_agente'].values()))

    def test_audio_is_measured(self):
        a = self.brief['audio']
        self.assertTrue(a['tem_audio'])
        self.assertIsNotNone(a['integrado_lufs'])
        self.assertTrue(all(s['loudness_lufs'] is not None for s in self.brief['planos']))


class PureFunctionTests(unittest.TestCase):
    def test_pacing_class_boundaries(self):
        self.assertEqual(rb.pacing_class(12), 'contemplativo')
        self.assertEqual(rb.pacing_class(10), 'educativo')
        self.assertEqual(rb.pacing_class(6), 'educativo')
        self.assertEqual(rb.pacing_class(5), 'dinamico')
        self.assertEqual(rb.pacing_class(2), 'rajada')

    def test_merge_cuts_drops_flashes_and_edges(self):
        self.assertEqual(rb.merge_cuts([0.1, 2.0, 2.1, 5.0, 9.9], 10.0), [2.0, 5.0])

    def test_pacing_profile_numbers(self):
        shots = rb.shots_from_cuts([3.0, 6.0], 12.0)
        p = rb.pacing_profile(shots, 12.0, 40)
        self.assertEqual(p['cortes'], 2)
        self.assertEqual(p['cortes_por_minuto'], 10.0)
        self.assertEqual(p['plano_medio_s'], 4.0)
        self.assertEqual((p['plano_min_s'], p['plano_max_s']), (3.0, 6.0))
        self.assertEqual(p['palavras_por_minuto'], 200.0)
        self.assertEqual(p['classe'], 'dinamico')

    def test_motion_class(self):
        self.assertEqual(rb.motion_class(0.5), 'parado')
        self.assertEqual(rb.motion_class(4.0), 'leve')
        self.assertEqual(rb.motion_class(20.0), 'movimento')
        self.assertIsNone(rb.motion_class(None))

    def test_validate_catches_gap_between_shots(self):
        shots = rb.shots_from_cuts([2.0], 4.0)
        shots[1]['start'] = 2.5
        brief = {'schema': rb.SCHEMA_VERSION, 'fonte': {}, 'video': {'duration': 4.0},
                 'cortes': [2.0], 'planos': shots, 'ritmo': {'classe': 'dinamico'},
                 'audio': {}, 'folhas': {}, 'para_o_agente': {k: None for k in rb.AGENT_FIELDS}}
        self.assertTrue(any('buraco' in e for e in rb.validate_brief(brief)))


if __name__ == '__main__':
    unittest.main()
