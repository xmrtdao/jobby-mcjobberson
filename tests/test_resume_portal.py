import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class ResumePortalContractTest(unittest.TestCase):
    def test_hero_exposes_one_drag_and_drop_resume_control(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="resume-drop-zone"', html)
        self.assertIn('id="resume-file"', html)
        self.assertIn('accept=".pdf,.docx,.txt"', html)
        self.assertIn('id="resume-status"', html)
        self.assertLess(html.count('id="resume-file"'), 2)

    def test_hero_has_a_source_derived_parsed_profile_panel(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="parsed-profile"', html)
        self.assertIn('id="parsed-skills"', html)
        self.assertIn('id="parsed-fields"', html)
        self.assertIn('id="parsed-links"', html)

    def test_hero_loads_the_resume_interaction_script(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")

        self.assertIn('<script src="app.js" defer></script>', html)

    def test_portal_avoids_inline_script_and_javascript_urls(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")
        script = (DOCS / "app.js").read_text(encoding="utf-8")
        combined = html + "\n" + script

        self.assertNotIn("javascript:", combined)
        self.assertNotIn("onclick=", combined)
        self.assertNotIn("<script>", combined)
        self.assertNotIn("innerHTML", script)
        self.assertIn("textContent", script)

    def test_portal_uses_declarative_onboarding_controls(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")
        script = (DOCS / "app.js").read_text(encoding="utf-8")

        self.assertIn("data-open-onboarding", html)
        self.assertIn("data-onboarding-step", html)
        self.assertIn("data-onboarding-finish", html)
        self.assertIn("data-open-onboarding", script)
        self.assertIn("data-onboarding-step", script)
        self.assertIn("data-onboarding-finish", script)

    def test_portal_parser_supports_only_planned_formats_and_size_limit(self):
        script = (DOCS / "app.js").read_text(encoding="utf-8")

        self.assertIn("application/pdf", script)
        self.assertIn("application/vnd.openxmlformats-officedocument.wordprocessingml.document", script)
        self.assertIn("text/plain", script)
        self.assertIn("10 * 1024 * 1024", script)

    def test_portal_does_not_send_resume_data_to_hardcoded_local_services(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")
        script = (DOCS / "app.js").read_text(encoding="utf-8")

        combined = html + "\n" + script
        self.assertNotIn("localhost", combined)
        self.assertNotIn("127.0.0.1", combined)
        self.assertNotIn("38401", combined)
        self.assertNotIn("4700", combined)

    def test_portal_has_responsive_drop_zone_styles(self):
        css = (DOCS / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".resume-drop-zone", css)
        self.assertIn(".drop-area.drag-over", css)
        self.assertIn(".parsed-profile-section", css)

    def test_parsed_profile_is_revealed_after_a_successful_parse(self):
        script = (DOCS / "app.js").read_text(encoding="utf-8")

        self.assertIn("existing.hidden = false", script)


if __name__ == "__main__":
    unittest.main()
