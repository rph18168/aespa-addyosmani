"""Filter feed entries into a relevant, trusted and deduplicated digest."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Article, SourceConfig

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}


def _canonical_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        port = parsed.port
    except (AttributeError, ValueError):
        return None

    hostname = parsed.hostname.rstrip(".").lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if port is not None and port != 443:
        netloc = f"{netloc}:{port}"

    query_parts = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_QUERY_KEYS
    ]
    query_parts.sort()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query = urlencode(query_parts, doseq=True)
    return urlunsplit(("https", netloc, path, query, ""))


def _title_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _domain(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value if "://" in value else f"//{value}")
        if parsed.username or parsed.password or not parsed.hostname:
            return None
        return parsed.hostname.rstrip(".").lower()
    except ValueError:
        return None


def _is_trusted(article: Article, trusted_domains: tuple[str, ...]) -> bool:
    trusted = {_domain(domain) for domain in trusted_domains}
    trusted.discard(None)
    source_domain = _domain(article.source_domain)
    candidates = {source_domain} if source_domain else {_domain(article.link)}
    candidates.discard(None)
    return any(
        candidate == domain or candidate.endswith(f".{domain}")
        for candidate in candidates
        for domain in trusted
    )


def _is_relevant(article: Article, keywords: tuple[str, ...]) -> bool:
    haystack = f"{article.title} {article.summary}".casefold()
    return any(keyword.casefold() in haystack for keyword in keywords if keyword.strip())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def qualify_articles(
    articles: list[Article],
    source_config: SourceConfig,
    *,
    now: datetime,
    lookback_hours: int,
    max_articles: int,
) -> list[Article]:
    """Apply relevance, trust, freshness, canonicalization and ordering rules."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if lookback_hours <= 0:
        raise ValueError("lookback_hours must be positive")
    if max_articles <= 0:
        raise ValueError("max_articles must be positive")

    now_utc = _as_utc(now)
    lower_bound = now_utc - timedelta(hours=lookback_hours)
    upper_bound = now_utc + timedelta(hours=2)
    candidates: list[tuple[datetime, Article, str]] = []
    for article in articles:
        if not article.title or not _https_url_is_valid(article.link):
            continue
        if not _is_relevant(article, source_config.keywords):
            continue
        if not _is_trusted(article, source_config.trusted_domains):
            continue
        if article.published_at is None:
            continue
        published_at = _as_utc(article.published_at)
        if not lower_bound <= published_at <= upper_bound:
            continue
        canonical = _canonical_url(article.link)
        if canonical is None:
            continue
        candidates.append((published_at, article, canonical))

    candidates.sort(key=lambda item: item[0], reverse=True)
    result: list[Article] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for _, article, canonical in candidates:
        title_key = _title_key(article.title)
        if canonical in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(canonical)
        seen_titles.add(title_key)
        result.append(article)
        if len(result) >= max_articles:
            break
    return result


def _https_url_is_valid(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return False
        if parsed.username or parsed.password:
            return False
        _ = parsed.port
    except (AttributeError, ValueError):
        return False
    return True
