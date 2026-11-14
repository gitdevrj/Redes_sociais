"""Monitora a pasta inbox/ (watchdog) e dispara a ingestão quando o arquivo termina de copiar.

- Arquivo solto em inbox/  → post individual (vídeo ou imagem).
- Subpasta em inbox/       → carrossel (imagens) — processada quando parar de mudar.
- arquivo.txt com o mesmo nome do arquivo → briefing.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from .ingest import is_supported
from .logging_setup import get_logger

log = get_logger("watcher")


def _snapshot(path: Path) -> tuple:
    if path.is_dir():
        return tuple(sorted((p.name, p.stat().st_size) for p in path.rglob("*") if p.is_file()))
    return (path.stat().st_size,) if path.exists() else ()


class InboxWatcher:
    def __init__(self, inbox: Path, on_ready: Callable[[Path], None], settle_seconds: float = 5.0,
                 polling: bool = False):
        self.inbox = inbox
        self.polling = polling  # True no Docker Desktop/Windows e em pastas de rede/Google Drive
        self.on_ready = on_ready
        self.settle = settle_seconds
        self._pending: dict[Path, tuple[float, tuple]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ----- detecção -----
    def _top_level(self, raw: str) -> Path | None:
        p = Path(raw)
        try:
            rel = p.resolve().relative_to(self.inbox.resolve())
        except (ValueError, OSError):
            return None
        if not rel.parts or rel.parts[0].startswith((".", "~")):
            return None
        return self.inbox / rel.parts[0]

    def touch(self, raw: str) -> None:
        top = self._top_level(raw)
        if top is None:
            return
        if top.is_file() and top.suffix.lower() == ".txt":
            return  # briefing acompanha a mídia
        if top.is_file() and not is_supported(top):
            return
        with self._lock:
            self._pending[top] = (time.monotonic(), ())

    def scan_existing(self) -> None:
        for p in self.inbox.iterdir():
            if p.name.startswith(".") or p.name == ".gitkeep":
                continue
            self.touch(str(p))

    # ----- processamento -----
    def check_ready(self) -> list[Path]:
        ready: list[Path] = []
        now = time.monotonic()
        with self._lock:
            for path, (ts, snap) in list(self._pending.items()):
                if not path.exists():
                    self._pending.pop(path, None)
                    continue
                try:
                    current = _snapshot(path)
                except OSError:
                    continue  # ainda sendo escrito/bloqueado (comum no Windows)
                if current != snap:
                    self._pending[path] = (now, current)
                    continue
                if now - ts >= self.settle and current:
                    ready.append(path)
                    self._pending.pop(path, None)
        for path in ready:
            try:
                self.on_ready(path)
            except Exception:  # noqa: BLE001 — um arquivo ruim não derruba o watcher
                log.exception("falha ao processar item da inbox", extra={"data": {"item": path.name}})
        return ready

    def run(self, poll_seconds: float = 1.0) -> None:
        handler = _Handler(self)
        observer = PollingObserver(timeout=3) if self.polling else Observer()
        observer.schedule(handler, str(self.inbox), recursive=True)
        observer.start()
        self.scan_existing()
        log.info("monitorando inbox", extra={"data": {"pasta": str(self.inbox)}})
        try:
            while not self._stop.is_set():
                self.check_ready()
                time.sleep(poll_seconds)
        finally:
            observer.stop()
            observer.join()

    def stop(self) -> None:
        self._stop.set()


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: InboxWatcher):
        self.w = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in {"created", "modified", "moved", "closed"}:
            self.w.touch(getattr(event, "dest_path", None) or event.src_path)
