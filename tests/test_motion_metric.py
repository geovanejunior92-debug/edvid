"""Gate de movimento: mede onde há movimento e vale igual em qualquer fps."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'helpers'))
import check_inserts
import motion_metric
import review_final


def objeto_em_fundo_chapado(path, lado=200, velocidade=12, fps=60, dur=3):
    """O caso da animação 3D: fundo preto, objeto pequeno se movendo devagar."""
    subprocess.run(['ffmpeg', '-y', '-v', 'error',
                    '-f', 'lavfi', '-i', f'color=c=black:s=1080x750:r={fps}:d={dur}',
                    '-f', 'lavfi', '-i', f'testsrc2=s={lado}x{lado}:r={fps}:d={dur}',
                    '-filter_complex', f"[0][1]overlay=x='300+{velocidade}*t':y='200+{velocidade}*t'",
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '12', '-pix_fmt', 'yuv420p',
                    str(path)], check=True)


def filmagem(path, fps=60, dur=3):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                    f"testsrc2=s=1080x750:r={fps}:d={dur},crop=800:600:x='100+20*t':y=50",
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '12', '-pix_fmt', 'yuv420p',
                    str(path)], check=True)


def parado(path, fps=30, dur=3):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                    f'smptebars=s=1080x750:r={fps}:d={dur}',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(path)], check=True)


def reamostrar(origem, destino, fps):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(origem), '-vf', f'fps={fps}',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '12', '-pix_fmt', 'yuv420p',
                    str(destino)], check=True)


def media_vizinhos_antiga(path):
    """A métrica antiga: média do quadro inteiro, entre quadros vizinhos nativos."""
    out = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf',
                          'scale=160:-2,tblend=all_mode=difference,signalstats,'
                          'metadata=print:key=lavfi.signalstats.YAVG:file=-', '-f', 'null', '-'],
                         capture_output=True, text=True).stdout
    vals = [float(l.split('=')[-1]) for l in out.splitlines() if 'YAVG' in l][1:]
    return sum(vals) / len(vals)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)


class RegiaoTests(Base):
    def test_objeto_em_fundo_estatico_nao_reprova(self):
        v = self.dir / 'anim.mp4'
        objeto_em_fundo_chapado(v)
        self.assertLess(media_vizinhos_antiga(v), 0.6, 'o caso precisa reprovar pela métrica antiga')
        m = motion_metric.medir(v)
        self.assertGreater(m['nota'], 0.6)
        self.assertLess(m['area'], 0.25)

    def test_quadro_parado_continua_reprovando(self):
        v = self.dir / 'parado.mp4'
        parado(v)
        self.assertLess(motion_metric.medir(v)['nota'], 0.05)

    def test_detalhe_minusculo_em_quadro_parado_nao_salva_o_clipe(self):
        v = self.dir / 'logo.mp4'
        objeto_em_fundo_chapado(v, lado=60)
        m = motion_metric.medir(v)
        self.assertLess(m['area'], motion_metric.AREA_MINIMA)
        self.assertLess(m['nota'], 0.6)


class FpsTests(Base):
    def test_mesmo_clipe_da_a_mesma_nota_a_24_30_e_60(self):
        v60 = self.dir / 'v60.mp4'
        filmagem(v60)
        notas = {60: motion_metric.medir(v60)['nota']}
        for fps in (30, 24):
            v = self.dir / f'v{fps}.mp4'
            reamostrar(v60, v, fps)
            notas[fps] = motion_metric.medir(v)['nota']
        self.assertAlmostEqual(notas[30], notas[60], delta=notas[60] * 0.05)
        # a métrica antiga cai com o fps: é esse o defeito que a nota não pode ter
        self.assertLess(media_vizinhos_antiga(v60), 0.75 * media_vizinhos_antiga(self.dir / 'v30.mp4'))
        self.assertAlmostEqual(notas[24], notas[60], delta=notas[60] * 0.15)

    def test_o_veredito_no_limiar_nao_muda_com_o_fps(self):
        # devagar o bastante para a métrica antiga cair abaixo de 0,3 só a 60 fps
        v60 = self.dir / 'lento60.mp4'
        v30 = self.dir / 'lento30.mp4'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                        "gradients=s=1080x750:r=60:d=4:speed=0.002:c0=black:c1=white",
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '10', '-pix_fmt', 'yuv420p', str(v60)],
                       check=True)
        reamostrar(v60, v30, 30)
        a, b = motion_metric.medir(v60)['nota'], motion_metric.medir(v30)['nota']
        self.assertAlmostEqual(a, b, delta=max(a, b) * 0.1 + 0.01)


class GatesTests(Base):
    def rodar_check(self, nome):
        (self.dir / 'edit-data.json').write_text(json.dumps({'splitInserts': [
            {'src': nome, 'start': 1, 'end': 3.5, 'fit': 'contain'}]}))
        sys.argv = ['check_inserts', str(self.dir / 'edit-data.json')]
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida), self.assertRaises(SystemExit) as ctx:
            check_inserts.main()
        return ctx.exception.code, saida.getvalue()

    def test_check_inserts_aprova_a_animacao_e_reprova_o_parado(self):
        objeto_em_fundo_chapado(self.dir / 'anim.mp4')
        parado(self.dir / 'parado.mp4')
        self.assertEqual(self.rodar_check('anim.mp4')[0], 0)
        codigo, texto = self.rodar_check('parado.mp4')
        self.assertEqual(codigo, 1)
        self.assertIn('parado', texto)

    def test_review_final_passa_o_recorte_e_mede_por_regiao(self):
        v = self.dir / 'anim.mp4'
        objeto_em_fundo_chapado(v)
        self.assertGreater(review_final.motion(v, 0.5, 2.0, crop='crop=1080:460:0:0'), 0.3)
        parado(self.dir / 'parado.mp4')
        self.assertLess(review_final.motion(self.dir / 'parado.mp4', 0.5, 2.0, crop='crop=1080:460:0:0'), 0.05)


class RenderTests(unittest.TestCase):
    def test_4k_acima_de_30fps_limita_a_concorrencia(self):
        import studio_phase2
        cmd = studio_phase2.StudioPhase2.__new__(studio_phase2.StudioPhase2).build_render_command
        self.assertNotIn('--concurrency', cmd(Path('/tmp/f.mp4'), 2))
        com = cmd(Path('/tmp/f.mp4'), 2, 4)
        self.assertEqual(com[com.index('--concurrency') + 1], '4')
        self.assertEqual(studio_phase2.render_concurrency(2160, 3840, 60), 4)
        self.assertIsNone(studio_phase2.render_concurrency(2160, 3840, 30))
        self.assertIsNone(studio_phase2.render_concurrency(1080, 1920, 60))


if __name__ == '__main__':
    unittest.main()
