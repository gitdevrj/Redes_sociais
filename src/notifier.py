"""Notificações pelo Telegram (post pronto para aprovar, publicado, falha)."""
from __future__ import annotations

from typing import Any

import httpx

from .logging_setup import get_logger
from .settings import Settings

log = get_logger("notifier")


class TelegramClient:
    """Cliente mínimo da Bot API (https://core.telegram.org/bots/api) via httpx."""

    def __init__(self, token: str, base: str = "https://api.telegram.org", http: httpx.Client | None = None):
        self._token = token
        self.base = base.rstrip("/")
        self.http = http or httpx.Client(timeout=httpx.Timeout(70.0, connect=10.0))

    def _url(self, method: str) -> str:
        return f"{self.base}/bot{self._token}/{method}"

    def call(self, method: str, **params: Any) -> Any:
        files = params.pop("_files", None)
        if files:
            r = self.http.post(self._url(method), data={k: v for k, v in params.items() if v is not None}, files=files)
        else:
            r = self.http.post(self._url(method), json={k: v for k, v in params.items() if v is not None})
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description', r.status_code)}")
        return data["result"]

    def file_url(self, file_path: str) -> str:
        return f"{self.base}/file/bot{self._token}/{file_path}"

    def download(self, file_path: str) -> bytes:
        if file_path.startswith("/"):
            # Local Bot API Server devolve caminho absoluto no disco compartilhado
            with open(file_path, "rb") as f:
                return f.read()
        r = self.http.get(self.file_url(file_path))
        r.raise_for_status()
        return r.content


def review_keyboard(post_id: str) -> dict:
    # callback_data tem limite de 64 bytes (Bot API) — IDs têm ~22 caracteres.
    return {"inline_keyboard": [
        [{"text": "✅ Aprovar", "callback_data": f"ap:{post_id}"},
         {"text": "🔁 Regenerar", "callback_data": f"rg:{post_id}"}],
        [{"text": "🗑 Descartar", "callback_data": f"ds:{post_id}"}],
    ]}


class Notifier:
    def __init__(self, settings: Settings, client: TelegramClient | None = None):
        self.s = settings
        self.client = client
        if client is None and settings.telegram_bot_token:
            self.client = TelegramClient(settings.telegram_bot_token.get_secret_value(), settings.telegram_api_base)

    def _chat(self, chat_id: int | None) -> int | None:
        return chat_id or self.s.telegram_notify_chat_id or (self.s.telegram_allowed_user_ids or [None])[0]

    def send(self, text: str, chat_id: int | None = None, keyboard: dict | None = None,
             photo: bytes | None = None) -> bool:
        chat = self._chat(chat_id)
        if not self.client or not chat:
            log.info("notificação (Telegram não configurado)", extra={"data": {"texto": text[:200]}})
            return False
        try:
            if photo:
                self.client.call("sendPhoto", chat_id=chat, caption=text[:1024], parse_mode="HTML",
                                 reply_markup=_json(keyboard), _files={"photo": ("preview.jpg", photo, "image/jpeg")})
            else:
                self.client.call("sendMessage", chat_id=chat, text=text[:4096], parse_mode="HTML",
                                 reply_markup=keyboard, link_preview_options={"is_disabled": True})
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("falha ao notificar no Telegram", extra={"data": {"erro": str(exc)[:200]}})
            return False


def _json(obj: dict | None) -> str | None:
    import json

    return json.dumps(obj) if obj else None
