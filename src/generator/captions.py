"""Legendas por rede: 3 variações (informativa, storytelling, provocativa) + regras da marca."""
from __future__ import annotations

import json
import re

from ..ai import StructuredLLM
from ..analyzer.content import norm
from ..config import AppConfig
from ..schemas import ContentAnalysis, CopyPorRede, GeracaoIA, LegendaVariacao

ESTILOS = ("informativa", "storytelling", "provocativa")

GUIA_REDES = {
    "instagram": "Gancho forte na 1ª linha (aparece antes do 'mais'). Parágrafos curtos com quebras de linha. "
                 "Até 3 emojis. CTA no final. Sem hashtags no texto (são adicionadas depois). 600–1500 caracteres.",
    "facebook": "Tom conversacional, como se falasse com um empresário conhecido. Pergunta para gerar comentários. "
                "Até 3 emojis. 300–900 caracteres. Sem hashtags no texto.",
    "linkedin": "Tom profissional e analítico. Abra com um insight ou dado. Parágrafos curtos, 1 ideia por linha. "
                "No máximo 1 emoji. Termine com uma pergunta para a rede. 700–1800 caracteres. Sem hashtags no texto. "
                "Evite os caracteres ( ) [ ] { } < > | ~ _ * \\ — o LinkedIn os trata como formatação.",
    "tiktok": "Curta e direta, 1–3 frases, linguagem falada. Até 3 emojis. Sem hashtags no texto.",
    "youtube": "`titulo`: até 70 caracteres, com a palavra-chave principal no início, sem clickbait enganoso. "
               "Legenda = descrição: 2–4 parágrafos curtos explicando o que a pessoa vai aprender + CTA para se inscrever. "
               "Sem hashtags no texto.",
}

CTA_HINTS = ("siga", "salve", "compartilhe", "comente", "inscreva", "fale com", "link na bio", "me conta", "conta aqui",
             "o que você acha", "?")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")


def build_system_prompt(cfg: AppConfig) -> str:
    b = cfg.brand
    temas = "\n".join(
        f"- {t.rotulo}" + (f" (diretriz: {t.diretriz.strip()})" if t.diretriz else "")
        + (f" (incluir aviso: \"{t.disclaimer}\")" if t.disclaimer else "")
        for t in b.temas.values()
    )
    return f"""Você é o redator de redes sociais de {b.nome} ({b.handle_principal}).
Segmento: {b.segmento}
Público-alvo: {b.publico_alvo}
Promessa da marca (pilares): {", ".join(b.pilares)}. Toda legenda deve entregar pelo menos um pilar de forma concreta.
Tom de voz: {b.tom_de_voz.descricao}
Faça: {"; ".join(b.tom_de_voz.faca)}
Evite: {"; ".join(b.tom_de_voz.evite)}
Palavras/expressões PROIBIDAS (nunca use, nem parecidas): {"; ".join(b.palavras_proibidas)}
CTA padrão: "{b.cta_padrao}". Alternativos: {"; ".join(b.cta_alternativos)}
Temas da marca:
{temas}

Regras gerais:
- Português do Brasil, correto e natural. Nada de promessas de ganho ou resultado garantido.
- Nunca invente @ de perfis, nomes de clientes, números ou dados que não estejam no material.
  Se houver números no material (dashboards, falas), use-os com fidelidade.
- Para cada rede pedida, escreva EXATAMENTE 3 legendas com os estilos: informativa, storytelling, provocativa.
- `hashtags_sugeridas`: 3 a 6 hashtags específicas do assunto (sem acento, minúsculas).
- `primeiro_comentario`: opcional (pergunta para engajar ou complemento útil); pode ser vazio.
- `titulo`: obrigatório só no YouTube; vazio nas demais.
- `texto_alternativo`: um texto descritivo e objetivo (acessibilidade) por imagem recebida, na ordem.
- `nota_confianca` (0–100): o quanto o material é claro e as legendas estão prontas para publicar sem edição.
  Diminua a nota se o material for ambíguo, se faltar contexto ou se houver qualquer risco.

Guia por rede:
""" + "\n".join(f"- {r}: {g}" for r, g in GUIA_REDES.items())


def build_user_prompt(a: ContentAnalysis, redes: list[str], instrucao: str = "", n_alt: int = 1) -> str:
    resumo = {
        "tipo": a.tipo,
        "briefing_do_autor": a.briefing,
        "descricao": a.visao.descricao,
        "tema_principal": a.visao.tema_principal,
        "subtemas": a.visao.subtemas,
        "tom_emocional": a.visao.tom_emocional,
        "textos_visiveis": a.visao.textos_visiveis,
        "gancho_sugerido": a.visao.gancho_sugerido,
        "local": a.visao.local_provavel,
        "pilares_detectados": a.pilares,
        "transcricao": (a.audio.transcricao[:6000] if a.audio else ""),
        "duracao_s": a.video.duracao_s if a.video else None,
        "riscos": a.riscos,
    }
    txt = (f"Redes: {', '.join(redes)}\nNúmero de textos alternativos necessários: {n_alt}\n\n"
           f"MATERIAL ANALISADO (JSON):\n{json.dumps(resumo, ensure_ascii=False, indent=2)}")
    if instrucao:
        txt += f"\n\nINSTRUÇÃO DO AUTOR PARA ESTA VERSÃO (priorize): {instrucao}"
    return txt


def generate_with_claude(llm: StructuredLLM, a: ContentAnalysis, cfg: AppConfig, redes: list[str],
                         instrucao: str = "", n_alt: int = 1) -> GeracaoIA:
    content = [{"type": "text", "text": build_user_prompt(a, redes, instrucao, n_alt)}]
    return llm.generate(system=build_system_prompt(cfg), content=content, schema=GeracaoIA, max_tokens=16000)


def generate_offline(a: ContentAnalysis, cfg: AppConfig, redes: list[str], instrucao: str = "",
                     n_alt: int = 1) -> GeracaoIA:
    """Modelos de texto simples para quando não há IA. Servem de rascunho — sempre exigem revisão."""
    b = cfg.brand
    tema = cfg.brand.temas[a.tema_chave].rotulo if a.tema_chave in cfg.brand.temas else a.visao.tema_principal
    gancho = a.visao.gancho_sugerido.strip().rstrip(".") or f"O que {tema.lower()} tem a ver com o lucro da sua empresa?"
    contexto = (a.briefing or (a.audio.transcricao if a.audio else "") or a.visao.descricao).strip()
    contexto = re.sub(r"\s+", " ", contexto)[:600]
    pilar = (a.pilares or b.pilares[:1] or ["Clareza"])[0]
    out: list[CopyPorRede] = []
    for rede in redes:
        info = (f"{gancho}.\n\n{contexto}\n\nO ponto central: {pilar.lower()} nas decisões vem de olhar os números "
                f"com método, não com achismo.\n\n{b.cta_padrao}")
        story = (f"Toda semana eu converso com empresários que sentem que trabalham muito e veem pouco resultado.\n\n"
                 f"{contexto}\n\nQuando a gestão ganha {pilar.lower()}, as decisões ficam mais simples.\n\n{b.cta_padrao}")
        provoc = (f"Pergunta sincera: você sabe exatamente para onde vai o dinheiro da sua empresa?\n\n{contexto}\n\n"
                  f"Se a resposta não veio na hora, este conteúdo é para você. Me conta nos comentários.")
        if rede == "tiktok":
            info, story, provoc = f"{gancho}.", f"{pilar} nos números muda o jogo.", "Você sabe sua margem real?"
        out.append(CopyPorRede(
            rede=rede,  # type: ignore[arg-type]
            titulo=(f"{tema}: {gancho}"[:95] if rede == "youtube" else ""),
            legendas=[LegendaVariacao(estilo="informativa", texto=info),
                      LegendaVariacao(estilo="storytelling", texto=story),
                      LegendaVariacao(estilo="provocativa", texto=provoc)],
            hashtags_sugeridas=[],
            primeiro_comentario="Qual indicador você acompanha toda semana? 👇" if rede in {"instagram", "facebook"} else "",
        ))
    return GeracaoIA(
        redes=out,
        texto_alternativo=[f"Imagem sobre {tema.lower()}." for _ in range(max(n_alt, 1))],
        nota_confianca=30,
        justificativa_confianca="Gerado em modo offline (sem IA): texto modelo que precisa de revisão e edição.",
    )


# ------------------------------------------------------------------ pós-processamento
def find_forbidden(texto: str, cfg: AppConfig) -> list[str]:
    t = norm(texto)
    return [p for p in cfg.brand.palavras_proibidas if norm(p) in t]


def has_cta(texto: str) -> bool:
    t = texto.lower()[-300:]
    return any(h in t for h in CTA_HINTS)


def truncate(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[: limite - 1]
    for sep in ("\n\n", ". ", "\n", " "):
        idx = corte.rfind(sep)
        if idx > limite * 0.6:
            return corte[: idx + (1 if sep == ". " else 0)].rstrip() + "…"
    return corte.rstrip() + "…"


def count_emojis(texto: str) -> int:
    return len(EMOJI_RE.findall(texto))


def finalize_caption(texto: str, rede: str, cfg: AppConfig, *, disclaimer: str, aviso_publi: str,
                     reserva_hashtags: int) -> tuple[str, list[str]]:
    """Aplica as regras da marca/rede a uma legenda. Retorna (texto, alertas)."""
    alertas: list[str] = []
    pc = cfg.platforms.redes.get(rede)
    texto = texto.strip()

    proibidas = find_forbidden(texto, cfg)
    if proibidas:
        alertas.append(f"Expressões proibidas encontradas: {', '.join(proibidas)}")

    if rede in {"instagram", "facebook", "tiktok", "youtube"} and not has_cta(texto):
        texto += f"\n\n{cfg.brand.cta_padrao}"
    if aviso_publi and aviso_publi.lower() not in texto.lower():
        texto = f"{aviso_publi} {texto}" if rede != "linkedin" else f"{texto}\n\nConteúdo em parceria paga."
    if disclaimer and norm(disclaimer)[:25] not in norm(texto):
        texto += f"\n\n{disclaimer}"

    if pc:
        limite = pc.legenda_max_caracteres - reserva_hashtags
        if len(texto) > limite:
            alertas.append(f"Legenda cortada para {limite} caracteres (limite da rede)")
            texto = truncate(texto, limite)
        if count_emojis(texto) > pc.emojis_max:
            alertas.append(f"Mais de {pc.emojis_max} emojis (diretriz da marca para {rede})")
    return texto, alertas


LITTLE_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")


def escape_linkedin(texto: str) -> str:
    """Escapa caracteres reservados do formato 'little text' da Posts API do LinkedIn.

    Hashtags e menções são montadas pelo publisher (Fase 3) com a sintaxe própria.
    """
    return LITTLE_RESERVED.sub(r"\\\1", texto)
