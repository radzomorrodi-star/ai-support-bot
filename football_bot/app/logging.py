"""Structured JSON logging with secret redaction."""
from __future__ import annotations

import logging
import re
import sys

from pythonjsonlogger.json import JsonFormatter

# Telegram bot tokens, API keys in query strings, 64-hex keys, bearer tokens, TOTP-ish secrets.
_PATTERNS = [
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"(?i)(apikey|api_key|token|secret|password|authorization)(=|\":\s*\"|:\s*)[^&\s\",]+"),
    re.compile(r"\b[A-Fa-f0-9]{48,}\b"),
]


def redact(text: str) -> str:
    for p in _PATTERNS:
        text = p.sub(lambda m: (m.group(1) + m.group(2) + "[REDACTED]") if m.lastindex and m.lastindex >= 2 else "[REDACTED]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = None
        except Exception:  # never let logging crash the app
            pass
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s", rename_fields={"asctime": "ts"}))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # httpx logs full URLs (which may contain API keys in query strings)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
