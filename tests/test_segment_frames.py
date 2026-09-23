"""Segmento de vídeo com o número EXATO de quadros, mesmo em fonte VFR (2026-09-22).

Uma gravação do iPhone reexportada pelo CapCut (~59,98 fps, quadros de duração
variável) fazia cada segmento sair com 2 quadros a mais. O J-cut posiciona o som
pela duração planejada e a imagem pela real, então o erro somava a cada emenda:
+0,9 s de som adiantado no fim de um corte de 17 takes.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))

import render  # noqa: E402


def _frames(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg ausente")
class SegmentFrameCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.src = cls.tmp / "vfr.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x568:r=60:d=8",
             "-f", "lavfi", "-i", "sine=f=440:d=8",
             "-vf", "setpts='(N+0.35*sin(N*0.7))/(59.98*TB)'", "-fps_mode", "vfr",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
             str(cls.src)], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_vfr_segments_have_the_planned_frame_count(self):
        old = render.NATIVE_FPS
        render.NATIVE_FPS = False
        try:
            for i, start in enumerate((1.23, 2.41, 3.07)):
                out = self.tmp / f"seg{i}.mp4"
                render.extract_segment(self.src, start, 3.367, "", out,
                                       keep_resolution=True, streams="v")
                self.assertEqual(_frames(out), round(3.367 * 30), f"início {start}")
        finally:
            render.NATIVE_FPS = old


if __name__ == "__main__":
    unittest.main()
