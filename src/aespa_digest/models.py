from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FeedConfig:
    name: str
    url: str
    fallback_domain: str | None = None


@dataclass(frozen=True, slots=True)
class SourceConfig:
    keywords: tuple[str, ...]
    trusted_domains: tuple[str, ...]
    feeds: tuple[FeedConfig, ...]


@dataclass(frozen=True, slots=True)
class AppConfig:
    sources: SourceConfig
    state_path: Path
    summary_base_url: str
    summary_model: str
    summary_api_key: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    mail_from: str
    mail_to: str
    smtp_security: str
    lookback_hours: int
    max_articles: int
    request_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class Article:
    title: str
    summary: str
    link: str
    source_name: str
    source_domain: str | None
    published_at: datetime | None
