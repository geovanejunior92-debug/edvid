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


class NativeFpsDefaultTests(unittest.TestCase):
    """2026-09-22: com o template independente de fps, 60 continua 60 também no short-form."""

    def test_native_fps_is_the_default(self):
        self.assertTrue(render.NATIVE_FPS)

    def test_old_mode_is_opt_in(self):
        src = (Path(render.__file__)).read_text()
        self.assertIn('"--shortform-fps"', src)
        self.assertIn("NATIVE_FPS = not args.shortform_fps", src)

    def test_jcut_defaults_keep_their_duration_at_60(self):
        two = {"ranges": [{}, {}]}
        at30 = render.jcut_settings(two, 30)
        at60 = render.jcut_settings(two, 60)
        self.assertEqual((at30["lead_frames"], at30["tail_trim_frames"]), (5, 2))
        self.assertEqual((at60["lead_frames"], at60["tail_trim_frames"]), (10, 4))
        self.assertEqual(render.jcut_settings(two, 24)["lead_frames"], 5)

    def test_explicit_jcut_frames_are_literal(self):
        cfg = render.jcut_settings({"ranges": [{}, {}], "jcut": {"lead_frames": 3}}, 60)
        self.assertEqual(cfg["lead_frames"], 3)


TEMPLATE_SRC = Path(__file__).resolve().parents[1] / "assets" / "shortform" / "src"


class TemplateFpsIndependenceTests(unittest.TestCase):
    """As durações do template são contagens a 30fps convertidas por F() (fps.ts)."""

    def test_helper_exists(self):
        src = (TEMPLATE_SRC / "fps.ts").read_text()
        self.assertIn("export const useF", src)
        self.assertIn("fps === BASE_FPS ? n", src)  # 30fps fica intocado

    def test_animated_files_use_the_helper(self):
        for name in ("Main.tsx", "CustomGraphics.tsx", "StackedCaptions.tsx", "ScatterCaptions.tsx"):
            self.assertIn("from './fps'", (TEMPLATE_SRC / name).read_text(), name)

    def test_no_literal_sequence_timings(self):
        import re
        for tsx in TEMPLATE_SRC.glob("*.tsx"):
            body = tsx.read_text()
            self.assertIsNone(re.search(r"(?:from|durationInFrames)=\{[1-9]", body), tsx.name)


if __name__ == "__main__":
    unittest.main()
