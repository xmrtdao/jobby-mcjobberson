import unittest

from resend_inbox_adapter import ingest_resend_email, ingest_resend_inbox


class ResendInboxAdapterTest(unittest.TestCase):
    def test_ingests_each_recent_email_from_domains_payload(self):
        payload = {
            "domains": {
                "pfp": {
                    "recent": [
                        {
                            "id": "message-1",
                            "subject": "Contract role",
                            "receivedAt": "2026-09-12T15:00:00Z",
                            "read": False,
                            "text": (
                                "Apply at https://example.com/jobs/1 and reply "
                                "to Hiring@example.com."
                            ),
                        },
                        {
                            "id": "message-2",
                            "subject": "No opportunity",
                            "receivedAt": "2026-09-12T15:01:00Z",
                            "read": True,
                            "text": "This digest contains no job links.",
                        },
                    ]
                }
            }
        }

        results = ingest_resend_inbox(payload)

        self.assertEqual(len(results), 2)
        first = results[0]
        self.assertEqual(first["id"], "message-1")
        self.assertEqual(first["domain"], "pfp")
        self.assertEqual(first["subject"], "Contract role")
        self.assertEqual(first["receivedAt"], "2026-09-12T15:00:00Z")
        self.assertFalse(first["read"])
        self.assertEqual(
            first["ingestion"]["contacts"]["job_urls"],
            ["https://example.com/jobs/1"],
        )
        self.assertEqual(
            first["ingestion"]["contacts"]["emails"],
            ["Hiring@example.com"],
        )
        self.assertEqual(len(first["ingestion"]["eligible"]), 2)

    def test_adapts_full_email_and_preserves_available_metadata(self):
        email = {
            "id": "full-message",
            "subject": "Consulting opening",
            "receivedAt": "2026-09-12T15:02:00Z",
            "read": False,
            "text": "See https://example.com/careers/consultant.",
        }

        result = ingest_resend_email(email, domain="mobilemonero")

        self.assertEqual(result["id"], "full-message")
        self.assertEqual(result["domain"], "mobilemonero")
        self.assertEqual(result["subject"], "Consulting opening")
        self.assertEqual(result["receivedAt"], "2026-09-12T15:02:00Z")
        self.assertFalse(result["read"])
        self.assertEqual(
            result["ingestion"]["contacts"]["job_urls"],
            ["https://example.com/careers/consultant"],
        )

    def test_full_email_does_not_invent_missing_metadata(self):
        email = {"id": "full-message", "subject": "Role", "text": "No links."}

        result = ingest_resend_email(email, domain="31harbor")

        self.assertIsNone(result["receivedAt"])
        self.assertIsNone(result["read"])
        self.assertEqual(result["ingestion"]["contacts"]["job_urls"], [])

    def test_rejects_non_mapping_payloads(self):
        with self.assertRaises(TypeError):
            ingest_resend_email(None)
        with self.assertRaises(TypeError):
            ingest_resend_inbox([])


if __name__ == "__main__":
    unittest.main()
