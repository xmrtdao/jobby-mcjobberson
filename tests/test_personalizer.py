import unittest
from personalizer import personalize_message, prepare_outreach_batch
from profile import save_profile

class TestPersonalizer(unittest.TestCase):
    def setUp(self):
        # Setup a test profile
        save_profile({
            "full_name": "Joseph Andrew Lee",
            "target_roles": ["Systems Architect", "Senior Engineer"],
            "resume_url": "https://example.com/resume",
            "cover_letter_url": "https://example.com/cover",
            "primary_sources": ["LinkedIn"],
            "preferences": {}
        })

    def test_personalize_track1(self):
        lead = {
            "name": "Jane Doe",
            "company": "Consultancy X",
            "email": "jane@consultancyx.com",
            "track": "track1"
        }
        message = personalize_message(lead)
        
        self.assertIn("Consultancy Inquiry", message["subject"])
        self.assertIn("Hi Jane Doe,", message["body"])
        self.assertIn("Consultancy X", message["body"])
        self.assertIn("Systems Architect, Senior Engineer", message["body"])
        self.assertIn("[CANONICAL_RESUME_BLOCK]", message["body"])

    def test_personalize_track3(self):
        lead = {
            "name": "Hiring Manager",
            "company": "BigCorp",
            "email": "hr@bigcorp.com",
            "track": "track3"
        }
        message = personalize_message(lead)
        
        self.assertIn("Application for", message["subject"])
        self.assertIn("Dear Hiring Manager,", message["body"])
        self.assertIn("BigCorp", message["body"])

    def test_fallback_handling(self):
        # Lead with missing data
        lead = {
            "email": "mystery@hidden.com",
            "track": "track3"
        }
        message = personalize_message(lead)
        
        # Should use "Hiring Manager" fallback
        self.assertIn("Dear Hiring Manager,", message["body"])
        # Should use "your company" fallback
        self.assertIn("your company", message["body"])

    def test_batch_processing(self):
        leads = [
            {"name": "A", "email": "a@test.com", "track": "track1"},
            {"name": "B", "email": "b@test.com", "track": "track3"}
        ]
        batch = prepare_outreach_batch(leads)
        self.assertEqual(len(batch), 2)
        self.assertIn("Consultancy", batch[0]["subject"])
        self.assertIn("Application", batch[1]["subject"])

if __name__ == "__main__":
    unittest.main()
