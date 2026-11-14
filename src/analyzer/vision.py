"""Descrição de imagens/frames: Claude (visão) ou modo offline heurístico."""
from __future__ import annotations

import re
from pathlib import Path

from ..ai import StructuredLLM, image_block
from ..config import Brand
from ..schemas import VisionResult

CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
PHONE_RE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b")

VISION_SYSTEM = """Você é um analista de conteúdo para redes sociais de uma marca brasileira de finanças e negócios.
Analise as imagens (frames de um vídeo ou fotos de um post) e devolva APENAS o JSON pedido, em português do Brasil.

Regras:
- NÃO identifique pessoas pelo rosto. Descreva-as de forma genérica (ex.: "homem de camisa azul falando para a câmera").
  Nomes só podem aparecer se estiverem escritos na imagem (OCR) ou no briefing.
- Em `textos_visiveis`, transcreva os textos legíveis (OCR), inclusive números de gráficos/dashboards.
- Em `riscos`, liste QUALQUER um destes, se houver: dados pessoais visíveis (CPF, CNPJ, RG, documentos, e-mails,
  telefones, extratos, telas de banco), menores de idade, logos/marcas de terceiros em destaque, conteúdo sensível,
  promessa de ganho financeiro, informação que pareça confidencial de cliente. Lista vazia se não houver nada.
- `tom_emocional`: uma ou duas palavras (inspirador, didático, sério, descontraído, urgente, reflexivo, motivacional...).
- `gancho_sugerido`: uma frase curta e forte para os 3 primeiros segundos / primeira linha da legenda.
- `local_provavel`: tipo de ambiente (escritório, estúdio, evento, rua...). Não invente endereço."""


def _context_text(brand: Brand, briefing: str, transcricao: str, n_imgs: int, tipo: str) -> str:
    temas = ", ".join(t.rotulo for t in brand.temas.values())
    parts = [
        f"Marca: {brand.nome} — {brand.segmento}. Público: {brand.publico_alvo}",
        f"Temas frequentes da marca: {temas}.",
        f"Tipo de post: {tipo}. Número de imagens enviadas: {n_imgs}.",
    ]
    if briefing:
        parts.append(f"BRIEFING DO AUTOR (tem prioridade sobre a sua interpretação):\n{briefing}")
    if transcricao:
        parts.append(f"TRANSCRIÇÃO DA FALA DO VÍDEO:\n{transcricao[:6000]}")
    return "\n\n".join(parts)


def describe_with_claude(llm: StructuredLLM, images: list[Path], brand: Brand, briefing: str,
                         transcricao: str, tipo: str) -> VisionResult:
    content: list[dict] = [image_block(p) for p in images[:12]]
    content.append({"type": "text", "text": _context_text(brand, briefing, transcricao, len(images), tipo)})
    return llm.generate(system=VISION_SYSTEM, content=content, schema=VisionResult, max_tokens=8000)


def describe_offline(images: list[Path], brand: Brand, briefing: str, transcricao: str,
                     tipo: str, nome_arquivo: str = "") -> VisionResult:
    """Fallback sem IA: usa briefing, transcrição e nome do arquivo. Sempre exige revisão humana."""
    base = briefing or transcricao or re.sub(r"[_\-]+", " ", Path(nome_arquivo).stem)
    texto = base.lower()
    tema = "Conteúdo de negócios"
    subtemas: list[str] = []
    for t in brand.temas.values():
        hits = [k for k in t.palavras_chave if re.search(rf"\b{re.escape(k.lower())}\b", texto)]
        if hits:
            if tema == "Conteúdo de negócios":
                tema = t.rotulo
            else:
                subtemas.append(t.rotulo)
    return VisionResult(
        descricao=(f"[modo offline — sem análise visual] {tipo} com {len(images)} imagem(ns). "
                   f"Contexto: {base[:300]}").strip(),
        tema_principal=tema,
        subtemas=subtemas,
        tom_emocional="didático",
        pessoas=[],
        textos_visiveis=[],
        logos_marcas=[],
        local_provavel="",
        objetos=[],
        gancho_sugerido=(f"O que ninguém te explica sobre {tema.lower()}" if tema != "Conteúdo de negócios"
                         else "Você sabe o que os seus números estão dizendo sobre a sua empresa?"),
        riscos=[],
    )


def detect_text_risks(*texts: str) -> list[str]:
    """Checagem determinística (não depende da IA) de dados pessoais em textos/OCR/fala."""
    joined = "\n".join(t for t in texts if t)
    riscos = []
    if CPF_RE.search(joined):
        riscos.append("Possível CPF visível/falado")
    if CNPJ_RE.search(joined):
        riscos.append("Possível CNPJ visível/falado")
    if EMAIL_RE.search(joined):
        riscos.append("E-mail visível/falado")
    if PHONE_RE.search(joined):
        riscos.append("Telefone visível/falado")
    return riscos
