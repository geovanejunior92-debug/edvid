"""O seam_check só avisa. Quem define a costura é o topo do cabelo pela máscara."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'helpers'))
import preview_server
import seam_apply
import seam_check


def mascara(path, largura=540, altura=960, topo=200):
    """ProRes com alfa: transparente acima de `topo`, opaco abaixo."""
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                    f'color=c=white:s={largura}x{altura}:r=30:d=0.2,format=rgba,'
                    f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(gte(Y,{topo}),255,0)'",
                    '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', str(path)],
                   check=True)


class AvisoTests(unittest.TestCase):
    def rodar_cli(self):
        sys.argv = ['seam_check', 'x.mp4', '--at', '1', '--band-h', '860', '--focus-y', '900', '--zoom', '1']
        saida = io.StringIO()
        with mock.patch.object(seam_check, 'head_box', return_value=(300.0, 900.0)), \
                contextlib.redirect_stdout(saida), self.assertRaises(SystemExit) as ctx:
            seam_check.main()
        return ctx.exception.code, saida.getvalue()

    def test_veredito_ruim_nao_reprova_nem_manda_mexer(self):
        codigo, texto = self.rodar_cli()
        self.assertEqual(codigo, 0)
        self.assertIn('AVISO BAIXA DEMAIS', texto)
        self.assertNotIn('rode de novo', texto)

    def test_seam_apply_grava_com_aviso_sem_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit = Path(tmp)
            (edit / 'remotion/public').mkdir(parents=True)
            (edit / 'cut.mp4').write_bytes(b'x')
            alvo = edit / 'remotion/public/edit-data.json'
            alvo.write_text(json.dumps({'width': 1080, 'splitInserts': [
                {'src': 'a.mp4', 'start': 1, 'end': 3, 'bandH': 860, 'focusY': 400, 'layout': 'top'}]}))
            (edit / 'preview_edits.json').write_text(json.dumps({'seam': [{'ref': 0, 'focusY': 950, 'start': 1}]}))
            sys.argv = ['seam_apply', str(edit), '--apply']
            saida = io.StringIO()
            with mock.patch.object(seam_check, 'head_box', return_value=(300.0, 900.0)), \
                    contextlib.redirect_stdout(saida):
                seam_apply.main()
            self.assertEqual(json.loads(alvo.read_text())['splitInserts'][0]['focusY'], 950)
            self.assertIn('AVISO', saida.getvalue())


class RegraDoCabeloTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_formula(self):
        self.assertAlmostEqual(seam_check.focus_from_rule(200, 1000), 304)

    def test_topo_vem_do_alfa_na_grade_do_layout(self):
        m = self.dir / 'm.mov'
        mascara(m, 540, 960, 200)
        # máscara na metade da grade: 200 no quadro são 400 no layout de 1080
        self.assertAlmostEqual(seam_check.hair_top(m, 1080), 400, delta=2)

    def test_mascara_em_4k_da_o_mesmo_topo(self):
        m = self.dir / 'm4k.mov'
        mascara(m, 2160, 3840, 800)
        self.assertAlmostEqual(seam_check.hair_top(m, 1080), 400, delta=2)

    def test_detector_de_rosto_so_entra_no_queixo(self):
        # a caixa começa na testa (y 500): se ela definisse o topo, o focusY seria outro
        m = self.dir / 'm.mov'
        mascara(m, 1080, 1920, 300)
        with mock.patch.object(seam_check, 'head_box', return_value=(500.0, 1100.0)):
            r = seam_check.rule_focus(Path('x.mp4'), 0.0, m, 1080)
        self.assertAlmostEqual(r['focusY'], 300 + 0.13 * 800, delta=2)
        self.assertAlmostEqual(r['hairTop'], 300, delta=2)
        self.assertEqual(r['chin'], 1100.0)

    def test_mascara_vazia_nao_inventa_topo(self):
        m = self.dir / 'vazia.mov'
        mascara(m, 320, 320, 400)
        with self.assertRaises(ValueError):
            seam_check.hair_top(m, 1080)

    def test_rota_do_preview_usa_a_mascara_da_janela(self):
        pub = self.dir / 'remotion/public'
        pub.mkdir(parents=True)
        mascara(pub / 'm.mov', 1080, 1920, 300)
        (pub / 'edit-data.json').write_text(json.dumps({'width': 1080, 'splitInserts': [
            {'start': 1, 'end': 3}, {'start': 5, 'end': 7, 'matte': 'm.mov'}]}))

        class H:
            root = self.dir
            respostas = []
            def _json(self, payload, status=200):
                self.respostas.append((status, payload))

        h = H()
        h.path = '/api/seam-rule?ref=1'
        with mock.patch.object(seam_check, 'head_box', return_value=(500.0, 1100.0)) as caixa:
            preview_server.Handler._seam_rule(h)
        self.assertEqual(h.respostas[-1][0], 200)
        self.assertAlmostEqual(h.respostas[-1][1]['focusY'], 404, delta=2)
        self.assertEqual(caixa.call_args[0][1], 5.0)
        h.path = '/api/seam-rule?ref=0'
        preview_server.Handler._seam_rule(h)
        self.assertEqual(h.respostas[-1][0], 404)


class InterfaceTests(unittest.TestCase):
    def test_aplicar_em_todas_nao_usa_mais_a_fracao(self):
        app = (SKILL / 'assets/preview/app.js').read_text()
        trecho = app[app.index('  applyToAll() {'):app.index('  reset() {\n    this.draft')]
        self.assertIn('api/seam-rule', trecho)
        self.assertNotIn('fraction', trecho)
        self.assertNotIn('seam-head', trecho)


if __name__ == '__main__':
    unittest.main()
