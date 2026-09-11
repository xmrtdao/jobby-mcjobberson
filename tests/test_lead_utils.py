import unittest

from lead_utils import normalize_lead


class LeadUtilsTest(unittest.TestCase):
    def test_removes_placeholder_email(self):
        lead = {"email": "contact1@placeholder.com", "name": "Example"}
        self.assertIsNone(normalize_lead(lead)["email"])

    def test_preserves_real_email_and_does_not_mutate_input(self):
        lead = {"email": " person@example.com ", "name": "Example"}
        result = normalize_lead(lead)
        self.assertEqual(result["email"], "person@example.com")
        self.assertEqual(lead["email"], " person@example.com ")

    def test_missing_email_stays_none(self):
        lead = {"email": None, "name": "Example"}
        self.assertIsNone(normalize_lead(lead)["email"])


if __name__ == "__main__":
    unittest.main()
