"""Marcações (@): SOMENTE a partir de config/mentions.yaml.

- Perfil cadastrado + evidência (palavra-chave citada / logo detectado / briefing) → marcação.
- Qualquer @ ou marca fora da lista → apenas SUGESTÃO (nunca marca automaticamente).
- Sem reconhecimento facial (LGPD). Presença de pessoa só conta se houver consentimento
  registrado E o nome estiver no briefing.
"""
from __future__ import annotations

import re

from ..analyzer.content import norm
from ..config import AppConfig, Perfil
from ..schemas import ContentAnalysis, Marcacao

HANDLE_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{2,30})")


def _contains(term: str, text: str) -> bool:
    return bool(term) and re.search(rf"(?<!\w){re.escape(norm(term))}(?!\w)", text) is not None


def _evidence(p: Perfil, a: ContentAnalysis) -> tuple[str, str] | None:
    briefing = norm(a.briefing)
    fala = norm(a.audio.transcricao if a.audio else "")
    ocr = norm(" ".join(a.visao.textos_visiveis))
    logos = norm(" | ".join(a.visao.logos_marcas))
    handles = [h for h in (p.handles.instagram, p.handles.facebook) if h]

    for h in handles:
        if norm(h) in briefing:
            return "briefing", f"{h} citado no briefing"
    for kw in [p.nome, *p.palavras_chave]:
        if _contains(kw, briefing):
            origem = "imagem_com_consentimento" if p.consentimento_imagem else "briefing"
            return origem, f"'{kw}' citado no briefing"
        if _contains(kw, fala):
            return "palavra_chave", f"'{kw}' citado na fala"
        if _contains(kw, ocr):
            return "palavra_chave", f"'{kw}' aparece em texto na imagem"
    for logo in p.logos:
        if _contains(logo, logos):
            return "logo", f"logo '{logo}' detectado"
    return None


def resolve_mentions(rede: str, a: ContentAnalysis, cfg: AppConfig) -> tuple[list[Marcacao], list[Marcacao], list[str]]:
    """Retorna (marcacoes, sugeridas, colaboradores_instagram)."""
    marcacoes: list[Marcacao] = []
    sugeridas: list[Marcacao] = []
    conhecidos: set[str] = set()

    for p in cfg.mentions.perfis:
        for h in (p.handles.instagram, p.handles.facebook, p.handles.tiktok, p.handles.youtube):
            if h:
                conhecidos.add(h.lower().lstrip("@"))
        handle = p.handles.for_rede(rede)
        if p.tipo == "proprio" or not handle:
            continue
        ev = _evidence(p, a)
        if not ev:
            continue
        m = Marcacao(perfil_id=p.id, nome=p.nome, handle=handle, origem=ev[0], evidencia=ev[1],  # type: ignore[arg-type]
                     colaborador=bool(p.colaborador_instagram and rede == "instagram"))
        (marcacoes if p.auto_marcar else sugeridas).append(m)

    # @ citados no briefing que NÃO estão na lista → sugestão
    for h in HANDLE_RE.findall(a.briefing):
        if h.lower() not in conhecidos:
            sugeridas.append(Marcacao(nome=h, handle=f"@{h}", origem="briefing",
                                      evidencia="@ citado no briefing, mas não está em mentions.yaml"))
            conhecidos.add(h.lower())
    # marcas/logos detectados pela IA sem cadastro → sugestão sem handle
    cadastrados = {norm(l) for p in cfg.mentions.perfis for l in p.logos + [p.nome]}
    for logo in a.visao.logos_marcas:
        if norm(logo) not in cadastrados:
            sugeridas.append(Marcacao(nome=logo, handle="", origem="sugestao_ia",
                                      evidencia="marca detectada na imagem; cadastre em mentions.yaml para marcar"))

    pc = cfg.platforms.redes.get(rede)
    if pc and pc.mencoes_max:
        marcacoes = marcacoes[: pc.mencoes_max]
    colab_max = (pc.colaboradores_max if pc else None) or 0
    colaboradores = [m.handle.lstrip("@") for m in marcacoes if m.colaborador][:colab_max]
    return marcacoes, sugeridas, colaboradores
