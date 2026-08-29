import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from aespa_digest.config import ConfigurationError, load_config
from aespa_digest.models import Article, FeedConfig, SourceConfig
from aespa_digest.qualification import qualify_articles
from aespa_digest.sources import FeedError, fetch_feed


class FeedHardeningTests(unittest.TestCase):
    def test_retries_transient_fetch_failure_once(self):
        feed = FeedConfig(
            name="Test",
            url="https://feeds.example.test/aespa.xml",
            fallback_domain="soompi.com",
        )
        attempts = []
        payload = b"""
        <rss version="2.0"><channel><item>
          <title>aespa update</title>
          <description>New plans.</description>
          <link>https://www.soompi.com/article/123</link>
          <pubDate>Sat, 29 Aug 2026 00:00:00 +0000</pubDate>
        </item></channel></rss>
        """

        def flaky_fetcher(url, timeout_seconds):
            attempts.append(url)
            if len(attempts) == 1:
                raise TimeoutError("temporary failure")
            return payload

        articles = fetch_feed(feed, timeout_seconds=1, fetch_bytes=flaky_fetcher)

        self.assertEqual(len(articles), 1)
        self.assertEqual(len(attempts), 2)


class QualificationHardeningTests(unittest.TestCase):
    def test_requires_article_link_to_be_trusted_too(self):
        now = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        article = Article(
            title="aespa shares an update",
            summary="The group shared new plans.",
            link="https://evil.example/article",
            source_name="Soompi",
            source_domain="soompi.com",
            published_at=now,
        )
        source_config = SourceConfig(
            keywords=("aespa",),
            trusted_domains=("soompi.com",),
            feeds=(),
        )

        result = qualify_articles(
            [article],
            source_config,
            now=now,
            lookback_hours=36,
            max_articles=20,
        )

        self.assertEqual(result, [])


class ConfigurationHardeningTests(unittest.TestCase):
    def test_rejects_summary_endpoint_with_query(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_path = Path(temp_dir) / "sources.json"
            sources_path.write_text(
                json.dumps(
                    {
                        "keywords": ["aespa"],
                        "trusted_domains": ["soompi.com"],
                        "feeds": [
                            {
                                "name": "Soompi",
                                "url": "https://www.soompi.com/feed",
                                "fallback_domain": "soompi.com",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            environment = {
                "SUMMARY_API_KEY": "summary-secret",
                "SUMMARY_BASE_URL": "https://summary.example.test/v1?key=bad",
                "SMTP_HOST": "smtp.example.test",
                "SMTP_PORT": "587",
                "SMTP_USERNAME": "sender@example.test",
                "SMTP_PASSWORD": "smtp-secret",
                "MAIL_FROM": "sender@example.test",
                "MAIL_TO": "receiver@example.test",
            }

            with self.assertRaises(ConfigurationError):
                load_config(sources_path, environ=environment)


if __name__ == "__main__":
    unittest.main()
