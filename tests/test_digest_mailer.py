from datetime import datetime, timezone
import json
import unittest

from aespa_digest.digest import DigestError, DigestItem, build_digest
from aespa_digest.mailer import MailError, send_email
from aespa_digest.models import Article


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.generated_at = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        self.article = Article(
            title="aespa <new> release",
            summary="A new appearance was announced.",
            link="https://www.soompi.com/article/123?utm_source=rss",
            source_name="Soompi",
            source_domain="www.soompi.com",
            published_at=datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc),
        )

    def test_builds_explicit_no_update_digest(self):
        digest = build_digest([], generated_at=self.generated_at)

        self.assertIn("今日暂无更新", digest.subject)
        self.assertIn("今日暂无更新", digest.text)
        self.assertIn("今日暂无更新", digest.html)

    def test_builds_text_and_escaped_html_for_articles(self):
        item = DigestItem(
            article=self.article,
            summary="摘要含有 <script>alert('x')</script>。",
        )

        digest = build_digest([item], generated_at=self.generated_at)

        self.assertIn("aespa <new> release", digest.text)
        self.assertIn("Soompi", digest.text)
        self.assertIn("原文：https://www.soompi.com/article/123?utm_source=rss", digest.text)
        self.assertIn("&lt;new&gt;", digest.html)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", digest.html)
        self.assertNotIn("<script>", digest.html)
        self.assertIn('href="https://www.soompi.com/article/123?utm_source=rss"', digest.html)

    def test_rejects_non_https_article_link(self):
        article = Article(
            title=self.article.title,
            summary=self.article.summary,
            link="http://www.soompi.com/article/123",
            source_name=self.article.source_name,
            source_domain=self.article.source_domain,
            published_at=self.article.published_at,
        )

        with self.assertRaises(DigestError):
            build_digest(
                [DigestItem(article=article, summary="摘要")],
                generated_at=self.generated_at,
            )


class _FakeSMTP:
    def __init__(self):
        self.calls = []
        self.message = None

    def ehlo(self):
        self.calls.append(("ehlo",))

    def starttls(self, context):
        self.calls.append(("starttls", context))

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message, from_addr, to_addrs):
        self.calls.append(("send_message", from_addr, to_addrs))
        self.message = message

    def quit(self):
        self.calls.append(("quit",))


class MailerTests(unittest.TestCase):
    def setUp(self):
        self.content = build_digest(
            [], generated_at=datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        )
        self.smtp = _FakeSMTP()

    def factory(self, host, port, timeout_seconds, security):
        self.factory_args = (host, port, timeout_seconds, security)
        return self.smtp

    def test_sends_starttls_message_and_never_logs_password(self):
        send_email(
            self.content,
            host="smtp.example.test",
            port=587,
            username="sender@example.test",
            password="smtp-secret",
            mail_from="sender@example.test",
            mail_to="receiver@example.test, second@example.test",
            security="starttls",
            timeout_seconds=9,
            smtp_factory=self.factory,
        )

        self.assertEqual(
            self.factory_args,
            ("smtp.example.test", 587, 9, "starttls"),
        )
        self.assertEqual(self.smtp.calls[0], ("ehlo",))
        self.assertEqual(self.smtp.calls[1][0], "starttls")
        self.assertEqual(self.smtp.calls[2], ("ehlo",))
        self.assertEqual(
            self.smtp.calls[3], ("login", "sender@example.test", "smtp-secret")
        )
        send_call = self.smtp.calls[4]
        self.assertEqual(send_call[0], "send_message")
        self.assertEqual(send_call[1], "sender@example.test")
        self.assertEqual(send_call[2], ["receiver@example.test", "second@example.test"])
        self.assertEqual(self.smtp.message["Subject"], self.content.subject)
        self.assertEqual(self.smtp.calls[-1], ("quit",))
        self.assertNotIn("smtp-secret", json.dumps(self.smtp.message.as_string()))

    def test_rejects_header_injection(self):
        with self.assertRaises(MailError):
            send_email(
                self.content,
                host="smtp.example.test",
                port=587,
                username="sender@example.test",
                password="smtp-secret",
                mail_from="sender@example.test\r\nBcc: attacker@example.test",
                mail_to="receiver@example.test",
                smtp_factory=self.factory,
            )

    def test_wraps_smtp_failure_without_exposing_password(self):
        class FailingSMTP(_FakeSMTP):
            def login(self, username, password):
                raise OSError("connection failed")

        failing = FailingSMTP()

        def factory(host, port, timeout_seconds, security):
            return failing

        with self.assertRaisesRegex(MailError, "email delivery failed") as context:
            send_email(
                self.content,
                host="smtp.example.test",
                port=587,
                username="sender@example.test",
                password="smtp-secret",
                mail_from="sender@example.test",
                mail_to="receiver@example.test",
                smtp_factory=factory,
            )
        self.assertNotIn("smtp-secret", str(context.exception))


if __name__ == "__main__":
    unittest.main()
