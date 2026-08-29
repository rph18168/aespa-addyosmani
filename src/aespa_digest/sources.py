"""Fetch and parse small RSS/Atom feeds without third-party dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .models import Article, FeedConfig

MAX_FEED_BYTES = 1_000_000
MAX_FIELD_LENGTH = 20_000


class FeedError(RuntimeError):
    """Raised when a feed cannot be downloaded or parsed safely."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    extractor = _TextExtractor()
    try:
        extractor.feed(value)
        extractor.close()
        value = " ".join(extractor.parts)
    except (ValueError, AssertionError):
        # Malformed markup is still safe to represent as plain text.
        value = value
    value = re.sub(r"\s+", " ", value).strip()
    return value[:MAX_FIELD_LENGTH]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _element_text(element: ElementTree.Element) -> str:
    return _clean_text("".join(element.itertext()))


def _first_child_text(element: ElementTree.Element, names: set[str]) -> str:
    for child in element:
        if _local_name(child.tag) in names:
            text = _element_text(child)
            if text:
                return text
    return ""


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            iso_value = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(iso_value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hostname(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlparse(value if "://" in value else f"//{value}")
        if parsed.username or parsed.password or not parsed.hostname:
            return None
        return parsed.hostname.rstrip(".").lower()
    except ValueError:
        return None


def _https_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = urlparse(value)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        # Accessing port validates malformed port values.
        _ = parsed.port
    except ValueError:
        return None
    return value


def _link(entry: ElementTree.Element) -> str | None:
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        rel = child.attrib.get("rel", "alternate").lower()
        candidate = href if href and rel in {"alternate", ""} else _element_text(child)
        link = _https_url(candidate)
        if link:
            return link
    return None


def _source(entry: ElementTree.Element, feed: FeedConfig, link: str) -> tuple[str, str | None]:
    for child in entry:
        if _local_name(child.tag) != "source":
            continue
        name = _element_text(child) or feed.name
        domain = _hostname(child.attrib.get("url"))
        if domain:
            return name, domain
        break
    return feed.name, _hostname(feed.fallback_domain) or _hostname(link)


def _article(entry: ElementTree.Element, feed: FeedConfig) -> Article | None:
    title = _first_child_text(entry, {"title"})
    summary = _first_child_text(entry, {"description", "summary", "content"})
    link = _link(entry)
    if not title or not link:
        return None
    date_text = _first_child_text(entry, {"pubdate", "published", "updated", "date"})
    source_name, source_domain = _source(entry, feed, link)
    return Article(
        title=title,
        summary=summary,
        link=link,
        source_name=source_name,
        source_domain=source_domain,
        published_at=_parse_datetime(date_text),
    )


def parse_feed(payload: bytes, feed: FeedConfig) -> list[Article]:
    """Parse RSS 2.0 or Atom XML into normalized articles."""
    if not isinstance(payload, bytes):
        raise FeedError("feed payload must be bytes")
    if len(payload) > MAX_FEED_BYTES:
        raise FeedError("feed payload exceeds the size limit")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise FeedError("feed XML is invalid") from exc

    articles: list[Article] = []
    for element in root.iter():
        if _local_name(element.tag) not in {"item", "entry"}:
            continue
        article = _article(element, feed)
        if article is not None:
            articles.append(article)
    return articles


def _fetch_bytes(url: str, timeout_seconds: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "User-Agent": "aespa-daily-news-digest/0.1 (+https://github.com/)",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read(MAX_FEED_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise FeedError("feed request failed") from exc
    if len(payload) > MAX_FEED_BYTES:
        raise FeedError("feed payload exceeds the size limit")
    return payload


def fetch_feed(
    feed: FeedConfig,
    *,
    timeout_seconds: float,
    fetch_bytes: Callable[[str, float], bytes] | None = None,
) -> list[Article]:
    """Download and parse one HTTPS feed.

    ``fetch_bytes`` is injectable so unit tests do not need network access.
    """
    if _https_url(feed.url) is None:
        raise FeedError("feed URL must use HTTPS and contain no credentials")
    if timeout_seconds <= 0:
        raise FeedError("feed timeout must be positive")
    fetcher = fetch_bytes or _fetch_bytes
    try:
        payload = fetcher(feed.url, timeout_seconds)
    except FeedError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise FeedError("feed request failed") from exc
    return parse_feed(payload, feed)
