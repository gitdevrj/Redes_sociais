"""CLI do AutoPost.

    python -m src.main run                 # watcher + bot do Telegram + painel (tudo junto)
    python -m src.main watch               # só monitora a inbox
    python -m src.main bot                 # só o bot do Telegram
    python -m src.main review              # só o painel web
    python -m src.main analyze <arquivo>   # processa um arquivo/pasta e imprime o JSON gerado
    python -m src.main status [--todos]
    python -m src.main publish <id>        # Fase 3
"""
from __future__ import annotations

import argparse
import shutil
import sys
import threading
from pathlib import Path

from .ingest import ingest
from .logging_setup import get_logger, setup_logging
from .pipeline import Pipeline, dump
from .review_queue.db import Database
from .settings import Settings, load_settings

log = get_logger("main")


def build(settings: Settings) -> Pipeline:
    settings.ensure_dirs()
    setup_logging(settings.logs_dir, settings.log_level)
    return Pipeline(settings, Database(settings.db_path))


def _process_async(pipe: Pipeline, worker):
    def handler(ids: list[str], _chat_id: int | None = None) -> None:
        for pid in ids:
            worker.submit(_safe_process, pipe, pid)
    return handler


def _safe_process(pipe: Pipeline, pid: str) -> None:
    try:
        pipe.process(pid)
    except Exception:  # noqa: BLE001 — já registrado no banco/log
        pass


def cmd_watch(pipe: Pipeline, block: bool = True):
    from .telegram_bot import make_worker
    from .watcher import InboxWatcher

    worker = make_worker()
    handle = _process_async(pipe, worker)
    w = InboxWatcher(pipe.s.inbox, lambda p: handle(ingest(p, pipe.db, pipe.s.processing, origem="inbox")),
                     polling=pipe.s.watcher_polling)
    if block:
        w.run()
    else:
        threading.Thread(target=w.run, daemon=True, name="watcher").start()
    return w


def cmd_bot(pipe: Pipeline, block: bool = True):
    from .telegram_bot import TelegramBot, make_worker

    worker = make_worker()

    def regen(pid: str, instr: str, _chat: int) -> None:
        worker.submit(lambda: pipe.regenerate(pid, instr))

    bot = TelegramBot(pipe.s, pipe.db, _process_async(pipe, worker), on_regen=regen)
    if block:
        bot.run()
    else:
        threading.Thread(target=bot.run, daemon=True, name="telegram").start()
    return bot


def cmd_review(pipe: Pipeline) -> None:
    import uvicorn

    from .review_queue.review_app import create_app

    print(f"Painel: http://{pipe.s.review_host}:{pipe.s.review_port}  (usuário: {pipe.s.review_user})")
    uvicorn.run(create_app(pipe), host=pipe.s.review_host, port=pipe.s.review_port, log_level="warning")


def cmd_analyze(pipe: Pipeline, path: Path, keep: bool) -> int:
    if not path.exists():
        print(f"Arquivo não encontrado: {path}", file=sys.stderr)
        return 1
    src = path
    if keep:  # trabalha numa cópia para não mover o original
        tmp = pipe.s.base_dir / "data" / "analyze_tmp" / path.name
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if tmp.exists():
            shutil.rmtree(tmp) if tmp.is_dir() else tmp.unlink()
        (shutil.copytree if path.is_dir() else shutil.copy2)(path, tmp)
        for extra in (path.with_suffix(".txt"),):
            if path.is_file() and extra.exists():
                shutil.copy2(extra, tmp.with_suffix(".txt"))
        src = tmp
    ids = ingest(src, pipe.db, pipe.s.processing, origem="cli")
    if not ids:
        print("Nada a processar (extensão não suportada?).", file=sys.stderr)
        return 1
    for pid in ids:
        posts = pipe.process(pid, notify=False)
        print(dump(posts))
        print(f"\n→ JSONs em output/{pid}/  ·  revise em http://{pipe.s.review_host}:{pipe.s.review_port}/post/{pid}",
              file=sys.stderr)
    return 0


def cmd_status(pipe: Pipeline, todos: bool) -> int:
    posts = pipe.db.list(None if todos else ["novo", "analisado", "gerado", "aprovado", "agendado", "erro"])
    if not posts:
        print("Fila vazia.")
    for p in posts:
        redes = ", ".join(f"{r.rede}:{r.status}" for r in pipe.db.redes(p.id))
        print(f"{p.id}  {p.tipo:<8} {p.status:<10} conf={p.confianca if p.confianca is not None else '—':<4} {redes}")
    return 0


def cmd_run(pipe: Pipeline) -> None:
    cmd_watch(pipe, block=False)
    if pipe.s.telegram_bot_token:
        cmd_bot(pipe, block=False)
    else:
        log.warning("TELEGRAM_BOT_TOKEN vazio: bot do Telegram desativado")
    cmd_review(pipe)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="autopost", description="AutoPost — publicador de conteúdo")
    ap.add_argument("--dry-run", action="store_true", help="força modo simulação (não publica nada)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("watch")
    sub.add_parser("bot")
    sub.add_parser("review")
    a = sub.add_parser("analyze")
    a.add_argument("arquivo", type=Path)
    a.add_argument("--mover", action="store_true", help="move o arquivo original (padrão: trabalha numa cópia)")
    st = sub.add_parser("status")
    st.add_argument("--todos", action="store_true")
    pb = sub.add_parser("publish")
    pb.add_argument("id")
    args = ap.parse_args(argv)

    settings = load_settings()
    if args.dry_run:
        settings.dry_run = True
    pipe = build(settings)

    if args.cmd == "run":
        cmd_run(pipe)
    elif args.cmd == "watch":
        cmd_watch(pipe)
    elif args.cmd == "bot":
        cmd_bot(pipe)
    elif args.cmd == "review":
        cmd_review(pipe)
    elif args.cmd == "analyze":
        return cmd_analyze(pipe, args.arquivo, keep=not args.mover)
    elif args.cmd == "status":
        return cmd_status(pipe, args.todos)
    elif args.cmd == "publish":
        print("Publicação real entra na Fase 3. Nesta fase o sistema só gera e coloca na fila de aprovação.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
