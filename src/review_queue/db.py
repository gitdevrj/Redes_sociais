"""Fila de posts em SQLite (sqlmodel).

Status: novo → analisado → gerado → aprovado → agendado → publicado | erro | descartado
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from sqlmodel import Field, Session, SQLModel, create_engine, select


class Status(str, Enum):
    NOVO = "novo"
    ANALISADO = "analisado"
    GERADO = "gerado"
    APROVADO = "aprovado"
    AGENDADO = "agendado"
    PUBLICADO = "publicado"
    ERRO = "erro"
    DESCARTADO = "descartado"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Post(SQLModel, table=True):
    id: str = Field(primary_key=True)
    tipo: str                                   # video | image | carousel
    origem: str = "inbox"                       # inbox | telegram | cli
    arquivos_json: str = "[]"
    briefing: str = ""
    is_sponsored: bool = False
    status: str = Field(default=Status.NOVO.value, index=True)
    confianca: int | None = None
    revisao_obrigatoria: bool = True
    erro: str = ""
    instrucao_regeneracao: str = ""
    telegram_chat_id: int | None = None
    criado_em: datetime = Field(default_factory=_now)
    atualizado_em: datetime = Field(default_factory=_now)

    @property
    def arquivos(self) -> list[str]:
        return json.loads(self.arquivos_json)


class PostRede(SQLModel, table=True):
    """Estado de cada post em cada rede (aprovação/agendamento/publicação)."""

    id: int | None = Field(default=None, primary_key=True)
    post_id: str = Field(index=True, foreign_key="post.id")
    rede: str
    status: str = Field(default=Status.GERADO.value)
    horario: datetime | None = None
    external_id: str = ""
    link: str = ""
    erro: str = ""
    atualizado_em: datetime = Field(default_factory=_now)


class Evento(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    post_id: str = Field(index=True)
    tipo: str
    detalhe: str = ""
    criado_em: datetime = Field(default_factory=_now)


class Database:
    def __init__(self, path: Path | str):
        url = "sqlite://" if str(path) == ":memory:" else f"sqlite:///{Path(path).as_posix()}"
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        from sqlalchemy.pool import StaticPool

        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if str(path) == ":memory:":
            kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)
        if str(path) != ":memory:":
            from sqlalchemy import event

            @event.listens_for(self.engine, "connect")
            def _pragmas(dbapi_conn, _rec):  # vários processos (watcher, bot, painel) no mesmo arquivo
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=10000")
                cur.close()
        SQLModel.metadata.create_all(self.engine)

    def session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)

    # ---------- posts ----------
    def add_post(self, post: Post) -> Post:
        with self.session() as s:
            s.add(post)
            s.add(Evento(post_id=post.id, tipo="criado", detalhe=post.origem))
            s.commit()
            s.refresh(post)
        return post

    def get(self, post_id: str) -> Post | None:
        with self.session() as s:
            return s.get(Post, post_id)

    def list(self, status: list[str] | None = None) -> list[Post]:
        with self.session() as s:
            q = select(Post).order_by(Post.criado_em.desc())  # type: ignore[attr-defined]
            if status:
                q = q.where(Post.status.in_(status))  # type: ignore[attr-defined]
            return list(s.exec(q))

    def update(self, post_id: str, evento: str | None = None, detalhe: str = "", **fields: Any) -> Post:
        with self.session() as s:
            post = s.get(Post, post_id)
            if post is None:
                raise KeyError(post_id)
            for k, v in fields.items():
                setattr(post, k, v.value if isinstance(v, Status) else v)
            post.atualizado_em = _now()
            s.add(post)
            if evento:
                s.add(Evento(post_id=post_id, tipo=evento, detalhe=detalhe))
            s.commit()
            s.refresh(post)
            return post

    def events(self, post_id: str) -> list[Evento]:
        with self.session() as s:
            q = select(Evento).where(Evento.post_id == post_id).order_by(Evento.id)  # type: ignore[arg-type]
            return list(s.exec(q))

    # ---------- redes ----------
    def upsert_rede(self, post_id: str, rede: str, **fields: Any) -> PostRede:
        with self.session() as s:
            q = select(PostRede).where(PostRede.post_id == post_id, PostRede.rede == rede)
            pr = s.exec(q).first() or PostRede(post_id=post_id, rede=rede)
            for k, v in fields.items():
                setattr(pr, k, v.value if isinstance(v, Status) else v)
            pr.atualizado_em = _now()
            s.add(pr)
            s.commit()
            s.refresh(pr)
            return pr

    def redes(self, post_id: str) -> list[PostRede]:
        with self.session() as s:
            return list(s.exec(select(PostRede).where(PostRede.post_id == post_id)))

    def agendados(self) -> Iterator[PostRede]:
        with self.session() as s:
            yield from s.exec(select(PostRede).where(PostRede.status == Status.AGENDADO.value))
