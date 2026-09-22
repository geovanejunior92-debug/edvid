"""Regra de 2026-09-22: a edição preserva a resolução da fonte (4K do iPhone sai 4K)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))

import render  # noqa: E402
import studio_phase2  # noqa: E402


class RenderScaleTests(unittest.TestCase):
    def test_same_size_is_scale_one(self):
        self.assertEqual(studio_phase2.render_scale(1080, 1920, 1080, 1920), 1)

    def test_4k_cut_renders_the_1080_layout_at_2x(self):
        self.assertEqual(studio_phase2.render_scale(1080, 1920, 2160, 3840), 2)

    def test_non_integer_or_other_aspect_is_refused(self):
        self.assertIsNone(studio_phase2.render_scale(1080, 1920, 1620, 2880))
        self.assertIsNone(studio_phase2.render_scale(1080, 1920, 2160, 1920))


class RenderCommandTests(unittest.TestCase):
    def cmd(self, scale):
        p = studio_phase2.StudioPhase2.__new__(studio_phase2.StudioPhase2)
        return p.build_render_command(Path("/tmp/final.mp4"), scale)

    def test_scale_flag_only_when_cut_is_bigger(self):
        self.assertNotIn("--scale", self.cmd(1))
        c = self.cmd(2)
        self.assertEqual(c[c.index("--scale") + 1], "2")

    def test_frames_are_not_rendered_at_remotion_default_quality(self):
        c = self.cmd(1)
        self.assertEqual(c[c.index("--jpeg-quality") + 1], "95")


class NativeFpsTests(unittest.TestCase):
    def rate(self, fps):
        with mock.patch.object(render, "source_fps", return_value=fps):
            return render.native_fps_rate(Path("x.mov"))

    def test_iphone_vfr_60_locks_to_a_standard_rate(self):
        self.assertEqual(self.rate(59.98), "60")
        self.assertEqual(self.rate(59.94), "60000/1001")
        self.assertEqual(self.rate(29.97), "30000/1001")

    def test_unknown_fps_falls_back_to_30(self):
        self.assertEqual(self.rate(0.0), "30")


if __name__ == "__main__":
    unittest.main()
