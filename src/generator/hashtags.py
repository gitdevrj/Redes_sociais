"""Mix de hashtags por rede: marca + nicho (tema) + amplas/sugeridas, respeitando limites."""
from __future__ import annotations

import re
import unicodedata

from ..config import AppConfig

AMPLAS = ["#empreendedorismo", "#gestao", "#negocios", "#empresarios", "#pme"]


def normalize(tag: str) -> str:
    tag = tag.strip().lstrip("#＃")
    tag = unicodedata.normalize("NFKD", tag)
    tag = "".join(c for c in tag if not unicodedata.combining(c))
    tag = re.sub(r"[^0-9A-Za-z_]", "", tag).lower()
    return f"#{tag}" if tag and not tag.isdigit() else ""


def build_hashtags(rede: str, cfg: AppConfig, tema_chave: str | None, relacionados: list[str],
                   sugeridas: list[str]) -> list[str]:
    pc = cfg.platforms.redes.get(rede)
    maximo = pc.hashtags_max if pc else 5
    minimo = pc.hashtags_min if pc else 0
    if maximo <= 0:
        return []
    proibidas = {normalize(p.replace(" ", "")) for p in cfg.brand.palavras_proibidas}
    temas = cfg.brand.temas

    nicho = list(temas[tema_chave].hashtags) if tema_chave and tema_chave in temas else []
    rel = [h for k in relacionados if k in temas for h in temas[k].hashtags[:1]]
    marca = cfg.brand.hashtags_marca

    # Prioridade: 1 da marca, 2 de nicho, sugestões da IA (específicas), relacionadas.
    # Completa com nicho restante/amplas só até um alvo moderado (mais hashtags ≠ mais alcance).
    alvo = min(maximo, max(minimo, 6))
    out: list[str] = []

    def add(raws: list[str], limite: int) -> None:
        for raw in raws:
            if len(out) >= limite:
                return
            tag = normalize(raw)
            if tag and tag not in out and tag not in proibidas:
                out.append(tag)

    add(marca[:1] + nicho[:2] + sugeridas + rel, maximo)
    add(nicho[2:] + AMPLAS, alvo)
    # Facebook: hashtags pesam pouco — usar só marca + nicho principal.
    if rede == "facebook":
        out = [t for t in out if t in {normalize(h) for h in marca + nicho}][:maximo] or out[:maximo]
    return out
