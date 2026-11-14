"""Ações da fila (usadas pelo painel web e pelo bot do Telegram)."""
from __future__ import annotations

import shutil
from datetime import datetime

from ..logging_setup import get_logger
from .db import Database, Status

log = get_logger("actions")

ATIVOS = {Status.GERADO.value, Status.APROVADO.value, Status.AGENDADO.value, Status.ERRO.value}


def approve(db: Database, post_id: str, horarios: dict[str, datetime | None] | None = None,
            redes: list[str] | None = None) -> list[str]:
    """Aprova o post. Redes com horário ficam 'agendado' (o agendador publica na Fase 3)."""
    post = db.get(post_id)
    if post is None:
        raise KeyError(post_id)
    if post.status not in ATIVOS:
        raise ValueError(f"post em status '{post.status}' não pode ser aprovado")
    aprovadas = []
    for pr in db.redes(post_id):
        if redes is not None and pr.rede not in redes:
            continue
        horario = (horarios or {}).get(pr.rede, pr.horario)
        db.upsert_rede(post_id, pr.rede, status=Status.AGENDADO if horario else Status.APROVADO, horario=horario)
        aprovadas.append(pr.rede)
    db.update(post_id, evento="aprovado", detalhe=",".join(aprovadas), status=Status.APROVADO)
    return aprovadas


def reschedule(db: Database, post_id: str, rede: str, horario: datetime) -> None:
    db.upsert_rede(post_id, rede, horario=horario)
    db.update(post_id, evento="reagendado", detalhe=f"{rede} → {horario.isoformat()}")


def discard(db: Database, post_id: str, trash_dir=None, processing_dir=None) -> None:
    db.update(post_id, evento="descartado", status=Status.DESCARTADO)
    for pr in db.redes(post_id):
        db.upsert_rede(post_id, pr.rede, status=Status.DESCARTADO)
    if trash_dir is not None and processing_dir is not None:
        src = processing_dir / post_id
        if src.exists():
            trash_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(trash_dir / post_id))
