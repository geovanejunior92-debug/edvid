"""Fase 2 no Studio: o que estes testes guardam é o que falha em SILÊNCIO.

Um edit-data com fps diferente do cut.mp4 renderiza inteiro, sem erro, e sai
fora de sincronia do começo ao fim. Um asset ausente vira quadro preto. Um
insert congelado passa por todo gate que não seja o check_inserts. Nenhum deles
aparece como exceção — aparecem como um vídeo errado entregue.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import studio_phase2
from studio_phase2 import Phase2Error, StudioPhase2

CUT_INFO = {'streams': [{'width': 1080, 'height': 1920, 'r_frame_rate': '30/1'}],
            'format': {'duration': '40.0'}}


def fake_runner(returncode=0, stdout='', stderr=''):
    calls = []

    def run(argv, **kw):
        calls.append({'argv': argv, 'kw': kw})
        if argv[0] == 'ffprobe':
            return subprocess.CompletedProcess(argv, 0, json.dumps(CUT_INFO), '')
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
    run.calls = calls
    return run


def base_data(**over):
    data = {'width': 1080, 'height': 1920, 'fps': 30, 'durationSec': 38.0}
    data.update(over)
    return data


class Phase2Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'proj'
        (self.root / 'edit').mkdir(parents=True)
        (self.root / 'edit' / 'cut.mp4').write_bytes(b'x' * 2048)
        self.runner = fake_runner()
        self.p = StudioPhase2(self.root, runner=self.runner)

    def write_data(self, data, name='edit/data.json'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return name


class ScaffoldTests(Phase2Base):
    def test_scaffold_copies_the_template_without_node_modules(self):
        r = self.p.scaffold()
        self.assertTrue(r['created'])
        self.assertTrue((self.p.remotion / 'src' / 'Main.tsx').is_file())
        self.assertFalse((self.p.remotion / 'node_modules').exists())
        self.assertTrue((self.p.public / 'cut.mp4').is_file())

    def test_scaffold_never_overwrites_an_existing_project(self):
        self.p.scaffold()
        marca = self.p.remotion / 'src' / 'CustomGraphics.tsx'
        marca.write_text('// trabalho do usuário')
        r = self.p.scaffold()
        self.assertFalse(r['created'])
        self.assertEqual(marca.read_text(), '// trabalho do usuário')

    def test_scaffold_refuses_without_an_approved_cut(self):
        (self.root / 'edit' / 'cut.mp4').unlink()
        with self.assertRaises(Phase2Error):
            self.p.scaffold()

    def test_the_skill_install_cannot_be_a_project(self):
        with self.assertRaises(Phase2Error):
            StudioPhase2(studio_phase2.SKILL_ROOT)


class ValidateTests(Phase2Base):
    def setUp(self):
        super().setUp()
        self.p.scaffold()

    def test_fps_mismatch_is_refused_with_the_reason(self):
        with self.assertRaises(Phase2Error) as cm:
            self.p.validate(base_data(fps=24))
        self.assertIn('sincronia', str(cm.exception))

    def test_dimension_mismatch_is_refused(self):
        with self.assertRaises(Phase2Error):
            self.p.validate(base_data(width=720, height=1280))

    def test_duration_far_past_the_cut_is_refused(self):
        with self.assertRaises(Phase2Error):
            self.p.validate(base_data(durationSec=90.0))
        # um encerramento a mais continua válido
        self.p.validate(base_data(durationSec=42.0))

    def test_missing_asset_is_named(self):
        data = base_data(splitInserts=[{'src': 'pexels/a.mp4', 'start': 1, 'end': 2}])
        with self.assertRaises(Phase2Error) as cm:
            self.p.validate(data)
        self.assertIn('pexels/a.mp4', str(cm.exception))
        (self.p.public / 'pexels').mkdir(parents=True)
        (self.p.public / 'pexels' / 'a.mp4').write_bytes(b'x')
        self.p.validate(data)

    def test_empty_caption_blocks_block_the_render(self):
        """O defeito que existe de verdade num projeto do canal: 90 blocos com
        tempo e sem texto. Renderiza sem erro e estraga o vídeo."""
        (self.p.public / 'captions.json').write_text(json.dumps([
            {'text': 'Você', 'startMs': 100, 'endMs': 400, 'timestampMs': 250},
            {'text': '', 'startMs': 420, 'endMs': 700, 'timestampMs': 560}]))
        with self.assertRaises(Phase2Error) as cm:
            self.p.validate(base_data(captions={'enabled': True}))
        self.assertIn('bloco vazio', str(cm.exception))

    def test_overlapping_captions_block_the_render(self):
        (self.p.public / 'captions.json').write_text(json.dumps([
            {'text': 'a', 'startMs': 100, 'endMs': 900, 'timestampMs': 500},
            {'text': 'b', 'startMs': 400, 'endMs': 1200, 'timestampMs': 800}]))
        with self.assertRaises(Phase2Error):
            self.p.validate(base_data(captions={'enabled': True}))

    def test_valid_captions_do_not_block(self):
        (self.p.public / 'captions.json').write_text(json.dumps([
            {'text': 'Você', 'startMs': 100, 'endMs': 400, 'timestampMs': 250},
            {'text': 'começou', 'startMs': 420, 'endMs': 900, 'timestampMs': 660}]))
        self.p.validate(base_data(captions={'enabled': True}))

    def test_captions_disabled_means_the_empty_list_is_not_a_problem(self):
        """O template vem com captions.json vazio. Cobrar legenda de quem
        desligou a legenda quebrava todo projeto recém-criado."""
        (self.p.public / 'captions.json').write_text('[]')
        self.p.validate(base_data(captions={'enabled': False}))
        self.p.validate(base_data())
        with self.assertRaises(Phase2Error):
            self.p.validate(base_data(captions={'enabled': True}))

    def test_asset_escaping_the_project_is_refused(self):
        for bad in ('/etc/passwd', '../../fora.mp4'):
            with self.assertRaises(Phase2Error) as cm:
                self.p.validate(base_data(splitInserts=[{'src': bad}]))
            self.assertIn('inseguro', str(cm.exception))

    def test_matte_counts_as_an_asset(self):
        with self.assertRaises(Phase2Error) as cm:
            self.p.validate(base_data(splitInserts=[{'src': 'a.mp4', 'matte': 'fg/b.mov'}]))
        self.assertIn('fg/b.mov', str(cm.exception))

    def test_disabled_soundtrack_is_not_required(self):
        self.p.validate(base_data(soundtrack={'enabled': False, 'file': 'trilha.mp3'}))
        with self.assertRaises(Phase2Error):
            self.p.validate(base_data(soundtrack={'enabled': True, 'file': 'trilha.mp3'}))


class RevisionTests(Phase2Base):
    def test_save_then_approve_then_hash_is_bound_to_the_cut(self):
        ref = self.write_data(base_data())
        saved = self.p.save(ref)
        self.assertEqual(saved['revision'], 1)
        self.assertTrue((self.p.public / 'edit-data.json').is_file())
        ok = self.p.approve(saved['revision'], saved['dataHash'], True)
        self.assertEqual(ok['revision'], 1)
        # o corte muda -> a aprovação anterior não vale mais
        (self.root / 'edit' / 'cut.mp4').write_bytes(b'y' * 4096)
        with self.assertRaises(Phase2Error) as cm:
            self.p.approve(saved['revision'], saved['dataHash'], True)
        self.assertIn('corte mudou', str(cm.exception))

    def test_approval_needs_the_explicit_flag(self):
        ref = self.write_data(base_data())
        saved = self.p.save(ref)
        with self.assertRaises(Phase2Error):
            self.p.approve(saved['revision'], saved['dataHash'], False)

    def test_a_wrong_hash_is_refused(self):
        ref = self.write_data(base_data())
        saved = self.p.save(ref)
        with self.assertRaises(Phase2Error):
            self.p.approve(saved['revision'], 'f' * 64, True)

    def test_saving_again_invalidates_the_previous_approval(self):
        ref = self.write_data(base_data())
        first = self.p.save(ref)
        self.p.approve(first['revision'], first['dataHash'], True)
        self.write_data(base_data(durationSec=39.0))
        second = self.p.save(ref)
        self.assertEqual(second['revision'], 2)
        with self.assertRaises(Phase2Error) as cm:
            self.p.render(first['revision'], first['dataHash'])
        self.assertIn('não está aprovada', str(cm.exception))


class RenderTests(Phase2Base):
    def approved(self):
        ref = self.write_data(base_data())
        saved = self.p.save(ref)
        self.p.approve(saved['revision'], saved['dataHash'], True)
        return saved

    def test_render_is_blocked_without_remotion_dependencies(self):
        saved = self.approved()
        with self.assertRaises(Phase2Error) as cm:
            self.p.render(saved['revision'], saved['dataHash'])
        self.assertIn('npm install', str(cm.exception))

    def test_check_inserts_failing_aborts_before_rendering(self):
        saved = self.approved()
        (self.p.remotion / 'node_modules').mkdir(parents=True)
        self.p.runner = fake_runner(returncode=1, stdout='insert congelado')
        with self.assertRaises(Phase2Error) as cm:
            self.p.render(saved['revision'], saved['dataHash'])
        self.assertIn('check_inserts reprovou', str(cm.exception))
        chamados = [c['argv'][0] for c in self.p.runner.calls]
        self.assertNotIn('npx', chamados, 'não pode renderizar depois do gate reprovar')

    def test_the_render_command_targets_the_template_composition(self):
        cmd = self.p.build_render_command(Path('/tmp/final.mp4'))
        self.assertEqual(cmd[:4], ['npx', '--no-install', 'remotion', 'render'])
        self.assertIn(studio_phase2.COMPOSITION, cmd)

    def test_full_pass_runs_both_gates_and_records_the_output(self):
        saved = self.approved()
        (self.p.remotion / 'node_modules').mkdir(parents=True)
        final = self.root / 'edit' / 'final.mp4'

        def runner(argv, **kw):
            if argv[0] == 'ffprobe':
                return subprocess.CompletedProcess(argv, 0, json.dumps(CUT_INFO), '')
            if argv[0] == 'npx':
                final.write_bytes(b'v' * 4096)
            runner.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, '', '')
        runner.calls = []
        self.p.runner = runner
        r = self.p.render(saved['revision'], saved['dataHash'])
        self.assertEqual(r['output'], 'edit/final.mp4')
        scripts = [Path(a[1]).name for a in runner.calls if a[0] == sys.executable]
        self.assertEqual(scripts, ['check_inserts.py', 'qc_final.py'],
                         'os dois gates rodam, e nessa ordem')

    def test_qc_failing_does_not_record_a_delivered_render(self):
        saved = self.approved()
        (self.p.remotion / 'node_modules').mkdir(parents=True)
        final = self.root / 'edit' / 'final.mp4'

        def runner(argv, **kw):
            if argv[0] == 'ffprobe':
                return subprocess.CompletedProcess(argv, 0, json.dumps(CUT_INFO), '')
            if argv[0] == 'npx':
                final.write_bytes(b'v' * 4096)
                return subprocess.CompletedProcess(argv, 0, '', '')
            if Path(argv[1]).name == 'qc_final.py':
                return subprocess.CompletedProcess(argv, 1, 'legenda em silêncio', '')
            return subprocess.CompletedProcess(argv, 0, '', '')
        self.p.runner = runner
        with self.assertRaises(Phase2Error) as cm:
            self.p.render(saved['revision'], saved['dataHash'])
        self.assertIn('qc_final reprovou', str(cm.exception))
        self.assertIsNone(self.p._state().get('render'))


class HardRuleTests(unittest.TestCase):
    def test_module_never_writes_tsx(self):
        source = (Path(__file__).resolve().parents[1] / 'helpers' / 'studio_phase2.py').read_text()
        self.assertNotIn('.tsx"', source.replace("'", '"').replace('ignore_patterns', ''))
        self.assertIn('copytree', source)   # o template é COPIADO, não editado


if __name__ == '__main__':
    unittest.main()
