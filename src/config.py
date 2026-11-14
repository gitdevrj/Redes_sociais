"""Modelos e carregamento dos arquivos YAML de configuração."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Rede = Literal["instagram", "facebook", "linkedin", "tiktok", "youtube"]
REDES: tuple[str, ...] = ("instagram", "facebook", "linkedin", "tiktok", "youtube")


class Tema(BaseModel):
    rotulo: str
    palavras_chave: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    disclaimer: str | None = None
    diretriz: str | None = None


class TomDeVoz(BaseModel):
    descricao: str
    faca: list[str] = Field(default_factory=list)
    evite: list[str] = Field(default_factory=list)


class Visual(BaseModel):
    fonte: str = "Montserrat"
    fonte_arquivo: str = ""
    cor_primaria: str = "#0B2545"
    cor_secundaria: str = "#13315C"
    cor_destaque: str = "#F2C14E"
    cor_texto: str = "#FFFFFF"


class Publicidade(BaseModel):
    aviso_padrao: str = "#publi"


class Brand(BaseModel):
    nome: str
    handle_principal: str = ""
    segmento: str
    idioma: str = "pt-BR"
    fuso_horario: str = "America/Sao_Paulo"
    publico_alvo: str
    pilares: list[str] = Field(default_factory=list)
    temas: dict[str, Tema] = Field(default_factory=dict)
    tom_de_voz: TomDeVoz
    palavras_proibidas: list[str] = Field(default_factory=list)
    cta_padrao: str
    cta_alternativos: list[str] = Field(default_factory=list)
    hashtags_marca: list[str] = Field(default_factory=list)
    publicidade: Publicidade = Field(default_factory=Publicidade)
    visual: Visual = Field(default_factory=Visual)


class Handles(BaseModel):
    instagram: str = ""
    facebook: str = ""
    linkedin: str = ""
    tiktok: str = ""
    youtube: str = ""

    def for_rede(self, rede: str) -> str:
        return (getattr(self, rede, "") or "").strip()


class Perfil(BaseModel):
    id: str
    nome: str
    tipo: str = "parceiro"
    handles: Handles = Field(default_factory=Handles)
    palavras_chave: list[str] = Field(default_factory=list)
    logos: list[str] = Field(default_factory=list)
    consentimento_imagem: bool = False
    consentimento_registrado_em: str = ""
    auto_marcar: bool = True
    colaborador_instagram: bool = False


class Mentions(BaseModel):
    perfis: list[Perfil] = Field(default_factory=list)


class PlatformCfg(BaseModel):
    ativo: bool = False
    conta: str = ""
    legenda_max_caracteres: int = 2200
    titulo_max_caracteres: int | None = None
    hashtags_min: int = 0
    hashtags_max: int = 5
    hashtags_max_api: int | None = None
    mencoes_max: int | None = None
    colaboradores_max: int | None = None
    carrossel_max_itens: int | None = None
    emojis_max: int = 3
    proporcao_video: str = "9:16"
    proporcao_imagem: str = "1:1"
    formatos_video: list[str] = Field(default_factory=list)
    formatos_imagem: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class Local(BaseModel):
    nome: str
    palavras_chave: list[str] = Field(default_factory=list)
    instagram_location_id: str = ""
    facebook_place_id: str = ""


class Platforms(BaseModel):
    redes: dict[str, PlatformCfg]
    locais: list[Local] = Field(default_factory=list)

    def ativas(self) -> list[str]:
        return [r for r, c in self.redes.items() if c.ativo]


class ModoPublicacao(BaseModel):
    auto_publish: bool = False
    confianca_minima_auto: int = 85


class Schedule(BaseModel):
    fuso_horario: str = "America/Sao_Paulo"
    espacamento_entre_redes_min: int = 20
    antecedencia_minima_min: int = 30
    modo: ModoPublicacao = Field(default_factory=ModoPublicacao)
    janelas: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    frequencia: dict[str, int] = Field(default_factory=dict)


class AppConfig(BaseModel):
    brand: Brand
    mentions: Mentions
    platforms: Platforms
    schedule: Schedule


def _read(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(config_dir: Path) -> AppConfig:
    plat_raw = _read(config_dir / "platforms.yaml")
    locais = plat_raw.pop("locais", None) or []
    redes = {k: PlatformCfg(**(v or {})) for k, v in plat_raw.items() if k in REDES}
    mentions_raw = _read(config_dir / "mentions.yaml")
    return AppConfig(
        brand=Brand(**_read(config_dir / "brand.yaml")),
        mentions=Mentions(perfis=mentions_raw.get("perfis") or []),
        platforms=Platforms(redes=redes, locais=locais),
        schedule=Schedule(**_read(config_dir / "schedule.yaml")),
    )
