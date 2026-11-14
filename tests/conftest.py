from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image
from pydantic import SecretStr

from src.config import load_config
from src.review_queue.db import Database
from src.schemas import AudioInfo, ContentAnalysis, VisionResult
from src.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
def base(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    for d in ("inbox", "processing", "output", "published", "logs", "data"):
        (tmp_path / d).mkdir()
    return tmp_path


@pytest.fixture
def settings(base: Path) -> Settings:
    return Settings(base_dir=base, dry_run=True, ai_provider="offline", whisper_enabled=False,
                    review_user="admin", review_password=SecretStr("s3nha"),
                    telegram_allowed_user_ids=[111])


@pytest.fixture
def cfg(base: Path):
    return load_config(base / "config")


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


def make_image(path: Path, color=(11, 37, 69), size=(800, 1000)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def vision(**kw) -> VisionResult:
    data = dict(descricao="Dashboard de margem de contribuição", tema_principal="Indicadores financeiros",
                subtemas=["margem"], tom_emocional="didático", pessoas=[], textos_visiveis=["Margem 38%"],
                logos_marcas=[], local_provavel="escritório", objetos=["gráfico"],
                gancho_sugerido="Sua margem está mentindo para você?", riscos=[])
    data.update(kw)
    return VisionResult(**data)


def analysis(post_id="p1", briefing="", transcricao="", tipo="image", **vkw) -> ContentAnalysis:
    return ContentAnalysis(
        post_id=post_id, tipo=tipo, arquivos=["a.jpg"], briefing=briefing,
        audio=AudioInfo(transcricao=transcricao, transcrito=bool(transcricao)) if transcricao else None,
        visao=vision(**vkw), tema_chave="indicadores", analisado_em=datetime.now(timezone.utc),
    )
