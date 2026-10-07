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

_GROUP = r"(?<![a-z0-9_])aespa(?![a-z0-9_])|에스파|エスパ"
_MEMBERS = (
    r"\bkarina\b|카리나|カリナ|卡[琳丽麗]娜",
    r"\bwinter\b|윈터|ウィンター",
    r"\bgiselle\b|지젤|ジゼル",
    r"\bningning\b|닝닝|ニンニン|宁宁|寧寧",
)
_COMPARISON = re.compile(
    rf"(?:{_GROUP})(?:['’]s\s+sister(?:\s+group)?|の妹|의\s*후배)"
    rf"|(?:sister\s+group\s+(?:of|to)|next|compared\s+to)\s+(?:{_GROUP})"
    r"|\bkarina\s+of\s+athletics\b|육상계(?:의)?\s*카리나",
    re.IGNORECASE,
)
_LA = re.compile(
    r"(?<![a-z])l\.?a\.?(?![a-z])|los\s+angeles|洛杉[矶磯]"
    r"|ロサンゼルス|로스앤젤레스|intuit\s+dome|인튜이트\s*돔",
    re.IGNORECASE,
)
_CONCERT = re.compile(r"\bconcert\b|\btour\b|콘서트|공연|돔|演唱会|演出|公演|ツアー", re.IGNORECASE)
_SUCCESS = re.compile(
    r"\bsells?\s+out\b|\bsold[ -]out\b|매진|완판|채웠|꽉\s*채운"
    r"|성료|完売|售[罄完]|圆满落幕|圓滿落幕",
    re.IGNORECASE,
)
_REVIEW = re.compile(r"\breview\b|评论|評論|レビュー|리뷰|후기", re.IGNORECASE)
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


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
    link_domain = _domain(article.link)
    if not _matches_trusted_domain(link_domain, trusted):
        return False
    return source_domain is None or _matches_trusted_domain(source_domain, trusted)


def _matches_trusted_domain(candidate: str | None, trusted: set[str]) -> bool:
    return bool(
        candidate
        and any(
            candidate == domain or candidate.endswith(f".{domain}")
            for domain in trusted
        )
    )


def _is_relevant(article: Article, keywords: tuple[str, ...]) -> bool:
    # A name in a comparison or an unrelated summary is not the article's subject.
    title = _COMPARISON.sub("", article.title)
    aliases = tuple(keyword.strip() for keyword in keywords if keyword.strip())
    aespa_enabled = any(keyword.casefold() in {"aespa", "에스파", "エスパ"} for keyword in aliases)
    if aespa_enabled:
        aliases += ("aespa", "에스파", "エスパ")
    for keyword in aliases:
        pattern = re.escape(keyword)
        if keyword.isascii():
            pattern = rf"(?<![a-z0-9_]){pattern}(?![a-z0-9_])"
        if re.search(pattern, title, re.IGNORECASE):
            return True
    if not aespa_enabled:
        return False
    # Bare member names (especially Winter) require an explicit group affiliation.
    summary = _COMPARISON.sub("", article.summary)
    for member in _MEMBERS:
        if re.search(member, title, re.IGNORECASE) and re.search(
            rf"(?:{_GROUP})(?:['’]s\s*|\s*(?:member\s+|멤버\s*|의\s*|の|成员|成員)?)"
            rf"(?:{member})|(?:{member})\s+(?:of|from)\s+(?:{_GROUP})",
            summary,
            re.IGNORECASE,
        ):
            return True
    return False


def _event_key(article: Article) -> tuple[str, tuple[str, ...]] | None:
    """Conservative multilingual key for LA concert success reports, not reviews."""
    title = article.title
    if (
        not re.search(_GROUP, title, re.IGNORECASE)
        or any(re.search(member, title, re.IGNORECASE) for member in _MEMBERS)
        or _REVIEW.search(title)
        or not (_LA.search(title) and _CONCERT.search(title) and _SUCCESS.search(title))
    ):
        return None
    # Keep explicitly dated shows separate; missing dates never override known ones.
    dates = {
        f"{int(month):02d}-{int(day):02d}"
        for month, day in re.findall(
            r"(?<!\d)(?:\d{4}[-/年년]\s*)?(\d{1,2})[-/月월]\s*(\d{1,2})(?:[日일])?",
            title,
        )
    }
    for month, day in re.findall(
        r"\b(" + "|".join(_MONTHS) + r")[a-z]*\.?\s+(\d{1,2})\b", title, re.IGNORECASE
    ):
        dates.add(f"{_MONTHS.index(month.casefold()) + 1:02d}-{int(day):02d}")
    return "aespa:los-angeles:concert-success", tuple(sorted(dates))


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
    seen_events: dict[tuple[str, tuple[str, ...]], datetime] = {}
    for published_at, article, canonical in candidates:
        title_key = _title_key(article.title)
        if canonical in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(canonical)
        seen_titles.add(title_key)
        event_key = _event_key(article)
        if event_key is not None:
            previous = seen_events.get(event_key)
            # Compare to the newest representative, avoiding transitive day chains.
            if previous is not None and previous - published_at <= timedelta(hours=48):
                continue
            seen_events[event_key] = published_at
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
