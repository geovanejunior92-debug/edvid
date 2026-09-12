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
    data = {'width': 1080, 'height': 1920, 'fps': 30, 'durationSec': 40.0}
    data.update(over)
    return data


class Phase2Base(unittest.TestCase):
    def sem_dependencias(self):
        """Projeto sem node_modules, haja ou não instalação compartilhada."""
        alvo = self.p.remotion / 'node_modules'
        if alvo.is_symlink() or alvo.exists():
            alvo.unlink() if alvo.is_symlink() else __import__('shutil').rmtree(alvo)

    def com_dependencias(self):
        """Projeto COM node_modules, sem depender do compartilhado existir."""
        alvo = self.p.remotion / 'node_modules'
        if alvo.is_symlink():
            return                       # já aponta para o compartilhado
        alvo.mkdir(parents=True, exist_ok=True)

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
    def test_scaffold_never_copies_node_modules_into_the_project(self):
        """Copiar são 570 MB por vídeo. Ou não existe, ou é link para a
        instalação compartilhada — nunca uma cópia."""
        r = self.p.scaffold()
        self.assertTrue(r['created'])
        self.assertTrue((self.p.remotion / 'src' / 'Main.tsx').is_file())
        alvo = self.p.remotion / 'node_modules'
        if alvo.exists():
            self.assertTrue(alvo.is_symlink(), 'node_modules não pode ser cópia')
            self.assertEqual(alvo.resolve(), (studio_phase2.TEMPLATE / 'node_modules').resolve())
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
        # só a extensão descrita pelo encerramento continua válida
        self.p.validate(base_data(durationSec=42.0,
                                  outro={'enabled': True, 'startSec': 39.5,
                                         'durationSec': 2.5}))
        with self.assertRaises(Phase2Error):
            self.p.validate(base_data(durationSec=42.0))

    def test_duration_cannot_truncate_the_cut_or_the_outro(self):
        with self.assertRaisesRegex(Phase2Error, 'termina antes'):
            self.p.validate(base_data(durationSec=12.0))
        with self.assertRaisesRegex(Phase2Error, 'termina antes'):
            self.p.validate(base_data(durationSec=40.0,
                                      outro={'enabled': True, 'startSec': 39.5,
                                             'durationSec': 2.5}))

    def test_placeholders_and_bad_scalar_types_are_refused_as_phase2_errors(self):
        for bad in (base_data(splitInserts='PREENCHER'), base_data(fps='trinta'),
                    base_data(durationSec=float('nan'))):
            with self.assertRaises(Phase2Error):
                self.p.validate(bad)

    def test_stacked_caption_sfx_requires_an_object(self):
        (self.p.public / 'captions.json').write_text(json.dumps([
            {'text': 'Você', 'startMs': 100, 'endMs': 600, 'timestampMs': 350}]))
        (self.p.public / 'caption-cues.json').write_text(json.dumps([{
            'i': 0, 'startMs': 100, 'endMs': 600, 'preset': 'SOLO_BIG',
            'exit': 'abrupt', 'styleOffset': 0,
            'lines': [[{'text': 'Você', 'fromMs': 100, 'toMs': 600}]],
        }]))
        with self.assertRaisesRegex(Phase2Error, 'captions.sfx'):
            self.p.validate(base_data(captions={
                'enabled': True, 'style': 'stacked', 'sfx': 'ligado'}))

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

    def test_captions_cannot_cover_the_outro(self):
        (self.p.public / 'captions.json').write_text(json.dumps([
            {'text': 'Você', 'startMs': 39000, 'endMs': 40100, 'timestampMs': 39500}]))
        with self.assertRaises(Phase2Error) as cm:
            self.p.validate(base_data(durationSec=42.0, captions={'enabled': True},
                                      outro={'enabled': True, 'startSec': 40,
                                             'durationSec': 2.0}))
        self.assertIn('encerramento', str(cm.exception))

    def test_stacked_captions_require_real_cues_and_their_implicit_sfx(self):
        (self.p.public / 'captions.json').write_text(json.dumps([
            {'text': 'Você', 'startMs': 100, 'endMs': 600, 'timestampMs': 350}]))
        data = base_data(captions={'enabled': True, 'style': 'stacked'})
        with self.assertRaises(Phase2Error) as cm:
            self.p.validate(data)
        self.assertIn('caption-cues.json', str(cm.exception))
        (self.p.public / 'caption-cues.json').write_text(json.dumps([{
            'i': 0, 'startMs': 100, 'endMs': 600, 'preset': 'SOLO_BIG',
            'exit': 'abrupt', 'styleOffset': 0,
            'lines': [[{'text': 'Você', 'fromMs': 100, 'toMs': 600}]],
        }]))
        self.p.validate(data)
        (self.p.public / 'sfx' / 'caption-click.mp3').unlink()
        with self.assertRaises(Phase2Error) as cm:
            self.p.validate(data)
        self.assertIn('caption-click.mp3', str(cm.exception))
        self.p.validate(base_data(captions={'enabled': True, 'style': 'stacked',
                                            'sfx': {'enabled': False}}))

    def test_enabled_captions_require_the_file(self):
        (self.p.public / 'captions.json').unlink()
        with self.assertRaises(Phase2Error) as cm:
            self.p.validate(base_data(captions={'enabled': True}))
        self.assertIn('captions.json', str(cm.exception))

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

    def test_hook_and_sfx_assets_follow_the_template_paths(self):
        (self.p.public / 'brand').mkdir(parents=True)
        (self.p.public / 'brand' / 'logo.png').write_bytes(b'x')
        (self.p.public / 'sfx').mkdir(parents=True, exist_ok=True)
        (self.p.public / 'sfx' / 'click.wav').write_bytes(b'x')
        data = base_data(hook={'enabled': True, 'logo': 'brand/logo.png'},
                         sfxCues=[{'src': 'click.wav', 'at': 1}])
        self.p.validate(data)
        (self.p.public / 'brand' / 'logo.png').unlink()
        with self.assertRaises(Phase2Error) as cm:
            self.p.validate(data)
        self.assertIn('brand/logo.png', str(cm.exception))

    def test_every_template_asset_field_is_checked_at_its_real_public_path(self):
        """Guarda o contrato entre o validador e os staticFile() do TSX."""
        cases = [
            ({'soundtrack': {'enabled': True, 'file': 'music/track.mp3'}},
             'music/track.mp3'),
            ({'logo': {'enabled': True, 'src': 'brand/opening.png'}},
             'brand/opening.png'),
            ({'hook': {'enabled': True, 'sign': 'brand/sign.png'}},
             'brand/sign.png'),
            ({'inserts': [{'src': 'inserts/card.jpg'}]}, 'inserts/card.jpg'),
            ({'behind': [{'src': 'behind/bg.jpg', 'matte': 'behind/matte.mov'}]},
             'behind/bg.jpg'),
            ({'behindVideos': [{'src': 'behind/video.mp4', 'matte': 'behind/person.mov'}]},
             'behind/video.mp4'),
            ({'splitInserts': [{'src': 'split/art.mp4', 'matte': 'split/person.mov'}]},
             'split/art.mp4'),
            ({'sfxCues': [{'src': 'missing-cue.mp3'}]}, 'sfx/missing-cue.mp3'),
            ({'transitions': [{'at': 1, 'sfx': 'missing-transition.wav'}]},
             'sfx/missing-transition.wav'),
        ]
        for fragment, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(Phase2Error) as cm:
                    self.p.validate(base_data(**fragment))
                self.assertIn(expected, str(cm.exception))

    def test_all_top_level_template_collections_reject_placeholders(self):
        for name in ('splitInserts', 'inserts', 'behind', 'behindVideos',
                     'sfxCues', 'transitions', 'graphics', 'titleCards'):
            with self.subTest(name=name), self.assertRaisesRegex(Phase2Error, name):
                self.p.validate(base_data(**{name: 'PREENCHER'}))


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
        self.write_data(base_data(camera={'enabled': False}))
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
        self.sem_dependencias()
        with self.assertRaises(Phase2Error) as cm:
            self.p.render(saved['revision'], saved['dataHash'])
        self.assertIn('npm install', str(cm.exception))

    def test_check_inserts_failing_aborts_before_rendering(self):
        saved = self.approved()
        self.com_dependencias()
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
        self.com_dependencias()
        final = self.root / 'edit' / 'final.mp4'

        def runner(argv, **kw):
            if argv[0] == 'ffprobe':
                return subprocess.CompletedProcess(argv, 0, json.dumps(CUT_INFO), '')
            if argv[0] == 'npx':
                Path(argv[5]).write_bytes(b'v' * 4096)
            runner.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, '', '')
        runner.calls = []
        self.p.runner = runner
        r = self.p.render(saved['revision'], saved['dataHash'])
        self.assertEqual(r['output'], 'edit/final.mp4')
        scripts = [Path(a[1]).name for a in runner.calls if a[0] == sys.executable]
        self.assertEqual(scripts, ['check_inserts.py', 'qc_final.py'],
                         'os dois gates rodam, e nessa ordem')
        self.assertIsNone(self.p._state().get('delivery'))
        with self.assertRaises(Phase2Error):
            self.p.review_approve(r['fingerprint']['sha256'], False)
        delivered = self.p.review_approve(r['fingerprint']['sha256'], True)
        self.assertEqual(delivered['status'], 'approved-for-delivery')

    def test_review_refuses_a_render_changed_after_the_gates(self):
        saved = self.approved()
        self.com_dependencias()

        def runner(argv, **kw):
            if argv[0] == 'ffprobe':
                return subprocess.CompletedProcess(argv, 0, json.dumps(CUT_INFO), '')
            if argv[0] == 'npx':
                Path(argv[5]).write_bytes(b'v' * 4096)
            return subprocess.CompletedProcess(argv, 0, '', '')

        self.p.runner = runner
        rendered = self.p.render(saved['revision'], saved['dataHash'])
        (self.root / rendered['output']).write_bytes(b'alterado depois do QC')
        with self.assertRaisesRegex(Phase2Error, 'mudou depois do render'):
            self.p.review_approve(rendered['fingerprint']['sha256'], True)

    def test_qc_failing_does_not_record_a_delivered_render(self):
        saved = self.approved()
        self.com_dependencias()
        final = self.root / 'edit' / 'final.mp4'
        final.write_bytes(b'ultimo-render-bom')

        def runner(argv, **kw):
            if argv[0] == 'ffprobe':
                return subprocess.CompletedProcess(argv, 0, json.dumps(CUT_INFO), '')
            if argv[0] == 'npx':
                Path(argv[5]).write_bytes(b'v' * 4096)
                return subprocess.CompletedProcess(argv, 0, '', '')
            if Path(argv[1]).name == 'qc_final.py':
                return subprocess.CompletedProcess(argv, 1, 'legenda em silêncio', '')
            return subprocess.CompletedProcess(argv, 0, '', '')
        self.p.runner = runner
        with self.assertRaises(Phase2Error) as cm:
            self.p.render(saved['revision'], saved['dataHash'])
        self.assertIn('qc_final reprovou', str(cm.exception))
        self.assertIsNone(self.p._state().get('render'))
        self.assertEqual(final.read_bytes(), b'ultimo-render-bom')
        self.assertFalse(any(self.root.joinpath('edit').glob('.final-phase2-*.mp4')))


class HardRuleTests(Phase2Base):
    def test_save_approve_and_render_leave_every_tsx_byte_unchanged(self):
        self.p.scaffold()
        before = {path.relative_to(self.p.remotion): path.read_bytes()
                  for path in self.p.remotion.rglob('*.tsx')}
        ref = self.write_data(base_data())
        saved = self.p.save(ref)
        self.p.approve(saved['revision'], saved['dataHash'], True)
        self.com_dependencias()
        def runner(argv, **kw):
            if argv[0] == 'ffprobe':
                return subprocess.CompletedProcess(argv, 0, json.dumps(CUT_INFO), '')
            if argv[0] == 'npx':
                Path(argv[5]).write_bytes(b'v' * 4096)
            return subprocess.CompletedProcess(argv, 0, '', '')

        self.p.runner = runner
        self.p.render(saved['revision'], saved['dataHash'])
        after = {path.relative_to(self.p.remotion): path.read_bytes()
                 for path in self.p.remotion.rglob('*.tsx')}
        self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
