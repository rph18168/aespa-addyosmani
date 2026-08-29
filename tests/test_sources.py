import unittest
from datetime import datetime, timedelta, timezone

from aespa_digest.models import Article, FeedConfig, SourceConfig
from aespa_digest.qualification import qualify_articles
from aespa_digest.sources import FeedError, MAX_FEED_BYTES, fetch_feed, parse_feed


class FeedParsingTests(unittest.TestCase):
    def test_parses_rss_entry_and_strips_markup(self):
        feed = FeedConfig(
            name="Soompi",
            url="https://news.google.com/rss/search?q=aespa",
            fallback_domain="soompi.com",
        )
        payload = """
        <rss version="2.0">
          <channel>
            <item>
              <title>aespa announces a new release</title>
              <description><![CDATA[<p>aespa <b>shared</b> new plans.</p>]]></description>
              <link>https://www.soompi.com/article/123</link>
              <pubDate>Sat, 29 Aug 2026 00:00:00 +0000</pubDate>
              <source url="https://www.soompi.com">Soompi</source>
            </item>
          </channel>
        </rss>
        """.encode("utf-8")

        articles = parse_feed(payload, feed)

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.title, "aespa announces a new release")
        self.assertEqual(article.summary, "aespa shared new plans.")
        self.assertEqual(article.source_name, "Soompi")
        self.assertEqual(article.source_domain, "www.soompi.com")
        self.assertEqual(article.published_at.tzinfo, timezone.utc)

    def test_parses_atom_entry_and_uses_fallback_domain(self):
        feed = FeedConfig(
            name="Billboard",
            url="https://feeds.example.test/aespa.atom",
            fallback_domain="billboard.com",
        )
        payload = """
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>에스파 returns to the stage</title>
            <summary>The group announced a new appearance.</summary>
            <link rel="alternate" href="https://www.billboard.com/music/news/aespa" />
            <updated>2026-08-29T01:30:00Z</updated>
          </entry>
        </feed>
        """.encode("utf-8")

        articles = parse_feed(payload, feed)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].source_name, "Billboard")
        self.assertEqual(articles[0].source_domain, "billboard.com")
        self.assertEqual(
            articles[0].published_at,
            datetime(2026, 8, 29, 1, 30, tzinfo=timezone.utc),
        )

    def test_fetch_feed_rejects_payload_over_size_limit(self):
        feed = FeedConfig(
            name="Test",
            url="https://feeds.example.test/aespa.xml",
            fallback_domain="example.test",
        )

        def oversized_fetcher(url, timeout_seconds):
            return b"x" * (MAX_FEED_BYTES + 1)

        with self.assertRaises(FeedError):
            fetch_feed(feed, timeout_seconds=1, fetch_bytes=oversized_fetcher)


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        self.sources = SourceConfig(
            keywords=("aespa", "에스파"),
            trusted_domains=("soompi.com", "billboard.com"),
            feeds=(),
        )

    def article(self, **overrides):
        values = {
            "title": "aespa shares an update",
            "summary": "The group shared new plans.",
            "link": "https://www.soompi.com/article/123",
            "source_name": "Soompi",
            "source_domain": "www.soompi.com",
            "published_at": self.now - timedelta(hours=1),
        }
        values.update(overrides)
        return Article(**values)

    def test_keeps_recent_relevant_trusted_articles_sorted_newest_first(self):
        older = self.article(
            title="aespa older update",
            link="https://www.soompi.com/article/older",
            published_at=self.now - timedelta(hours=2),
        )
        newer = self.article(
            title="aespa newest update",
            link="https://www.billboard.com/article/newer",
            source_domain="billboard.com",
            published_at=self.now - timedelta(minutes=10),
        )

        result = qualify_articles(
            [older, newer],
            self.sources,
            now=self.now,
            lookback_hours=36,
            max_articles=20,
        )

        self.assertEqual([article.title for article in result], ["aespa newest update", "aespa older update"])

    def test_drops_untrusted_irrelevant_old_future_and_undated_articles(self):
        candidates = [
            self.article(source_domain="unknown.example"),
            self.article(title="another group update"),
            self.article(
                title="aespa old update",
                published_at=self.now - timedelta(hours=37),
            ),
            self.article(
                title="aespa future update",
                published_at=self.now + timedelta(hours=3),
            ),
            self.article(title="aespa undated update", published_at=None),
        ]

        result = qualify_articles(
            candidates,
            self.sources,
            now=self.now,
            lookback_hours=36,
            max_articles=20,
        )

        self.assertEqual(result, [])

    def test_deduplicates_urls_and_titles_and_applies_maximum(self):
        same_url = self.article(
            title="aespa shares an update",
            link="https://www.soompi.com/article/123?utm_source=rss",
            published_at=self.now - timedelta(minutes=30),
        )
        same_title = self.article(
            title="  AESPA shares an update  ",
            link="https://www.billboard.com/article/456",
            source_domain="billboard.com",
            published_at=self.now - timedelta(minutes=20),
        )
        another = self.article(
            title="aespa second update",
            link="https://www.soompi.com/article/789",
            published_at=self.now - timedelta(minutes=10),
        )

        result = qualify_articles(
            [same_url, same_title, another],
            self.sources,
            now=self.now,
            lookback_hours=36,
            max_articles=1,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "aespa second update")


if __name__ == "__main__":
    unittest.main()
