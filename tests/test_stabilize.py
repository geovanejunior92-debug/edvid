"""Verdade-terrestre sintética: tremida conhecida entra, a saída é medida.

No material real a tremida é pequena e um erro de sinal ou de origem some dentro
do ruído. Aqui o sinal é forte e conhecido, e o número que conta sai do arquivo
final, não da conta que a própria correção faz.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import stabilize

W, H, FPS, QUADROS = 480, 854, 30, 60


def clipe_tremido(destino: Path) -> None:
    """Cena fixa com random walk conhecido de translação e rotação."""
    rng = np.random.default_rng(7)
    cena = cv2.GaussianBlur(rng.integers(0, 255, (H, W, 3), dtype=np.uint8), (0, 0), 2)
    cena = cv2.normalize(cena, None, 0, 255, cv2.NORM_MINMAX)
    passos = rng.normal(0, [1.6, 1.6, 0.004], (QUADROS, 3))
    caminho = np.cumsum(passos, axis=0)
    caminho -= caminho.mean(axis=0)
    enc = subprocess.Popen(
        ['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
         '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-crf', '10', '-preset', 'veryfast',
         '-pix_fmt', 'yuv420p', str(destino)], stdin=subprocess.PIPE)
    for dx, dy, da in caminho:
        m = cv2.getRotationMatrix2D((W / 2, H / 2), float(np.degrees(da)), 1.0)
        m[0, 2] += dx
        m[1, 2] += dy
        enc.stdin.write(cv2.warpAffine(cena, m, (W, H), borderMode=cv2.BORDER_REFLECT).tobytes())
    enc.stdin.close()
    enc.wait()


class TremidaSinteticaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        raiz = Path(cls.tmp.name)
        fonte = raiz / 'tremido.mp4'
        clipe_tremido(fonte)
        argv = ['stabilize.py', str(fonte), '--edit-dir', str(raiz), '--max-zoom', '1.25']
        with mock.patch.object(sys, 'argv', argv):
            assert stabilize.main() == 0
        cls.fonte = fonte
        cls.saida = raiz / 'stab' / 'tremido.mp4'
        cls.report = json.loads((raiz / 'stab' / 'tremido.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_tremida_injetada_foi_detectada(self):
        self.assertGreater(self.report['shake_px_before'], 3.0)

    def test_a_saida_medida_tira_quase_toda_a_tremida(self):
        # 25% do original: a versão com sinal e origem errados ficava em 43%.
        self.assertLess(self.report['shake_px_after'], self.report['shake_px_before'] * 0.25)

    def test_a_rotacao_tambem_sai(self):
        # A métrica do relatório é só translação: um sinal de rotação invertido
        # passa nela. Por isso a rotação é medida à parte, nos dois arquivos.
        def rotacao(video):
            return float(np.sqrt(np.mean(stabilize.analyze(video, stabilize.probe(video))[:, 2] ** 2)))
        self.assertLess(rotacao(self.saida), rotacao(self.fonte) * 0.25)

    def test_o_relatorio_guarda_o_medido_e_nao_o_previsto(self):
        medido = stabilize.measure_output(self.saida)
        self.assertAlmostEqual(self.report['shake_px_after'], medido, places=3)
        self.assertIn('shake_px_after_predicted', self.report)


if __name__ == '__main__':
    unittest.main()
