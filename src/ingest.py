"""Ingestão: recebe arquivos/pastas, gera ID, move para processing/ e registra no banco."""
from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image

from .logging_setup import get_logger
from .review_queue.db import Database, Post

log = get_logger("ingest")

VIDEO_EXT = {".mp4", ".mov", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
SUPPORTED = VIDEO_EXT | IMAGE_EXT
SPONSOR_MARKERS = re.compile(r"(#publi\b|#ad\b|parceria paga|publicidade|patrocinado)", re.I)


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED


def new_post_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def convert_heic(path: Path) -> Path:
    """Converte HEIC → JPG (mantém o original fora do fluxo)."""
    from pillow_heif import register_heif_opener

    register_heif_opener()
    out = path.with_suffix(".jpg")
    with Image.open(path) as im:
        im.convert("RGB").save(out, "JPEG", quality=95)
    path.unlink()
    return out


def _read_briefing(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc).strip()
        except UnicodeDecodeError:
            continue
    return ""


def _briefing_for(media: Path) -> Path | None:
    for cand in (media.with_suffix(".txt"), media.with_suffix(media.suffix + ".txt")):
        if cand.exists():
            return cand
    return None


def ingest(path: Path, db: Database, processing_dir: Path, origem: str = "inbox",
           telegram_chat_id: int | None = None) -> list[str]:
    """Ingere um arquivo ou uma pasta (pasta com imagens = carrossel).

    Retorna os IDs criados. Arquivos não suportados são ignorados.
    """
    path = Path(path)
    if path.is_dir():
        return _ingest_dir(path, db, processing_dir, origem, telegram_chat_id)
    if not is_supported(path):
        log.info("arquivo ignorado (extensão não suportada)", extra={"data": {"arquivo": path.name}})
        return []
    briefing_file = _briefing_for(path)
    briefing = _read_briefing(briefing_file) if briefing_file else ""
    pid = new_post_id()
    dest = processing_dir / pid
    dest.mkdir(parents=True, exist_ok=True)
    moved = Path(shutil.move(str(path), dest / path.name))
    if briefing_file:
        shutil.move(str(briefing_file), dest / "briefing.txt")
    if moved.suffix.lower() == ".heic":
        moved = convert_heic(moved)
    tipo = "video" if moved.suffix.lower() in VIDEO_EXT else "image"
    _register(db, pid, tipo, [moved.name], briefing, origem, telegram_chat_id)
    return [pid]


def _ingest_dir(folder: Path, db: Database, processing_dir: Path, origem: str,
                telegram_chat_id: int | None) -> list[str]:
    files = sorted(p for p in folder.iterdir() if p.is_file() and is_supported(p))
    images = [p for p in files if p.suffix.lower() in IMAGE_EXT]
    videos = [p for p in files if p.suffix.lower() in VIDEO_EXT]
    ids: list[str] = []
    folder_briefing = folder / "briefing.txt"
    if not folder_briefing.exists():
        txts = [p for p in folder.glob("*.txt") if not any(p.stem == f.stem for f in files)]
        folder_briefing = txts[0] if len(txts) == 1 else folder_briefing

    # Vídeos dentro da pasta são posts individuais.
    for v in videos:
        ids += ingest(v, db, processing_dir, origem, telegram_chat_id)

    if len(images) == 1:
        img = images[0]
        if folder_briefing.exists() and not _briefing_for(img):
            shutil.copy(folder_briefing, img.with_suffix(".txt"))
        ids += ingest(img, db, processing_dir, origem, telegram_chat_id)
    elif len(images) > 1:
        pid = new_post_id()
        dest = processing_dir / pid
        dest.mkdir(parents=True, exist_ok=True)
        names: list[str] = []
        briefing_parts: list[str] = []
        if folder_briefing.exists():
            briefing_parts.append(_read_briefing(folder_briefing))
        for i, img in enumerate(images[:20], start=1):   # carrossel: até 20 itens (Instagram)
            bf = _briefing_for(img)
            if bf:
                briefing_parts.append(f"[Imagem {i}] {_read_briefing(bf)}")
                bf.unlink()
            moved = Path(shutil.move(str(img), dest / f"{i:02d}_{img.name}"))
            if moved.suffix.lower() == ".heic":
                moved = convert_heic(moved)
            names.append(moved.name)
        if len(images) > 20:
            log.warning("carrossel com mais de 20 imagens: excedentes ficaram na pasta",
                        extra={"data": {"pasta": folder.name, "total": len(images)}})
        briefing = "\n".join(b for b in briefing_parts if b)
        if briefing:
            (dest / "briefing.txt").write_text(briefing, encoding="utf-8")
        _register(db, pid, "carousel", names, briefing, origem, telegram_chat_id)
        ids.append(pid)

    if folder_briefing.exists():
        folder_briefing.unlink()
    try:
        if not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass
    return ids


def _register(db: Database, pid: str, tipo: str, arquivos: list[str], briefing: str,
              origem: str, telegram_chat_id: int | None) -> None:
    import json

    db.add_post(Post(
        id=pid, tipo=tipo, origem=origem, arquivos_json=json.dumps(arquivos, ensure_ascii=False),
        briefing=briefing, is_sponsored=bool(SPONSOR_MARKERS.search(briefing or "")),
        telegram_chat_id=telegram_chat_id,
    ))
    log.info("post ingerido", extra={"data": {"post_id": pid, "tipo": tipo, "arquivos": len(arquivos)}})
