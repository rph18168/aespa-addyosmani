import json
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from .models import AppConfig, FeedConfig, SourceConfig


DEFAULT_SUMMARY_BASE_URL = "https://a-ocnfniawgw.cn-shanghai.fcapp.run/v1"
DEFAULT_SUMMARY_MODEL = "gpt-5-codex"


class ConfigurationError(ValueError):
    """Raised when application configuration is missing or unsafe."""


def load_config(
    sources_path: str | Path,
    *,
    state_path: str | Path = Path("data/state.json"),
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    environment = os.environ if environ is None else environ
    sources = _load_source_config(Path(sources_path))

    required_keys = (
        "SUMMARY_API_KEY",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "MAIL_FROM",
        "MAIL_TO",
    )
    missing_keys = [key for key in required_keys if not environment.get(key)]
    if missing_keys:
        missing = ", ".join(missing_keys)
        raise ConfigurationError(f"Missing required configuration: {missing}")

    summary_base_url = environment.get(
        "SUMMARY_BASE_URL", DEFAULT_SUMMARY_BASE_URL
    ).rstrip("/")
    _require_https_url(summary_base_url, "SUMMARY_BASE_URL")

    smtp_port = _parse_int(environment["SMTP_PORT"], "SMTP_PORT", 1, 65535)
    lookback_hours = _parse_int(
        environment.get("LOOKBACK_HOURS", "36"), "LOOKBACK_HOURS", 1, 168
    )
    max_articles = _parse_int(
        environment.get("MAX_ARTICLES", "20"), "MAX_ARTICLES", 1, 100
    )
    request_timeout = _parse_float(
        environment.get("REQUEST_TIMEOUT_SECONDS", "15"),
        "REQUEST_TIMEOUT_SECONDS",
        1,
        60,
    )
    smtp_security = environment.get("SMTP_SECURITY", "starttls").lower()
    if smtp_security not in {"starttls", "ssl", "none"}:
        raise ConfigurationError(
            "SMTP_SECURITY must be one of: starttls, ssl, none"
        )

    return AppConfig(
        sources=sources,
        state_path=Path(environment.get("STATE_PATH", str(state_path))),
        summary_base_url=summary_base_url,
        summary_model=environment.get("SUMMARY_MODEL", DEFAULT_SUMMARY_MODEL),
        summary_api_key=environment["SUMMARY_API_KEY"],
        smtp_host=environment["SMTP_HOST"],
        smtp_port=smtp_port,
        smtp_username=environment["SMTP_USERNAME"],
        smtp_password=environment["SMTP_PASSWORD"],
        mail_from=environment["MAIL_FROM"],
        mail_to=environment["MAIL_TO"],
        smtp_security=smtp_security,
        lookback_hours=lookback_hours,
        max_articles=max_articles,
        request_timeout_seconds=request_timeout,
    )


def _load_source_config(path: Path) -> SourceConfig:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"Unable to read source configuration: {path}") from error

    if not isinstance(payload, dict):
        raise ConfigurationError("Source configuration must be a JSON object")

    keywords = _read_non_empty_strings(payload.get("keywords"), "keywords")
    trusted_domains = tuple(
        _normalize_domain(value, "trusted_domains")
        for value in _read_non_empty_strings(
            payload.get("trusted_domains"), "trusted_domains"
        )
    )
    feeds_payload = payload.get("feeds")
    if not isinstance(feeds_payload, list) or not feeds_payload:
        raise ConfigurationError("feeds must be a non-empty list")

    feeds: list[FeedConfig] = []
    for index, feed_payload in enumerate(feeds_payload):
        if not isinstance(feed_payload, dict):
            raise ConfigurationError(f"feeds[{index}] must be an object")
        name = feed_payload.get("name")
        url = feed_payload.get("url")
        fallback_domain = feed_payload.get("fallback_domain")
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError(f"feeds[{index}].name must be non-empty")
        if not isinstance(url, str) or not url.strip():
            raise ConfigurationError(f"feeds[{index}].url must be non-empty")
        _require_https_url(url, f"feeds[{index}].url")
        if fallback_domain is not None:
            if not isinstance(fallback_domain, str) or not fallback_domain.strip():
                raise ConfigurationError(
                    f"feeds[{index}].fallback_domain must be non-empty"
                )
            fallback_domain = _normalize_domain(
                fallback_domain, f"feeds[{index}].fallback_domain"
            )
        feeds.append(
            FeedConfig(
                name=name.strip(),
                url=url.strip(),
                fallback_domain=fallback_domain,
            )
        )

    return SourceConfig(
        keywords=tuple(keyword.strip() for keyword in keywords),
        trusted_domains=trusted_domains,
        feeds=tuple(feeds),
    )


def _read_non_empty_strings(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ConfigurationError(f"{field_name} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigurationError(f"{field_name} must contain non-empty strings")
    return value


def _normalize_domain(value: str, field_name: str) -> str:
    domain = value.strip().lower().rstrip(".")
    if domain.startswith(".") or "/" in domain or " " in domain:
        raise ConfigurationError(f"{field_name} contains an invalid domain")
    return domain


def _require_https_url(value: str, field_name: str) -> None:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as error:
        raise ConfigurationError(f"{field_name} must be a valid HTTPS URL") from error
    if parsed.scheme.lower() != "https" or not hostname:
        raise ConfigurationError(f"{field_name} must be an HTTPS URL")
    if parsed.username or parsed.password:
        raise ConfigurationError(f"{field_name} must not contain credentials")
    if field_name == "SUMMARY_BASE_URL" and (parsed.query or parsed.fragment):
        raise ConfigurationError(f"{field_name} must not contain a query or fragment")
    if any(character.isspace() for character in value):
        raise ConfigurationError(f"{field_name} must not contain whitespace")


def _parse_int(value: str, field_name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{field_name} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise ConfigurationError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    return parsed


def _parse_float(
    value: str, field_name: str, minimum: float, maximum: float
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{field_name} must be a number") from error
    if not minimum <= parsed <= maximum:
        raise ConfigurationError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    return parsed
