"""Logs estruturados em JSON, com mascaramento de segredos."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Padrões que nunca devem aparecer em log.
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{30,}\b"),            # token de bot do Telegram
    re.compile(r"/bot[^/\s]+/"),                                   # URL com token do Telegram
    re.compile(r"(access_token|refresh_token|client_secret|password|api_key)=([^&\s]+)", re.I),
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-\._~\+/]+=*", re.I),
    re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),                  # CPF
    re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"),            # CNPJ
]


def redact(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 2:
            text = pat.sub(lambda m: f"{m.group(1)}=***", text)
        elif pat.groups == 1:
            text = pat.sub(lambda m: f"{m.group(1)}***", text)
        elif pat.pattern.startswith("/bot"):
            text = pat.sub("/bot***/", text)
        else:
            text = pat.sub("***", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "data", None)
        if extra:
            payload["data"] = json.loads(redact(json.dumps(extra, ensure_ascii=False, default=str)))
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


_configured = False


def setup_logging(logs_dir: Path, level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level.upper())
    fh = logging.FileHandler(logs_dir / "autopost.jsonl", encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(JsonFormatter())
    root.handlers = [fh, sh]
    # bibliotecas verbosas que podem logar URLs com token
    for noisy in ("httpx", "httpcore", "httpx2", "anthropic", "watchdog"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
