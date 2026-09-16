"""Contrato do preset técnico VideoPro Original."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

from grade import get_preset  # noqa: E402


class VideoProPresetTests(unittest.TestCase):
    def test_exposes_all_five_stages_without_creative_lut(self):
        chain = get_preset("videopro_original")
        for filter_name in ("hqdn3d=", "smartblur=", "eq=", "curves=", "unsharp="):
            self.assertIn(filter_name, chain)
        self.assertNotIn("lut3d=", chain)
        self.assertNotIn("colortemperature=", chain)

    def test_filter_chain_renders_and_keeps_frame_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "frame.png"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=1",
                    "-frames:v", "1", "-vf", get_preset("videopro_original"),
                    str(output),
                ],
                check=True,
            )
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(probe.stdout.strip(), "640x360")


if __name__ == "__main__":
    unittest.main()
