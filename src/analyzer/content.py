"""Consolida a análise: vídeo + áudio + visão + briefing → ContentAnalysis."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from ..ai import AIError, StructuredLLM
from ..config import AppConfig
from ..logging_setup import get_logger
from ..schemas import AudioInfo, ContentAnalysis, VideoInfo, VisionResult
from . import vision
from .audio import analyze_audio
from .video import analyze_video

log = get_logger("analyzer.content")

PILAR_KEYWORDS = {
    "Clareza": ["clareza", "entender", "simples", "explicar", "número", "numeros", "indicador", "dashboard", "dre", "visão"],
    "Direção": ["direção", "estratégia", "planejamento", "meta", "objetivo", "decisão", "rumo", "plano", "futuro"],
    "Lucro": ["lucro", "margem", "preço", "precificação", "rentabilidade", "faturamento", "resultado", "custo"],
    "Segurança": ["segurança", "reserva", "risco", "proteção", "caixa", "capital de giro", "consórcio", "planejamento patrimonial"],
}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _count(keyword: str, text: str) -> int:
    return len(re.findall(rf"(?<!\w){re.escape(norm(keyword))}(?!\w)", text))


def classify_theme(cfg: AppConfig, texto: str) -> tuple[str | None, list[str]]:
    t = norm(texto)
    scores = {k: sum(_count(kw, t) for kw in tema.palavras_chave) for k, tema in cfg.brand.temas.items()}
    ranked = [k for k, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s > 0]
    return (ranked[0] if ranked else None), ranked[1:4]


def detect_pillars(cfg: AppConfig, texto: str) -> list[str]:
    t = norm(texto)
    found = [p for p, kws in PILAR_KEYWORDS.items() if p in cfg.brand.pilares and any(_count(k, t) for k in kws)]
    return found or cfg.brand.pilares[:1]


def analyze_post(*, post_id: str, tipo: str, arquivos: list[str], post_dir: Path, briefing: str,
                 cfg: AppConfig, llm: StructuredLLM | None, whisper_enabled: bool = True,
                 whisper_model: str = "small", whisper_device: str = "cpu",
                 whisper_compute_type: str = "int8") -> ContentAnalysis:
    video_info: VideoInfo | None = None
    audio_info: AudioInfo | None = None
    paths = [post_dir / a for a in arquivos]

    if tipo == "video":
        video_info = analyze_video(paths[0], post_dir)
        audio_info = analyze_audio(paths[0], video_info.duracao_s, video_info.tem_audio, whisper_enabled,
                                   whisper_model, whisper_device, whisper_compute_type)
        imagens = [post_dir / f for f in video_info.frames]
    else:
        imagens = paths
    transcricao = audio_info.transcricao if audio_info else ""

    modo = "offline"
    visao: VisionResult
    if llm is not None:
        try:
            visao = vision.describe_with_claude(llm, imagens, cfg.brand, briefing, transcricao, tipo)
            modo = "claude"
        except AIError as exc:
            log.warning("visão via Claude falhou; usando modo offline", extra={"data": {"post_id": post_id, "erro": str(exc)}})
            visao = vision.describe_offline(imagens, cfg.brand, briefing, transcricao, tipo, arquivos[0])
    else:
        visao = vision.describe_offline(imagens, cfg.brand, briefing, transcricao, tipo, arquivos[0])

    corpus = " \n".join([briefing, transcricao, visao.descricao, visao.tema_principal, " ".join(visao.subtemas),
                         " ".join(visao.textos_visiveis)])
    tema_chave, relacionados = classify_theme(cfg, corpus)
    riscos = list(dict.fromkeys(
        visao.riscos
        + vision.detect_text_risks(" ".join(visao.textos_visiveis), transcricao)
        + (["Possível menor de idade na imagem"] if any(p.aparenta_menor_de_idade for p in visao.pessoas) else [])
    ))
    entidades = list(dict.fromkeys(visao.logos_marcas + [t for t in visao.textos_visiveis if len(t) <= 60]))
    return ContentAnalysis(
        post_id=post_id, tipo=tipo, arquivos=arquivos, briefing=briefing, video=video_info, audio=audio_info,
        visao=visao, tema_chave=tema_chave, temas_relacionados=relacionados,
        pilares=detect_pillars(cfg, corpus), entidades=entidades, riscos=riscos, modo_ia=modo,  # type: ignore[arg-type]
        analisado_em=datetime.now(timezone.utc),
    )
