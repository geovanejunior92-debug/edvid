import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
import studio_pipeline as pipeline


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.fail_verify = False

    def __call__(self, command, **_kwargs):
        self.calls.append(command)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, "24/1\n", "")
        helper = Path(command[1]).name if len(command) > 1 else ""
        if helper == "transcribe.py":
            source = Path(command[2])
            edit = Path(command[command.index("--edit-dir") + 1])
            write_json(edit / "transcripts" / f"{source.stem}.json", aligned_transcript())
        elif helper == "render.py":
            edl_path = Path(command[2])
            edl = json.loads(edl_path.read_text())
            edl["ranges"][0]["end"] = round(edl["ranges"][0]["end"] - 0.01, 3)
            edl["jcut_timeline"] = [{"synthetic": True}]
            edl["total_duration_s"] = round(sum(r["end"] - r["start"] for r in edl["ranges"]), 3)
            write_json(edl_path, edl)
            Path(command[command.index("-o") + 1]).write_bytes(b"good-cut")
        elif helper == "speech_regions.py":
            return subprocess.CompletedProcess(command, 0, "speech regions:\n  0.90 -> 1.40\n  2.30 -> 3.30\n", "")
        elif helper == "detect_color.py":
            return subprocess.CompletedProcess(command, 0, json.dumps({"profile": "rec709", "confidence": "high"}), "")
        elif helper == "shot_check.py":
            return subprocess.CompletedProcess(command, 0, json.dumps({"flags": 0}), "")
        elif helper == "verify_cut.py" and self.fail_verify:
            return subprocess.CompletedProcess(command, 1, "CHECK failed", "")
        elif helper == "fillers.py":
            edl = Path(command[2])
            data = json.loads(edl.read_text())
            data["ranges"][0]["end"] -= 0.25
            write_json(edl, data)
        return subprocess.CompletedProcess(command, 0, "ok", "")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def aligned_transcript(backend="whisperx/large-v3", source=b"source"):
    return {"_transcription_backend": backend, "_cache": {"sha256": hashlib.sha256(source).hexdigest()}, "words": [
        {"type": "word", "text": "um", "start": 1.0, "end": 1.3},
        {"type": "spacing", "text": " ", "start": 1.3, "end": 2.4},
        {"type": "word", "text": "dois", "start": 2.4, "end": 2.8},
        {"type": "word", "text": "três", "start": 2.9, "end": 3.2},
    ]}


class StudioPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir()
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"source")
        self.runner = FakeRunner()
        self.pipe = pipeline.StudioPipeline(self.root, self.runner)

    def test_paths_cannot_escape_project_or_use_skill_root(self):
        outside = Path(self.tmp.name) / "outside.mp4"
        outside.write_bytes(b"x")
        with self.assertRaisesRegex(pipeline.PipelineError, "dentro do projeto"):
            self.pipe.transcribe(str(outside), "pt", "large-v3-turbo")
        with self.assertRaisesRegex(pipeline.PipelineError, "instalação"):
            pipeline.StudioPipeline(pipeline.SKILL_ROOT)

    def test_fractional_output_fps_is_preserved(self):
        self.assertEqual(pipeline._parse_fps("30000/1001"), 29.97003)

    def test_rejects_edit_symlink_outside_project_before_any_write(self):
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        linked = Path(self.tmp.name) / "linked-project"
        linked.mkdir()
        (linked / "edit").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(pipeline.PipelineError, "dentro do projeto"):
            pipeline.StudioPipeline(linked)
        self.assertEqual(list(other.iterdir()), [])

    def test_status_is_read_only_and_does_not_create_edit(self):
        clean = Path(self.tmp.name) / "clean"
        clean.mkdir()
        result = pipeline.StudioPipeline(clean).status()
        self.assertTrue(result["ok"])
        self.assertFalse((clean / "edit").exists())

    def test_brief_accepts_text_and_project_json_file(self):
        result = self.pipe.save_brief("  Minha fala  ", None)
        self.assertTrue(result["ok"])
        self.assertEqual(json.loads((self.pipe.data / "brief.json").read_text())["script"], "Minha fala")
        write_json(self.root / "brief-input.json", {"roteiro": "Outra fala"})
        self.pipe.save_brief(None, "brief-input.json")
        self.assertEqual(json.loads((self.pipe.data / "brief.json").read_text())["script"], "Outra fala")

    def test_transcribe_uses_whisperx_helper_and_registers_only_existing_output(self):
        result = self.pipe.transcribe("source.mp4", "pt", "large-v3-turbo")
        self.assertEqual(result["backend"], "whisperx/large-v3")
        command = self.runner.calls[0]
        self.assertEqual(Path(command[1]).name, "transcribe.py")
        self.assertIn("--language", command)
        state = json.loads(self.pipe.state_path.read_text())
        self.assertEqual(state["lastCommand"]["transcript"], "edit/transcripts/source.json")

    def test_proposal_splits_only_at_long_pause_and_rejects_unaligned(self):
        write_json(self.edit_transcript, aligned_transcript())
        result = self.pipe.propose_cut("source.mp4", 0.65)
        plan = json.loads((self.pipe.data / "plans" / "rev-1.json").read_text())
        self.assertEqual(result["proposal"], pipeline.PROPOSAL_LABEL)
        self.assertEqual(len(plan["edl"]["ranges"]), 2)
        self.assertEqual(plan["edl"]["ranges"][0]["start"], 0.87)
        self.assertEqual(plan["edl"]["ranges"][0]["end"], 1.46)
        self.assertEqual(plan["hash"], pipeline._digest(plan["edl"]))
        write_json(self.edit_transcript, aligned_transcript("parakeet/UNALIGNED"))
        with self.assertRaisesRegex(pipeline.PipelineError, "UNALIGNED"):
            self.pipe.propose_cut("source.mp4")

    def test_proposal_merges_groups_in_same_acoustic_region_and_clamps_eof(self):
        write_json(self.edit_transcript, aligned_transcript())
        original = self.runner.__call__
        def broad_region(command, **kwargs):
            if Path(command[1]).name == "speech_regions.py":
                return subprocess.CompletedProcess(command, 0, "  0.90 -> 3.22\n", "")
            return original(command, **kwargs)
        self.pipe.runner = broad_region
        result = self.pipe.propose_cut("source.mp4")
        plan = json.loads((self.pipe.data / "plans" / "rev-1.json").read_text())
        self.assertEqual(result["ranges"], 1)
        self.assertEqual(plan["edl"]["ranges"][0]["end"], 3.22)

    def test_proposal_rejects_stale_or_unbound_transcript(self):
        transcript = aligned_transcript()
        transcript["_cache"]["sha256"] = hashlib.sha256(b"old-source").hexdigest()
        write_json(self.edit_transcript, transcript)
        with self.assertRaisesRegex(pipeline.PipelineError, "não pertence"):
            self.pipe.propose_cut("source.mp4")
        transcript.pop("_cache")
        write_json(self.edit_transcript, transcript)
        with self.assertRaisesRegex(pipeline.PipelineError, "transcreva novamente"):
            self.pipe.propose_cut("source.mp4")

    @property
    def edit_transcript(self):
        return self.root / "edit" / "transcripts" / "source.json"

    def _proposal(self):
        write_json(self.edit_transcript, aligned_transcript())
        result = self.pipe.propose_cut("source.mp4")
        return result["revision"], result["planHash"]

    def test_approval_requires_flag_and_exact_revision_hash(self):
        revision, digest = self._proposal()
        with self.assertRaisesRegex(pipeline.PipelineError, "--approve"):
            self.pipe.approve_plan(revision, digest, False)
        with self.assertRaisesRegex(pipeline.PipelineError, "hash"):
            self.pipe.approve_plan(revision, "0" * 64, True)
        result = self.pipe.approve_plan(revision, digest, True)
        self.assertEqual((result["revision"], result["planHash"]), (revision, digest))

    def test_render_never_runs_without_approval_and_promotes_only_verified_stage(self):
        revision, digest = self._proposal()
        with self.assertRaisesRegex(pipeline.PipelineError, "aprovada"):
            self.pipe.render_cut(revision, digest)
        self.pipe.approve_plan(revision, digest, True)
        live = self.root / "edit" / "cut.mp4"
        live.write_bytes(b"previous-good")
        self.runner.fail_verify = True
        with self.assertRaisesRegex(pipeline.PipelineError, "CHECK"):
            self.pipe.render_cut(revision, digest)
        self.assertEqual(live.read_bytes(), b"previous-good")
        self.runner.fail_verify = False
        write_json(self.root / "edit" / "state.json", {"project": "Keep me", "video": "old.mp4"})
        result = self.pipe.render_cut(revision, digest)
        self.assertTrue(result["verified"])
        self.assertEqual(live.read_bytes(), b"good-cut")
        published_edl = json.loads((self.root / "edit" / "edl.json").read_text())
        self.assertEqual(published_edl["jcut_timeline"], [{"synthetic": True}])
        self.assertEqual(result["renderedEdlHash"], pipeline._digest(published_edl))
        preview_state = json.loads((self.root / "edit" / "state.json").read_text())
        self.assertEqual(preview_state["project"], "Keep me")
        self.assertEqual((preview_state["video"], preview_state["edl"], preview_state["fps"]),
                         ("cut.mp4", "edl.json", 24.0))
        self.assertEqual(preview_state["renderedAt"], result["renderedAt"])
        self.assertEqual(result["fps"], 24.0)
        backups = list((self.pipe.data / "renders").glob("cut-*.mp4"))
        self.assertEqual([x.read_bytes() for x in backups], [b"previous-good"])

    def test_render_rejects_source_replaced_after_approval(self):
        revision, digest = self._proposal()
        self.pipe.approve_plan(revision, digest, True)
        self.source.write_bytes(b"different-source")
        with self.assertRaisesRegex(pipeline.PipelineError, "fonte mudou"):
            self.pipe.render_cut(revision, digest)
        self.assertFalse(any(Path(call[1]).name == "render.py" for call in self.runner.calls))

    def test_render_blocks_log_source_without_approved_grade(self):
        revision, digest = self._proposal()
        self.pipe.approve_plan(revision, digest, True)
        original = self.runner.__call__
        def log_color(command, **kwargs):
            if Path(command[1]).name == "detect_color.py":
                return subprocess.CompletedProcess(command, 0, json.dumps({"profile": "log_desconhecido", "confidence": "high"}), "")
            return original(command, **kwargs)
        self.pipe.runner = log_color
        with self.assertRaisesRegex(pipeline.PipelineError, "LOG/HDR"):
            self.pipe.render_cut(revision, digest)

    def test_cli_mutations_take_nonblocking_project_lock(self):
        args = pipeline.parser().parse_args(["--root", str(self.root), "--action", "save-brief", "--script", "fala"])
        locked = pipeline.StudioPipeline(self.root)
        with locked.mutation_lock():
            with self.assertRaisesRegex(pipeline.PipelineError, "em execução"):
                pipeline.dispatch(args)

    def test_apply_preview_edits_has_bounded_undo_redo(self):
        revision, digest = self._proposal()
        self.pipe.approve_plan(revision, digest, True)
        write_json(self.root / "edit" / "edl.json", json.loads((self.pipe.data / "approved.json").read_text())["edl"])
        write_json(self.root / "edit" / "preview_edits.json", {"textCuts": [{"start": 1, "end": 1.1}]})
        initial = json.loads((self.root / "edit" / "edl.json").read_text())
        applied = self.pipe.apply_preview_edits()
        self.assertNotEqual(applied["beforeHash"], applied["afterHash"])
        self.assertTrue(applied["requiresApproval"])
        self.assertFalse((self.pipe.data / "approved.json").exists())
        with self.assertRaisesRegex(pipeline.PipelineError, "aprovada"):
            self.pipe.render_cut(revision, digest)
        undone = self.pipe.restore("undo")
        self.assertTrue(undone["requiresApproval"])
        self.assertEqual(json.loads((self.root / "edit" / "edl.json").read_text()), initial)
        redone = self.pipe.restore("redo")
        self.assertTrue(redone["requiresApproval"])
        self.assertNotEqual(json.loads((self.root / "edit" / "edl.json").read_text()), initial)

    def test_cli_errors_are_json_and_persisted(self):
        code = pipeline.main(["--root", str(self.root), "--action", "approve-plan",
                              "--revision", "1", "--plan-hash", "abc"])
        self.assertEqual(code, 1)
        state = json.loads(self.pipe.state_path.read_text())
        self.assertFalse(state["lastCommand"]["ok"])


if __name__ == "__main__":
    unittest.main()
