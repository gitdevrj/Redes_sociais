"""Configurações vindas do .env (segredos e parâmetros de execução)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _int_list(value: str | None) -> list[int]:
    if not value:
        return []
    return [int(v) for v in value.replace(";", ",").split(",") if v.strip()]


class Settings(BaseModel):
    base_dir: Path
    dry_run: bool = True

    anthropic_api_key: SecretStr | None = None
    claude_model: str = "claude-sonnet-5-5"
    claude_effort: str = "medium"
    ai_provider: str = "auto"  # auto | claude | offline

    whisper_enabled: bool = True
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    review_host: str = "127.0.0.1"
    review_port: int = 8000
    review_user: str = "admin"
    review_password: SecretStr = SecretStr("")

    telegram_bot_token: SecretStr | None = None
    telegram_allowed_user_ids: list[int] = Field(default_factory=list)
    telegram_notify_chat_id: int | None = None
    telegram_api_base: str = "https://api.telegram.org"

    log_level: str = "INFO"
    watcher_polling: bool = False

    # ---- caminhos derivados ----
    @property
    def inbox(self) -> Path:
        return self.base_dir / "inbox"

    @property
    def processing(self) -> Path:
        return self.base_dir / "processing"

    @property
    def output(self) -> Path:
        return self.base_dir / "output"

    @property
    def published(self) -> Path:
        return self.base_dir / "published"

    @property
    def config_dir(self) -> Path:
        return self.base_dir / "config"

    @property
    def music_dir(self) -> Path:
        return self.base_dir / "music"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"

    @property
    def db_path(self) -> Path:
        return self.base_dir / "data" / "autopost.db"

    @property
    def use_claude(self) -> bool:
        if self.ai_provider == "offline":
            return False
        if self.ai_provider == "claude":
            return True
        return bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value())

    def ensure_dirs(self) -> None:
        for p in (self.inbox, self.processing, self.output, self.published, self.logs_dir, self.db_path.parent):
            p.mkdir(parents=True, exist_ok=True)


def load_settings(base_dir: Path | None = None, env_file: Path | None = None) -> Settings:
    root = Path(base_dir or os.getenv("AUTOPOST_BASE_DIR") or Path(__file__).resolve().parents[1]).resolve()
    load_dotenv(env_file or root / ".env", override=False)
    env = os.environ
    key = env.get("ANTHROPIC_API_KEY") or None
    tg = env.get("TELEGRAM_BOT_TOKEN") or None
    notify = env.get("TELEGRAM_NOTIFY_CHAT_ID")
    return Settings(
        base_dir=root,
        dry_run=_bool(env.get("DRY_RUN"), True),
        anthropic_api_key=SecretStr(key) if key else None,
        claude_model=env.get("CLAUDE_MODEL") or "claude-sonnet-5-5",
        claude_effort=env.get("CLAUDE_EFFORT") or "medium",
        ai_provider=(env.get("AI_PROVIDER") or "auto").lower(),
        whisper_enabled=_bool(env.get("WHISPER_ENABLED"), True),
        whisper_model=env.get("WHISPER_MODEL") or "small",
        whisper_device=env.get("WHISPER_DEVICE") or "cpu",
        whisper_compute_type=env.get("WHISPER_COMPUTE_TYPE") or "int8",
        review_host=env.get("REVIEW_HOST") or "127.0.0.1",
        review_port=int(env.get("REVIEW_PORT") or 8000),
        review_user=env.get("REVIEW_USER") or "admin",
        review_password=SecretStr(env.get("REVIEW_PASSWORD") or ""),
        telegram_bot_token=SecretStr(tg) if tg else None,
        telegram_allowed_user_ids=_int_list(env.get("TELEGRAM_ALLOWED_USER_IDS")),
        telegram_notify_chat_id=int(notify) if notify and notify.strip() else None,
        telegram_api_base=(env.get("TELEGRAM_API_BASE") or "https://api.telegram.org").rstrip("/"),
        log_level=env.get("LOG_LEVEL") or "INFO",
        watcher_polling=_bool(env.get("WATCHER_POLLING"), False),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
