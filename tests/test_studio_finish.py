import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
import studio_finish as finish


class FakeRunner:
    def __init__(self, cut: Path):
        self.cut = cut
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "format": {"duration": "4.000"},
                "streams": [
                    {"codec_type": "video", "width": 1080, "height": 1920,
                     "avg_frame_rate": "30/1"},
                    {"codec_type": "audio"},
                ],
            }), "")
        if "ebur128" in " ".join(command):
            return subprocess.CompletedProcess(command, 0, "", "Summary:\n  I: -15.0 LUFS\n  Peak: -2.0 dBFS")
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"rendered-video")
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1].endswith("qc_final.py"):
            return subprocess.CompletedProcess(command, 0, json.dumps({"fails": [], "warns": []}), "")
        if command[1].endswith("contact_sheet.py"):
            Path(command[command.index("-o") + 1]).write_bytes(b"sheet")
            return subprocess.CompletedProcess(command, 0, "made", "")
        raise AssertionError(command)


class StudioFinishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        (self.root / "edit").mkdir(parents=True)
        self.cut = self.root / "edit" / "cut.mp4"
        self.cut.write_bytes(b"approved-cut")
        (self.root / "media").mkdir()
        (self.root / "media" / "insert.jpg").write_bytes(b"image")
        (self.root / "media" / "music.wav").write_bytes(b"audio")
        self.runner = FakeRunner(self.cut)
        self.engine = finish.StudioFinish(self.root, runner=self.runner)

    def settings(self):
        return {
            "version": 1,
            "captions": {"mode": "manual", "cues": [
                {"start": 0.2, "end": 1.1, "text": "Legenda manual"},
            ]},
            "headline": {"enabled": True, "text": "Título seguro", "start": 0, "end": 1.5},
            "inserts": [{"file": "media/insert.jpg", "start": 1.5, "end": 2.5,
                         "layout": "split"}],
            "music": {"enabled": True, "file": "media/music.wav", "gainDb": -18,
                      "fadeIn": 0.2, "fadeOut": 0.4, "duckingDb": -10},
            "platform": "reels",
        }

    def test_save_versions_validated_settings_and_binds_current_cut(self):
        saved = self.engine.save(self.settings())
        self.assertEqual(saved["revision"], 1)
        self.assertTrue(saved["requiresApproval"])
        doc = json.loads((self.root / saved["settings"]).read_text())
        self.assertEqual(doc["cutFingerprint"]["sha256"], hashlib.sha256(b"approved-cut").hexdigest())
        self.assertEqual(doc["settingsHash"], saved["settingsHash"])

        changed = self.settings()
        changed["headline"]["text"] = "Outra"
        self.assertEqual(self.engine.save(changed)["revision"], 2)

    def test_save_rejects_assets_outside_project_and_invalid_intervals(self):
        settings = self.settings()
        settings["music"]["file"] = "/etc/passwd"
        with self.assertRaisesRegex(finish.FinishError, "dentro do projeto"):
            self.engine.save(settings)
        settings = self.settings()
        settings["inserts"][0]["end"] = 9
        with self.assertRaisesRegex(finish.FinishError, "duração do corte"):
            self.engine.save(settings)

    def test_imported_caption_cues_are_copied_into_revision(self):
        captions = self.root / "captions.json"
        captions.write_text(json.dumps([{"startMs": 100, "endMs": 900, "text": "Importada"}]))
        settings = self.settings()
        settings["captions"] = {"mode": "import", "file": "captions.json"}
        saved = self.engine.save(settings)
        doc = json.loads((self.root / saved["settings"]).read_text())
        self.assertEqual(doc["settings"]["captions"]["cues"],
                         [{"start": 0.1, "end": 0.9, "text": "Importada"}])
        self.assertNotIn("file", doc["settings"]["captions"])

    def test_approve_requires_explicit_consent_and_exact_revision_hash(self):
        saved = self.engine.save(self.settings())
        with self.assertRaisesRegex(finish.FinishError, "aprovação explícita"):
            self.engine.approve(saved["revision"], saved["settingsHash"], False)
        with self.assertRaisesRegex(finish.FinishError, "revisão ou o hash"):
            self.engine.approve(saved["revision"], "0" * 64, True)
        approved = self.engine.approve(saved["revision"], saved["settingsHash"], True)
        self.assertEqual(approved["cutFingerprint"], saved["cutFingerprint"])

    def test_cut_change_invalidates_finishing_approval_and_render(self):
        saved = self.engine.save(self.settings())
        self.engine.approve(saved["revision"], saved["settingsHash"], True)
        self.cut.write_bytes(b"different-cut")
        with self.assertRaisesRegex(finish.FinishError, "corte mudou"):
            self.engine.render(saved["revision"], saved["settingsHash"])

    def test_asset_change_invalidates_finishing_approval_and_render(self):
        saved = self.engine.save(self.settings())
        self.engine.approve(saved["revision"], saved["settingsHash"], True)
        (self.root / "media" / "music.wav").write_bytes(b"replacement")
        with self.assertRaisesRegex(finish.FinishError, "asset media/music.wav mudou"):
            self.engine.render(saved["revision"], saved["settingsHash"])

    def test_hdr_cut_is_blocked_instead_of_merely_retagged(self):
        original = self.runner

        def hdr_probe(command, **kwargs):
            if command[0] == "ffprobe":
                return subprocess.CompletedProcess(command, 0, json.dumps({
                    "format": {"duration": "4"},
                    "streams": [{"codec_type": "video", "width": 1080, "height": 1920,
                                 "avg_frame_rate": "30/1", "color_primaries": "bt2020",
                                 "color_transfer": "smpte2084"}],
                }), "")
            return original(command, **kwargs)

        self.engine.runner = hdr_probe
        with self.assertRaisesRegex(finish.FinishError, "HDR/wide gamut"):
            self.engine.save(self.settings())

    def test_hdr_video_insert_is_blocked_instead_of_retagged(self):
        video = self.root / "media" / "insert.mp4"
        video.write_bytes(b"video")
        settings = self.settings()
        settings["inserts"][0]["file"] = "media/insert.mp4"
        original = self.runner

        def hdr_insert(command, **kwargs):
            if command[0] == "ffprobe" and str(command[-1]).endswith("insert.mp4"):
                return subprocess.CompletedProcess(command, 0, json.dumps({
                    "streams": [{"color_primaries": "bt2020", "color_transfer": "smpte2084"}]
                }), "")
            return original(command, **kwargs)

        self.engine.runner = hdr_insert
        with self.assertRaisesRegex(finish.FinishError, "insert insert.mp4.*HDR"):
            self.engine.save(settings)

    def test_render_uses_rec709_overlays_ducking_qc_and_awaits_full_review(self):
        saved = self.engine.save(self.settings())
        self.engine.approve(saved["revision"], saved["settingsHash"], True)
        result = self.engine.render(saved["revision"], saved["settingsHash"])
        self.assertEqual(result["deliveryStatus"], "awaiting-visual-review")
        self.assertTrue((self.root / result["output"]).is_file())
        self.assertTrue(all((self.root / p).is_file() for p in result["reviewSheets"]))
        ffmpeg = next(c for c in self.runner.commands if c[0] == "ffmpeg" and "-filter_complex" in c)
        graph = ffmpeg[ffmpeg.index("-filter_complex") + 1]
        self.assertIn("sidechaincompress", graph)
        self.assertIn("overlay=", graph)
        self.assertIn("setpts=PTS-STARTPTS+1.5/TB", graph)
        self.assertNotIn("subtitles=", graph)
        self.assertNotIn("drawtext=", graph)
        self.assertIn("loudnorm=I=-10.0:TP=-1.0", graph)
        self.assertIn("alimiter=limit=0.891251:level=false:latency=true", graph)
        self.assertIn("-color_primaries", ffmpeg)
        self.assertEqual(ffmpeg[ffmpeg.index("-color_primaries") + 1], "bt709")
        qc = next(c for c in self.runner.commands if len(c) > 1 and c[1].endswith("qc_final.py"))
        self.assertIn("--cut", qc)
        self.assertIn("--captions", qc)

    def test_qc_failure_keeps_staging_and_does_not_publish(self):
        saved = self.engine.save(self.settings())
        self.engine.approve(saved["revision"], saved["settingsHash"], True)
        original = self.runner

        def fail_qc(command, **kwargs):
            if len(command) > 1 and command[1].endswith("qc_final.py"):
                return subprocess.CompletedProcess(command, 1, json.dumps({"fails": ["black"]}), "")
            return original(command, **kwargs)

        self.engine.runner = fail_qc
        with self.assertRaisesRegex(finish.FinishError, "QC final reprovou"):
            self.engine.render(saved["revision"], saved["settingsHash"])
        self.assertEqual(list((self.root / "edit" / "studio-finish" / "renders").glob("*")), [])
        self.assertTrue(list((self.root / "edit" / "studio-finish" / "staging").glob("*/final.mp4")))

    def test_review_approval_requires_exact_output_hash_and_full_video_confirmation(self):
        saved = self.engine.save(self.settings())
        self.engine.approve(saved["revision"], saved["settingsHash"], True)
        rendered = self.engine.render(saved["revision"], saved["settingsHash"])
        with self.assertRaisesRegex(finish.FinishError, "revisão integral"):
            self.engine.review_approve(rendered["outputHash"], False)
        with self.assertRaisesRegex(finish.FinishError, "hash"):
            self.engine.review_approve("0" * 64, True)
        reviewed = self.engine.review_approve(rendered["outputHash"], True)
        self.assertEqual(reviewed["deliveryStatus"], "approved")

    def test_identical_rerender_preserves_both_published_outputs(self):
        saved = self.engine.save(self.settings())
        self.engine.approve(saved["revision"], saved["settingsHash"], True)
        first = self.engine.render(saved["revision"], saved["settingsHash"])
        second = self.engine.render(saved["revision"], saved["settingsHash"])
        self.assertEqual(first["outputHash"], second["outputHash"])
        self.assertNotEqual(first["output"], second["output"])
        self.assertTrue((self.root / first["output"]).is_file())
        self.assertTrue((self.root / second["output"]).is_file())
        self.assertEqual(second["deliveryStatus"], "awaiting-visual-review")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg não disponível")
class StudioFinishRealSmokeTests(unittest.TestCase):
    def test_real_ffmpeg_renders_all_supported_layers_in_sdr_rec709(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "project"
            edit = root / "edit"
            edit.mkdir(parents=True)
            cut = edit / "cut.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=600:sample_rate=48000", "-t", "2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cut),
            ], check=True)
            image = root / "insert.png"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "color=c=blue:size=320x284", "-frames:v", "1", str(image)], check=True)
            music = root / "music.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "sine=frequency=220:sample_rate=48000", "-t", "2", str(music)], check=True)
            engine = finish.StudioFinish(root)
            saved = engine.save({
                "version": 1,
                "captions": {"mode": "manual", "cues": [{"start": .3, "end": 1.2, "text": "Teste real"}]},
                "headline": {"enabled": True, "text": "Título", "start": 0, "end": .8},
                "inserts": [{"file": "insert.png", "start": 1.2, "end": 1.8, "layout": "split"}],
                "music": {"enabled": True, "file": "music.wav", "gainDb": -24,
                          "fadeIn": .1, "fadeOut": .2, "duckingDb": -10},
                "platform": "reels",
            })
            engine.approve(saved["revision"], saved["settingsHash"], True)
            # Keep this smoke independent of qc_final's strict visual thresholds.
            command, _ = engine.build_render_command(json.loads((root / saved["settings"]).read_text()),
                                                      edit / "smoke.mp4")
            subprocess.run(command, check=True, capture_output=True)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                    "format=duration:stream=codec_type,color_primaries,color_transfer,color_space",
                                    "-of", "json", str(edit / "smoke.mp4")],
                                   check=True, capture_output=True, text=True)
            info = json.loads(probe.stdout)
            self.assertAlmostEqual(float(info["format"]["duration"]), 2.0, delta=0.08)
            stream = next(x for x in info["streams"] if x.get("codec_type") == "video")
            self.assertEqual(stream["color_primaries"], "bt709")
            self.assertEqual(stream["color_transfer"], "bt709")
            self.assertEqual(stream["color_space"], "bt709")


if __name__ == "__main__":
    unittest.main()
