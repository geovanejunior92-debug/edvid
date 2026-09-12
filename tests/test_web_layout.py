"""Contrato do shell web: mesma organização do Studio, sem editor duplicado."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "assets" / "preview"


class WebLayoutTests(unittest.TestCase):
    def test_library_uses_the_studio_information_hierarchy(self):
        html = (PREVIEW / "projects.html").read_text(encoding="utf-8")
        css = (PREVIEW / "projects.css").read_text(encoding="utf-8")
        for marker in (
            'class="topbar"',
            'class="brand"',
            'class="library-view"',
            'class="library-intro"',
            'class="library-list"',
            'id="projects"',
            'id="archived"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "width: min(1420px, 100%)",
            "max-width: 860px",
            "grid-template-rows: 132px 1fr",
            "font-size: clamp(34px, 4.2vw, 58px)",
        ):
            self.assertIn(marker, css)

    def test_browser_editor_adds_the_studio_rail_around_existing_controls(self):
        script = (PREVIEW / "workspace.js").read_text(encoding="utf-8")
        for marker in (
            "workspace-rail",
            "workspace-tools",
            "if (embedded) return",
            ".tab[data-tab=\"1\"]",
            ".tab[data-tab=\"style\"]",
            ".tab[data-tab=\"2\"]",
            "phaseTabs[key].click()",
            "#takesPanel",
        ):
            self.assertIn(marker, script)
        self.assertNotIn('id="timelinePanel"', script)
        self.assertNotIn('id="video"', script)

    def test_embedded_editor_does_not_duplicate_the_native_rail(self):
        css = (PREVIEW / "workspace.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: 64px 330px minmax(0, 1fr)", css)
        self.assertIn("body.workspace-editor.embedded-studio", css)
        self.assertIn(".workspace-editor.embedded-studio .workspace-rail { display: none; }", css)
        self.assertIn("grid-template-columns: 330px minmax(0, 1fr)", css)
        self.assertIn("workspace-tools-collapsed", css)

    def test_small_viewport_keeps_the_editor_surface_in_the_fixed_viewport(self):
        css = (PREVIEW / "workspace.css").read_text(encoding="utf-8")
        self.assertIn("height: 100dvh", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn("@media (max-width: 740px)", css)
        self.assertIn("position: fixed", css)
        self.assertIn("bottom: 8px", css)

    def test_image_hint_is_safe_before_the_first_project_poll(self):
        script = (PREVIEW / "app.js").read_text(encoding="utf-8")
        self.assertIn("const image = S.style?.image || {};", script)
        self.assertNotIn("Object.entries(S.style.image || {})", script)


if __name__ == "__main__":
    unittest.main()
