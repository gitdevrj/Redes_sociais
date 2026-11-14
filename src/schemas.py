"""Schemas pydantic dos JSONs do pipeline (análise e posts por rede)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MediaKind = Literal["video", "image", "carousel"]


# ---------------- Análise ----------------
class Cena(BaseModel):
    inicio_s: float
    fim_s: float


class TrechoFala(BaseModel):
    inicio_s: float
    fim_s: float
    texto: str


class VideoInfo(BaseModel):
    duracao_s: float
    largura: int
    altura: int
    fps: float = 0.0
    orientacao: Literal["vertical", "horizontal", "quadrado"]
    tem_audio: bool = False
    codec_video: str = ""
    codec_audio: str = ""
    cenas: list[Cena] = Field(default_factory=list)
    frames: list[str] = Field(default_factory=list)  # caminhos relativos ao diretório do post


class AudioInfo(BaseModel):
    transcricao: str = ""
    trechos: list[TrechoFala] = Field(default_factory=list)
    silencios: list[Cena] = Field(default_factory=list)
    proporcao_fala: float = 0.0      # 0..1 do tempo com fala
    transcrito: bool = False
    motivo_sem_transcricao: str = ""


class PessoaDetectada(BaseModel):
    descricao: str = Field(description="Descrição visual genérica, SEM identificar quem é")
    aparenta_menor_de_idade: bool = False


class VisionResult(BaseModel):
    """Saída estruturada pedida ao Claude (visão)."""

    descricao: str
    tema_principal: str
    subtemas: list[str]
    tom_emocional: str = Field(description="ex.: inspirador, didático, sério, descontraído, urgente, reflexivo")
    pessoas: list[PessoaDetectada]
    textos_visiveis: list[str] = Field(description="OCR: textos legíveis na imagem")
    logos_marcas: list[str]
    local_provavel: str
    objetos: list[str]
    gancho_sugerido: str = Field(description="Gancho para os 3 primeiros segundos / primeira linha")
    riscos: list[str] = Field(
        description="Conteúdo sensível, marca de terceiros, dados pessoais visíveis (CPF/CNPJ/documentos), menores de idade"
    )


class ContentAnalysis(BaseModel):
    post_id: str
    tipo: MediaKind
    arquivos: list[str]
    briefing: str = ""
    video: VideoInfo | None = None
    audio: AudioInfo | None = None
    visao: VisionResult
    tema_chave: str | None = None     # chave do tema em brand.yaml
    temas_relacionados: list[str] = Field(default_factory=list)
    pilares: list[str] = Field(default_factory=list)
    entidades: list[str] = Field(default_factory=list)
    riscos: list[str] = Field(default_factory=list)
    modo_ia: Literal["claude", "offline"] = "offline"
    analisado_em: datetime


# ---------------- Geração ----------------
class LegendaVariacao(BaseModel):
    estilo: Literal["informativa", "storytelling", "provocativa"]
    texto: str


class CopyPorRede(BaseModel):
    """Saída estruturada pedida ao Claude para cada rede."""

    rede: Literal["instagram", "facebook", "linkedin", "tiktok", "youtube"]
    titulo: str = Field(description="Obrigatório no YouTube (até 100 caracteres); vazio nas demais redes")
    legendas: list[LegendaVariacao] = Field(description="Exatamente 3: informativa, storytelling, provocativa")
    hashtags_sugeridas: list[str]
    primeiro_comentario: str


class GeracaoIA(BaseModel):
    """Bundle de geração retornado pelo Claude."""

    redes: list[CopyPorRede]
    texto_alternativo: list[str] = Field(description="Um texto alternativo por imagem/frame de capa, na ordem")
    nota_confianca: int = Field(description="0 a 100")
    justificativa_confianca: str


class Marcacao(BaseModel):
    perfil_id: str | None = None
    nome: str
    handle: str
    origem: Literal["palavra_chave", "logo", "imagem_com_consentimento", "briefing", "sugestao_ia"]
    evidencia: str = ""
    colaborador: bool = False


class Localizacao(BaseModel):
    nome: str
    location_id: str = ""


class Confianca(BaseModel):
    nota: int
    justificativa: str


class PlatformPost(BaseModel):
    post_id: str
    rede: str
    formato: str
    modo_ia: Literal["claude", "offline"]
    titulo: str = ""
    legendas: list[LegendaVariacao]
    legenda_escolhida: int = 0
    hashtags: list[str] = Field(default_factory=list)
    marcacoes: list[Marcacao] = Field(default_factory=list)
    marcacoes_sugeridas: list[Marcacao] = Field(default_factory=list)
    colaboradores: list[str] = Field(default_factory=list)
    localizacao: Localizacao | None = None
    texto_alternativo: list[str] = Field(default_factory=list)
    primeiro_comentario: str = ""
    horario_sugerido: datetime | None = None
    is_sponsored: bool = False
    aviso_publicidade: str = ""
    disclaimer: str = ""
    musica: dict | None = None          # Fase 2
    midia: list[str] = Field(default_factory=list)
    confianca: Confianca
    riscos: list[str] = Field(default_factory=list)
    revisao_obrigatoria: bool = True
    alertas: list[str] = Field(default_factory=list)
    gerado_em: datetime

    def legenda_final(self) -> str:
        """Texto que seria publicado (legenda escolhida + hashtags conforme a rede)."""
        texto = self.legendas[self.legenda_escolhida].texto.rstrip()
        if self.hashtags:
            texto += "\n\n" + " ".join(self.hashtags)
        return texto
