"""Bot do Telegram: recebe vídeos/imagens (com legenda = briefing) e aprova posts por botões.

Bot API consultada em 2026-11-14 (versão 10.4). Pontos relevantes:
- getUpdates (long polling); callback_data de 1–64 bytes; media_group_id agrupa álbuns.
- getFile só baixa arquivos de até 20 MB nos servidores do Telegram. Com o Local Bot API Server
  não há limite de download (TELEGRAM_API_BASE apontando para ele).
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .ingest import IMAGE_EXT, VIDEO_EXT, ingest
from .logging_setup import get_logger
from .notifier import TelegramClient
from .review_queue import actions
from .review_queue.db import Database
from .settings import Settings

log = get_logger("telegram")
CLOUD_LIMIT = 20 * 1024 * 1024
MIME_EXT = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-m4v": ".m4v", "image/jpeg": ".jpg",
            "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic", "image/heif": ".heic"}
HELP = (
    "Envie um <b>vídeo</b> ou <b>imagem</b> (de preferência como <i>arquivo</i>, para não perder qualidade).\n"
    "O texto que você escrever junto vira o <b>briefing</b> do post.\n"
    "Várias fotos no mesmo envio (álbum) viram um <b>carrossel</b>.\n\n"
    "Comandos:\n/status — posts aguardando revisão\n/regen &lt;id&gt; &lt;instrução&gt; — gerar nova versão\n"
    "/aprovar &lt;id&gt; · /descartar &lt;id&gt;\n/meuid — mostra seu ID do Telegram"
)


class TelegramBot:
    def __init__(self, settings: Settings, db: Database, on_ingested: Callable[[list[str], int], None],
                 client: TelegramClient | None = None, on_regen: Callable[[str, str, int], None] | None = None,
                 group_wait: float = 4.0):
        if client is None:
            if not settings.telegram_bot_token:
                raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado no .env")
            client = TelegramClient(settings.telegram_bot_token.get_secret_value(), settings.telegram_api_base)
        self.s = settings
        self.db = db
        self.client = client
        self.on_ingested = on_ingested
        self.on_regen = on_regen
        self.group_wait = group_wait
        self.staging = settings.base_dir / "data" / "telegram_staging"
        self.offset = 0
        self._groups: dict[str, dict[str, Any]] = {}
        self._pending_regen: dict[int, str] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.local_server = "api.telegram.org" not in settings.telegram_api_base

    # ------------------------------------------------------------ util
    def allowed(self, user_id: int | None) -> bool:
        return bool(user_id) and user_id in self.s.telegram_allowed_user_ids

    def reply(self, chat_id: int, text: str, **kw: Any) -> None:
        try:
            self.client.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", **kw)
        except Exception as exc:  # noqa: BLE001
            log.warning("falha ao responder no Telegram", extra={"data": {"erro": str(exc)[:200]}})

    # ------------------------------------------------------------ loop
    def poll_once(self, timeout: int = 50) -> int:
        updates = self.client.call("getUpdates", offset=self.offset or None, timeout=timeout,
                                   allowed_updates=["message", "callback_query"])
        for upd in updates:
            self.offset = max(self.offset, upd["update_id"] + 1)
            try:
                self.handle_update(upd)
            except Exception:  # noqa: BLE001
                log.exception("erro tratando update do Telegram")
        self.flush_groups()
        return len(updates)

    def run(self) -> None:
        if not self.s.telegram_allowed_user_ids:
            log.warning("TELEGRAM_ALLOWED_USER_IDS vazio: o bot só responderá /meuid até você configurar.")
        log.info("bot do Telegram iniciado")
        while not self._stop.is_set():
            try:
                self.poll_once(timeout=2 if self._groups else 50)
            except Exception as exc:  # noqa: BLE001
                log.warning("falha no long polling; tentando de novo", extra={"data": {"erro": str(exc)[:200]}})
                time.sleep(5)

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------ updates
    def handle_update(self, upd: dict) -> None:
        if "callback_query" in upd:
            return self.handle_callback(upd["callback_query"])
        msg = upd.get("message")
        if not msg:
            return
        chat_id = msg["chat"]["id"]
        user_id = (msg.get("from") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if text.startswith(("/meuid", "/start")):
            self.reply(chat_id, f"Seu ID do Telegram: <code>{user_id}</code>\n"
                                f"Coloque-o em TELEGRAM_ALLOWED_USER_IDS no .env." +
                       (f"\n\n{HELP}" if self.allowed(user_id) else ""))
            return
        if not self.allowed(user_id):
            log.warning("mensagem de usuário não autorizado ignorada", extra={"data": {"user_id": user_id}})
            self.reply(chat_id, "Usuário não autorizado. Use /meuid e cadastre seu ID no .env.")
            return
        if text:
            return self.handle_text(chat_id, text)
        self.handle_media(msg)

    def handle_text(self, chat_id: int, text: str) -> None:
        if text.startswith("/help") or text.startswith("/ajuda"):
            return self.reply(chat_id, HELP)
        if text.startswith("/status"):
            pend = self.db.list(["gerado", "analisado", "novo", "erro"])
            if not pend:
                return self.reply(chat_id, "Nenhum post aguardando revisão. ✅")
            linhas = [f"• <code>{p.id}</code> — {p.tipo} — {p.status} — conf. {p.confianca or '—'}" for p in pend[:15]]
            return self.reply(chat_id, "Aguardando revisão:\n" + "\n".join(linhas))
        m = re.match(r"^/(regen|aprovar|descartar)\s+(\S+)\s*(.*)$", text, re.S)
        if m:
            cmd, pid, resto = m.groups()
            return self._command(chat_id, cmd, pid, resto.strip())
        if chat_id in self._pending_regen:
            pid = self._pending_regen.pop(chat_id)
            return self._command(chat_id, "regen", pid, text)
        self.reply(chat_id, "Não entendi. Envie uma mídia ou use /ajuda.")

    def _command(self, chat_id: int, cmd: str, pid: str, arg: str = "") -> None:
        if self.db.get(pid) is None:
            return self.reply(chat_id, f"Post <code>{pid}</code> não encontrado.")
        try:
            if cmd == "aprovar":
                redes = actions.approve(self.db, pid)
                self.reply(chat_id, f"✅ Aprovado ({', '.join(redes)}). "
                                    + ("Modo DRY-RUN: nada será publicado." if self.s.dry_run else
                                       "Será publicado nos horários agendados."))
            elif cmd == "descartar":
                actions.discard(self.db, pid)
                self.reply(chat_id, "🗑 Descartado.")
            elif cmd == "regen":
                if not arg:
                    self._pending_regen[chat_id] = pid
                    return self.reply(chat_id, "Escreva a instrução para a nova versão (ex.: <i>mais curto, foco em MEI</i>).")
                self.reply(chat_id, "🔁 Gerando nova versão…")
                if self.on_regen:
                    self.on_regen(pid, arg, chat_id)
        except ValueError as exc:
            self.reply(chat_id, f"Não foi possível: {exc}")

    def handle_callback(self, cq: dict) -> None:
        user_id = (cq.get("from") or {}).get("id")
        chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id") or user_id
        try:
            self.client.call("answerCallbackQuery", callback_query_id=cq["id"])
        except Exception:  # noqa: BLE001
            pass
        if not self.allowed(user_id):
            return
        data = cq.get("data") or ""
        acao, _, pid = data.partition(":")
        cmd = {"ap": "aprovar", "ds": "descartar", "rg": "regen"}.get(acao)
        if cmd:
            self._command(chat_id, cmd, pid)

    # ------------------------------------------------------------ mídia
    def _pick_file(self, msg: dict) -> tuple[dict, str] | None:
        if msg.get("photo"):
            return msg["photo"][-1], ".jpg"  # maior resolução (foto comprimida pelo Telegram)
        if msg.get("video"):
            v = msg["video"]
            return v, MIME_EXT.get(v.get("mime_type", ""), ".mp4")
        doc = msg.get("document")
        if doc:
            name = doc.get("file_name") or ""
            ext = Path(name).suffix.lower() or MIME_EXT.get(doc.get("mime_type", ""), "")
            if ext in IMAGE_EXT | VIDEO_EXT:
                return doc, ext
        return None

    def handle_media(self, msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        picked = self._pick_file(msg)
        if not picked:
            return self.reply(chat_id, "Formato não suportado. Envie .mp4 .mov .m4v .jpg .png .heic .webp.")
        fobj, ext = picked
        size = int(fobj.get("file_size") or 0)
        if size > CLOUD_LIMIT and not self.local_server:
            return self.reply(chat_id, (
                f"⚠️ Arquivo de {size / 1_048_576:.0f} MB. Pelos servidores do Telegram o bot só consegue baixar "
                "até 20 MB.\nOpções: (1) coloque o arquivo na pasta <b>inbox</b> do AutoPost (ou na pasta do Google "
                "Drive sincronizada com ela); (2) ative o <i>Local Bot API Server</i> (veja o README)."))
        caption = (msg.get("caption") or "").strip()
        group = msg.get("media_group_id")
        key = f"g{group}" if group else f"m{msg['message_id']}"
        folder = self.staging / key
        folder.mkdir(parents=True, exist_ok=True)
        info = self.client.call("getFile", file_id=fobj["file_id"])
        data = self.client.download(info["file_path"])
        original = (fobj.get("file_name") or f"{msg['message_id']}{ext}")
        dest = folder / f"{msg['message_id']:012d}_{Path(original).stem[:40]}{ext}"
        dest.write_bytes(data)
        with self._lock:
            g = self._groups.setdefault(key, {"chat_id": chat_id, "captions": [], "ts": 0.0, "folder": folder,
                                              "single": not group})
            if caption:
                g["captions"].append(caption)
            g["ts"] = time.monotonic()
        if not group:
            self.flush_groups(force_key=key)

    def flush_groups(self, force_key: str | None = None) -> None:
        now = time.monotonic()
        with self._lock:
            ready = [k for k, g in self._groups.items()
                     if k == force_key or now - g["ts"] >= self.group_wait]
            items = [(k, self._groups.pop(k)) for k in ready]
        for _key, g in items:
            folder: Path = g["folder"]
            if g["captions"]:
                (folder / "briefing.txt").write_text("\n".join(g["captions"]), encoding="utf-8")
            ids = ingest(folder, self.db, self.s.processing, origem="telegram", telegram_chat_id=g["chat_id"])
            if ids:
                self.reply(g["chat_id"], f"📥 Recebido! Analisando {len(ids)} post(s): " +
                           ", ".join(f"<code>{i}</code>" for i in ids))
                self.on_ingested(ids, g["chat_id"])


def make_worker() -> ThreadPoolExecutor:
    """Processa um post por vez (FFmpeg/Whisper são pesados)."""
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="autopost-worker")


