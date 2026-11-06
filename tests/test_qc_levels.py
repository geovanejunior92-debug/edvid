"""Gate de níveis: pixel isolado de borda de legenda passa; clipagem em área reprova."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'helpers'))
import qc_final

W, H = 640, 360


def video_com_luma(path, pintar, n=6, fundo=120):
    """Vídeo sem perda: o valor de Y escrito aqui é o que chega ao medidor."""
    y = np.full((H, W), fundo, np.uint8)
    pintar(y)
    uv = np.full(W // 2 * (H // 2) * 2, 128, np.uint8)
    quadro = y.tobytes() + uv.tobytes()
    proc = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'yuv420p',
                             '-s', f'{W}x{H}', '-r', '2', '-i', '-', '-c:v', 'ffv1', str(path)],
                            stdin=subprocess.PIPE)
    proc.communicate(quadro * n)
    assert proc.returncode == 0


class NiveisTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.v = Path(tmp.name) / 'v.mkv'

    def medir(self, pintar):
        video_com_luma(self.v, pintar)
        lv = qc_final.illegal_levels(self.v)
        return lv, qc_final.level_fails(lv)

    def test_pixel_isolado_de_borda_nao_reprova(self):
        # Proporção medida numa entrega real: uma dúzia de pixels de cada lado.
        def pintar(y):
            y[100, 100:112] = 255
            y[200, 200:212] = 0
        lv, fails = self.medir(pintar)
        self.assertEqual(lv['frames'], 6)
        self.assertEqual((lv['clipped_pct'], lv['crushed_pct']), (0.0, 0.0))
        self.assertEqual(fails, [])

    def test_o_medidor_ve_o_valor_real_sem_conversao_de_faixa(self):
        # Se o caminho convertesse a faixa, 240 viraria 255 e reprovaria aqui.
        lv, fails = self.medir(lambda y: y.__setitem__((slice(0, 90), slice(None)), 240))
        self.assertEqual(lv['clipped_pct'], 0.0)
        self.assertEqual(fails, [])

    def test_clipagem_em_area_significativa_reprova(self):
        lv, fails = self.medir(lambda y: y.__setitem__((slice(0, 90), slice(None)), 255))
        self.assertEqual(lv['clipped_pct'], 100.0)
        self.assertTrue(any('estourado' in f for f in fails))

    def test_preto_esmagado_em_area_significativa_reprova(self):
        lv, fails = self.medir(lambda y: y.__setitem__((slice(0, 90), slice(None)), 2))
        self.assertEqual(lv['crushed_pct'], 100.0)
        self.assertTrue(any('esmagado' in f for f in fails))


if __name__ == '__main__':
    unittest.main()
