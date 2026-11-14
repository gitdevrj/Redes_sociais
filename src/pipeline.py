"""Orquestra: análise → geração por rede → fila de aprovação → notificação."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .ai import AIError, ClaudeLLM, StructuredLLM
from .analyzer.content import analyze_post, norm
from .config import AppConfig, load_config
from .generator import captions
from .generator.hashtags import build_hashtags
from .generator.mentions import resolve_mentions
from .logging_setup import get_logger
from .notifier import Notifier, review_keyboard
from .review_queue.db import Database, Status
from .scheduler import suggest_times
from .schemas import Confianca, ContentAnalysis, GeracaoIA, Localizacao, PlatformPost
from .settings import Settings

log = get_logger("pipeline")


def formato_para(rede: str, a: ContentAnalysis) -> str | None:
    """Formato de publicação por rede, ou None se a rede não suporta esse tipo de mídia."""
    if a.tipo == "video":
        v = a.video
        if rede == "youtube":
            return "shorts" if v and v.orientacao != "horizontal" and v.duracao_s <= 180 else "video"
        return {"instagram": "reels", "facebook": "reels", "linkedin": "video", "tiktok": "video"}.get(rede)
    if a.tipo == "carousel":
        return {"instagram": "carrossel", "facebook": "album", "linkedin": "multi_imagem", "tiktok": "fotos"}.get(rede)
    return {"instagram": "feed", "facebook": "foto", "linkedin": "imagem", "tiktok": "fotos"}.get(rede)


class Pipeline:
    def __init__(self, settings: Settings, db: Database, cfg: AppConfig | None = None,
                 llm: StructuredLLM | None = None, notifier: Notifier | None = None):
        self.s = settings
        self.db = db
        self.cfg = cfg or load_config(settings.config_dir)
        if llm is None and settings.use_claude:
            key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
            llm = ClaudeLLM(key, settings.claude_model, settings.claude_effort)
        self.llm = llm
        self.notifier = notifier or Notifier(settings)

    # ------------------------------------------------------------ caminhos
    def post_dir(self, post_id: str) -> Path:
        return self.s.processing / post_id

    def out_dir(self, post_id: str) -> Path:
        d = self.s.output / post_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------ etapas
    def process(self, post_id: str, notify: bool = True) -> list[PlatformPost]:
        post = self.db.get(post_id)
        if post is None:
            raise KeyError(post_id)
        try:
            analysis = analyze_post(
                post_id=post.id, tipo=post.tipo, arquivos=post.arquivos, post_dir=self.post_dir(post.id),
                briefing=post.briefing, cfg=self.cfg, llm=self.llm, whisper_enabled=self.s.whisper_enabled,
                whisper_model=self.s.whisper_model, whisper_device=self.s.whisper_device,
                whisper_compute_type=self.s.whisper_compute_type,
            )
            (self.out_dir(post_id) / "analysis.json").write_text(
                analysis.model_dump_json(indent=2), encoding="utf-8")
            self.db.update(post_id, evento="analisado", status=Status.ANALISADO)
            posts = self.generate(analysis, is_sponsored=post.is_sponsored)
        except Exception as exc:
            log.exception("falha no processamento", extra={"data": {"post_id": post_id}})
            self.db.update(post_id, evento="erro", detalhe=str(exc)[:500], status=Status.ERRO, erro=str(exc)[:500])
            if notify:
                self.notifier.send(f"❌ Falha ao processar <code>{post_id}</code>: {html.escape(str(exc)[:300])}",
                                   chat_id=post.telegram_chat_id)
            raise
        if notify:
            self.notify_ready(post_id, posts)
        return posts

    def load_analysis(self, post_id: str) -> ContentAnalysis:
        return ContentAnalysis.model_validate_json((self.out_dir(post_id) / "analysis.json").read_text(encoding="utf-8"))

    def regenerate(self, post_id: str, instrucao: str, notify: bool = True) -> list[PlatformPost]:
        post = self.db.get(post_id)
        if post is None:
            raise KeyError(post_id)
        self.db.update(post_id, evento="regenerar", detalhe=instrucao[:300], instrucao_regeneracao=instrucao)
        posts = self.generate(self.load_analysis(post_id), is_sponsored=post.is_sponsored, instrucao=instrucao)
        if notify:
            self.notify_ready(post_id, posts)
        return posts

    def generate(self, a: ContentAnalysis, is_sponsored: bool = False, instrucao: str = "") -> list[PlatformPost]:
        redes = [r for r in self.cfg.platforms.ativas() if formato_para(r, a)]
        n_alt = len(a.arquivos) if a.tipo != "video" else 1
        modo = a.modo_ia
        bundle: GeracaoIA
        if self.llm is not None:
            try:
                bundle = captions.generate_with_claude(self.llm, a, self.cfg, redes, instrucao, n_alt)
                modo = "claude"
            except AIError as exc:
                log.warning("geração via Claude falhou; usando modelos offline",
                            extra={"data": {"post_id": a.post_id, "erro": str(exc)}})
                bundle, modo = captions.generate_offline(a, self.cfg, redes, instrucao, n_alt), "offline"
        else:
            bundle, modo = captions.generate_offline(a, self.cfg, redes, instrucao, n_alt), "offline"

        por_rede = {c.rede: c for c in bundle.redes}
        tema = self.cfg.brand.temas.get(a.tema_chave or "")
        disclaimer = (tema.disclaimer or "") if tema else ""
        aviso = self.cfg.brand.publicidade.aviso_padrao if is_sponsored else ""
        horarios = suggest_times(redes, self.cfg.schedule, ocupados=self._ocupados())
        local = self._local(a)
        nota_base = min(max(bundle.nota_confianca, 0), 100)
        out_dir = self.out_dir(a.post_id)
        result: list[PlatformPost] = []

        for rede in redes:
            copy = por_rede.get(rede)
            if copy is None:
                log.warning("IA não retornou texto para a rede", extra={"data": {"rede": rede}})
                copy = captions.generate_offline(a, self.cfg, [rede], instrucao, n_alt).redes[0]
            hashtags = build_hashtags(rede, self.cfg, a.tema_chave, a.temas_relacionados, copy.hashtags_sugeridas)
            reserva = sum(len(h) + 1 for h in hashtags) + 2
            alertas: list[str] = []
            legendas = []
            for leg in copy.legendas[:3]:
                texto, al = captions.finalize_caption(leg.texto, rede, self.cfg, disclaimer=disclaimer,
                                                      aviso_publi=aviso, reserva_hashtags=reserva)
                alertas += [f"[{leg.estilo}] {x}" for x in al]
                legendas.append(leg.model_copy(update={"texto": texto}))
            if len(legendas) < 3:
                alertas.append("IA retornou menos de 3 variações de legenda")
            marcacoes, sugeridas, colaboradores = resolve_mentions(rede, a, self.cfg)
            titulo = copy.titulo.strip()
            if rede == "youtube":
                lim = self.cfg.platforms.redes["youtube"].titulo_max_caracteres or 100
                titulo = captions.truncate(titulo or a.visao.tema_principal, lim)
            nota, justificativa = self._confianca(nota_base, bundle.justificativa_confianca, modo, a, alertas)
            revisao = self._revisao_obrigatoria(nota, modo, a, alertas)
            pp = PlatformPost(
                post_id=a.post_id, rede=rede, formato=formato_para(rede, a) or "", modo_ia=modo,  # type: ignore[arg-type]
                titulo=titulo, legendas=legendas, hashtags=hashtags, marcacoes=marcacoes,
                marcacoes_sugeridas=sugeridas, colaboradores=colaboradores if rede == "instagram" else [],
                localizacao=local if rede in {"instagram", "facebook"} else None,
                texto_alternativo=bundle.texto_alternativo[:n_alt] if rede in {"instagram", "facebook", "linkedin"} else [],
                primeiro_comentario=copy.primeiro_comentario.strip() if rede in {"instagram", "facebook", "linkedin", "youtube"} else "",
                horario_sugerido=horarios.get(rede), is_sponsored=is_sponsored, aviso_publicidade=aviso,
                disclaimer=disclaimer, musica=None, midia=self._midia(a),
                confianca=Confianca(nota=nota, justificativa=justificativa), riscos=a.riscos,
                revisao_obrigatoria=revisao, alertas=alertas, gerado_em=datetime.now(timezone.utc),
            )
            (out_dir / f"{rede}.json").write_text(pp.model_dump_json(indent=2), encoding="utf-8")
            self.db.upsert_rede(a.post_id, rede, status=Status.GERADO, horario=pp.horario_sugerido, erro="")
            result.append(pp)

        nota_post = min((p.confianca.nota for p in result), default=0)
        self.db.update(a.post_id, evento="gerado", detalhe=f"{len(result)} redes; modo={modo}",
                       status=Status.GERADO, confianca=nota_post,
                       revisao_obrigatoria=any(p.revisao_obrigatoria for p in result))
        return result

    # ------------------------------------------------------------ regras
    def _confianca(self, nota: int, justificativa: str, modo: str, a: ContentAnalysis,
                   alertas: list[str]) -> tuple[int, str]:
        motivos = [justificativa.strip().rstrip(".;")] if justificativa.strip() else []
        if modo == "offline":
            nota = min(nota, 40)
            motivos.append("modo offline (sem IA): nota limitada a 40")
        if a.riscos:
            nota = max(0, nota - 20 * len(a.riscos))
            motivos.append(f"{len(a.riscos)} risco(s) detectado(s)")
        if any("proibidas" in x for x in alertas):
            nota = max(0, nota - 30)
            motivos.append("expressão proibida na legenda")
        if a.tipo == "video" and a.audio and not a.audio.transcrito and a.audio.proporcao_fala > 0.3:
            nota = max(0, nota - 10)
            motivos.append("vídeo com áudio, mas sem transcrição")
        return nota, "; ".join(motivos)

    def _revisao_obrigatoria(self, nota: int, modo: str, a: ContentAnalysis, alertas: list[str]) -> bool:
        m = self.cfg.schedule.modo
        if not m.auto_publish or modo == "offline" or a.riscos:
            return True
        if any("proibidas" in x for x in alertas):
            return True
        return nota < m.confianca_minima_auto

    def _local(self, a: ContentAnalysis) -> Localizacao | None:
        texto = norm(" ".join([a.briefing, a.visao.local_provavel, a.visao.descricao]))
        for loc in self.cfg.platforms.locais:
            if any(norm(k) in texto for k in loc.palavras_chave):
                return Localizacao(nome=loc.nome, location_id=loc.instagram_location_id)
        return None

    def _midia(self, a: ContentAnalysis) -> list[str]:
        base = self.post_dir(a.post_id)
        return [str((base / f).relative_to(self.s.base_dir).as_posix()) for f in a.arquivos]

    def _ocupados(self) -> dict[str, list[datetime]]:
        occ: dict[str, list[datetime]] = {}
        for pr in self.db.agendados():
            if pr.horario:
                h = pr.horario if pr.horario.tzinfo else pr.horario.replace(tzinfo=timezone.utc)
                occ.setdefault(pr.rede, []).append(h)
        return occ

    # ------------------------------------------------------------ leitura
    def load_platform_posts(self, post_id: str) -> list[PlatformPost]:
        d = self.s.output / post_id
        out = []
        for rede in self.cfg.platforms.redes:
            f = d / f"{rede}.json"
            if f.exists():
                out.append(PlatformPost.model_validate_json(f.read_text(encoding="utf-8")))
        return out

    def save_platform_post(self, pp: PlatformPost) -> None:
        (self.out_dir(pp.post_id) / f"{pp.rede}.json").write_text(pp.model_dump_json(indent=2), encoding="utf-8")

    # ------------------------------------------------------------ notificação
    def notify_ready(self, post_id: str, posts: list[PlatformPost]) -> None:
        post = self.db.get(post_id)
        if not posts or post is None:
            return
        ig = next((p for p in posts if p.rede == "instagram"), posts[0])
        linhas = [f"📝 <b>Post pronto para revisão</b> <code>{post_id}</code>",
                  f"Tipo: {post.tipo} · Confiança: {post.confianca}/100 · IA: {ig.modo_ia}"]
        if ig.riscos:
            linhas.append("⚠️ Riscos: " + html.escape("; ".join(ig.riscos)))
        linhas.append("")
        linhas.append(html.escape(ig.legendas[0].texto[:600]))
        linhas.append("")
        for p in posts:
            h = p.horario_sugerido.strftime("%d/%m %H:%M") if p.horario_sugerido else "—"
            linhas.append(f"• {p.rede}: {p.formato}, sugerido {h}")
        linhas.append(f"\nPainel: http://{self.s.review_host}:{self.s.review_port}/post/{post_id}")
        linhas.append(f"Para regenerar com instrução: <code>/regen {post_id} mais curto</code>")
        preview = self._preview_bytes(post_id)
        self.notifier.send("\n".join(linhas), chat_id=post.telegram_chat_id, keyboard=review_keyboard(post_id),
                           photo=preview)

    def _preview_bytes(self, post_id: str) -> bytes | None:
        try:
            a = self.load_analysis(post_id)
            rel = a.video.frames[len(a.video.frames) // 2] if (a.video and a.video.frames) else a.arquivos[0]
            from PIL import Image
            import io

            with Image.open(self.post_dir(post_id) / rel) as im:
                im = im.convert("RGB")
                im.thumbnail((1280, 1280))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=80)
                return buf.getvalue()
        except Exception:  # noqa: BLE001
            return None


def dump(posts: list[PlatformPost]) -> str:
    return json.dumps([json.loads(p.model_dump_json()) for p in posts], ensure_ascii=False, indent=2)
