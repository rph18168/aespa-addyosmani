"""SMTP delivery with explicit TLS modes and header validation."""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
import smtplib
import ssl
from typing import Callable

from .digest import DigestContent


class MailError(RuntimeError):
    """Raised when an email cannot be validated or delivered."""


def send_email(
    content: DigestContent,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    mail_from: str,
    mail_to: str,
    security: str = "starttls",
    timeout_seconds: float = 15,
    smtp_factory: Callable[[str, int, float, str], object] | None = None,
) -> None:
    """Send a multipart email through SMTP after validating all headers."""
    _validate_content(content)
    host = _validate_host(host)
    if not isinstance(port, int) or not 1 <= port <= 65_535:
        raise MailError("SMTP port is invalid")
    if not isinstance(username, str) or not username.strip():
        raise MailError("SMTP username must not be empty")
    if not isinstance(password, str) or not password:
        raise MailError("SMTP password must not be empty")
    if timeout_seconds <= 0:
        raise MailError("SMTP timeout must be positive")
    security = security.lower()
    if security not in {"starttls", "ssl", "none"}:
        raise MailError("SMTP security must be starttls, ssl or none")

    from_address = _mailbox(mail_from, "MAIL_FROM")
    recipient_addresses = _recipients(mail_to)
    message = EmailMessage()
    message["Subject"] = _header(content.subject, "Subject")
    message["From"] = _header(mail_from.strip(), "MAIL_FROM")
    message["To"] = _header(mail_to.strip(), "MAIL_TO")
    message.set_content(content.text)
    message.add_alternative(content.html, subtype="html")

    client = None
    try:
        if smtp_factory is not None:
            client = smtp_factory(host, port, timeout_seconds, security)
        else:
            client = _open_smtp(host, port, timeout_seconds, security)
        if security == "starttls":
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        client.login(username, password)
        client.send_message(
            message,
            from_addr=from_address,
            to_addrs=recipient_addresses,
        )
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError("email delivery failed") from exc
    finally:
        if client is not None:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                pass


def _validate_content(content: DigestContent) -> None:
    if not isinstance(content, DigestContent):
        raise MailError("invalid digest content")
    for field in (content.subject, content.text, content.html):
        if not isinstance(field, str):
            raise MailError("digest content fields must be strings")


def _validate_host(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MailError("SMTP host must not be empty")
    value = value.strip()
    if "\r" in value or "\n" in value or any(char.isspace() for char in value):
        raise MailError("SMTP host is invalid")
    return value


def _header(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MailError(f"{field_name} must not be empty")
    if "\r" in value or "\n" in value:
        raise MailError(f"{field_name} contains invalid header characters")
    return value.strip()


def _valid_address(value: str) -> bool:
    if not value or any(char.isspace() for char in value):
        return False
    if value.count("@") != 1:
        return False
    local, domain = value.rsplit("@", 1)
    return bool(local and domain and not local.startswith(".") and not domain.startswith("."))


def _mailbox(value: str, field_name: str) -> str:
    value = _header(value, field_name)
    _, address = parseaddr(value)
    if not _valid_address(address):
        raise MailError(f"{field_name} is not a valid email address")
    return address


def _recipients(value: str) -> list[str]:
    value = _header(value, "MAIL_TO")
    parsed = getaddresses([value])
    if not parsed or any(not _valid_address(address) for _, address in parsed):
        raise MailError("MAIL_TO contains an invalid email address")
    return [address for _, address in parsed]


def _open_smtp(host: str, port: int, timeout_seconds: float, security: str):
    if security == "ssl":
        return smtplib.SMTP_SSL(
            host,
            port,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        )
    return smtplib.SMTP(host, port, timeout=timeout_seconds)
