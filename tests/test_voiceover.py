"""A locução entra no volume certo, abaixa o som só durante a fala e não toca no vídeo.

Roda com mídia sintética do ffmpeg, sem VoiceStudio e sem vídeo do usuário.
"""
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile
import unittest

HELPERS = Path(__file__).resolve().parents[1] / 'helpers'
sys.path.insert(0, str(HELPERS))
import voiceover as vo


def ff(*args):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *args], check=True)


def video_hash(path: Path) -> str:
    out = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-c', 'copy',
                          '-f', 'data', '-'], capture_output=True, check=True)
    return hashlib.sha256(out.stdout).hexdigest()


def rms_db(path: Path, start: float, length: float) -> float:
    out = subprocess.run(['ffmpeg', '-hide_banner', '-ss', str(start), '-t', str(length), '-i', str(path),
                          '-af', 'volumedetect', '-f', 'null', '-'], capture_output=True, text=True)
    line = next(l for l in out.stderr.splitlines() if 'mean_volume' in l)
    return float(line.split('mean_volume:')[1].split()[0])


class Unidade(unittest.TestCase):
    def test_ganho_iguala_a_fonte_e_tem_teto(self):
        self.assertEqual(vo.match_gain(-20.0, -14.0), 6.0)
        self.assertEqual(vo.match_gain(-20.0, None), 6.0)
        self.assertEqual(vo.match_gain(-60.0, -10.0), vo.MAX_GAIN_DB)

    def test_filtro_sem_fonte_nao_usa_audio_do_video(self):
        self.assertNotIn('[0:a:0]', vo.build_filter(1.0, 2.0, 0.0, 12.0, keep_source=False))
        self.assertIn('[0:a:0]', vo.build_filter(1.0, 2.0, 0.0, 12.0, keep_source=True))


class Mixagem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.video = self.dir / 'corte.mp4'
        self.voz = self.dir / 'voz.wav'
        ff('-f', 'lavfi', '-i', 'testsrc=size=320x568:rate=30:duration=6',
           '-f', 'lavfi', '-i', 'sine=frequency=220:duration=6:sample_rate=48000',
           '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(self.video))
        ff('-f', 'lavfi', '-i', 'sine=frequency=880:duration=2:sample_rate=24000',
           '-ac', '1', str(self.voz))

    def tearDown(self):
        self.tmp.cleanup()

    def rodar(self, *extra, video=None):
        out = self.dir / 'saida.mp4'
        return out, subprocess.run(
            [sys.executable, str(HELPERS / 'voiceover.py'), 'mix', '--video', str(video or self.video),
             '--voiceover', str(self.voz), '-o', str(out), *extra],
            capture_output=True, text=True)

    def test_video_intacto_duracao_igual_e_fonte_preservada(self):
        antes = self.video.read_bytes()
        out, r = self.rodar('--at', '2')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(video_hash(out), video_hash(self.video))
        self.assertAlmostEqual(vo.duration(out), vo.duration(self.video), delta=0.1)
        self.assertEqual(self.video.read_bytes(), antes)

    def test_som_original_cai_so_durante_a_locucao(self):
        out, r = self.rodar('--at', '2', '--duck-db', '20')
        self.assertEqual(r.returncode, 0, r.stderr)
        bed = self.dir / 'bed.wav'
        ff('-i', str(out), '-af', 'lowpass=f=300,lowpass=f=300,lowpass=f=300', str(bed))
        fora = rms_db(bed, 0.5, 1.0)
        durante = rms_db(bed, 2.6, 0.8)
        depois = rms_db(bed, 4.8, 0.8)
        self.assertGreater(fora - durante, 12)
        self.assertAlmostEqual(fora, depois, delta=2)

    def test_recusa_locucao_que_passa_do_fim(self):
        _, r = self.rodar('--at', '5')
        self.assertEqual(r.returncode, 1)
        self.assertIn('passa do fim', r.stderr)

    def test_recusa_sobrescrever_o_video(self):
        r = subprocess.run(
            [sys.executable, str(HELPERS / 'voiceover.py'), 'mix', '--video', str(self.video),
             '--voiceover', str(self.voz), '-o', str(self.video)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)

    def test_video_sem_som_recebe_a_locucao(self):
        mudo = self.dir / 'mudo.mp4'
        ff('-i', str(self.video), '-an', '-c:v', 'copy', str(mudo))
        out, r = self.rodar('--at', '1', video=mudo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(vo.has_audio(out))


if __name__ == '__main__':
    unittest.main()
