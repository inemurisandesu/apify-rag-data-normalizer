import unittest

from src.normalizer import process_documents


class TestRagDataNormalizer(unittest.TestCase):
    def test_markdown_pii_redaction_and_heading_context(self) -> None:
        docs = [
            {
                "id": "policy-1",
                "format": "markdown",
                "content": (
                    "# Support\n"
                    "Email alice@example.com or call 090-1234-5678 from 192.168.1.10.\n"
                    "Token: ghp_1234567890abcdefghij123456\n\n"
                    "## Billing\n"
                    "Refunds take 5 days."
                ),
            }
        ]
        chunks, stats = process_documents(docs, chunk_size=400, chunk_overlap=50, do_redact_pii=True)
        self.assertEqual(stats["outputChunks"], 2)
        self.assertEqual(chunks[0].heading, "Support")
        self.assertIn("[REDACTED_EMAIL]", chunks[0].text)
        self.assertIn("[REDACTED_PHONE]", chunks[0].text)
        self.assertIn("[REDACTED_IP]", chunks[0].text)
        self.assertIn("[REDACTED_TOKEN]", chunks[0].text)
        self.assertNotIn("alice@example.com", chunks[0].text)
        self.assertEqual(chunks[1].heading, "Billing")

    def test_csv_and_json_conversion_and_deduplication(self) -> None:
        docs = [
            {"id": "c1", "format": "csv", "content": "name,plan\nAcme,Pro\nBeta,Free\n"},
            {"id": "c2", "format": "csv", "content": "name,plan\nAcme,Pro\nBeta,Free\n"},
            {"id": "j1", "format": "json", "content": '{"service": "FlowCraft", "tiers": ["free", "pro"]}'},
        ]
        chunks, stats = process_documents(docs, chunk_size=500, chunk_overlap=50, deduplicate=True)
        self.assertEqual(stats["duplicatesSkipped"], 1)
        self.assertEqual(stats["outputChunks"], 2)
        self.assertIn("name: Acme | plan: Pro", chunks[0].text)
        self.assertIn("service: FlowCraft", chunks[1].text)
        self.assertIn("tiers[1]: pro", chunks[1].text)

    def test_chunk_splitting_respects_size_and_overlap(self) -> None:
        long_text = " ".join(f"word{i}" for i in range(250))
        chunks, stats = process_documents(
            [{"id": "long", "format": "text", "content": long_text}],
            chunk_size=300,
            chunk_overlap=50,
            do_redact_pii=False,
        )
        self.assertGreater(stats["outputChunks"], 3)
        for c in chunks:
            self.assertLessEqual(c.char_count, 300)
            self.assertGreater(c.estimated_tokens, 0)


if __name__ == "__main__":
    unittest.main()
