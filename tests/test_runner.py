from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from aespa_digest.digest import DigestContent
from aespa_digest.logging_utils import configure_logging, log_event
from aespa_digest.mailer import MailError
from aespa_digest.models import AppConfig, Article, FeedConfig, SourceConfig
from aespa_digest.runner import RunError, run_once
from aespa_digest.sources import FeedError
from aespa_digest.state import load_state


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.now = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        self.good_feed = FeedConfig(
            name="Soompi",
            url="https://feeds.example.test/soompi.xml",
            fallback_domain="soompi.com",
        )
        self.second_feed = FeedConfig(
            name="Billboard",
            url="https://feeds.example.test/billboard.xml",
            fallback_domain="billboard.com",
        )
        self.config = AppConfig(
            sources=SourceConfig(
                keywords=("aespa", "에스파"),
                trusted_domains=("soompi.com", "billboard.com"),
                feeds=(self.good_feed, self.second_feed),
            ),
            state_path=Path(self.temp_dir.name) / "state.json",
            summary_base_url="https://summary.example.test/v1",
            summary_model="gpt-5-codex",
            summary_api_key="summary-secret",
            smtp_host="smtp.example.test",
            smtp_port=587,
            smtp_username="sender@example.test",
            smtp_password="smtp-secret",
            mail_from="sender@example.test",
            mail_to="receiver@example.test",
            smtp_security="starttls",
            lookback_hours=36,
            max_articles=20,
            request_timeout_seconds=5,
        )
        self.article = Article(
            title="aespa shares a new update",
            summary="The group announced a new appearance.",
            link="https://www.soompi.com/article/123",
            source_name="Soompi",
            source_domain="www.soompi.com",
            published_at=self.now - timedelta(hours=1),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_success_delivers_then_persists_state(self):
        delivered = []

        def fetch(feed, timeout_seconds):
            return [self.article] if feed is self.good_feed else []

        def summarize(article, config):
            return "这是中文摘要。"

        def deliver(content, config):
            delivered.append(content)

        result = run_once(
            self.config,
            now=self.now,
            fetch_feed_fn=fetch,
            summarize_fn=summarize,
            deliver_fn=deliver,
        )

        self.assertEqual(result.new_articles, 1)
        self.assertEqual(result.summary_failures, 0)
        self.assertTrue(result.delivered)
        self.assertTrue(result.state_updated)
        self.assertEqual(len(delivered), 1)
        self.assertIn("这是中文摘要。", delivered[0].text)
        self.assertTrue(load_state(self.config.state_path).sent)

    def test_delivery_failure_does_not_persist_state(self):
        def fetch(feed, timeout_seconds):
            return [self.article]

        def deliver(content, config):
            raise MailError("email delivery failed")

        with self.assertRaises(RunError):
            run_once(
                self.config,
                now=self.now,
                fetch_feed_fn=fetch,
                summarize_fn=lambda article, config: "摘要",
                deliver_fn=deliver,
            )

        self.assertFalse(self.config.state_path.exists())

    def test_all_feed_failures_do_not_send_no_update_message(self):
        delivered = []

        def fetch(feed, timeout_seconds):
            raise FeedError("feed unavailable")

        with self.assertRaises(RunError):
            run_once(
                self.config,
                now=self.now,
                fetch_feed_fn=fetch,
                deliver_fn=lambda content, config: delivered.append(content),
            )

        self.assertEqual(delivered, [])
        self.assertFalse(self.config.state_path.exists())

    def test_partial_feed_failure_still_sends_no_update_message(self):
        delivered = []

        def fetch(feed, timeout_seconds):
            if feed is self.good_feed:
                return []
            raise FeedError("feed unavailable")

        result = run_once(
            self.config,
            now=self.now,
            fetch_feed_fn=fetch,
            deliver_fn=lambda content, config: delivered.append(content),
        )

        self.assertEqual(result.failed_feeds, 1)
        self.assertTrue(result.delivered)
        self.assertIn("今日暂无更新", delivered[0].text)
        self.assertFalse(self.config.state_path.exists())

    def test_dry_run_builds_digest_without_delivery_or_state(self):
        delivered = []

        result = run_once(
            self.config,
            now=self.now,
            dry_run=True,
            fetch_feed_fn=lambda feed, timeout_seconds: [self.article],
            summarize_fn=lambda article, config: "摘要",
            deliver_fn=lambda content, config: delivered.append(content),
        )

        self.assertFalse(result.delivered)
        self.assertFalse(result.state_updated)
        self.assertEqual(delivered, [])
        self.assertFalse(self.config.state_path.exists())
        self.assertIsInstance(result.digest, DigestContent)


class LoggingTests(unittest.TestCase):
    def test_structured_logs_allow_counts_but_drop_sensitive_fields(self):
        stream = io.StringIO()
        logger = configure_logging(stream)

        log_event(
            logger,
            "run_finished",
            new_articles=2,
            api_key="summary-secret",
            password="smtp-secret",
            mail_to="receiver@example.test",
        )

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["event"], "run_finished")
        self.assertEqual(payload["new_articles"], 2)
        self.assertNotIn("summary-secret", stream.getvalue())
        self.assertNotIn("smtp-secret", stream.getvalue())
        self.assertNotIn("receiver@example.test", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
