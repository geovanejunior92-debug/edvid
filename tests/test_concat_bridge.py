"""A ponte do Concat leva o corte exato e traz de volta só o que mudou.

A leitura da volta roda sobre um concat.json escrito à mão. O ciclo de ida e
volta usa o binário de verdade e fica de fora onde o Concat não está instalado.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import concat_bridge as cb


def write_edl(edit: Path, source: Path, ranges: list) -> dict:
    edl = {'sources': {'A': str(source)}, 'ranges': ranges,
           'grade': 'neutral', 'jcut': {'lead': 0.2}}
    (edit / 'edl.json').write_text(json.dumps(edl))
    return edl


def clip(start, duration, source_start, media='m1', kind='video', track='T1', **extra):
    return {'id': f'c{start}', 'kind': kind, 'mediaId': media, 'trackId': track,
            'name': 'x', 'start': start, 'duration': duration,
            'sourceStart': source_start, 'speed': 1.0, **extra}


class ReadsSavedProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.source = self.tmp / 'fonte.mp4'
        self.source.touch()
        self.edl = {'sources': {'A': str(self.source)},
                    'ranges': [{'source': 'A', 'start': 2.0, 'end': 5.0}]}

    def read(self, clips, media=None):
        doc = {'activeTimelineId': 'TL1',
               'media': media or [{'id': 'm1', 'path': str(self.source)}],
               'timelines': [{'id': 'TL1', 'clips': clips}]}
        (self.tmp / 'concat.json').write_text(json.dumps(doc))
        return cb.ranges_from_project(self.tmp, self.edl)

    def test_ordem_segue_a_timeline(self):
        ranges, _ = self.read([clip(3.0, 1.0, 8.0), clip(0.0, 3.0, 2.0)])
        self.assertEqual([r['start'] for r in ranges], [2.0, 8.0])

    def test_arredondamento_nao_vira_ajuste(self):
        ranges, _ = self.read([clip(0.0, 3.01, 1.995)])
        self.assertEqual((ranges[0]['start'], ranges[0]['end']), (2.0, 5.0))

    def test_ajuste_real_passa(self):
        ranges, _ = self.read([clip(0.0, 3.5, 1.5)])
        self.assertEqual((ranges[0]['start'], ranges[0]['end']), (1.5, 5.0))

    def test_midia_de_fora_bloqueia(self):
        with self.assertRaisesRegex(SystemExit, 'fora do edl'):
            self.read([clip(0.0, 3.0, 2.0)],
                      media=[{'id': 'm1', 'path': str(self.tmp / 'outra.mp4')}])

    def test_duas_trilhas_de_video_bloqueiam(self):
        with self.assertRaisesRegex(SystemExit, 'trilhas'):
            self.read([clip(0.0, 3.0, 2.0), clip(1.0, 1.0, 2.0, track='T2')])

    def test_avisa_titulo_vao_e_velocidade(self):
        _, notes = self.read([
            clip(0.0, 3.0, 2.0, speed=1.5),
            clip(5.0, 1.0, 8.0),
            clip(0.0, 1.0, 0.0, kind='title'),
        ])
        text = ' '.join(notes)
        for expected in ('velocidade', 'vão', 'title'):
            self.assertIn(expected, text)


@unittest.skipUnless(cb.CONCAT_BIN.exists(), 'Concat não instalado')
class RoundTrip(unittest.TestCase):
    def setUp(self):
        # O MCP só escreve dentro da pasta pessoal.
        self.tmp = Path(tempfile.mkdtemp(dir=Path.home(), prefix='.edvid-concat-test-'))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.source = self.tmp / 'fonte.mp4'
        subprocess.run(['ffmpeg', '-y', '-v', 'error',
                        '-f', 'lavfi', '-i', 'testsrc2=s=720x1280:r=30:d=12',
                        '-f', 'lavfi', '-i', 'sine=f=440:d=12',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                        '-shortest', str(self.source)], check=True)
        self.edl = write_edl(self.tmp, self.source, [
            {'source': 'A', 'start': 2.123, 'end': 5.0, 'beat': 'HOOK', 'gain_db': -1.5},
            {'source': 'A', 'start': 7.5, 'end': 10.853333, 'beat': 'CTA'},
        ])

    def edit_project(self, change):
        """Salva uma mudança no projeto, como a janela faria."""
        project = cb.build_project(self.tmp, self.edl)
        client = cb.Concat()
        try:
            client.tool('project_open', path=str(project))
            change(client, project,
                       client.tool('timeline_read', path=str(project))['timeline']['clips'])
            client.tool('project_close', path=str(project), save=True)
        finally:
            client.close()
        return project

    def pull(self, project):
        ranges, _ = cb.ranges_from_project(project, self.edl)
        cb.merge_back(self.tmp, ranges, editor='Concat', state_dir='concat')
        return json.loads((self.tmp / 'edl.json').read_text())

    def test_sem_mexer_nada_muda(self):
        after = self.pull(self.edit_project(lambda *_: None))
        self.assertEqual(after['ranges'], self.edl['ranges'])

    def test_resolucao_da_fonte(self):
        project = cb.build_project(self.tmp, self.edl)
        client = cb.Concat()
        try:
            info = client.tool('project_open', path=str(project))['project']
        finally:
            client.close()
        self.assertEqual((info['width'], info['height']), (720, 1280))

    def test_arraste_e_remocao_voltam_preservando_o_resto(self):
        def change(client, project, clips):
            client.tool('clip_trim', path=str(project), clipId=clips[0]['id'],
                        edge='end', delta=-0.5, ripple=True)
            client.tool('clips_remove', path=str(project),
                        clipIds=[clips[1]['id']], ripple=True)
        after = self.pull(self.edit_project(change))
        self.assertEqual(len(after['ranges']), 1)
        take = after['ranges'][0]
        self.assertAlmostEqual(take['end'], 4.5, places=2)
        self.assertEqual(take['start'], 2.123)
        self.assertEqual((take['beat'], take['gain_db']), ('HOOK', -1.5))
        self.assertEqual((after['grade'], after['jcut']), ('neutral', {'lead': 0.2}))
        self.assertTrue(list(self.tmp.glob('edl.json.bak-*')))
        self.assertTrue((self.tmp / 'concat' / 'last_return.json').exists())

    def test_nome_do_take_vai_pro_clipe(self):
        project = cb.build_project(self.tmp, self.edl)
        doc = json.loads((project / 'concat.json').read_text())
        self.assertEqual([c['name'] for c in doc['timelines'][0]['clips']], ['HOOK', 'CTA'])


if __name__ == '__main__':
    unittest.main()
