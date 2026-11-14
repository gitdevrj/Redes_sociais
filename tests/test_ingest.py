from src.ingest import ingest

from .conftest import make_image


def test_single_image_with_briefing(settings, db):
    img = make_image(settings.inbox / "foto.jpg")
    (settings.inbox / "foto.txt").write_text("Post sobre margem. #publi parceria", encoding="utf-8")
    [pid] = ingest(img, db, settings.processing)
    post = db.get(pid)
    assert post.tipo == "image" and post.arquivos == ["foto.jpg"]
    assert "margem" in post.briefing and post.is_sponsored is True
    assert (settings.processing / pid / "foto.jpg").exists()
    assert (settings.processing / pid / "briefing.txt").exists()
    assert not img.exists()


def test_folder_of_images_becomes_carousel(settings, db):
    folder = settings.inbox / "carrossel"
    for i in range(3):
        make_image(folder / f"{i}.png")
    (folder / "briefing.txt").write_text("3 indicadores", encoding="utf-8")
    [pid] = ingest(folder, db, settings.processing)
    post = db.get(pid)
    assert post.tipo == "carousel" and len(post.arquivos) == 3
    assert post.briefing == "3 indicadores"
    assert not folder.exists()


def test_heic_is_converted_to_jpg(settings, db):
    from PIL import Image
    from pillow_heif import register_heif_opener

    register_heif_opener()
    p = settings.inbox / "iphone.heic"
    Image.new("RGB", (64, 64), (200, 10, 10)).save(p, format="HEIF")
    [pid] = ingest(p, db, settings.processing)
    assert db.get(pid).arquivos == ["iphone.jpg"]
    assert (settings.processing / pid / "iphone.jpg").exists()


def test_unsupported_file_is_ignored(settings, db):
    p = settings.inbox / "planilha.xlsx"
    p.write_bytes(b"x")
    assert ingest(p, db, settings.processing) == []
    assert p.exists()
