"""Build safe plain-text and HTML email content for the daily digest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import re
from typing import Iterable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .models import Article

BEIJING = ZoneInfo("Asia/Shanghai")


class DigestError(ValueError):
    """Raised when an article cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class DigestItem:
    article: Article
    summary: str


@dataclass(frozen=True, slots=True)
class DigestContent:
    subject: str
    text: str
    html: str


def build_digest(
    items: Iterable[DigestItem],
    *,
    generated_at: datetime,
) -> DigestContent:
    """Render all selected articles, or an explicit no-update message."""
    if generated_at.tzinfo is None:
        raise DigestError("generated_at must be timezone-aware")
    digest_items = list(items)
    local_generated_at = generated_at.astimezone(BEIJING)
    date_label = f"{local_generated_at.year}年{local_generated_at.month}月{local_generated_at.day}日"
    as_of = local_generated_at.strftime("%Y-%m-%d %H:%M") + "（北京时间）"
    heading = f"aespa 每日新闻（{date_label}）"

    if not digest_items:
        subject = "aespa 每日新闻｜今日暂无更新"
        text = f"{heading}\n\n今日暂无更新。\n\n截至：{as_of}\n"
        html = (
            "<!doctype html><html><head><meta charset=\"utf-8\"></head><body>"
            f"<h1>{escape(heading)}</h1>"
            "<p><strong>今日暂无更新。</strong></p>"
            f"<p>截至：{escape(as_of)}</p></body></html>"
        )
        return DigestContent(subject=subject, text=text, html=html)

    subject = f"aespa 每日新闻｜{date_label}｜{len(digest_items)} 条更新"
    text_lines = [heading, "", f"共 {len(digest_items)} 条更新。", ""]
    html_parts = [
        "<!doctype html><html><head><meta charset=\"utf-8\"></head><body>",
        f"<h1>{escape(heading)}</h1>",
        f"<p>共 {len(digest_items)} 条更新。更新时间：{escape(as_of)}</p>",
    ]
    for index, item in enumerate(digest_items, start=1):
        article = item.article
        link = _validated_link(article.link)
        title = _display(article.title, "未命名文章")
        summary = _display(item.summary, "暂无中文摘要")
        source = _display(article.source_name, "未知来源")
        published = _article_time(article.published_at)
        text_lines.extend(
            [
                f"{index}. {title}",
                f"中文摘要：{summary}",
                f"来源：{source}",
                f"发布时间：{published}",
                f"原文：{link}",
                "",
            ]
        )
        html_parts.append(
            "<article>"
            f"<h2>{index}. {escape(title)}</h2>"
            f"<p><strong>中文摘要：</strong>{escape(summary)}</p>"
            f"<p><strong>来源：</strong>{escape(source)}<br>"
            f"<strong>发布时间：</strong>{escape(published)}<br>"
            f"<strong>原文：</strong><a href=\"{escape(link, quote=True)}\">查看原文</a></p>"
            "</article>"
        )
    html_parts.append("</body></html>")
    return DigestContent(
        subject=subject,
        text="\n".join(text_lines).rstrip() + "\n",
        html="".join(html_parts),
    )


def _validated_link(value: str) -> str:
    if not isinstance(value, str):
        raise DigestError("article link must be a string")
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise DigestError("article links must use HTTPS")
        if parsed.username or parsed.password:
            raise DigestError("article links must not contain credentials")
        _ = parsed.port
    except ValueError as exc:
        raise DigestError("article link is invalid") from exc
    return value


def _display(value: str, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned[:5_000] or fallback


def _article_time(value: datetime | None) -> str:
    if value is None:
        return "未知"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M（北京时间）")
