from datetime import datetime, timezone
from unittest.mock import patch
import unittest

from aespa_digest.digest import build_digest
from aespa_digest.mailer import MailError, send_email
from aespa_digest.models import Article
from aespa_digest.state import DeliveryState, mark_sent
from aespa_digest.summarizer import SummaryError, summarize_article


class BoundaryTypeTests(unittest.TestCase):
    def setUp(self):
        self.article = Article(
            title="aespa update",
            summary="New plans.",
            link="https://www.soompi.com/article/123",
            source_name="Soompi",
            source_domain="soompi.com",
            published_at=datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc),
        )
        self.content = build_digest(
            [], generated_at=datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        )

    def test_state_keeps_only_the_newest_entries_above_limit(self):
        articles = [
            Article(
                title=f"aespa update {index}",
                summary="New plans.",
                link=f"https://www.soompi.com/article/{index}",
                source_name="Soompi",
                source_domain="soompi.com",
                published_at=self.article.published_at,
            )
            for index in range(3)
        ]
        state = DeliveryState(sent={})

        with patch("aespa_digest.state.MAX_SENT_ITEMS", 2):
            mark_sent(state, articles)

        self.assertEqual(len(state.sent), 2)

    def test_invalid_smtp_security_type_raises_mail_error(self):
        with self.assertRaises(MailError):
            send_email(
                self.content,
                host="smtp.example.test",
                port=587,
                username="sender@example.test",
                password="smtp-secret",
                mail_from="sender@example.test",
                mail_to="receiver@example.test",
                security=None,
            )

    def test_invalid_summary_model_type_raises_summary_error(self):
        with self.assertRaises(SummaryError):
            summarize_article(
                self.article,
                base_url="https://summary.example.test/v1",
                model=None,
                api_key="summary-secret",
                timeout_seconds=5,
                send_request=lambda request, timeout: b"{}",
            )


if __name__ == "__main__":
    unittest.main()
