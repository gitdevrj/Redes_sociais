from types import SimpleNamespace

import pytest

from src.ai import AIError, ClaudeLLM
from src.ingest import ingest
from src.pipeline import Pipeline
from src.schemas import CopyPorRede, GeracaoIA, LegendaVariacao, VisionResult

from .conftest import HAS_FFMPEG, make_image, vision


class FakeLLM:
    """Simula o Claude: devolve objetos pydantic conforme o schema pedido."""

    def __init__(self, vision_result: VisionResult | None = None, nota: int = 92, texto: str | None = None):
        self.vision_result = vision_result or vision()
        self.nota = nota
        self.texto = texto
        self.calls: list[str] = []

    def generate(self, *, system, content, schema, max_tokens=16000):
        self.calls.append(schema.__name__)
        if schema is VisionResult:
            return self.vision_result
        redes = [r.strip() for r in content[-1]["text"].split("\n")[0].replace("Redes:", "").split(",")]
        t = self.texto or "Sua margem conta uma história.\n\nVeja como ler.\n\nSalve este post."
        return GeracaoIA(
            redes=[CopyPorRede(rede=r, titulo="Margem de contribuição em 1 minuto" if r == "youtube" else "",
                               legendas=[LegendaVariacao(estilo=e, texto=f"{t} ({e})")
                                         for e in ("informativa", "storytelling", "provocativa")],
                               hashtags_sugeridas=["#margemdecontribuicao", "#pme"], primeiro_comentario="")
                   for r in redes],
            texto_alternativo=["Gráfico de barras com a margem mensal"], nota_confianca=self.nota,
            justificativa_confianca="material claro")


def _pipe(settings, db, cfg, llm=None):
    return Pipeline(settings, db, cfg=cfg, llm=llm)


def test_claude_wrapper_sends_structured_request_and_handles_refusal():
    seen = {}

    def parse(**kw):
        seen.update(kw)
        return SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"),
                               parsed_output=None, model="m", usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    llm = ClaudeLLM(None, "claude-sonnet-5-5", "medium", client=client)
    with pytest.raises(AIError, match="recusou"):
        llm.generate(system="s", content=[{"type": "text", "text": "x"}], schema=VisionResult)
    assert seen["model"] == "claude-sonnet-5-5"
    assert seen["output_format"] is VisionResult and seen["fallbacks"] == "default"
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen["output_config"] == {"effort": "medium"}


def test_image_pipeline_with_claude(settings, db, cfg):
    img = make_image(settings.inbox / "dash.jpg")
    [pid] = ingest(img, db, settings.processing)
    llm = FakeLLM()
    posts = _pipe(settings, db, cfg, llm).process(pid, notify=False)
    assert {p.rede for p in posts} == {"instagram", "facebook", "linkedin"}  # YouTube não recebe imagem
    ig = next(p for p in posts if p.rede == "instagram")
    assert ig.modo_ia == "claude" and ig.formato == "feed" and len(ig.legendas) == 3
    assert "#margemdecontribuicao" in ig.hashtags
    assert ig.texto_alternativo == ["Gráfico de barras com a margem mensal"]
    assert ig.revisao_obrigatoria is True          # auto_publish desligado por padrão
    assert ig.confianca.nota == 92
    assert (settings.output / pid / "instagram.json").exists()
    assert db.get(pid).status == "gerado"
    assert llm.calls == ["VisionResult", "GeracaoIA"]


def test_risks_force_review_even_in_auto_mode(settings, db, cfg):
    cfg.schedule.modo.auto_publish = True
    img = make_image(settings.inbox / "doc.jpg")
    [pid] = ingest(img, db, settings.processing)
    llm = FakeLLM(vision(textos_visiveis=["CPF 123.456.789-09"]))
    posts = _pipe(settings, db, cfg, llm).process(pid, notify=False)
    assert all(p.revisao_obrigatoria for p in posts)
    assert any("CPF" in r for r in posts[0].riscos)
    assert posts[0].confianca.nota < 92


def test_auto_mode_allows_high_confidence_without_risk(settings, db, cfg):
    cfg.schedule.modo.auto_publish = True
    img = make_image(settings.inbox / "ok.jpg")
    [pid] = ingest(img, db, settings.processing)
    posts = _pipe(settings, db, cfg, FakeLLM(nota=95)).process(pid, notify=False)
    assert not any(p.revisao_obrigatoria for p in posts)


def test_forbidden_word_from_ai_forces_review(settings, db, cfg):
    cfg.schedule.modo.auto_publish = True
    img = make_image(settings.inbox / "x.jpg")
    [pid] = ingest(img, db, settings.processing)
    posts = _pipe(settings, db, cfg, FakeLLM(nota=95, texto="Lucro garantido! Comente.")).process(pid, notify=False)
    assert all(p.revisao_obrigatoria for p in posts) and posts[0].alertas


def test_regenerate_uses_instruction(settings, db, cfg):
    img = make_image(settings.inbox / "r.jpg")
    [pid] = ingest(img, db, settings.processing)
    pipe = _pipe(settings, db, cfg, FakeLLM())
    pipe.process(pid, notify=False)
    pipe.regenerate(pid, "mais curto, foco em MEI", notify=False)
    assert db.get(pid).instrucao_regeneracao == "mais curto, foco em MEI"
    assert any(e.tipo == "regenerar" for e in db.events(pid))


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg não instalado")
def test_video_pipeline_offline(settings, db, cfg, tmp_path):
    import subprocess

    video = settings.inbox / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=30:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=4", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=True)
    [pid] = ingest(video, db, settings.processing)
    posts = _pipe(settings, db, cfg).process(pid, notify=False)
    redes = {p.rede: p for p in posts}
    assert set(redes) == {"instagram", "facebook", "linkedin", "youtube"}
    assert redes["instagram"].formato == "reels" and redes["youtube"].formato == "shorts"
    assert redes["youtube"].titulo
    a = _pipe(settings, db, cfg).load_analysis(pid)
    assert a.video.orientacao == "vertical" and a.video.tem_audio and 6 <= len(a.video.frames) <= 12
    assert all(p.modo_ia == "offline" and p.revisao_obrigatoria and p.confianca.nota <= 40 for p in posts)
