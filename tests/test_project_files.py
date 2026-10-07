import json
from pathlib import Path
import unittest

from aespa_digest.config import load_config
from aespa_digest.state import load_state


ROOT = Path(__file__).resolve().parents[1]


class ProjectConfigurationTests(unittest.TestCase):
    def test_default_sources_are_https_and_loadable(self):
        environment = {
            "SUMMARY_API_KEY": "summary-secret",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "sender@example.test",
            "SMTP_PASSWORD": "smtp-secret",
            "MAIL_FROM": "sender@example.test",
            "MAIL_TO": "receiver@example.test",
        }

        config = load_config(ROOT / "config/sources.json", environ=environment)

        self.assertGreaterEqual(len(config.sources.feeds), 4)
        self.assertTrue(all(feed.url.startswith("https://") for feed in config.sources.feeds))
        self.assertIn("soompi.com", config.sources.trusted_domains)
        self.assertIn("에스파", config.sources.keywords)

    def test_repository_state_has_expected_schema(self):
        state_path = ROOT / "data/state.json"
        payload = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(set(payload), {"version", "sent"})
        self.assertEqual(payload["version"], 1)
        # Successful deliveries legitimately populate this tracked file.
        # The runtime loader validates fingerprints, metadata and timestamps.
        state = load_state(state_path)
        self.assertEqual(set(state.sent), set(payload["sent"]))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/daily-digest.yml").read_text(
            encoding="utf-8"
        )

    def test_workflow_has_beijing_schedule_and_manual_trigger(self):
        self.assertIn('cron: "0 8 * * *"', self.workflow)
        self.assertIn('timezone: "Asia/Shanghai"', self.workflow)
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_workflow_uses_secrets_artifact_and_scoped_write_permission(self):
        for secret in (
            "SUMMARY_API_KEY",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "MAIL_FROM",
            "MAIL_TO",
        ):
            self.assertIn(f"secrets.{secret}", self.workflow)
        self.assertIn("actions/upload-artifact@v4", self.workflow)
        self.assertIn("actions/download-artifact@v5", self.workflow)
        self.assertIn("permissions:\n      contents: write", self.workflow)
        self.assertNotIn("OPENAI_API_KEY", self.workflow)


if __name__ == "__main__":
    unittest.main()
