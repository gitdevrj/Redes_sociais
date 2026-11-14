from datetime import datetime
from zoneinfo import ZoneInfo

from src.generator import captions
from src.scheduler import suggest_times

TZ = ZoneInfo("America/Sao_Paulo")


def test_finalize_adds_cta_disclaimer_and_publi(cfg):
    txt, alertas = captions.finalize_caption("Texto sobre CDB e renda fixa.", "instagram", cfg,
                                             disclaimer="Não é recomendação de investimento.",
                                             aviso_publi="#publi", reserva_hashtags=50)
    assert txt.startswith("#publi")
    assert cfg.brand.cta_padrao in txt
    assert txt.rstrip().endswith("Não é recomendação de investimento.")
    assert alertas == []


def test_forbidden_words_are_flagged(cfg):
    _, alertas = captions.finalize_caption("Lucro GARANTIDO em 30 dias. Siga!", "instagram", cfg,
                                           disclaimer="", aviso_publi="", reserva_hashtags=0)
    assert any("proibidas" in a for a in alertas)


def test_truncates_to_network_limit(cfg):
    longo = ("Frase de teste sobre gestão financeira. " * 200).strip()
    txt, alertas = captions.finalize_caption(longo, "linkedin", cfg, disclaimer="", aviso_publi="",
                                             reserva_hashtags=100)
    assert len(txt) <= 3000 - 100 and txt.endswith("…")
    assert any("cortada" in a for a in alertas)


def test_linkedin_escape():
    assert captions.escape_linkedin("Margem (bruta) [x] @a #b") == r"Margem \(bruta\) \[x\] \@a \#b"


def test_offline_generation_has_three_styles(cfg):
    from .conftest import analysis

    g = captions.generate_offline(analysis(briefing="margem de contribuição"), cfg, ["instagram", "youtube"])
    assert [l.estilo for l in g.redes[0].legendas] == ["informativa", "storytelling", "provocativa"]
    assert g.redes[1].titulo and len(g.redes[1].titulo) <= 100
    assert g.nota_confianca <= 40


def test_schedule_respects_windows_spacing_and_lead_time(cfg):
    now = datetime(2026, 11, 16, 11, 50, tzinfo=TZ)   # segunda 11:50
    r = suggest_times(["instagram", "facebook", "linkedin", "youtube"], cfg.schedule, now=now)
    assert r["instagram"] == datetime(2026, 11, 16, 12, 20, tzinfo=TZ)  # 30 min de antecedência
    times = sorted(r.values())
    assert all((b - a).total_seconds() >= 20 * 60 for a, b in zip(times, times[1:]))
    assert r["linkedin"].hour >= 12  # 07:30 já passou; próxima janela 12:00–13:00
    for rede, t in r.items():
        assert t > now


def test_schedule_skips_full_days(cfg):
    now = datetime(2026, 11, 16, 8, 0, tzinfo=TZ)
    ocupados = {"instagram": [datetime(2026, 11, 16, 12, 0, tzinfo=TZ), datetime(2026, 11, 16, 19, 0, tzinfo=TZ)]}
    r = suggest_times(["instagram"], cfg.schedule, now=now, ocupados=ocupados)
    assert r["instagram"].date().day == 17
