import unittest

from newsletter_ingest import extract_newsletter_contacts, ingest_newsletter


class NewsletterIngestTest(unittest.TestCase):
    def test_extracts_explicit_job_links_and_addresses_without_duplicates(self):
        text = """
            Read [Senior Engineer opening](https://example.com/company/role/123)
            or https://jobs.example.com/openings/42.
            Ignore https://example.com/blog and [company homepage](https://example.com/).
            Reply to Hiring@Example.com or mailto:recruiter@example.com.
            Hiring@example.com is a duplicate.
        """

        contacts = extract_newsletter_contacts(text)

        self.assertEqual(
            contacts["job_urls"],
            [
                "https://example.com/company/role/123",
                "https://jobs.example.com/openings/42",
            ],
        )
        self.assertEqual(
            contacts["emails"],
            ["Hiring@Example.com", "recruiter@example.com"],
        )

        ingested = ingest_newsletter(text)

        self.assertEqual(len(ingested["eligible"]), 4)
        self.assertTrue(
            all(record.get("email") is None for record in ingested["eligible"])
        )
        self.assertEqual(
            [record["email_status"] for record in ingested["eligible"]],
            ["missing", "missing", "unverified", "unverified"],
        )
        self.assertEqual(ingested["suppressed"], [])
        self.assertEqual(ingested["discarded"], [])

    def test_plain_url_requires_an_explicit_job_path_or_label(self):
        text = """
            Ignore https://example.com/blog/job-market.
            Accept [Product role](https://example.com/company/role/9).
            Accept https://example.com/careers/senior-engineer.
        """

        contacts = extract_newsletter_contacts(text)

        self.assertEqual(
            contacts["job_urls"],
            [
                "https://example.com/company/role/9",
                "https://example.com/careers/senior-engineer",
            ],
        )

    def test_extracts_job_links_from_html_without_network_or_fabrication(self):
        text = """
            <a href="https://example.com/openings/engineer">Engineer opening</a>
            <a href="https://example.com/about">About us</a>
            Contact unknown@example.com.
        """

        contacts = extract_newsletter_contacts(text)
        ingested = ingest_newsletter(text)

        self.assertEqual(
            contacts["job_urls"],
            ["https://example.com/openings/engineer"],
        )
        self.assertEqual(contacts["emails"], ["unknown@example.com"])
        self.assertEqual(len(ingested["eligible"]), 2)
        self.assertIsNone(ingested["eligible"][1].get("email"))
        self.assertEqual(ingested["eligible"][1]["email_status"], "unverified")

    def test_placeholder_email_is_discarded_instead_of_invented(self):
        text = "Contact fake@placeholder.com."

        ingested = ingest_newsletter(text)

        self.assertEqual(ingested["eligible"], [])
        self.assertEqual(len(ingested["discarded"]), 1)
        self.assertEqual(
            ingested["discarded"][0]["discarded_status"],
            "malformed",
        )


if __name__ == "__main__":
    unittest.main()
