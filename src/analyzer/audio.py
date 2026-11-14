"""Áudio: trechos de silêncio (FFmpeg) e transcrição com timestamps (faster-whisper, opcional)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..logging_setup import get_logger
from ..schemas import AudioInfo, Cena, TrechoFala
from .video import _bin

log = get_logger("analyzer.audio")
_model_cache: dict[str, object] = {}


def detect_silences(path: Path, noise_db: int = -35, min_dur: float = 0.6) -> list[Cena]:
    proc = subprocess.run(
        [_bin("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-af",
         f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        out.append(Cena(inicio_s=round(max(s, 0), 2), fim_s=round(e, 2) if e is not None else -1))
    return out


def _load_whisper(model: str, device: str, compute_type: str):
    key = f"{model}:{device}:{compute_type}"
    if key not in _model_cache:
        from faster_whisper import WhisperModel  # import tardio: dependência pesada e opcional

        _model_cache[key] = WhisperModel(model, device=device, compute_type=compute_type)
    return _model_cache[key]


def transcribe(path: Path, model: str = "small", device: str = "cpu", compute_type: str = "int8",
               language: str = "pt") -> tuple[list[TrechoFala], str]:
    """Retorna (trechos, motivo_falha). Falha não é fatal: o pipeline segue sem transcrição."""
    try:
        wm = _load_whisper(model, device, compute_type)
        segments, _ = wm.transcribe(str(path), language=language, vad_filter=True)  # type: ignore[attr-defined]
        return [TrechoFala(inicio_s=round(s.start, 2), fim_s=round(s.end, 2), texto=s.text.strip())
                for s in segments if s.text.strip()], ""
    except ImportError:
        return [], "faster-whisper não instalado"
    except Exception as exc:  # noqa: BLE001
        log.warning("transcrição falhou", extra={"data": {"erro": str(exc)[:300]}})
        return [], f"falha na transcrição: {type(exc).__name__}"


def analyze_audio(path: Path, duracao: float, tem_audio: bool, whisper_enabled: bool = True,
                  model: str = "small", device: str = "cpu", compute_type: str = "int8") -> AudioInfo:
    if not tem_audio:
        return AudioInfo(motivo_sem_transcricao="vídeo sem trilha de áudio")
    silencios = detect_silences(path)
    for s in silencios:
        if s.fim_s < 0:
            s.fim_s = round(duracao, 2)
    silencio_total = sum(max(0.0, s.fim_s - s.inicio_s) for s in silencios)
    trechos, motivo = ([], "transcrição desativada (WHISPER_ENABLED=false)")
    if whisper_enabled:
        trechos, motivo = transcribe(path, model, device, compute_type)
    fala = sum(t.fim_s - t.inicio_s for t in trechos)
    proporcao = fala / duracao if (trechos and duracao) else max(0.0, 1 - silencio_total / duracao) if duracao else 0.0
    return AudioInfo(
        transcricao=" ".join(t.texto for t in trechos), trechos=trechos, silencios=silencios,
        proporcao_fala=round(min(proporcao, 1.0), 3), transcrito=bool(trechos),
        motivo_sem_transcricao="" if trechos else (motivo or "nenhuma fala detectada"),
    )
