"""Painel web de revisão/aprovação (FastAPI + Jinja2). Roda só em localhost por padrão."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from ..logging_setup import get_logger
from ..pipeline import Pipeline
from . import actions
from .db import Status

log = get_logger("review_app")
TEMPLATES = Path(__file__).parent / "templates"
STATUS_PENDENTES = [Status.GERADO.value, Status.ANALISADO.value, Status.NOVO.value, Status.ERRO.value]


def create_app(pipeline: Pipeline) -> FastAPI:
    s = pipeline.s
    if not s.review_password.get_secret_value():
        raise RuntimeError("Defina REVIEW_PASSWORD no .env antes de abrir o painel.")
    if s.review_password.get_secret_value() == "troque-esta-senha":
        log.warning("REVIEW_PASSWORD ainda está com o valor de exemplo — troque no .env")

    app = FastAPI(title="AutoPost — Revisão", docs_url=None, redoc_url=None, openapi_url=None)
    tpl = Jinja2Templates(directory=str(TEMPLATES))
    security = HTTPBasic(realm="AutoPost")
    csrf_key = secrets.token_bytes(32)
    tz = ZoneInfo(pipeline.cfg.schedule.fuso_horario)

    def auth(cred: HTTPBasicCredentials = Depends(security)) -> str:
        ok_user = hmac.compare_digest(cred.username.encode(), s.review_user.encode())
        ok_pass = hmac.compare_digest(cred.password.encode(), s.review_password.get_secret_value().encode())
        if not (ok_user and ok_pass):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas",
                                headers={"WWW-Authenticate": 'Basic realm="AutoPost"'})
        return cred.username

    def csrf_token(post_id: str) -> str:
        return hmac.new(csrf_key, post_id.encode(), hashlib.sha256).hexdigest()

    def check_csrf(post_id: str, token: str) -> None:
        if not hmac.compare_digest(csrf_token(post_id), token or ""):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Token CSRF inválido; recarregue a página.")

    def get_post_or_404(post_id: str):
        post = pipeline.db.get(post_id)
        if post is None:
            raise HTTPException(404, "Post não encontrado")
        return post

    def local_dt(dt: datetime | None) -> str:
        if not dt:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(tz).strftime("%Y-%m-%dT%H:%M")

    tpl.env.filters["local_dt"] = local_dt

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, filtro: str = "pendentes", _: str = Depends(auth)):
        posts = pipeline.db.list(None if filtro == "todos" else STATUS_PENDENTES)
        return tpl.TemplateResponse(request, "index.html", {"posts": posts, "filtro": filtro, "dry_run": s.dry_run})

    @app.get("/post/{post_id}", response_class=HTMLResponse)
    def detail(request: Request, post_id: str, msg: str = "", _: str = Depends(auth)):
        post = get_post_or_404(post_id)
        redes = pipeline.load_platform_posts(post_id)
        estado = {r.rede: r for r in pipeline.db.redes(post_id)}
        analysis = None
        try:
            analysis = pipeline.load_analysis(post_id)
        except FileNotFoundError:
            pass
        return tpl.TemplateResponse(request, "post.html", {
            "post": post, "redes": redes, "estado": estado, "analysis": analysis, "msg": msg,
            "csrf": csrf_token(post_id), "dry_run": s.dry_run, "eventos": pipeline.db.events(post_id)[-15:],
        })

    @app.get("/media/{post_id}/{path:path}")
    def media(post_id: str, path: str, _: str = Depends(auth)):
        base = (s.processing / post_id).resolve()
        target = (base / path).resolve()
        if base not in target.parents or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target)

    def _apply_edits(post_id: str, form: dict) -> None:
        for pp in pipeline.load_platform_posts(post_id):
            r = pp.rede
            for i, leg in enumerate(pp.legendas):
                novo = form.get(f"{r}_legenda_{i}")
                if novo is not None:
                    leg.texto = novo.replace("\r\n", "\n").strip()
            esc = form.get(f"{r}_escolhida")
            if esc is not None and esc.isdigit() and int(esc) < len(pp.legendas):
                pp.legenda_escolhida = int(esc)
            if f"{r}_hashtags" in form:
                from ..generator.hashtags import normalize

                pp.hashtags = [t for t in (normalize(x) for x in form[f"{r}_hashtags"].split()) if t]
            if f"{r}_titulo" in form:
                pp.titulo = form[f"{r}_titulo"].strip()
            if f"{r}_primeiro_comentario" in form:
                pp.primeiro_comentario = form[f"{r}_primeiro_comentario"].strip()
            manter = {k.split("__", 1)[1] for k in form if k.startswith(f"{r}_mencao__")}
            if f"{r}_mencoes_form" in form:
                pp.marcacoes = [m for m in pp.marcacoes if m.handle in manter]
            horario = form.get(f"{r}_horario")
            if horario:
                pp.horario_sugerido = datetime.fromisoformat(horario).replace(tzinfo=tz)
                pipeline.db.upsert_rede(post_id, r, horario=pp.horario_sugerido)
            if f"{r}_ativo_form" in form:
                atual = next((x for x in pipeline.db.redes(post_id) if x.rede == r), None)
                if not form.get(f"{r}_ativo"):
                    pipeline.db.upsert_rede(post_id, r, status=Status.DESCARTADO)
                elif atual and atual.status == Status.DESCARTADO.value:
                    pipeline.db.upsert_rede(post_id, r, status=Status.GERADO)
            pipeline.save_platform_post(pp)
        pipeline.db.update(post_id, evento="editado")

    async def _form(request: Request) -> dict:
        data = await request.form()
        return {k: str(v) for k, v in data.items()}

    @app.post("/post/{post_id}/acao")
    async def acao(request: Request, post_id: str, background: BackgroundTasks, _: str = Depends(auth)):
        form = await _form(request)
        check_csrf(post_id, form.get("csrf", ""))
        get_post_or_404(post_id)
        op = form.get("op", "salvar")
        if op == "descartar":
            actions.discard(pipeline.db, post_id)
            return RedirectResponse("/?filtro=pendentes", status.HTTP_303_SEE_OTHER)
        if op == "regenerar":
            instrucao = form.get("instrucao", "").strip() or "gere novas variações"
            background.add_task(pipeline.regenerate, post_id, instrucao, False)
            return _back(post_id, "Regenerando em segundo plano… recarregue em alguns segundos.")
        _apply_edits(post_id, form)
        if op == "salvar":
            return _back(post_id, "Edições salvas.")
        redes = [r.rede for r in pipeline.db.redes(post_id) if r.status != Status.DESCARTADO.value]
        if op in {"aprovar", "publicar_agora"}:
            try:
                horarios = {r: datetime.now(tz) for r in redes} if op == "publicar_agora" else None
                feitas = actions.approve(pipeline.db, post_id, horarios=horarios, redes=redes)
            except ValueError as exc:
                return _back(post_id, f"Não foi possível aprovar: {exc}")
            aviso = (" Modo DRY-RUN ativo: nada será publicado." if s.dry_run
                     else " A publicação automática entra na Fase 3.")
            return _back(post_id, f"Aprovado para: {', '.join(feitas)}.{aviso}")
        if op == "reagendar":
            return _back(post_id, "Horários atualizados.")
        raise HTTPException(400, "Ação desconhecida")

    def _back(post_id: str, msg: str) -> RedirectResponse:
        from urllib.parse import quote

        return RedirectResponse(f"/post/{post_id}?msg={quote(msg)}", status.HTTP_303_SEE_OTHER)

    return app
