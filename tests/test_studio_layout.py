"""Contrato visual do Studio: biblioteca web e editor compartilhado."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "assets" / "studio"
PREVIEW = ROOT / "assets" / "preview"


class StudioLayoutTests(unittest.TestCase):
    def test_library_and_editor_have_the_same_information_hierarchy_as_web(self):
        html = (STUDIO / "index.html").read_text()
        for marker in (
            "Comece um vídeo novo.",
            'id="project-list"',
            'class="editor-shell"',
            'class="toolbox"',
            'id="editor-frame"',
            'id="archived-projects"',
            '?embedded=1',
        ):
            self.assertIn(marker, html if marker != '?embedded=1' else (STUDIO / "app.js").read_text())

    def test_the_embedded_editor_is_still_the_shared_web_editor(self):
        html = (STUDIO / "index.html").read_text()
        self.assertIn('id="editor-frame"', html)
        self.assertNotIn('id="timelinePanel"', html, "o Studio não pode copiar a timeline web")
        self.assertIn("embedded-studio", (PREVIEW / "app.js").read_text())
        self.assertIn("body.embedded-studio>header", (PREVIEW / "app.css").read_text())

    def test_native_library_keeps_the_web_library_actions_and_thumbnails(self):
        script = (STUDIO / "app.js").read_text()
        for marker in ('PROJECT_ICONS', 'project.thumbnail', 'Renomear projeto',
                       'Fixar projeto no topo', 'Arquivar projeto sem apagar arquivos',
                       '"/api/projects/update"'):
            self.assertIn(marker, script)

    def test_phase2_controls_are_reachable_from_the_app(self):
        html = (STUDIO / "index.html").read_text()
        script = (STUDIO / "phase2.js").read_text()
        for marker in ("phase2-scaffold", "phase2-save", "phase2-approve", "phase2-render",
                       "phase2-output", "phase2-output-hash", "phase2-delivery-status",
                       "phase2-review-check", "phase2-review-approve"):
            self.assertIn(f'id="{marker}"', html)
        self.assertIn('kind: "phase2"', script)
        self.assertIn('dispatch("review-approve"', script)
        self.assertIn("window.loadPhase2", script)


if __name__ == "__main__":
    unittest.main()
