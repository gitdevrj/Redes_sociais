"""Análise técnica do vídeo: metadados (ffprobe), cortes de cena e frames representativos."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..logging_setup import get_logger
from ..schemas import Cena, VideoInfo

log = get_logger("analyzer.video")


def _bin(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} não encontrado no PATH. Instale o FFmpeg (veja o README).")
    return found


def probe(path: Path) -> dict:
    out = subprocess.run(
        [_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def _orientacao(w: int, h: int) -> str:
    if abs(w - h) <= max(w, h) * 0.05:
        return "quadrado"
    return "vertical" if h > w else "horizontal"


def _fps(rate: str) -> float:
    try:
        num, den = rate.split("/")
        return round(float(num) / float(den), 3) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def detect_scenes(path: Path, duracao: float) -> list[Cena]:
    try:
        from scenedetect import AdaptiveDetector, detect

        def secs(tc) -> float:
            return float(getattr(tc, "seconds", None) if hasattr(tc, "seconds") else tc.get_seconds())

        scenes = detect(str(path), AdaptiveDetector(), show_progress=False)
        cenas = [Cena(inicio_s=round(secs(a), 2), fim_s=round(secs(b), 2)) for a, b in scenes]
    except Exception as exc:  # noqa: BLE001
        log.warning("PySceneDetect indisponível/falhou; usando cena única", extra={"data": {"erro": str(exc)}})
        cenas = []
    return cenas or [Cena(inicio_s=0.0, fim_s=round(duracao, 2))]


def pick_timestamps(cenas: list[Cena], duracao: float, minimo: int = 6, maximo: int = 12) -> list[float]:
    """Um frame no meio de cada cena; completa com amostragem uniforme até `minimo`."""
    ts = [round((c.inicio_s + c.fim_s) / 2, 2) for c in cenas if c.fim_s - c.inicio_s > 0.3]
    if len(ts) > maximo:
        step = len(ts) / maximo
        ts = [ts[int(i * step)] for i in range(maximo)]
    if len(ts) < minimo and duracao > 0:
        n = minimo
        uniforme = [round(duracao * (i + 0.5) / n, 2) for i in range(n)]
        ts = sorted(set(ts) | set(uniforme))
        while len(ts) > maximo:
            ts.pop(len(ts) // 2)
    return [min(t, max(duracao - 0.05, 0)) for t in ts]


def extract_frames(path: Path, out_dir: Path, timestamps: list[float]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for i, t in enumerate(timestamps, start=1):
        dest = out_dir / f"frame_{i:02d}_{t:07.2f}s.jpg"
        subprocess.run(
            [_bin("ffmpeg"), "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path),
             "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(dest)],
            check=True,
        )
        if dest.exists():
            frames.append(dest)
    return frames


def sharpness(path: Path) -> float:
    """Nitidez (variância do Laplaciano) — usada para escolher a capa na Fase 2."""
    try:
        import cv2

        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        return float(cv2.Laplacian(img, cv2.CV_64F).var()) if img is not None else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def analyze_video(path: Path, post_dir: Path) -> VideoInfo:
    info = probe(path)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = abs(int(sd["rotation"]))
    if rot in (90, 270):
        w, h = h, w
    dur = float(info.get("format", {}).get("duration") or v.get("duration") or 0)
    cenas = detect_scenes(path, dur)
    frames = extract_frames(path, post_dir / "frames", pick_timestamps(cenas, dur))
    return VideoInfo(
        duracao_s=round(dur, 2), largura=w, altura=h, fps=_fps(v.get("avg_frame_rate", "0/1")),
        orientacao=_orientacao(w, h), tem_audio=a is not None,
        codec_video=v.get("codec_name", ""), codec_audio=(a or {}).get("codec_name", ""),
        cenas=cenas, frames=[f.relative_to(post_dir).as_posix() for f in frames],
    )
