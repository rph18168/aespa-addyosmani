"""Single-run orchestration and failure boundaries for the daily digest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from typing import Callable

from .digest import DigestContent, DigestItem, build_digest
from .logging_utils import configure_logging, log_event
from .mailer import MailError, send_email
from .models import AppConfig, Article, FeedConfig
from .qualification import qualify_articles
from .sources import FeedError, fetch_feed
from .state import StateError, has_been_sent, load_state, mark_sent, save_state
from .summarizer import SummaryError, summarize_article


class RunError(RuntimeError):
    """Raised when a run cannot produce a reliable delivery result."""


@dataclass(frozen=True, slots=True)
class RunResult:
    feed_count: int
    successful_feeds: int
    failed_feeds: int
    fetched_articles: int
    qualified_articles: int
    new_articles: int
    summary_failures: int
    delivered: bool
    state_updated: bool
    digest: DigestContent


FetchFeed = Callable[[FeedConfig, float], list[Article]]
Summarize = Callable[[Article, AppConfig], str]
Deliver = Callable[[DigestContent, AppConfig], None]


def run_once(
    config: AppConfig,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    fetch_feed_fn: FetchFeed | None = None,
    summarize_fn: Summarize | None = None,
    deliver_fn: Deliver | None = None,
    logger: logging.Logger | None = None,
) -> RunResult:
    """Run one digest cycle; state is persisted only after delivery succeeds."""
    logger = logger or configure_logging()
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        raise RunError("run time must be timezone-aware")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    log_event(
        logger,
        "run_started",
        run_id=run_id,
        feed_count=len(config.sources.feeds),
        dry_run=dry_run,
    )

    try:
        state = load_state(config.state_path)
    except StateError as exc:
        log_event(logger, "state_load_failed", level=logging.ERROR, error_type=type(exc).__name__)
        raise RunError("state load failed") from exc

    fetcher = fetch_feed_fn or _default_fetch_feed
    fetched: list[Article] = []
    successful_feeds = 0
    failed_feeds = 0
    for feed in config.sources.feeds:
        try:
            feed_articles = fetcher(feed, config.request_timeout_seconds)
            if not isinstance(feed_articles, list):
                raise FeedError("feed fetcher returned an invalid result")
            fetched.extend(feed_articles)
            successful_feeds += 1
        except Exception as exc:
            failed_feeds += 1
            log_event(
                logger,
                "feed_failed",
                level=logging.WARNING,
                feed_name=feed.name,
                error_type=type(exc).__name__,
            )

    if successful_feeds == 0:
        log_event(
            logger,
            "run_failed",
            level=logging.ERROR,
            run_id=run_id,
            failed_feeds=failed_feeds,
            error_type="AllFeedsFailed",
        )
        raise RunError("all configured feeds failed")

    try:
        qualified = qualify_articles(
            fetched,
            config.sources,
            now=generated_at,
            lookback_hours=config.lookback_hours,
            max_articles=config.max_articles,
        )
    except Exception as exc:
        log_event(logger, "qualification_failed", level=logging.ERROR, error_type=type(exc).__name__)
        raise RunError("article qualification failed") from exc
    new_articles = [article for article in qualified if not has_been_sent(state, article)]

    summary_failures = 0
    summarizer = summarize_fn or _default_summarize
    digest_items: list[DigestItem] = []
    for article in new_articles:
        try:
            summary = summarizer(article, config)
            if not isinstance(summary, str) or not summary.strip():
                raise SummaryError("summary was empty")
        except Exception as exc:
            summary_failures += 1
            log_event(
                logger,
                "summary_failed",
                level=logging.WARNING,
                error_type=type(exc).__name__,
            )
            summary = _fallback_summary(article)
        digest_items.append(DigestItem(article=article, summary=summary))

    try:
        digest = build_digest(digest_items, generated_at=generated_at)
    except Exception as exc:
        log_event(logger, "digest_build_failed", level=logging.ERROR, error_type=type(exc).__name__)
        raise RunError("digest build failed") from exc

    if dry_run:
        log_event(
            logger,
            "run_finished",
            run_id=run_id,
            successful_feeds=successful_feeds,
            failed_feeds=failed_feeds,
            fetched_articles=len(fetched),
            qualified_articles=len(qualified),
            new_articles=len(new_articles),
            summary_failures=summary_failures,
            sent_count=0,
            state_updated=False,
            dry_run=True,
        )
        return RunResult(
            feed_count=len(config.sources.feeds),
            successful_feeds=successful_feeds,
            failed_feeds=failed_feeds,
            fetched_articles=len(fetched),
            qualified_articles=len(qualified),
            new_articles=len(new_articles),
            summary_failures=summary_failures,
            delivered=False,
            state_updated=False,
            digest=digest,
        )

    deliverer = deliver_fn or _default_deliver
    try:
        deliverer(digest, config)
    except Exception as exc:
        log_event(logger, "delivery_failed", level=logging.ERROR, error_type=type(exc).__name__)
        raise RunError("email delivery failed") from exc

    state_updated = False
    if new_articles:
        try:
            mark_sent(state, new_articles, sent_at=generated_at)
            save_state(config.state_path, state)
            state_updated = True
        except StateError as exc:
            log_event(logger, "state_save_failed", level=logging.ERROR, error_type=type(exc).__name__)
            raise RunError("state save failed after delivery") from exc

    log_event(
        logger,
        "run_finished",
        run_id=run_id,
        successful_feeds=successful_feeds,
        failed_feeds=failed_feeds,
        fetched_articles=len(fetched),
        qualified_articles=len(qualified),
        new_articles=len(new_articles),
        summary_failures=summary_failures,
        sent_count=len(new_articles) if not dry_run else 0,
        state_updated=state_updated,
        dry_run=False,
    )
    return RunResult(
        feed_count=len(config.sources.feeds),
        successful_feeds=successful_feeds,
        failed_feeds=failed_feeds,
        fetched_articles=len(fetched),
        qualified_articles=len(qualified),
        new_articles=len(new_articles),
        summary_failures=summary_failures,
        delivered=True,
        state_updated=state_updated,
        digest=digest,
    )


def _default_fetch_feed(feed: FeedConfig, timeout_seconds: float) -> list[Article]:
    return fetch_feed(feed, timeout_seconds=timeout_seconds)


def _default_summarize(article: Article, config: AppConfig) -> str:
    return summarize_article(
        article,
        base_url=config.summary_base_url,
        model=config.summary_model,
        api_key=config.summary_api_key,
        timeout_seconds=config.request_timeout_seconds,
    )


def _default_deliver(content: DigestContent, config: AppConfig) -> None:
    send_email(
        content,
        host=config.smtp_host,
        port=config.smtp_port,
        username=config.smtp_username,
        password=config.smtp_password,
        mail_from=config.mail_from,
        mail_to=config.mail_to,
        security=config.smtp_security,
        timeout_seconds=config.request_timeout_seconds,
    )


def _fallback_summary(article: Article) -> str:
    source_summary = " ".join(article.summary.split())[:1_000]
    if source_summary:
        return f"AI 摘要暂时不可用；来源摘要：{source_summary}"
    return "AI 摘要暂时不可用；暂无来源摘要。"
