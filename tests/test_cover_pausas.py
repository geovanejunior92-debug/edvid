"""A capa prefere quadro em pausa da fala e foge da boca aberta."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'helpers'))
import cover


class EyesFalso:
    """Olho sempre aberto; a boca segue o relógio de `abertura`, se houver."""
    abertura = None
    instante = [0.0]

    def medir(self, img):
        boca = type(self).abertura(type(self).instante[0]) if type(self).abertura else None
        return (None if boca is None and type(self).abertura is None else 0.3), boca


def video(path, dur=4):
    # imagem nítida e igual em todo quadro: nada além da fala e da boca desempata
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                    f'smptebars=s=320x568:r=30:d={dur}', '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-pix_fmt', 'yuv420p', str(path)], check=True)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.v = self.dir / 'cut.mp4'
        video(self.v)
        EyesFalso.abertura = None
        patches = [mock.patch.object(cover, 'Eyes', EyesFalso),
                   mock.patch.object(cover, 'detect_face', return_value=(100, 100, 120, 160))]
        original = cover.frame_at

        def frame_at(path, t, width):
            EyesFalso.instante[0] = t
            return original(path, t, width)
        patches.append(mock.patch.object(cover, 'frame_at', frame_at))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class PausasTests(Base):
    def test_lacunas_vem_da_transcricao(self):
        tr = self.dir / 't.json'
        tr.write_text(json.dumps({'words': [
            {'type': 'word', 'start': 0.5, 'end': 1.0, 'text': 'a'},
            {'type': 'spacing', 'start': 1.0, 'end': 1.1, 'text': ' '},
            {'type': 'word', 'start': 1.05, 'end': 2.0, 'text': 'b'},
            {'type': 'word', 'start': 2.3, 'end': 3.0, 'text': 'c'}]}))
        pausas = cover.pausas_da_fala(tr)
        self.assertEqual(pausas[0], (0.0, 0.5))
        self.assertEqual(pausas[1], (2.0, 2.3))
        self.assertEqual(pausas[2], (3.0, float('inf')))
        self.assertEqual(len(pausas), 3)   # 1.0→1.05 é curta demais

    def test_quadro_em_pausa_vence_o_que_esta_no_meio_da_fala(self):
        ranking = cover.score_frames(self.v, 0.0, 3.0, pausas=[(1.5, 1.7)])
        self.assertTrue(ranking[0]['pausa'])
        self.assertTrue(1.5 <= ranking[0]['t'] <= 1.7)

    def test_pausa_curta_fora_da_grade_entra_como_candidato(self):
        ranking = cover.score_frames(self.v, 0.0, 3.0, pausas=[(1.05, 1.24)])
        self.assertTrue(ranking[0]['pausa'])
        self.assertAlmostEqual(ranking[0]['t'], 1.14, delta=0.02)

    def test_boca_aberta_perde_mesmo_dentro_de_pausa(self):
        # duas pausas: na primeira a boca segue aberta, na segunda fechou
        EyesFalso.abertura = staticmethod(lambda t: 0.5 if t < 2 else 0.02)
        ranking = cover.score_frames(self.v, 0.0, 3.5, pausas=[(1.0, 1.3), (2.5, 2.8)])
        self.assertTrue(2.5 <= ranking[0]['t'] <= 2.8, ranking[0])

    def test_boca_fechada_na_fala_nao_perde_para_aberta_sem_medida_de_pausa(self):
        EyesFalso.abertura = staticmethod(lambda t: 0.5 if t < 2 else 0.02)
        ranking = cover.score_frames(self.v, 0.0, 3.5)
        self.assertGreaterEqual(ranking[0]['t'], 2.0)

    def test_sem_pausas_a_nota_e_a_de_antes(self):
        # sem transcrição nem pontos do rosto: 2,2 + nitidez + centro + tamanho, sem termo novo
        ranking = cover.score_frames(self.v, 0.0, 1.0)
        for r in ranking:
            esperado = 2.2 + 1.0 * r['sharp'] / max(x['sharp'] for x in ranking) + 0.5 * r['center'] + 0.6 * r['size_ok']
            self.assertAlmostEqual(r['score'], esperado, places=2)
            self.assertFalse(r['pausa'])


class CliTests(Base):
    def rodar(self, *extra):
        sys.argv = ['cover', str(self.v), '--text', 'Frase da capa', '--window', '0', '3', *extra]
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida), \
                mock.patch.object(cover, 'compose'), mock.patch.object(cover, 'detect_face', return_value=(100, 100, 120, 160)):
            self.assertEqual(cover.main(), 0)
        return saida.getvalue()

    def test_sem_transcricao_avisa_e_escolhe_mesmo_assim(self):
        texto = self.rodar()
        self.assertIn('AVISO: sem transcrição', texto)
        self.assertIn('capa: quadro em', texto)

    def test_acha_a_transcricao_ao_lado_e_usa_as_pausas(self):
        (self.dir / 'transcripts').mkdir()
        (self.dir / 'transcripts/cut.json').write_text(json.dumps({'words': [
            {'start': 0.0, 'end': 1.5, 'text': 'a'}, {'start': 2.0, 'end': 4.0, 'text': 'b'}]}))
        texto = self.rodar()
        self.assertNotIn('AVISO: sem transcrição', texto)
        escolhido = float(texto.split('quadro em ')[1].split('s')[0])
        self.assertTrue(1.5 <= escolhido <= 2.0, texto)

    def test_avisa_quando_os_pontos_do_rosto_nao_foram_medidos(self):
        self.assertIn('pontos do rosto', self.rodar())


class BocaTests(unittest.TestCase):
    def pontos(self, abertura):
        l = np.zeros((68, 2))
        l[60], l[64] = (0, 0), (10, 0)
        for de, para, x in ((61, 67, 3), (62, 66, 5), (63, 65, 7)):
            l[de], l[para] = (x, -abertura / 2), (x, abertura / 2)
        return l

    def test_abertura_labial_cresce_com_a_boca(self):
        self.assertAlmostEqual(cover.Eyes._boca(self.pontos(0)), 0.0)
        self.assertAlmostEqual(cover.Eyes._boca(self.pontos(4)), 0.4)


if __name__ == '__main__':
    unittest.main()
