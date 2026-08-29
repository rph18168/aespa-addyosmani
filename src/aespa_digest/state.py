"""Idempotency state for articles that were successfully delivered."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .models import Article
from .qualification import _canonical_url

STATE_VERSION = 1
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class StateError(RuntimeError):
    """Raised when idempotency state cannot be safely read or written."""


@dataclass(slots=True)
class DeliveryState:
    """In-memory state mapping article fingerprints to delivery timestamps."""

    sent: dict[str, str]


def load_state(path: str | Path) -> DeliveryState:
    """Load state, treating a missing file as the first run."""
    state_path = Path(path)
    try:
        raw = state_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DeliveryState(sent={})
    except OSError as exc:
        raise StateError("unable to read state file") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateError("state file contains invalid JSON") from exc
    return _state_from_payload(payload)


def save_state(path: str | Path, state: DeliveryState) -> None:
    """Atomically replace the state file with validated JSON."""
    payload = _payload_from_state(state)
    state_path = Path(path)
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{state_path.name}.",
            suffix=".tmp",
            dir=state_path.parent,
        )
    except OSError as exc:
        raise StateError("unable to create temporary state file") from exc

    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, state_path)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise StateError("unable to write state file") from exc


def article_fingerprint(article: Article) -> str:
    """Return a stable SHA-256 identity for one qualified article."""
    canonical_url = _canonical_url(article.link)
    if canonical_url is None:
        raise StateError("cannot fingerprint a non-HTTPS article link")
    title = re.sub(r"\s+", " ", article.title).strip().casefold()
    if not title:
        raise StateError("cannot fingerprint an article without a title")
    material = f"{canonical_url}\x00{title}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def has_been_sent(state: DeliveryState, article: Article) -> bool:
    """Check whether an article fingerprint is present in state."""
    _ensure_state(state)
    return article_fingerprint(article) in state.sent


def mark_sent(
    state: DeliveryState,
    articles: list[Article],
    *,
    sent_at: datetime | None = None,
) -> DeliveryState:
    """Mark articles as delivered in memory; callers persist only after SMTP success."""
    _ensure_state(state)
    timestamp = _normalize_datetime(sent_at or datetime.now(timezone.utc))
    for article in articles:
        state.sent[article_fingerprint(article)] = timestamp.isoformat()
    return state


def _state_from_payload(payload: object) -> DeliveryState:
    if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
        raise StateError("state file has an unsupported schema")
    sent_payload = payload.get("sent")
    if not isinstance(sent_payload, dict):
        raise StateError("state file sent field must be an object")

    sent: dict[str, str] = {}
    for fingerprint, metadata in sent_payload.items():
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise StateError("state file contains an invalid article fingerprint")
        if not isinstance(metadata, dict) or set(metadata) - {"sent_at"}:
            raise StateError("state file contains invalid article metadata")
        sent_at = metadata.get("sent_at")
        if not isinstance(sent_at, str):
            raise StateError("state file sent_at must be a string")
        sent[fingerprint] = _normalize_iso_timestamp(sent_at).isoformat()
    return DeliveryState(sent=sent)


def _payload_from_state(state: DeliveryState) -> dict[str, object]:
    _ensure_state(state)
    return {
        "version": STATE_VERSION,
        "sent": {
            fingerprint: {"sent_at": _normalize_iso_timestamp(sent_at).isoformat()}
            for fingerprint, sent_at in sorted(state.sent.items())
        },
    }


def _ensure_state(state: DeliveryState) -> None:
    if not isinstance(state, DeliveryState) or not isinstance(state.sent, dict):
        raise StateError("invalid in-memory state")


def _normalize_iso_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise StateError("state file contains an invalid timestamp") from exc
    return _normalize_datetime(parsed)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise StateError("timestamps must include a timezone")
    return value.astimezone(timezone.utc)
