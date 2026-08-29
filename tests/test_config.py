import json
import tempfile
import unittest
from pathlib import Path

from aespa_digest.config import ConfigurationError, load_config


class LoadConfigTests(unittest.TestCase):
    def make_sources_file(self, *, feed_url="https://news.google.com/rss/search?q=aespa"):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        sources_path = Path(temp_dir.name) / "sources.json"
        sources_path.write_text(
            json.dumps(
                {
                    "keywords": ["aespa", "에스파"],
                    "trusted_domains": ["soompi.com"],
                    "feeds": [
                        {
                            "name": "Soompi",
                            "url": feed_url,
                            "fallback_domain": "soompi.com",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return sources_path

    def valid_environment(self):
        return {
            "SUMMARY_API_KEY": "test-summary-key",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "sender@example.test",
            "SMTP_PASSWORD": "test-password",
            "MAIL_FROM": "sender@example.test",
            "MAIL_TO": "recipient@example.test",
        }

    def test_loads_valid_environment_and_safe_defaults(self):
        sources_path = self.make_sources_file()

        config = load_config(sources_path, environ=self.valid_environment())

        self.assertEqual(config.summary_model, "gpt-5-codex")
        self.assertEqual(
            config.summary_base_url,
            "https://a-ocnfniawgw.cn-shanghai.fcapp.run/v1",
        )
        self.assertEqual(config.lookback_hours, 36)
        self.assertEqual(config.sources.feeds[0].fallback_domain, "soompi.com")

    def test_rejects_missing_required_secret(self):
        sources_path = self.make_sources_file()
        environment = self.valid_environment()
        del environment["SUMMARY_API_KEY"]

        with self.assertRaisesRegex(ConfigurationError, "SUMMARY_API_KEY"):
            load_config(sources_path, environ=environment)

    def test_rejects_non_https_summary_endpoint(self):
        sources_path = self.make_sources_file()
        environment = self.valid_environment()
        environment["SUMMARY_BASE_URL"] = "http://summary.example.test/v1"

        with self.assertRaisesRegex(ConfigurationError, "HTTPS"):
            load_config(sources_path, environ=environment)

    def test_rejects_non_https_feed(self):
        sources_path = self.make_sources_file(feed_url="http://news.example.test/feed")

        with self.assertRaisesRegex(ConfigurationError, "HTTPS"):
            load_config(sources_path, environ=self.valid_environment())

    def test_rejects_invalid_integer_configuration(self):
        sources_path = self.make_sources_file()
        environment = self.valid_environment()
        environment["LOOKBACK_HOURS"] = "not-a-number"

        with self.assertRaisesRegex(ConfigurationError, "LOOKBACK_HOURS"):
            load_config(sources_path, environ=environment)


if __name__ == "__main__":
    unittest.main()
