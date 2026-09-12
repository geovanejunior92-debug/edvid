"""A costura ajustada no preview vira focusY no edit-data — com gate no meio.

O teste que importa aqui não é o de gravar: é o de RECUSAR. O preview mostra o
veredito ao vivo, e gravar um valor que o gate reprova desfaria o sentido de
ter o gate. Por isso só passa com --force.
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import seam_check
import seam_apply


class GeometriaTests(unittest.TestCase):
    """A conta que a interface faz ao vivo tem que ser a mesma do gate."""

    def test_a_fracao_nao_depende_de_bandh_nem_de_zoom(self):
        # É o fato que governa a ferramenta inteira: focusY é a única alavanca.
        base = seam_check.seam_position(300, 900, 640, 1.0, 860)['fraction']
        for band in (508, 750, 860, 960):
            for zoom in (1.0, 1.08, 1.2):
                r = seam_check.seam_position(300, 900, 640, zoom, band)
                self.assertAlmostEqual(r['fraction'], base, places=3,
                                       msg=f'bandH={band} zoom={zoom} mudou a fração')

    def test_descer_focusy_sobe_a_costura_na_cabeca(self):
        alto = seam_check.seam_position(300, 900, 520, 1.0, 860)['fraction']
        baixo = seam_check.seam_position(300, 900, 640, 1.0, 860)['fraction']
        self.assertLess(alto, baixo)

    def test_a_conta_da_interface_bate_com_a_do_gate(self):
        # o preview calcula (focusY - topo) / altura; o gate faz o caminho longo
        top, bottom, focus = 276.0, 869.0, 610.0
        interface = (focus - top) / (bottom - top)
        gate = seam_check.seam_position(top, bottom, focus, 1.0, 860)['fraction']
        self.assertAlmostEqual(interface, gate, places=3)


class AplicacaoTests(unittest.TestCase):
    def projeto(self, focus_y=640):
        tmp = Path(tempfile.mkdtemp())
        edit = tmp / 'edit'
        (edit / 'remotion' / 'public').mkdir(parents=True)
        data = {'width': 1080, 'height': 1920, 'fps': 24, 'durationSec': 60,
                'splitInserts': [
                    {'src': 'stock/a.mp4', 'start': 10, 'end': 16, 'bandH': 860,
                     'focusY': focus_y, 'layout': 'top'},
                    {'src': 'stock/b.mp4', 'start': 20, 'end': 26, 'bandH': 860,
                     'focusY': focus_y, 'layout': 'bottom'},
                ]}
        (edit / 'remotion' / 'public' / 'edit-data.json').write_text(json.dumps(data))
        return edit

    def escrever_edits(self, edit, seam):
        (edit / 'preview_edits.json').write_text(json.dumps({'type': 'timeline-edits', 'seam': seam}))

    def test_sem_cut_nao_mede_mas_grava(self):
        # sem cut.mp4 não há como medir; recusar aqui deixaria o ajuste inútil
        # num projeto cujo corte ainda não foi recuperado.
        edit = self.projeto()
        self.escrever_edits(edit, [{'ref': 0, 'focusY': 520, 'start': 10}])
        sys.argv = ['seam_apply', str(edit), '--apply']
        seam_apply.main()
        data = json.loads((edit / 'remotion' / 'public' / 'edit-data.json').read_text())
        self.assertEqual(data['splitInserts'][0]['focusY'], 520)

    def test_layout_bottom_e_ignorado(self):
        # a geometria do `bottom` não foi medida; chutar seria pior que recusar
        edit = self.projeto()
        self.escrever_edits(edit, [{'ref': 1, 'focusY': 520, 'start': 20}])
        sys.argv = ['seam_apply', str(edit), '--apply']
        with self.assertRaises(SystemExit) as ctx:
            seam_apply.main()
        self.assertIn('nada a aplicar', str(ctx.exception))

    def test_janela_inexistente_nao_derruba(self):
        edit = self.projeto()
        self.escrever_edits(edit, [{'ref': 9, 'focusY': 520}, {'ref': 0, 'focusY': 530, 'start': 10}])
        sys.argv = ['seam_apply', str(edit), '--apply']
        seam_apply.main()
        data = json.loads((edit / 'remotion' / 'public' / 'edit-data.json').read_text())
        self.assertEqual(data['splitInserts'][0]['focusY'], 530)

    def test_sem_seam_no_arquivo_recusa(self):
        edit = self.projeto()
        (edit / 'preview_edits.json').write_text(json.dumps({'type': 'timeline-edits'}))
        sys.argv = ['seam_apply', str(edit)]
        with self.assertRaises(SystemExit):
            seam_apply.main()

    def test_dry_run_nao_grava(self):
        edit = self.projeto()
        self.escrever_edits(edit, [{'ref': 0, 'focusY': 520, 'start': 10}])
        sys.argv = ['seam_apply', str(edit)]
        seam_apply.main()
        data = json.loads((edit / 'remotion' / 'public' / 'edit-data.json').read_text())
        self.assertEqual(data['splitInserts'][0]['focusY'], 640)


if __name__ == '__main__':
    unittest.main()
