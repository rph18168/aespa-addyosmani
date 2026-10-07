import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from aespa_digest.models import Article
from aespa_digest.state import (
    StateError,
    article_fingerprint,
    has_been_sent,
    load_state,
    mark_sent,
    save_state,
)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "state.json"
        self.article = Article(
            title="aespa shares a new update",
            summary="The group shared new plans.",
            link="https://www.soompi.com/article/123?utm_source=rss",
            source_name="Soompi",
            source_domain="www.soompi.com",
            published_at=datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_state_starts_empty(self):
        state = load_state(self.path)

        self.assertEqual(state.sent, {})
        self.assertFalse(has_been_sent(state, self.article))

    def test_existing_empty_state_starts_empty(self):
        self.path.write_text(
            json.dumps({"version": 1, "sent": {}}), encoding="utf-8"
        )

        state = load_state(self.path)

        self.assertEqual(state.sent, {})
        self.assertFalse(has_been_sent(state, self.article))

    def test_fingerprint_is_stable_across_tracking_parameters(self):
        without_tracking = Article(
            title=self.article.title,
            summary=self.article.summary,
            link="https://www.soompi.com/article/123",
            source_name=self.article.source_name,
            source_domain=self.article.source_domain,
            published_at=self.article.published_at,
        )

        self.assertEqual(
            article_fingerprint(self.article), article_fingerprint(without_tracking)
        )

    def test_round_trip_records_only_fingerprint_metadata(self):
        sent_at = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        state = load_state(self.path)
        mark_sent(state, [self.article], sent_at=sent_at)
        save_state(self.path, state)

        loaded = load_state(self.path)
        fingerprint = article_fingerprint(self.article)
        self.assertTrue(has_been_sent(loaded, self.article))
        self.assertEqual(loaded.sent[fingerprint], sent_at.isoformat())
        self.assertNotIn("aespa", self.path.read_text(encoding="utf-8"))
        self.assertEqual(
            [item.name for item in self.path.parent.iterdir()], ["state.json"]
        )

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["sent"][fingerprint]["sent_at"], sent_at.isoformat())

    def test_rejects_corrupt_json(self):
        self.path.write_text("{not json", encoding="utf-8")

        with self.assertRaises(StateError):
            load_state(self.path)

    def test_rejects_invalid_schema(self):
        self.path.write_text(
            json.dumps(
                {"version": 1, "sent": {"not-a-fingerprint": {"sent_at": "bad"}}}
            ),
            encoding="utf-8",
        )

        with self.assertRaises(StateError):
            load_state(self.path)

    def test_rejects_naive_sent_timestamp(self):
        state = load_state(self.path)

        with self.assertRaises(StateError):
            mark_sent(
                state,
                [self.article],
                sent_at=datetime(2026, 8, 29, 8, 0),
            )


if __name__ == "__main__":
    unittest.main()
