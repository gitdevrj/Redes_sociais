"""Interface comum dos publicadores (implementações reais na Fase 3)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..schemas import PlatformPost


@dataclass
class PublishResult:
    ok: bool
    external_id: str = ""
    link: str = ""
    erro: str = ""
    dry_run: bool = False


class Publisher(ABC):
    rede: str

    @abstractmethod
    def publish(self, post: PlatformPost, media_paths: list[str]) -> PublishResult: ...

    def schedule(self, post: PlatformPost, media_paths: list[str], when: datetime) -> PublishResult:
        """Por padrão o agendamento é local (APScheduler chama publish no horário)."""
        raise NotImplementedError

    @abstractmethod
    def status(self, external_id: str) -> str: ...

    @abstractmethod
    def delete(self, external_id: str) -> bool: ...


class DryRunPublisher(Publisher):
    """Não chama API nenhuma: só registra o que SERIA publicado."""

    def __init__(self, rede: str):
        self.rede = rede

    def publish(self, post: PlatformPost, media_paths: list[str]) -> PublishResult:
        return PublishResult(ok=True, external_id=f"dryrun-{post.post_id}-{self.rede}", dry_run=True)

    def status(self, external_id: str) -> str:
        return "dry_run"

    def delete(self, external_id: str) -> bool:
        return True
