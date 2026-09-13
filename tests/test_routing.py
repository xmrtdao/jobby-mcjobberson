import unittest
from routing import determine_track, calculate_match_score, route_opportunity
from profile import save_profile, load_profile

class TestRoutingEngine(unittest.TestCase):
    def setUp(self):
        # Setup a test profile
        save_profile({
            "full_name": "Joseph Lee",
            "target_roles": ["Senior Engineer", "Systems Architect"],
            "resume_url": "https://example.com/resume",
            "cover_letter_url": "https://example.com/cover",
            "primary_sources": ["LinkedIn"],
            "preferences": {}
        })

    def test_track_routing(self):
        self.assertEqual(determine_track("Fractional CTO Consultant"), "track1")
        self.assertEqual(determine_track("Temporary Admin Role"), "track2")
        self.assertEqual(determine_track("Full-time Software Engineer"), "track3")
        self.assertEqual(determine_track("Unknown Role"), "track3") # Default

    def test_match_scoring(self):
        roles = ["Senior Engineer", "Systems Architect"]
        self.assertEqual(calculate_match_score("Looking for a Senior Engineer", roles), 0.5)
        self.assertEqual(calculate_match_score("Looking for a Senior Engineer and Systems Architect", roles), 1.0)
        self.assertEqual(calculate_match_score("Looking for a Janitor", roles), 0.0)

    def test_route_opportunity_integration(self):
        lead = {
            "name": "Senior Engineer Role",
            "company": "TechCorp",
            "source": "Consultancy Lead"
        }
        routed = route_opportunity(lead)
        
        self.assertEqual(routed["track"], "track1") # "Consultancy" keyword
        self.assertEqual(routed["match_category"], "High Match") # "Senior Engineer" in text
        self.assertIn("match_score", routed)

if __name__ == "__main__":
    unittest.main()
