import unittest

from lead_utils import (
    apply_suppression,
    deduplicate_recipients,
    normalize_recipient,
    prepare_recipients,
    recipient_identity_key,
)


class RecipientNormalizationTest(unittest.TestCase):
    def test_trims_fields_and_normalizes_email_without_mutating_input(self):
        source = {
            "name": "  Owner Name  ",
            "company": "  Example Business  ",
            "source": "  Directory  ",
            "url": "  https://example.invalid/business  ",
            "track": "  track_1  ",
            "email": "  OWNER@Example.INVALID  ",
        }

        result = normalize_recipient(source)

        self.assertEqual(result["name"], "Owner Name")
        self.assertEqual(result["company"], "Example Business")
        self.assertEqual(result["source"], "Directory")
        self.assertEqual(result["url"], "https://example.invalid/business")
        self.assertEqual(result["track"], "track_1")
        self.assertEqual(result["email"], "owner@example.invalid")
        self.assertEqual(source["name"], "  Owner Name  ")
        self.assertEqual(source["email"], "  OWNER@Example.INVALID  ")

    def test_missing_and_explicitly_unverified_emails_stay_unknown(self):
        missing = normalize_recipient({"name": "Owner", "email": None})
        placeholder = normalize_recipient({"name": "Owner", "email": "owner@placeholder.com"})
        unverified = normalize_recipient(
            {"name": "Owner", "email": "owner@example.invalid", "email_status": "unverified"}
        )

        self.assertIsNone(missing["email"])
        self.assertEqual(missing["email_status"], "missing")
        self.assertIsNone(placeholder["email"])
        self.assertEqual(placeholder["email_status"], "missing")
        self.assertIsNone(unverified["email"])
        self.assertEqual(unverified["email_status"], "unverified")

    def test_normalization_never_creates_a_contact_address(self):
        result = normalize_recipient({"name": "Owner", "url": "https://example.invalid"})

        self.assertIsNone(result.get("email"))
        self.assertEqual(result["email_status"], "missing")

    def test_identity_key_uses_verified_email_case_insensitively(self):
        first = normalize_recipient({"name": "Owner", "email": "OWNER@example.invalid"})
        second = normalize_recipient({"name": "Other", "email": "owner@example.invalid"})

        self.assertEqual(recipient_identity_key(first), recipient_identity_key(second))
        self.assertEqual(recipient_identity_key(first), "email:owner@example.invalid")

    def test_identity_key_uses_source_url_and_name_when_email_is_missing(self):
        first = normalize_recipient(
            {"name": "  Owner  ", "source": " Directory ", "url": " https://example.invalid "},
        )
        second = normalize_recipient(
            {"name": "Owner", "source": "Directory", "url": "https://example.invalid"},
        )

        self.assertEqual(recipient_identity_key(first), recipient_identity_key(second))

    def test_deduplication_is_first_wins_and_preserves_order(self):
        records = [
            {"name": "First", "email": "first@example.invalid"},
            {"name": "Duplicate", "email": "FIRST@example.invalid"},
            {"name": "Missing One", "source": "Directory", "url": "https://one.invalid"},
            {"name": "Missing One", "source": "Directory", "url": "https://one.invalid"},
            {"name": "Last", "email": "last@example.invalid"},
        ]

        result = deduplicate_recipients(records)

        self.assertEqual([item["name"] for item in result], ["First", "Missing One", "Last"])
        self.assertEqual(result[0]["email"], "first@example.invalid")

    def test_suppression_filters_exact_identity_and_verified_email(self):
        records = [
            {"name": "Allowed", "email": "allowed@example.invalid"},
            {"name": "Identity Suppressed", "email": "blocked@example.invalid"},
            {"name": "Email Suppressed", "email": "blocked-two@example.invalid"},
            {"name": "Unverified", "email": "blocked@example.invalid", "email_status": "unverified"},
        ]

        eligible, suppressed = apply_suppression(
            records,
            suppressed_identity_keys={"email:blocked@example.invalid"},
            suppressed_emails={"blocked-two@example.invalid"},
        )

        self.assertEqual([item["name"] for item in eligible], ["Allowed", "Unverified"])
        self.assertEqual([item["name"] for item in suppressed], ["Identity Suppressed", "Email Suppressed"])
        self.assertEqual(suppressed[0]["suppression_status"], "suppressed")
        self.assertEqual(suppressed[0]["suppression_reason"], "identity_key")
        self.assertEqual(suppressed[1]["suppression_reason"], "verified_email")

    def test_explicit_consent_denial_is_auditable_suppression(self):
        records = [
            {"name": "Allowed", "email": "allowed@example.invalid", "consent_status": "granted"},
            {"name": "Denied", "email": "denied@example.invalid", "consent_status": "denied"},
        ]

        eligible, suppressed = apply_suppression(records)

        self.assertEqual([item["name"] for item in eligible], ["Allowed"])
        self.assertEqual([item["name"] for item in suppressed], ["Denied"])
        self.assertEqual(suppressed[0]["suppression_reason"], "consent_denied")

    def test_prepare_returns_empty_lists_for_empty_input(self):
        self.assertEqual(
            prepare_recipients([]),
            {"eligible": [], "suppressed": [], "discarded": []},
        )

    def test_prepare_discards_malformed_records_with_audit_data(self):
        result = prepare_recipients([{"name": "Good", "email": "good@example.invalid"}, "bad"])

        self.assertEqual([item["name"] for item in result["eligible"]], ["Good"])
        self.assertEqual(result["discarded"][0]["discarded_status"], "malformed")
        self.assertEqual(result["discarded"][0]["raw_record"], "bad")


if __name__ == "__main__":
    unittest.main()
