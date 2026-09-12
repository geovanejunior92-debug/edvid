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
        self.fail_speech = False

    def __call__(self, command, **_kwargs):
        self.calls.append(command)
        if command[0] == "ffprobe":
            if "format=duration" in command:
                return subprocess.CompletedProcess(command, 0, "4.0\n", "")
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
            if self.fail_speech:
                return subprocess.CompletedProcess(command, 1, "", "acoustic failure")
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

    def test_render_invalid_preview_state_does_not_move_previous_cut(self):
        revision, digest = self._proposal()
        self.pipe.approve_plan(revision, digest, True)
        live = self.root / "edit" / "cut.mp4"
        live.write_bytes(b"previous-good")
        (self.root / "edit" / "state.json").write_text("[]")
        with self.assertRaisesRegex(pipeline.PipelineError, "state.json"):
            self.pipe.render_cut(revision, digest)
        self.assertEqual(live.read_bytes(), b"previous-good")
        self.assertFalse(list((self.pipe.data / "renders").glob("cut-*.mp4")))

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
        write_json(self.root / "edit" / "preview_edits.json", {"textCuts": [{"start": .03, "end": .53}]})
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

    def _published_edl(self):
        revision, digest = self._proposal()
        self.pipe.approve_plan(revision, digest, True)
        edl = json.loads((self.pipe.data / "approved.json").read_text())["edl"]
        edl["ranges"][0]["gain_db"] = -2.5
        write_json(self.root / "edit" / "edl.json", edl)
        return edl

    def test_preview_manual_trim_and_removal_preserve_metadata(self):
        edl = self._published_edl()
        first, second = edl["ranges"]
        saved_first = {"source": first["source"], "beat": first["beat"], "start": 0.8, "end": first["end"]}
        payload = {"type": "timeline-edits", "edl": {
            "ranges": [saved_first],
            "removed": [{k: second[k] for k in ("source", "beat", "start", "end")}],
            "changes": [{"source": first["source"], "beat": first["beat"],
                         "from": {"start": first["start"], "end": first["end"]},
                         "to": {"start": 0.8, "end": first["end"]}}],
        }}
        write_json(self.root / "edit" / "preview_edits.json", payload)
        result = self.pipe.apply_preview_edits()
        current = json.loads((self.root / "edit" / "edl.json").read_text())
        self.assertEqual(len(current["ranges"]), 1)
        self.assertEqual(current["ranges"][0]["gain_db"], -2.5)
        self.assertEqual(current["ranges"][0]["start"], 0.8)
        self.assertTrue(result["requiresApproval"])
        self.assertFalse((self.root / "edit" / "preview_edits.json").exists())
        self.assertTrue((self.pipe.data / "consumed-previews" / f"{result['previewHash']}.json").exists())

    def test_preview_rejects_stale_malformed_and_duplicate_payloads(self):
        edl = self._published_edl()
        path = self.root / "edit" / "preview_edits.json"
        write_json(path, {"type": "timeline-edits", "timelineFingerprint": "stale", "textCuts": [{"start": .1, "end": .2}]})
        with self.assertRaisesRegex(pipeline.PipelineError, "outra revisão"):
            self.pipe.apply_preview_edits()
        write_json(path, {"type": "timeline-edits", "edl": {"ranges": "bad"}})
        with self.assertRaisesRegex(pipeline.PipelineError, "malformados"):
            self.pipe.apply_preview_edits()
        payload = {"type": "timeline-edits", "textCuts": [{"renderedStart": .03, "renderedEnd": .53}]}
        write_json(path, payload)
        self.pipe.apply_preview_edits()
        write_json(path, payload)
        with self.assertRaisesRegex(pipeline.PipelineError, "já foram aplicados"):
            self.pipe.apply_preview_edits()

    def test_simultaneous_manual_trim_and_text_cut_use_original_rendered_mapping(self):
        edl = self._published_edl()
        first, second = edl["ranges"]
        payload = {"type": "timeline-edits", "edl": {
            "ranges": [
                {"source": first["source"], "beat": first["beat"], "start": .8, "end": first["end"]},
                {k: second[k] for k in ("source", "beat", "start", "end")},
            ], "removed": [], "changes": [{"source": first["source"], "beat": first["beat"],
                "from": {"start": first["start"], "end": first["end"]},
                "to": {"start": .8, "end": first["end"]}}]},
            "textCuts": [{"renderedStart": .62, "renderedEnd": 1.62, "text": "dois três"}]}
        write_json(self.root / "edit" / "preview_edits.json", payload)
        self.pipe.apply_preview_edits()
        current = json.loads((self.root / "edit" / "edl.json").read_text())
        self.assertEqual(current["ranges"][0]["start"], .8)
        self.assertEqual(len(current["ranges"]), 1)

    def test_preview_validation_failure_never_mutates_live_edl_or_history(self):
        edl = self._published_edl()
        before = (self.root / "edit" / "edl.json").read_bytes()
        write_json(self.root / "edit" / "preview_edits.json",
                   {"type": "timeline-edits", "textCuts": [{"renderedStart": .1, "renderedEnd": .2}]})
        self.runner.fail_speech = True
        with self.assertRaisesRegex(pipeline.PipelineError, "acoustic failure"):
            self.pipe.apply_preview_edits()
        self.assertEqual((self.root / "edit" / "edl.json").read_bytes(), before)
        self.assertFalse((self.pipe.data / "undo.json").exists())
        self.assertTrue((self.root / "edit" / "preview_edits.json").exists())

    def test_preview_rejects_nonfinite_and_out_of_source_trims(self):
        edl = self._published_edl()
        first, second = edl["ranges"]
        def payload(end):
            return {"type": "timeline-edits", "edl": {"ranges": [
                {"source": first["source"], "beat": first["beat"], "start": first["start"], "end": end},
                {k: second[k] for k in ("source", "beat", "start", "end")},
            ], "removed": [], "changes": [{"source": first["source"], "beat": first["beat"],
                "from": {"start": first["start"], "end": first["end"]},
                "to": {"start": first["start"], "end": end}}]}}
        path = self.root / "edit" / "preview_edits.json"
        write_json(path, payload(float("nan")))
        with self.assertRaisesRegex(pipeline.PipelineError, "inválido"):
            self.pipe.apply_preview_edits()
        write_json(path, payload(4.5))
        with self.assertRaisesRegex(pipeline.PipelineError, "duração física"):
            self.pipe.apply_preview_edits()

    def test_text_selection_cannot_silently_expand_over_neighboring_words(self):
        edl = self._published_edl()
        write_json(self.root / "edit" / "preview_edits.json", {
            "type": "timeline-edits", "textCuts": [{"renderedStart": .1, "renderedEnd": .2}]})
        with self.assertRaisesRegex(pipeline.PipelineError, "fala vizinha"):
            self.pipe.apply_preview_edits()
        self.assertEqual(json.loads((self.root / "edit" / "edl.json").read_text()), edl)
        self.assertTrue((self.root / "edit" / "preview_edits.json").exists())

    def test_same_beat_trims_validate_each_actual_range(self):
        edl = self._published_edl()
        for r in edl["ranges"]:
            r["beat"] = ""
        write_json(self.root / "edit" / "edl.json", edl)
        first, second = edl["ranges"]
        saved = [{k: r[k] for k in ("source", "beat", "start", "end")} for r in edl["ranges"]]
        saved[1]["start"] = 2.8
        write_json(self.root / "edit" / "preview_edits.json", {
            "type": "timeline-edits", "edl": {"ranges": saved, "removed": [], "changes": [{
                "source": second["source"], "beat": "",
                "from": {"start": second["start"], "end": second["end"]},
                "to": {"start": 2.8, "end": second["end"]}}]}})
        with self.assertRaisesRegex(pipeline.PipelineError, "dentro de fala"):
            self.pipe.apply_preview_edits()
        self.assertEqual(json.loads((self.root / "edit" / "edl.json").read_text()), edl)

    def test_cli_errors_are_json_and_persisted(self):
        code = pipeline.main(["--root", str(self.root), "--action", "approve-plan",
                              "--revision", "1", "--plan-hash", "abc"])
        self.assertEqual(code, 1)
        state = json.loads(self.pipe.state_path.read_text())
        self.assertFalse(state["lastCommand"]["ok"])


if __name__ == "__main__":
    unittest.main()


class AlignScriptTests(unittest.TestCase):
    """A ação de alinhamento dentro do Studio.

    O que ela NÃO pode fazer é decidir: linha regravada tem que voltar com as
    tomadas para o usuário escolher, e linha não gravada tem que voltar
    marcada. É a regra de revisão humana antes do corte virar editorial.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "proj"
        (self.root / "edit" / "transcripts").mkdir(parents=True)
        self.pipe = pipeline.StudioPipeline(self.root)

    def _words(self, frase, inicio=0.0):
        out, t = [], inicio
        for palavra in frase.split():
            out.append({"text": palavra, "start": round(t, 3), "end": round(t + 0.4, 3)})
            t += 0.4
        return out, t

    def _transcript(self, nome, palavras):
        path = self.root / "edit" / "transcripts" / f"{nome}.json"
        path.write_text(json.dumps({"words": palavras}))

    def test_align_refuses_without_a_brief(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "salve o roteiro"):
            self.pipe.align_script()

    def test_align_refuses_without_any_transcript(self):
        self.pipe.save_brief("uma linha qualquer do roteiro", None)
        with self.assertRaisesRegex(pipeline.PipelineError, "transcreva"):
            self.pipe.align_script()

    def test_align_reports_retakes_and_omissions_without_deciding(self):
        a, t = self._words("o implante hormonal nao engorda")
        b, _ = self._words("o implante hormonal nao engorda", t + 1)
        self._transcript("C001", a + b)
        self.pipe.save_brief("O implante hormonal não engorda.\n"
                             "A reposição precisa de acompanhamento médico.", None)
        result = self.pipe.align_script()
        self.assertEqual(result["summary"]["multiple"], 1)
        self.assertEqual(result["summary"]["missing"], 1)
        saved = json.loads((self.root / "edit" / "studio-pipeline" / "alignment.json").read_text())
        self.assertEqual(len(saved["lines"][0]["candidates"]), 2,
                         "as duas tomadas têm que chegar ao usuário")
        self.assertEqual(saved["lines"][1]["status"], "missing")
        # nada disso pode ter virado EDL
        self.assertFalse((self.root / "edit" / "edl.json").exists())

    def test_the_cut_transcript_is_not_used_as_raw_material(self):
        a, _ = self._words("o implante hormonal nao engorda")
        self._transcript("cut", a)          # resultado, não matéria-prima
        self.pipe.save_brief("O implante hormonal não engorda.", None)
        with self.assertRaisesRegex(pipeline.PipelineError, "transcreva"):
            self.pipe.align_script()


class TreatTests(unittest.TestCase):
    """Tratamento técnico: liga o que PASSOU no gate, e diz o que bloqueou.

    O erro que isto evita é ligar tudo e torcer. Limpeza de áudio reprovada no
    check_audio tem que render SEM limpeza — nunca com um WAV pior que o
    original — e o motivo tem que chegar ao usuário.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "proj"
        (self.root / "edit").mkdir(parents=True)
        (self.root / "a.mp4").write_bytes(b"x" * 512)
        (self.root / "edit" / "edl.json").write_text(json.dumps({
            "version": 1, "sources": {"A": str(self.root / "a.mp4")}, "grade": "",
            "ranges": [{"source": "A", "start": 0, "end": 2}, {"source": "A", "start": 3, "end": 5}],
            "total_duration_s": 4}))
        self.calls = []

    def runner(self, codes):
        """codes: nome do helper -> (returncode, stdout)."""
        def run(argv, **kw):
            nome = Path(argv[1]).name if len(argv) > 1 else argv[0]
            self.calls.append(nome)
            code, out = codes.get(nome, (0, ""))
            return subprocess.CompletedProcess(argv, code, out, "")
        return run

    def pipe(self, codes):
        return pipeline.StudioPipeline(self.root, runner=self.runner(codes))

    def test_clean_audio_is_only_enabled_when_its_own_gate_passes(self):
        p = self.pipe({"stabilize.py": (0, "0.10 px/quadro")})
        r = p.treat()
        edl = json.loads((self.root / "edit" / "edl.json").read_text())
        self.assertTrue(edl["audio_clean"])
        self.assertIn("audio_clean", [x["etapa"] for x in r["report"]["applied"]])

    def test_a_failing_audio_gate_leaves_the_cut_unclean_and_says_why(self):
        p = self.pipe({"check_audio.py": (1, "agudos abaixo do limite"),
                       "stabilize.py": (0, "0.10")})
        r = p.treat()
        edl = json.loads((self.root / "edit" / "edl.json").read_text())
        self.assertNotIn("audio_clean", edl, "áudio reprovado não pode entrar no render")
        bloqueios = {x["etapa"]: x["detalhe"] for x in r["report"]["blocked"]}
        self.assertIn("check_audio", bloqueios)
        self.assertIn("agudos", bloqueios["check_audio"])

    def test_stabilization_only_when_the_shake_is_measured_above_the_floor(self):
        calmo = self.pipe({"stabilize.py": (0, 'C014.mp4: 1080x1920 30fps\n  tremida: 0.12 px/quadro RMS → 0.03\n{"shake_px_before": 0.12}')}).treat()
        self.assertNotIn("stabilize", json.loads((self.root / "edit" / "edl.json").read_text()))
        tremido = self.pipe({"stabilize.py": (0, 'video05.mp4: 1080x1920 30fps\n  tremida: 6.90 px/quadro RMS → 0.40\n{"shake_px_before": 6.9}')}).treat()
        self.assertTrue(json.loads((self.root / "edit" / "edl.json").read_text())["stabilize"])
        self.assertIn("6.90", str(tremido["report"]["applied"]))

    def test_take_matching_writes_grade_pre_back_into_the_plan(self):
        edl_path = self.root / "edit" / "edl.json"

        def run(argv, **kw):
            nome = Path(argv[1]).name if len(argv) > 1 else argv[0]
            if nome == "match_takes.py":
                doc = json.loads(edl_path.read_text())
                doc["ranges"][0]["grade_pre"] = "exposure=exposure=+0.2"
                edl_path.write_text(json.dumps(doc))
            if nome == "stabilize.py":
                return subprocess.CompletedProcess(argv, 0, "0.1", "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        p = pipeline.StudioPipeline(self.root, runner=run)
        p.treat()
        edl = json.loads(edl_path.read_text())
        self.assertEqual(edl["ranges"][0]["grade_pre"], "exposure=exposure=+0.2")

    def test_treatment_creates_a_new_revision_and_drops_the_old_approval(self):
        approved = self.root / "edit" / "studio-pipeline" / "approved.json"
        approved.parent.mkdir(parents=True, exist_ok=True)
        approved.write_text('{"revision": 1}')
        r = self.pipe({"stabilize.py": (0, "0.1")}).treat()
        self.assertTrue(r["requiresApproval"])
        self.assertFalse(approved.exists(), "tratar muda o plano: a aprovação antiga morre")

    def test_treat_refuses_without_a_plan_and_with_a_bad_denoise(self):
        empty = Path(self.temp.name) / "vazio"
        (empty / "edit").mkdir(parents=True)
        with self.assertRaisesRegex(pipeline.PipelineError, "proponha um corte"):
            pipeline.StudioPipeline(empty).treat()
        with self.assertRaisesRegex(pipeline.PipelineError, "denoise"):
            self.pipe({}).treat(denoise="mágico")

    def test_disabling_steps_skips_their_helpers_entirely(self):
        p = self.pipe({"stabilize.py": (0, "0.1")})
        p.treat(denoise="off", stabilize=False, match_takes=False)
        self.assertNotIn("audio_clean.py", self.calls)
        self.assertNotIn("stabilize.py", self.calls)
        self.assertNotIn("match_takes.py", self.calls)
        self.assertIn("voice_levels.py", self.calls, "nível de voz é sempre medido")
