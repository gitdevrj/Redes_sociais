import re

import pytest
from fastapi.testclient import TestClient

from src.ingest import ingest
from src.pipeline import Pipeline
from src.review_queue.review_app import create_app

from .conftest import make_image

AUTH = ("admin", "s3nha")


@pytest.fixture
def setup(settings, db, cfg):
    pipe = Pipeline(settings, db, cfg=cfg)
    [pid] = ingest(make_image(settings.inbox / "a.jpg"), db, settings.processing)
    pipe.process(pid, notify=False)
    return TestClient(create_app(pipe)), pid, pipe


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


def test_requires_login(setup):
    client, pid, _ = setup
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("admin", "errada")).status_code == 401
    r = client.get("/", auth=AUTH)
    assert r.status_code == 200 and pid in r.text


def test_edit_and_approve_flow(setup):
    client, pid, pipe = setup
    page = client.get(f"/post/{pid}", auth=AUTH)
    assert page.status_code == 200 and "informativa" in page.text
    token = _csrf(page.text)
    r = client.post(f"/post/{pid}/acao", auth=AUTH, follow_redirects=False, data={
        "csrf": token, "op": "aprovar", "instagram_legenda_1": "Texto editado à mão.", "instagram_escolhida": "1",
        "instagram_hashtags": "#Gestão #pme", "instagram_horario": "2026-12-01T12:30",
        "linkedin_ativo_form": "1",  # LinkedIn desmarcado
        "instagram_ativo_form": "1", "instagram_ativo": "1", "facebook_ativo_form": "1", "facebook_ativo": "1",
    })
    assert r.status_code == 303
    ig = next(p for p in pipe.load_platform_posts(pid) if p.rede == "instagram")
    assert ig.legenda_escolhida == 1 and ig.legendas[1].texto == "Texto editado à mão."
    assert ig.hashtags == ["#gestao", "#pme"]
    estado = {r.rede: r for r in pipe.db.redes(pid)}
    assert estado["instagram"].status == "agendado"
    assert estado["linkedin"].status == "descartado"
    assert pipe.db.get(pid).status == "aprovado"


def test_csrf_and_path_traversal_protection(setup):
    client, pid, _ = setup
    assert client.post(f"/post/{pid}/acao", auth=AUTH, data={"op": "descartar"}).status_code == 403
    assert client.get(f"/media/{pid}/../../config/brand.yaml", auth=AUTH).status_code == 404
    assert client.get(f"/media/{pid}/a.jpg", auth=AUTH).status_code == 200


def test_refuses_to_start_without_password(settings, db, cfg):
    from pydantic import SecretStr

    settings.review_password = SecretStr("")
    with pytest.raises(RuntimeError):
        create_app(Pipeline(settings, db, cfg=cfg))
